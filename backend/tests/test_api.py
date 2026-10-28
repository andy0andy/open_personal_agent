import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agents.main_agent.conversations import NewConversationTurn
from agents.main_agent.runtime import MessageDelta
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    BreakingChatModel,
    FailingChatModel,
    FakeConversationIndex,
    FakeMcpClient,
    FakeSandbox,
    HangingChatModel,
    ScriptedChatModel,
    UnavailableGateway,
    call,
    mcp_tool,
)
from agents.tests.waiting import until
from backend.runs import RunManager, RunRepo
from backend.runtime import EventEnvelope, InMemoryEventBus
from backend.tests.conftest import ClientFactory
from common.db import Pool
from common.errors import ConflictError

pytestmark = pytest.mark.integration


def _sse_events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


async def _wait_finished(client: AsyncClient, thread_id: str) -> list[dict[str, Any]]:
    for _ in range(100):
        history = (await client.get(f"/api/threads/{thread_id}/history")).json()
        if history and history[-1]["status"] not in ("queued", "running"):
            return list(history)
        await asyncio.sleep(0.05)  # 允许等待：有上限的轮询
    raise AssertionError("运行未在预期时间内结束")


async def _has_event(client: AsyncClient, thread_id: str, kind: str) -> bool:
    """最近一次运行的界面历史里已经有这种事件（运行中的事件分批写进去）。"""
    history = (await client.get(f"/api/threads/{thread_id}/history")).json()
    return bool(history) and any(event["type"] == kind for event in history[-1]["events"])


