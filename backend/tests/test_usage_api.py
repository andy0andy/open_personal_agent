"""用量汇总接口（设计文档 12.1 GET /usage/summary）。"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agents.main_agent.runtime import UsageReported
from agents.main_agent.usage import UsageRepo
from agents.tests.fakes import FakeMcpClient, ScriptedChatModel, call, mcp_tool
from agents.tests.waiting import until
from backend.tests.conftest import ClientFactory
from backend.threads import ThreadRepo
from common.db import Pool

pytestmark = pytest.mark.integration


def _usage(input_tokens: int) -> UsageReported:
    return UsageReported(
        caller="main",
        requested_model="m",
        actual_model="m",
        input_tokens=input_tokens,
        output_tokens=10,
    )


async def test_summary_endpoint_adds_titles(make_client: ClientFactory, db: Pool) -> None:
    """会话带标题；删掉的会话用量仍在，标题为空（前端显示"已删除的会话"）。"""
    threads, usage = ThreadRepo(db), UsageRepo(db)
    kept = await threads.create(model="m", title="写周报")
    gone = await threads.create(model="m", title="旧会话")
    await usage.add(thread_id=kept.id, run_id=uuid.uuid4(), usage=_usage(200))
    await usage.add(thread_id=gone.id, run_id=uuid.uuid4(), usage=_usage(100))
    await threads.delete(gone.id)
    async with make_client(ScriptedChatModel(responses=[AIMessage("好")])) as client:
        resp = await client.get("/api/usage/summary", params={"days": 1, "tz": "UTC"})
    assert resp.status_code == 200
    body = resp.json()
    assert [(t["title"], t["calls"]) for t in body["by_thread"]] == [("写周报", 1), (None, 1)]
    assert body["total"]["calls"] == 2
    assert body["until"] == datetime.now(UTC).date().isoformat()


@pytest.mark.parametrize(
    ("params", "reason"),
    [({"days": 0}, None), ({"days": 400}, None), ({"tz": "Mars/Base"}, "时区不认识")],
)
async def test_summary_rejects_bad_parameters(
    make_client: ClientFactory, params: dict[str, int | str], reason: str | None
) -> None:
    async with make_client(ScriptedChatModel(responses=[])) as client:
        resp = await client.get("/api/usage/summary", params=params)
    assert resp.status_code == 422
    if reason:
        assert reason in resp.json()["detail"]


async def test_summary_reports_input_and_output_only(make_client: ClientFactory, db: Pool) -> None:
    """用量只算输入（实际发给模型的全部输入，含命中缓存的）与输出（设计 4.11），不给费用与缓存。"""
    await UsageRepo(db).add(thread_id=None, run_id=None, usage=_usage(200))
    async with make_client(ScriptedChatModel(responses=[AIMessage("好")])) as client:
        body = (await client.get("/api/usage/summary", params={"days": 1, "tz": "UTC"})).json()
    assert set(body["total"]) == {"calls", "input_tokens", "output_tokens"}
    assert set(body["by_model"][0]) == {"model", "calls", "input_tokens", "output_tokens"}
    assert "unpriced_models" not in body


async def test_tool_and_skill_uses_are_counted(
    make_client: ClientFactory, db: Pool, tmp_path: Path
) -> None:
    """工具真正执行一次记一行；读技能说明另记技能名，分页往下读不重复记（设计 2026-10-23 6.8）。"""
    skills = tmp_path / "skills"
    (skills / "excel").mkdir(parents=True)
    (skills / "excel" / "SKILL.md").write_text(
        "---\nname: excel\ndescription: 表格\n---\n\n先看表头。\n", encoding="utf-8"
    )
    model = ScriptedChatModel(
        responses=[
            call("ls", {"path": "/"}, "c1"),
            call("read_file", {"file_path": "/skills/excel/SKILL.md"}, "c2"),
            call("read_file", {"file_path": "/skills/excel/SKILL.md", "offset": 3}, "c3"),
            AIMessage("好"),
        ]
    )
    async with make_client(model, skills_dir=skills) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "看看表格技能"})

        async def finished() -> bool:
            history = (await client.get(f"/api/threads/{thread['id']}/history")).json()
            return bool(history) and history[-1]["status"] not in ("queued", "running")

        await until(finished, what="运行结束")
        body = (await client.get("/api/usage/summary", params={"days": 1, "tz": "UTC"})).json()
    assert [(t["name"], t["count"]) for t in body["by_tool"]] == [("read_file", 2), ("ls", 1)]
    assert [(s["name"], s["count"]) for s in body["by_skill"]] == [("excel", 1)]


@tool
def demo_add_note(text: str) -> str:
    """记一条笔记"""
    return f"added {text}"


async def test_subagent_dispatch_counts_once_even_after_approval(
    make_client: ClientFactory,
) -> None:
    """派出子智能体记一次 task（积压小问题 B12）：子智能体里等审批、恢复后也不重复记。"""
    task = {"description": "记笔记", "subagent_type": "general-purpose"}
    model = ScriptedChatModel(
        responses=[
            call("task", task, "t1"),
            call("demo_add_note", {"text": "买牛奶"}, "c1"),
            AIMessage("子智能体记好了"),
            AIMessage("记好了"),
        ]
    )
    async with make_client(model, mcp=FakeMcpClient([mcp_tool(demo_add_note)])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "记个笔记"})
        ).json()
        body = (await client.get(f"/api/runs/{run['id']}/events")).text
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
        [request] = events[-1]["data"]["requests"]
        approve = {"interrupt_id": request["interrupt_id"], "decisions": [{"type": "approve"}]}
        resumed = await client.post(f"/api/runs/{run['id']}/resume", json={"answers": [approve]})
        assert resumed.status_code == 202

        async def finished() -> bool:
            history = (await client.get(f"/api/threads/{thread['id']}/history")).json()
            return bool(history) and history[-1]["status"] == "completed"

        await until(finished, what="运行结束")
        summary = await client.get("/api/usage/summary", params={"days": 1, "tz": "UTC"})
    counts = {row["name"]: row["count"] for row in summary.json()["by_tool"]}
    assert counts == {"task": 1, "demo_add_note": 1}