async def test_thread_crud(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        created = (await client.post("/api/threads", json={})).json()
        assert created["model"] == "fake-model"
        assert created["short_id"].startswith("c_")
        assert [t["id"] for t in (await client.get("/api/threads")).json()] == [created["id"]]
        assert (await client.get(f"/api/threads/{created['id']}")).status_code == 200
        assert (await client.get(f"/api/threads/{uuid.uuid4()}")).status_code == 404


async def test_run_streams_events_and_persists_history(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[AIMessage(content="你好")])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()

        body = (await client.get(f"/api/runs/{run['id']}/events")).text
        types = [e["type"] for e in _sse_events(body)]
        assert types[0] == "run.started"
        assert types[-1] == "run.finished"
        assert types.count("message.delta") == 2  # 逐字推送

        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "completed"
        stored = [(e["type"], e["data"].get("text")) for e in history[-1]["events"]]
        assert ("message.delta", "你好") in stored  # 存储时已合并
        threads = (await client.get("/api/threads")).json()
        assert threads[0]["title"] == "hi"


async def test_replay_after_finish_and_last_event_id(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[AIMessage(content="好")])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await _wait_finished(client, thread["id"])

        resp = await client.get(f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": "1"})
        assert next(e["seq"] for e in _sse_events(resp.text)) == 2


async def test_subscribe_after_events_already_shown(make_client: ClientFactory) -> None:
    """刷新页面时，进行中运行已存的事件已由历史重建：从 after 之后接着推送，避免文字重复；
    之后断线重连带的 Last-Event-ID 更靠后，以它为准。"""
    async with make_client(ScriptedChatModel(responses=[AIMessage(content="好")])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await _wait_finished(client, thread["id"])
        url = f"/api/runs/{run['id']}/events"

        resp = await client.get(url, params={"after": 1})
        assert next(e["seq"] for e in _sse_events(resp.text)) == 2
        resp = await client.get(url, params={"after": 1}, headers={"Last-Event-ID": "2"})
        assert next(e["seq"] for e in _sse_events(resp.text)) == 3


async def test_model_failure_marks_run_failed(make_client: ClientFactory) -> None:
    async with make_client(FailingChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "failed"
        assert "模型调用失败" in str(history[-1]["error"])


async def test_second_active_run_is_rejected(make_client: ClientFactory, db: Pool) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await RunRepo(db).create(thread_id=uuid.UUID(thread["id"]), model="m", message="占位")
        resp = await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        assert resp.status_code == 409


async def test_blank_message_and_unknown_ids(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        blank = await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "   "})
        assert blank.status_code == 422
        unknown_thread = await client.post(
            f"/api/threads/{uuid.uuid4()}/runs", json={"message": "hi"}
        )
        assert unknown_thread.status_code == 404
        assert (await client.get(f"/api/runs/{uuid.uuid4()}/events")).status_code == 404


async def test_unfinished_runs_fail_on_restart(make_client: ClientFactory, db: Pool) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await RunRepo(db).create(thread_id=uuid.UUID(thread["id"]), model="m", message="占位")
        assert len(await RunRepo(db).fail_unfinished()) == 1
        history = (await client.get(f"/api/threads/{thread['id']}/history")).json()
        assert (history[-1]["status"], history[-1]["error"]) == ("failed", "服务重启中断")


async def test_models_endpoint(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        assert [m["name"] for m in (await client.get("/api/models")).json()] == ["fake-model"]


async def test_models_endpoint_returns_503_when_gateway_down(make_client: ClientFactory) -> None:
    model = ScriptedChatModel(responses=[])
    async with make_client(model, gateway=UnavailableGateway(model)) as client:
        resp = await client.get("/api/models")
        assert resp.status_code == 503
        assert "模型网关不可用" in resp.json()["detail"]


async def test_replay_after_restart_ends_with_failure(make_client: ClientFactory, db: Pool) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = await RunRepo(db).create(thread_id=uuid.UUID(thread["id"]), model="m", message="占位")
        await RunRepo(db).fail_unfinished()

        events = _sse_events((await client.get(f"/api/runs/{run.id}/events")).text)

        # 重启前的事件只在旧进程内存里；重连必须以 run.finished 结束，前端才不会一直重连
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"] == {
            "status": "failed",
            "error": "服务重启中断",
            "error_kind": "interrupted",  # 设计 2026-10-23 4.5
            "retryable": False,  # 不知道中断前做过什么：只给"继续"
            "usage": None,
            "interrupted_usage": None,
            "undelivered": [],  # 设计 2026-10-23 6.3
            "next_run_id": None,
        }
        # 没有任何已存事件：结束时间取运行创建时间，前端不会算出"到现在为止"的假耗时
        assert datetime.fromisoformat(events[-1]["ts"]) == run.created_at


async def test_replay_from_history_resends_whole_message(make_client: ClientFactory) -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="你好")])
    bus = InMemoryEventBus(retain_seconds=0)
    async with make_client(model, bus=bus) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await _wait_finished(client, thread["id"])
        # 等内存保留期结束，确保走界面历史补发
        await until(lambda: not bus.has(run["id"]), what="过了保留时间")

        # 推送顺序：1 run.started，2「你」，3「好」，4 run.finished；客户端断线前只收到了「你」
        resp = await client.get(f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": "2"})
        events = _sse_events(resp.text)

        assert events[0]["type"] == "message.delta"
        assert events[0]["data"]["text"] == "你好"
        assert events[0]["data"]["full_text"] is True
        assert events[-1]["type"] == "run.finished"


async def test_usage_is_recorded_per_call_and_summed(make_client: ClientFactory) -> None:
    answer = AIMessage(
        content="好",
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        response_metadata={"model_name": "litellm_proxy/fake-model", "response_cost": 0.02},
    )
    async with make_client(ScriptedChatModel(responses=[answer])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        await _wait_finished(client, thread["id"])

        [usage_event] = [e for e in events if e["type"] == "usage"]
        # 网关算的费用不读（设计 2026-10-19 4.11）：只有 token
        assert usage_event["data"]["input_tokens"] == 100
        assert "cost" not in usage_event["data"]
        totals = {"calls": 1, "input_tokens": 100, "output_tokens": 10}
        assert events[-1]["data"]["usage"] == totals

        calls = (await client.get(f"/api/runs/{run['id']}/usage")).json()
        assert [(c["caller"], c["actual_model"], c["input_tokens"]) for c in calls] == [
            ("main", "fake-model", 100)
        ]
        thread_usage = (await client.get(f"/api/threads/{thread['id']}/usage")).json()
        assert thread_usage["total"] == totals
        assert [m["model"] for m in thread_usage["by_model"]] == ["fake-model"]
        missing = await client.get(f"/api/threads/{uuid.uuid4()}/usage")
        assert missing.status_code == 404


async def test_cancel_endpoint(make_client: ClientFactory) -> None:
    async with make_client(HangingChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await until(lambda: _has_event(client, thread["id"], "message.delta"), what="模型开始输出")

        assert (await client.post(f"/api/runs/{run['id']}/cancel", json={})).status_code == 202
        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "cancelled"
        assert history[-1]["events"][-1]["data"]["status"] == "cancelled"
        again = await client.post(f"/api/runs/{run['id']}/cancel", json={})
        assert again.status_code == 409
        missing = await client.post(f"/api/runs/{uuid.uuid4()}/cancel", json={})
        assert missing.status_code == 404


async def test_replay_of_partial_history_ends_with_failure(
    make_client: ClientFactory, db: Pool
) -> None:
    """进程在运行途中退出：界面历史里有分批写入的部分事件，但没有结束事件。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        runs = RunRepo(db)
        run = await runs.create(thread_id=uuid.UUID(thread["id"]), model="m", message="占位")
        partial = EventEnvelope.wrap(MessageDelta(message_id="m1", text="半"), seq=1, run_id="x")
        await runs.add_events(run.id, [partial])
        await runs.fail_unfinished()

        events = _sse_events((await client.get(f"/api/runs/{run.id}/events")).text)

        assert [(e["seq"], e["type"]) for e in events] == [
            (1, "message.delta"),
            (2, "run.finished"),
        ]
        assert events[-1]["data"]["error"] == "服务重启中断"
        assert events[-1]["data"]["error_kind"] == "interrupted"
        # 补发的结束事件用最后一个已存事件的时间（耗时只算到中断前）
        assert events[-1]["ts"] == events[0]["ts"]


async def test_retry_endpoint_returns_new_run(make_client: ClientFactory) -> None:
    """POST /api/runs/{id}/retry：失败的那一轮从运行前的存档重跑（D26），返回新运行。"""
    model = BreakingChatModel(
        error=RuntimeError("boom"), partial="", responses=[AIMessage(content="重试成功")]
    )
    async with make_client(model) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        resp = await client.post(f"/api/runs/{run['id']}/retry")
        assert resp.status_code == 202
        retried = resp.json()
        assert (retried["retry_of"], retried["message"]) == (run["id"], "hi")
        events = _sse_events((await client.get(f"/api/runs/{retried['id']}/events")).text)
        assert events[-1]["data"]["status"] == "completed"
        again = await client.post(f"/api/runs/{run['id']}/retry")
        assert again.status_code == 409


async def test_rename_and_reorder_threads(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        first = (await client.post("/api/threads", json={})).json()
        second = (await client.post("/api/threads", json={})).json()

        renamed = await client.patch(f"/api/threads/{first['id']}", json={"title": "  新名字 "})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "新名字"
        assert (
            await client.patch(f"/api/threads/{first['id']}", json={"title": " "})
        ).status_code == 422
        missing = await client.patch(f"/api/threads/{uuid.uuid4()}", json={"title": "x"})
        assert missing.status_code == 404

        order = [first["id"], second["id"]]
        assert (
            await client.put("/api/threads/order", json={"thread_ids": order})
        ).status_code == 204
        assert [t["id"] for t in (await client.get("/api/threads")).json()] == order
        repeated = {"thread_ids": [first["id"], first["id"]]}
        assert (await client.put("/api/threads/order", json=repeated)).status_code == 422


async def test_delete_thread_endpoint(make_client: ClientFactory) -> None:
    async with make_client(HangingChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await until(lambda: _has_event(client, thread["id"], "run.started"), what="运行中")

        refused = await client.delete(f"/api/threads/{thread['id']}")
        assert refused.status_code == 409
        assert "请先停止" in refused.json()["detail"]

        await client.post(f"/api/runs/{run['id']}/cancel", json={})
        await _wait_finished(client, thread["id"])
        assert (await client.delete(f"/api/threads/{thread['id']}")).status_code == 204
        assert (await client.get(f"/api/threads/{thread['id']}")).status_code == 404
        assert [t["id"] for t in (await client.get("/api/threads")).json()] == []
        assert (await client.delete(f"/api/threads/{uuid.uuid4()}")).status_code == 404


async def test_download_an_output_file(make_client: ClientFactory, tmp_path: Path) -> None:
    def make_chart(session: str, command: str) -> None:
        outputs = tmp_path / "workspace" / session / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "销售图.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python plot.py"}), AIMessage("好")]
    )
    workspace = LocalWorkspace(tmp_path, FakeSandbox(effect=make_chart))
    async with make_client(model, workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "画图"})
        ).json()
        # 执行命令固定先问（D21）：先同意
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        [request] = events[-1]["data"]["requests"]
        approve = {"interrupt_id": request["interrupt_id"], "decisions": [{"type": "approve"}]}
        resumed = await client.post(f"/api/runs/{run['id']}/resume", json={"answers": [approve]})
        assert resumed.status_code == 202
        history = await _wait_finished(client, thread["id"])
        created = next(e for e in history[-1]["events"] if e["type"] == "file.created")
        url = f"/api/threads/{thread['id']}/files/{created['data']['file_id']}/content"

        shown = await client.get(url)
        assert shown.status_code == 200
        assert shown.content == b"png!"
        assert shown.headers["content-type"] == "image/png"
        assert (
            shown.headers["content-disposition"]
            == "inline; filename*=UTF-8''%E9%94%80%E5%94%AE%E5%9B%BE.png"
        )
        # 产物可能是 HTML / SVG：直接打开时不执行其中的脚本，也不按内容猜类型
        assert shown.headers["content-security-policy"] == "sandbox"
        assert shown.headers["x-content-type-options"] == "nosniff"
        downloaded = await client.get(url, params={"download": "1"})
        assert downloaded.headers["content-disposition"].startswith("attachment;")

        other = (await client.post("/api/threads", json={})).json()
        stolen = f"/api/threads/{other['id']}/files/{created['data']['file_id']}/content"
        assert (await client.get(stolen)).status_code == 404  # 别的会话的文件
        unknown = f"/api/threads/{thread['id']}/files/{uuid.uuid4()}/content"
        assert (await client.get(unknown)).status_code == 404

        assert shown.headers["content-length"] == "4"

        chart = tmp_path / "workspace" / thread["short_id"] / "outputs" / "销售图.png"
        chart.unlink()
        gone = await client.get(url)
        assert gone.status_code == 404
        assert gone.json()["detail"] == "文件已不存在"
        # 被换成目录、或换成指向会话目录外的链接：同样是"已不存在"，不是服务器错误
        chart.mkdir()
        assert (await client.get(url)).json()["detail"] == "文件已不存在"
        chart.rmdir()
        chart.symlink_to(tmp_path / "elsewhere.png")
        assert (await client.get(url)).json()["detail"] == "文件已不存在"


async def test_upload_list_and_download(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    async with make_client(ScriptedChatModel(responses=[]), workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        headers = {"X-File-Name": quote("销售 数据.csv"), "Content-Type": "text/csv"}
        response = await client.post(files, content=b"a,b\n1,2\n", headers=headers)
        assert response.status_code == 201
        uploaded = response.json()
        assert (uploaded["path"], uploaded["source"], uploaded["size"]) == (
            "uploads/销售 数据.csv",
            "upload",
            8,
        )
        assert uploaded["media_type"] == "text/csv"
        assert [item["id"] for item in (await client.get(files)).json()] == [uploaded["id"]]
        content = await client.get(f"{files}/{uploaded['id']}/content")
        assert content.content == b"a,b\n1,2\n"

        unknown = f"/api/threads/{uuid.uuid4()}/files"
        assert (await client.get(unknown)).status_code == 404
        assert (await client.post(unknown, content=b"x", headers=headers)).status_code == 404


async def test_upload_over_the_limit_is_refused(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    model = ScriptedChatModel(responses=[])
    async with make_client(model, workspace=workspace, upload_limit_mb=1) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        response = await client.post(
            files, content=b"x" * (1024 * 1024 + 1), headers={"X-File-Name": "big.bin"}
        )
        assert response.status_code == 413
        assert response.json()["detail"] == "文件超过 1MB 上限"
        assert (await client.get(files)).json() == []


async def test_table_preview_of_an_uploaded_csv(make_client: ClientFactory, tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    async with make_client(ScriptedChatModel(responses=[]), workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        files = f"/api/threads/{thread['id']}/files"
        csv = (
            await client.post(files, content=b"a,b\n1,2\n", headers={"X-File-Name": "t.csv"})
        ).json()
        png = (await client.post(files, content=b"png", headers={"X-File-Name": "p.png"})).json()

        table = await client.get(f"{files}/{csv['id']}/table")
        assert table.json() == {
            "sheets": [],
            "sheet": None,
            "rows": [["a", "b"], ["1", "2"]],
            "truncated": False,
            "columns_truncated": False,
        }
        refused = await client.get(f"{files}/{png['id']}/table")
        assert refused.status_code == 422
        assert refused.json()["detail"] == "这种文件不能按表格预览"

        other = (await client.post("/api/threads", json={})).json()
        stolen = f"/api/threads/{other['id']}/files/{csv['id']}/table"
        assert (await client.get(stolen)).status_code == 404


@tool
def demo_add_note(text: str) -> str:
    """记一条笔记"""
    return f"added {text}"


async def test_resume_endpoint(make_client: ClientFactory) -> None:
    model = ScriptedChatModel(
        responses=[call("demo_add_note", {"text": "买牛奶"}), AIMessage(content="记好了")]
    )
    async with make_client(model, mcp=FakeMcpClient([mcp_tool(demo_add_note)])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "记一下"})
        ).json()
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        assert events[-1]["type"] == "approval.required"
        [request] = events[-1]["data"]["requests"]
        url = f"/api/runs/{run['id']}/resume"
        bad = {
            "answers": [{"interrupt_id": request["interrupt_id"], "decisions": [{"type": "edit"}]}]
        }
        assert (await client.post(url, json=bad)).status_code == 422
        good = {
            "answers": [
                {"interrupt_id": request["interrupt_id"], "decisions": [{"type": "approve"}]}
            ]
        }
        resp = await client.post(url, json=good)
        assert resp.status_code == 202
        assert resp.json()["status"] == "running"
        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "completed"
        assert (await client.post(url, json=good)).status_code == 409


async def test_patch_thread_sets_model_and_permission(make_client: ClientFactory) -> None:
    """会话的模型与审批权限存在会话上（设计 2026-10-19 4.1、4.2）。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        assert thread["permission_mode"] == "ask"
        url = f"/api/threads/{thread['id']}"
        resp = await client.patch(url, json={"model": "fake-model", "permission_mode": "skip"})
        assert resp.status_code == 200
        assert (resp.json()["model"], resp.json()["permission_mode"]) == ("fake-model", "skip")
        again = (await client.get(url)).json()
        assert (again["model"], again["permission_mode"]) == ("fake-model", "skip")
        assert again["title"] == thread["title"]


async def test_patch_thread_rejects_unknown_model(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        resp = await client.patch(f"/api/threads/{thread['id']}", json={"model": "nope"})
        assert resp.status_code == 422  # InvalidRequestError 在本项目统一是 422
        assert "没有这个模型" in resp.json()["detail"]


async def test_patch_thread_requires_a_field(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        assert (await client.patch(f"/api/threads/{thread['id']}", json={})).status_code == 422
        bad = await client.patch(
            f"/api/threads/{thread['id']}", json={"title": "新名字", "permission_mode": "x"}
        )
        assert bad.status_code == 422


async def test_skip_thread_runs_tools_without_approval(make_client: ClientFactory) -> None:
    """会话设为"跳过所有审批"：外部工具直接执行，没有审批暂停。"""
    model = ScriptedChatModel(
        responses=[call("demo_add_note", {"text": "买牛奶"}), AIMessage(content="记好了")]
    )
    async with make_client(model, mcp=FakeMcpClient([mcp_tool(demo_add_note)])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        changed = await client.patch(
            f"/api/threads/{thread['id']}", json={"permission_mode": "skip"}
        )
        assert changed.status_code == 200  # 积压小问题 I12：改不成时这条测试也该失败
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "记一下"})
        ).json()
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        assert "approval.required" not in [e["type"] for e in events]
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"]["status"] == "completed"


async def test_permission_change_while_waiting_keeps_the_runs_permission(
    make_client: ClientFactory, db: Pool
) -> None:
    """等审批时把会话改成"跳过所有审批"：这次运行仍按开始时的档位，审批照常能提交。"""
    model = ScriptedChatModel(
        responses=[call("demo_add_note", {"text": "买牛奶"}), AIMessage(content="记好了")]
    )
    async with make_client(model, mcp=FakeMcpClient([mcp_tool(demo_add_note)])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "记一下"})
        ).json()
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        assert events[-1]["type"] == "approval.required"
        [request] = events[-1]["data"]["requests"]
        changed = await client.patch(
            f"/api/threads/{thread['id']}", json={"permission_mode": "skip"}
        )
        assert changed.status_code == 200  # 积压小问题 I12：等审批时也改得了
        answer = {
            "answers": [
                {"interrupt_id": request["interrupt_id"], "decisions": [{"type": "approve"}]}
            ]
        }
        resp = await client.post(f"/api/runs/{run['id']}/resume", json=answer)
        assert resp.status_code == 202
        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "completed"
        assert (await RunRepo(db).get(uuid.UUID(run["id"]))).permission == "ask"


async def test_cross_origin_write_without_token_is_rejected(make_client: ClientFactory) -> None:
    """别的网站拿不到本机令牌（D25）：只带着 Cookie 的写请求被拒，界面带请求头的照常。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        token = client.headers.pop("X-Session-Token")
        client.cookies.set("opa_session", token)
        resp = await client.post("/api/threads", json={}, headers={"Origin": "http://evil.example"})
        assert resp.status_code == 401
        resp = await client.post("/api/threads", json={}, headers={"X-Session-Token": token})
        assert resp.status_code == 201


async def test_foreign_host_is_rejected(make_client: ClientFactory) -> None:
    """Host 不是本机就拒绝（D25）：挡住 DNS 重绑定。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        resp = await client.get("/api/threads", headers={"Host": "evil.example"})
        assert resp.status_code == 400


async def test_post_without_json_body_is_accepted(make_client: ClientFactory) -> None:
    """不要求 POST 必须是 JSON（D23）；带着令牌就行（D25）。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        assert (await client.post("/api/settings/reload")).status_code == 200


async def test_rename_updates_index_title(make_client: ClientFactory) -> None:
    """改了会话标题，会话搜索里显示新标题（设计 2026-10-23 6.1）。"""
    index = FakeConversationIndex()
    async with make_client(ScriptedChatModel(responses=[]), conversations=index) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await index.index(
            NewConversationTurn(
                thread_id=uuid.UUID(thread["id"]),
                run_id=uuid.uuid4(),
                title="旧标题",
                started_at=datetime.now(UTC),
                user_text="问",
                answer_text="答",
            )
        )
        resp = await client.patch(f"/api/threads/{thread['id']}", json={"title": "新标题"})
        assert resp.status_code == 200
        [row] = index.rows.values()
        assert row.title == "新标题"


async def test_search_threads_by_title_and_content(make_client: ClientFactory, db: Pool) -> None:
    """会话搜索（设计 2026-10-23 6.1）：标题匹配（含已归档的）与内容里提到（带片段、第几轮）。"""
    index = FakeConversationIndex()
    async with make_client(ScriptedChatModel(responses=[]), conversations=index) as client:
        travel = (await client.post("/api/threads", json={"title": "云南旅行"})).json()
        report = (await client.post("/api/threads", json={"title": "周报"})).json()
        old = (await client.post("/api/threads", json={"title": "云南美食"})).json()
        async with db.connection() as conn:
            await conn.execute("UPDATE threads SET archived = true WHERE id = %s", (old["id"],))
        await index.index(
            NewConversationTurn(
                thread_id=uuid.UUID(report["id"]),
                run_id=uuid.uuid4(),
                title="周报",
                started_at=datetime.now(UTC),
                user_text="香格里拉怎么去",
                answer_text="坐飞机到丽江再转车",
            )
        )
        found = (await client.get("/api/threads/search", params={"q": "云南"})).json()
        assert {t["id"] for t in found["titles"]} == {travel["id"], old["id"]}
        assert found["hits"] == []
        found = (await client.get("/api/threads/search", params={"q": "香格里拉"})).json()
        assert found["titles"] == []
        [hit] = found["hits"]
        assert (hit["thread_id"], hit["title"], hit["turn"]) == (report["id"], "周报", 1)
        assert "香格里拉" in hit["snippet"]
        assert (await client.get("/api/threads/search", params={"q": "%"})).json()["titles"] == []
        empty = (await client.get("/api/threads/search", params={"q": "  "})).json()
        assert empty == {"titles": [], "hits": []}


async def test_export_downloads_markdown(make_client: ClientFactory) -> None:
    """导出 Markdown（设计 2026-10-23 6.2）：作为附件下载，文件名是会话标题。"""
    model = ScriptedChatModel(responses=[AIMessage(content="晴，25 度")])
    async with make_client(model) as client:
        thread = (await client.post("/api/threads", json={"title": "天气/明天"})).json()
        await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "明天天气"})
        await _wait_finished(client, thread["id"])
        resp = await client.get(f"/api/threads/{thread['id']}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        disposition = resp.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "filename*=UTF-8''%E5%A4%A9%E6%B0%94_%E6%98%8E%E5%A4%A9.md" in disposition
        assert resp.text.startswith("# 天气/明天")
        assert "明天天气" in resp.text
        # 每轮的时间按浏览器所在时区写；时区不认识时说明原因
        url = f"/api/threads/{thread['id']}/export"
        assert (await client.get(url, params={"tz": "Asia/Shanghai"})).status_code == 200
        bad = await client.get(url, params={"tz": "Mars/Base"})
        assert bad.status_code == 422
        assert "时区不认识" in bad.json()["detail"]
        assert "晴，25 度" in resp.text
        missing = await client.get(f"/api/threads/{uuid.uuid4()}/export")
        assert missing.status_code == 404


async def test_create_thread_with_first_message_starts_a_run(make_client: ClientFactory) -> None:
    """建会话一次完成（设计 2026-10-23 6.4）：一次请求建好会话、设好模型和权限、发起运行。"""
    model = ScriptedChatModel(responses=[AIMessage(content="好的")])
    async with make_client(model) as client:
        resp = await client.post(
            "/api/threads",
            json={"message": "帮我写个周报", "model": "fake-model", "permission_mode": "skip"},
        )
        assert resp.status_code == 201
        created = resp.json()
        assert created["permission_mode"] == "skip"
        assert created["run"]["message"] == "帮我写个周报"
        history = await _wait_finished(client, created["id"])
        assert history[-1]["status"] == "completed"
        assert history[-1]["permission"] == "skip"
        plain = (await client.post("/api/threads", json={})).json()
        assert plain["run"] is None


async def test_create_with_unknown_model_leaves_no_thread(make_client: ClientFactory) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        resp = await client.post("/api/threads", json={"message": "你好", "model": "no-such"})
        assert resp.status_code >= 400
        assert (await client.get("/api/threads")).json() == []


async def test_failed_start_removes_the_new_thread(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """发起运行失败：删掉刚建的会话并返回原因，不留空会话（落地页的字还在）。"""

    async def refuse(self: RunManager, thread_id: uuid.UUID, body: object) -> None:
        raise ConflictError("发起不了")

    monkeypatch.setattr(RunManager, "start", refuse)
    async with make_client(ScriptedChatModel(responses=[])) as client:
        resp = await client.post("/api/threads", json={"message": "你好"})
        assert (resp.status_code, resp.json()["detail"]) == (409, "发起不了")
        assert (await client.get("/api/threads")).json() == []


async def test_archive_and_viewed(make_client: ClientFactory) -> None:
    """归档、取消归档经 PATCH；归档的会话能打开；打开会话后清掉"有新回答"。"""
    model = ScriptedChatModel(responses=[AIMessage(content="好")])
    async with make_client(model) as client:
        thread = (await client.post("/api/threads", json={"message": "你好"})).json()
        await _wait_finished(client, thread["id"])
        [listed] = (await client.get("/api/threads")).json()
        assert listed["activity"] == "new"
        assert (await client.post(f"/api/threads/{thread['id']}/viewed")).status_code == 204
        [listed] = (await client.get("/api/threads")).json()
        assert listed["activity"] is None
        resp = await client.patch(f"/api/threads/{thread['id']}", json={"archived": True})
        assert resp.json()["archived"] is True
        assert (await client.get("/api/threads")).json() == []
        archived = (await client.get("/api/threads", params={"archived": "true"})).json()
        assert [t["id"] for t in archived] == [thread["id"]]
        assert (await client.get(f"/api/threads/{thread['id']}")).status_code == 200
        await client.patch(f"/api/threads/{thread['id']}", json={"archived": False})
        assert len((await client.get("/api/threads")).json()) == 1


@tool
async def demo_slow_lookup() -> str:
    """要查一会儿的工具（插话的测试用）"""
    await asyncio.sleep(1.0)  # 允许等待：替身工具模拟要查一会儿
    return "查到了"


async def test_interject_reaches_the_running_agent(make_client: ClientFactory) -> None:
    """运行中插话（设计 2026-10-23 6.3）：202；主智能体下一次调用模型前送达，历史里有这一条。"""
    model = ScriptedChatModel(
        responses=[call("demo_slow_lookup", {}), AIMessage(content="好的，换成英文")]
    )
    mcp = FakeMcpClient([mcp_tool(demo_slow_lookup, read_only=True)])
    async with make_client(model, mcp=mcp) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "查一下"})
        ).json()
        await until(lambda: _has_event(client, thread["id"], "tool.running"), what="工具在跑")
        resp = await client.post(f"/api/runs/{run['id']}/interject", json={"message": "用英文"})
        assert resp.status_code == 202
        history = await _wait_finished(client, thread["id"])
        interjected = [e for e in history[-1]["events"] if e["type"] == "user.interjected"]
        assert [e["data"]["text"] for e in interjected] == ["用英文"]
        late = await client.post(f"/api/runs/{run['id']}/interject", json={"message": "再加一句"})
        assert late.status_code == 409  # 已经结束了


async def test_interject_while_waiting_for_approval_is_refused(make_client: ClientFactory) -> None:
    model = ScriptedChatModel(responses=[call("demo_add_note", {"text": "买牛奶"})])
    async with make_client(model, mcp=FakeMcpClient([mcp_tool(demo_add_note)])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "记一下"})
        ).json()
        events = _sse_events((await client.get(f"/api/runs/{run['id']}/events")).text)
        assert events[-1]["type"] == "approval.required"
        resp = await client.post(f"/api/runs/{run['id']}/interject", json={"message": "等等"})
        assert resp.status_code == 409
        assert "审批" in resp.json()["detail"]


async def test_long_search_query_is_cut_not_refused(make_client: ClientFactory) -> None:
    """搜索框里贴了很长一段：截到 200 字照常搜（审查 Minor 3：原来 422，界面一直"搜索失败"）。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        resp = await client.get("/api/threads/search", params={"q": "周报" * 200})
    assert resp.status_code == 200
    assert resp.json() == {"titles": [], "hits": []}
