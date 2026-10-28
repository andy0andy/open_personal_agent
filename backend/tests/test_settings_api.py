"""设置接口（设计文档 12.1）：MCP 服务、审批规则、技能与重新加载。"""

import base64
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agents.main_agent.runtime import SkillCatalog
from agents.main_agent.usage import UsageRepo
from agents.tests.fakes import FakeMcpClient, ScriptedChatModel, mcp_tool
from agents.tests.waiting import until
from backend.runs import RunRepo
from backend.tests.conftest import ClientFactory
from backend.threads import ThreadRepo
from common.db import Pool
from config.settings import SEED_DIR

pytestmark = pytest.mark.integration


@tool
def demo_add_note(text: str) -> str:
    """记一条笔记"""
    return text


@tool
def demo_list_notes() -> str:
    """列出笔记"""
    return ""


def _mcp() -> FakeMcpClient:
    return FakeMcpClient([mcp_tool(demo_add_note), mcp_tool(demo_list_notes, read_only=True)])


def _files(tmp_path: Path, rules: str = "tools: {}\n", servers: str = "servers: {}\n") -> Path:
    """临时的 .workdata（D22）：两个配置文件都在 config/ 下，只有这一份。返回 .workdata 的位置。"""
    workdata = tmp_path / "wd"
    (workdata / "config").mkdir(parents=True, exist_ok=True)
    (workdata / "config" / "mcp_servers.yaml").write_text(servers, encoding="utf-8")
    (workdata / "config" / "approval_rules.yaml").write_text(rules, encoding="utf-8")
    return workdata


def _model() -> ScriptedChatModel:
    return ScriptedChatModel(responses=[AIMessage(content="好")])


async def test_lists_servers_and_effective_approvals(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as client:
        servers = (await client.get("/api/settings/mcp-servers")).json()
        assert servers["config_error"] is None
        [server] = servers["servers"]
        assert server["state"] == "connected"
        assert "demo_add_note" in server["tools"]
        approvals = (await client.get("/api/settings/approval-rules")).json()
        tools = {row["name"]: (row["action"], row["reason"]) for row in approvals["tools"]}
        assert tools["demo_add_note"] == ("ask", "MCP 工具默认（mcp_default）")
        assert tools["demo_list_notes"] == ("auto", "服务声明为只读")
        assert tools["execute"] == ("ask", "执行命令每次先问（固定，D21）")
        assert approvals["mcp_default"] == "ask"


async def test_reload_reads_files_again(make_client: ClientFactory, tmp_path: Path) -> None:
    mcp = _mcp()
    files = _files(tmp_path)
    async with make_client(_model(), mcp=mcp, workdata=files) as client:
        (files / "config" / "approval_rules.yaml").write_text(
            "tools:\n  demo_add_note: auto\n", encoding="utf-8"
        )
        resp = await client.post("/api/settings/reload", json={})
        assert resp.status_code == 200
        tools = {row["name"]: row for row in resp.json()["approvals"]["tools"]}
        assert (tools["demo_add_note"]["action"], tools["demo_add_note"]["reason"]) == (
            "auto",
            "规则 demo_add_note",
        )
        assert resp.json()["approvals"]["rules"] == [{"tool": "demo_add_note", "action": "auto"}]
        assert len(mcp.connected) == 2  # 启动时一次，重新加载一次


async def test_reload_with_bad_file_keeps_old_config(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    files = _files(tmp_path, rules="tools:\n  demo_add_note: auto\n")
    async with make_client(_model(), mcp=_mcp(), workdata=files) as client:
        (files / "config" / "approval_rules.yaml").write_text("tools: [\n", encoding="utf-8")
        resp = await client.post("/api/settings/reload", json={})
        assert resp.status_code == 422
        assert "approval_rules.yaml" in resp.json()["detail"]
        approvals = (await client.get("/api/settings/approval-rules")).json()
        assert approvals["rules"] == [{"tool": "demo_add_note", "action": "auto"}]


async def test_reload_while_running_is_conflict(
    make_client: ClientFactory, tmp_path: Path, db: Pool
) -> None:
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as client:
        thread = await ThreadRepo(db).create(model="fake-model")
        await RunRepo(db).create(thread_id=thread.id, model="fake-model", message="hi")
        resp = await client.post("/api/settings/reload", json={})
        assert resp.status_code == 409


async def test_startup_config_error_is_shown(make_client: ClientFactory, tmp_path: Path) -> None:
    files = _files(tmp_path, servers="servers:\n  files:\n    comand: npx\n")
    async with make_client(_model(), mcp=_mcp(), workdata=files) as client:
        resp = await client.get("/api/settings/mcp-servers")
        assert resp.status_code == 200
        assert "mcp_servers.yaml" in (resp.json()["config_error"] or "")


async def test_lists_skills(make_client: ClientFactory) -> None:
    skills_dir = SEED_DIR / "files" / "skills"
    async with make_client(_model(), skills_dir=skills_dir) as client:
        skills = (await client.get("/api/settings/skills")).json()
        assert {"name": "excel", "error": None}.items() <= next(
            s for s in skills if s["name"] == "excel"
        ).items()


# ---- MCP 页改服务与审批规则（D22）：只有 .workdata/config/ 这一份 ----

_DEMO = "servers:\n  demo:\n    description: 测试服务\n    command: echo\n"


def _user_file(workdata: Path, name: str = "mcp_servers.yaml") -> dict[str, Any]:
    path = workdata / "config" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _memo(name: str = "memo") -> dict[str, Any]:
    return {"name": name, "command": "echo", "args": ["hi"]}


async def test_add_server_writes_the_workdata_file(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    wd = _files(tmp_path, servers=_DEMO)
    async with make_client(_model(), mcp=_mcp(), workdata=wd) as client:
        resp = await client.post("/api/settings/mcp-servers", json={"servers": [_memo()]})
        assert resp.status_code == 201
        servers = _user_file(wd)["servers"]
        assert (servers["memo"]["command"], servers["demo"]["command"]) == ("echo", "echo")
        listed = {s["name"]: s for s in resp.json()["servers"]}
        assert "builtin" not in listed["memo"]
        assert listed["memo"]["config"]["args"] == ["hi"]


async def test_add_duplicate_name_conflicts(make_client: ClientFactory, tmp_path: Path) -> None:
    files = _files(tmp_path, servers=_DEMO)
    async with make_client(_model(), mcp=_mcp(), workdata=files) as client:
        resp = await client.post("/api/settings/mcp-servers", json={"servers": [_memo("demo")]})
        assert (resp.status_code, resp.json()["detail"]) == (409, "已有同名服务：demo")


async def test_add_batch_is_all_or_nothing(make_client: ClientFactory, tmp_path: Path) -> None:
    wd = tmp_path / "wd"
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as c:
        body = {"servers": [_memo(), _memo("bad-name")]}
        assert (await c.post("/api/settings/mcp-servers", json=body)).status_code == 422
        assert _user_file(wd) == {"servers": {}}


async def test_disable_keeps_the_entry(make_client: ClientFactory, tmp_path: Path) -> None:
    """停用 = 断开连接、配置保留；重新启用时去掉 enabled 字段（默认就是启用）。"""
    wd = _files(tmp_path, servers=_DEMO)
    async with make_client(_model(), mcp=_mcp(), workdata=wd) as client:
        resp = await client.patch("/api/settings/mcp-servers/demo", json={"enabled": False})
        assert resp.status_code == 200
        demo_entry = {"description": "测试服务", "command": "echo"}
        assert _user_file(wd)["servers"] == {"demo": {**demo_entry, "enabled": False}}
        [demo] = [s for s in resp.json()["servers"] if s["name"] == "demo"]
        assert demo["state"] == "disabled"
        await client.patch("/api/settings/mcp-servers/demo", json={"enabled": True})
        assert _user_file(wd)["servers"] == {"demo": demo_entry}


async def test_delete_user_server_removes_its_rules(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    wd = tmp_path / "wd"
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as c:
        await c.post("/api/settings/mcp-servers", json={"servers": [_memo()]})
        await c.put("/api/settings/approval-rules/tools/memo_add", json={"action": "auto"})
        await c.put("/api/settings/approval-rules/tools/demo_add_note", json={"action": "auto"})
        assert (await c.delete("/api/settings/mcp-servers/memo")).status_code == 204
        assert "memo" not in (_user_file(wd).get("servers") or {})
        assert _user_file(wd, "approval_rules.yaml")["tools"] == {"demo_add_note": "auto"}


async def test_removing_a_server_keeps_rules_of_a_longer_named_server(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    """删 memo 时不误删 memo_backup 服务的规则（积压小问题 E14：原来按"memo_"开头一律删）。"""
    wd = tmp_path / "wd"
    backup = _memo("memo_backup")
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as c:
        await c.post("/api/settings/mcp-servers", json={"servers": [_memo(), backup]})
        await c.put("/api/settings/approval-rules/tools/memo_add", json={"action": "auto"})
        await c.put("/api/settings/approval-rules/tools/memo_backup_add", json={"action": "auto"})
        assert (await c.delete("/api/settings/mcp-servers/memo")).status_code == 204
        assert _user_file(wd, "approval_rules.yaml")["tools"] == {"memo_backup_add": "auto"}


async def test_changes_wait_for_running_conversation(
    make_client: ClientFactory, tmp_path: Path, db: Pool
) -> None:
    wd = tmp_path / "wd"
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as c:
        thread = await ThreadRepo(db).create(model="fake-model")
        await RunRepo(db).create(thread_id=thread.id, model="fake-model", message="hi")
        resp = await c.post("/api/settings/mcp-servers", json={"servers": [_memo()]})
        assert (resp.status_code, resp.json()["detail"]) == (
            409,
            "有对话正在进行，等它结束或停止后再改",
        )
        assert _user_file(wd) == {"servers": {}}


async def test_tool_action_applies_without_reconnect(
    make_client: ClientFactory, tmp_path: Path, db: Pool
) -> None:
    mcp = _mcp()
    async with make_client(_model(), mcp=mcp, workdata=_files(tmp_path)) as client:
        thread = await ThreadRepo(db).create(model="fake-model")
        await RunRepo(db).create(thread_id=thread.id, model="fake-model", message="hi")
        connects = len(mcp.connected)
        resp = await client.put(
            "/api/settings/approval-rules/tools/demo_add_note", json={"action": "auto"}
        )
        assert resp.status_code == 200
        tools = {row["name"]: row["action"] for row in resp.json()["tools"]}
        assert tools["demo_add_note"] == "auto"
        assert len(mcp.connected) == connects


async def test_execute_rule_cannot_be_relaxed(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as client:
        resp = await client.put(
            "/api/settings/approval-rules/tools/execute", json={"action": "auto"}
        )
        assert (resp.status_code, resp.json()["detail"]) == (422, "执行命令固定先问，不能改")


async def test_broken_user_file_is_reported_and_kept(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    wd = _files(tmp_path)
    broken = wd / "config" / "mcp_servers.yaml"
    broken.write_text("servers: [\n", encoding="utf-8")
    async with make_client(_model(), mcp=_mcp(), workdata=wd) as c:
        listed = (await c.get("/api/settings/mcp-servers")).json()
        assert "mcp_servers.yaml" in (listed["config_error"] or "")
        resp = await c.post("/api/settings/mcp-servers", json={"servers": [_memo()]})
        assert resp.status_code == 422
        assert broken.read_text(encoding="utf-8") == "servers: [\n"


async def test_probe_names_missing_env(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), mcp=_mcp(), workdata=_files(tmp_path)) as client:
        body = {**_memo(), "env": {"K": "${NOT_SET_X}"}}
        result = (await client.post("/api/settings/mcp-servers/test", json=body)).json()
        assert result["ok"] is False
        assert "NOT_SET_X" in result["error"]
        assert ".env" in result["error"]


async def test_mcp_catalog_is_gone(make_client: ClientFactory) -> None:
    """MCP 目录已去掉（设计 2026-10-19 4.9）：只剩手动添加、粘贴 JSON。"""
    async with make_client(_model(), mcp=_mcp()) as client:
        assert (await client.get("/api/settings/mcp-catalog")).status_code == 404


async def test_raw_config_keeps_env_references(make_client: ClientFactory, tmp_path: Path) -> None:
    """编辑时拿到的是没替换的原文：密钥写成 ${变量名}，页面上看不到真实的值。"""
    files = _files(
        tmp_path, servers="servers:\n  gh:\n    command: echo\n    env: { T: '${HOME}' }\n"
    )
    async with make_client(_model(), mcp=_mcp(), workdata=files) as client:
        [gh] = [
            s
            for s in (await client.get("/api/settings/mcp-servers")).json()["servers"]
            if s["name"] == "gh"
        ]
        assert gh["config"]["env"] == {"T": "${HOME}"}


# ---- 技能：上传、停用、查看、删除（D22：只有 .workdata/skills/ 一处） ----

_SKILL_MD = "---\nname: 周报写作\ndescription: 按模板写周报\n---\n\n# 怎么写\n"


def _catalog(tmp_path: Path) -> SkillCatalog:
    excel = tmp_path / "skills" / "excel"
    excel.mkdir(parents=True)
    (excel / "SKILL.md").write_text(
        "---\nname: excel\ndescription: 处理表格\n---\n正文\n", encoding="utf-8"
    )
    return SkillCatalog(tmp_path / "skills", tmp_path / "skills.yaml")


def _upload(*files: tuple[str, str]) -> dict[str, Any]:
    return {
        "files": [
            {"path": path, "content": base64.b64encode(text.encode()).decode()}
            for path, text in files
        ]
    }


async def test_upload_then_list_and_detail(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), skills=_catalog(tmp_path)) as client:
        resp = await client.post(
            "/api/settings/skills",
            json=_upload(("周报写作/SKILL.md", _SKILL_MD), ("周报写作/ref/a.md", "a")),
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == "周报写作"
        listed = (await client.get("/api/settings/skills")).json()
        assert [s["id"] for s in listed] == ["excel", "周报写作"]
        detail = (await client.get("/api/settings/skills/周报写作")).json()
        assert (detail["body"], detail["files"]) == ("# 怎么写", ["SKILL.md", "ref/a.md"])


async def test_upload_same_name_conflicts(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), skills=_catalog(tmp_path)) as client:
        same = "---\nname: Excel\ndescription: d\n---\n"
        resp = await client.post("/api/settings/skills", json=_upload(("SKILL.md", same)))
        assert (resp.status_code, resp.json()["detail"]) == (409, "已有同名技能：Excel")


async def test_upload_bad_package_is_rejected(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), skills=_catalog(tmp_path)) as client:
        resp = await client.post("/api/settings/skills", json=_upload(("report.pdf", "x")))
        assert (resp.status_code, resp.json()["detail"]) == (
            422,
            "只能上传技能文件夹、.zip 或 SKILL.md",
        )
        bad = {"files": [{"path": "SKILL.md", "content": "不是 base64"}]}
        assert (await client.post("/api/settings/skills", json=bad)).status_code == 422
        assert sorted(p.name for p in (tmp_path / "skills").iterdir()) == ["excel"]


async def test_toggle_persists_in_user_state(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), skills=_catalog(tmp_path)) as client:
        resp = await client.patch("/api/settings/skills/excel", json={"enabled": False})
        assert (resp.status_code, resp.json()["enabled"]) == (200, False)
        assert yaml.safe_load((tmp_path / "skills.yaml").read_text(encoding="utf-8")) == {
            "version": 1,
            "disabled": ["excel"],
        }


async def test_page_edits_keep_the_version(make_client: ClientFactory, tmp_path: Path) -> None:
    # 服务清单带着版本号；审批规则是启动后手改的、没写版本号：页面写入的都是当前格式
    wd = _files(tmp_path, servers="version: 1\nservers: {}\n")
    skills = _catalog(tmp_path)
    (tmp_path / "skills.yaml").write_text("version: 1\nnote: 我的备注\ndisabled: []\n", "utf-8")
    async with make_client(_model(), mcp=_mcp(), workdata=wd, skills=skills) as client:
        resp = await client.post("/api/settings/mcp-servers", json={"servers": [_memo()]})
        assert resp.status_code == 201
        resp = await client.put(
            "/api/settings/approval-rules/tools/memo_echo", json={"action": "auto"}
        )
        assert resp.status_code == 200
        resp = await client.patch("/api/settings/skills/excel", json={"enabled": False})
        assert resp.status_code == 200
    assert _user_file(wd)["version"] == 1
    assert _user_file(wd, "approval_rules.yaml") == {
        "version": 1,
        "tools": {"memo_echo": "auto"},
    }
    assert yaml.safe_load((tmp_path / "skills.yaml").read_text(encoding="utf-8")) == {
        "version": 1,
        "note": "我的备注",
        "disabled": ["excel"],
    }


async def test_skills_list_has_last_used(
    make_client: ClientFactory, tmp_path: Path, db: Pool
) -> None:
    catalog = _catalog(tmp_path)
    (tmp_path / "skills" / "周报写作").mkdir()
    (tmp_path / "skills" / "周报写作" / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    thread = await ThreadRepo(db).create(model="fake-model")
    run = await RunRepo(db).create(thread_id=thread.id, model="fake-model", message="hi")
    usage = UsageRepo(db)
    await usage.add_tool_use(thread_id=thread.id, run_id=run.id, tool="read_file", skill="excel")
    async with make_client(_model(), skills=catalog) as client:
        listed = {s["id"]: s for s in (await client.get("/api/settings/skills")).json()}
        detail = (await client.get("/api/settings/skills/excel")).json()
        toggled = (await client.patch("/api/settings/skills/excel", json={"enabled": False})).json()
    assert listed["excel"]["last_used_at"] is not None
    assert listed["周报写作"]["last_used_at"] is None
    # 详情、启停的返回也带上（积压小问题 F3：原来只有列表有）
    assert detail["last_used_at"] == listed["excel"]["last_used_at"]
    assert toggled["last_used_at"] == listed["excel"]["last_used_at"]


async def test_delete_skill(make_client: ClientFactory, tmp_path: Path) -> None:
    async with make_client(_model(), skills=_catalog(tmp_path)) as client:
        await client.post("/api/settings/skills", json=_upload(("SKILL.md", _SKILL_MD)))
        assert (await client.delete("/api/settings/skills/周报写作")).status_code == 204
        assert (await client.get("/api/settings/skills/nope")).status_code == 404


async def test_hand_edit_after_startup_is_reported(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    """启动后才手改坏（字段类型写错）：列表照常返回，并指出哪个文件（审查 Important 4）。"""
    wd = _files(tmp_path, servers=_DEMO)
    async with make_client(_model(), mcp=_mcp(), workdata=wd) as client:
        assert (await client.get("/api/settings/mcp-servers")).json()["config_error"] is None
        (wd / "config" / "mcp_servers.yaml").write_text(
            "servers:\n  demo:\n    env: { PORT: 8080 }\n", encoding="utf-8"
        )
        resp = await client.get("/api/settings/mcp-servers")
        assert resp.status_code == 200
        assert "mcp_servers.yaml" in (resp.json()["config_error"] or "")
        assert "demo" in [s["name"] for s in resp.json()["servers"]]


async def test_tool_action_during_reconnect_is_kept(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    """重连中把工具改成"先问"：重连结束后不能被旧规则改回"自动"（审查 Important 5）。"""
    import asyncio

    mcp = FakeMcpClient(
        [mcp_tool(demo_add_note), mcp_tool(demo_list_notes, read_only=True)], connect_delay=0.3
    )
    files = _files(tmp_path, rules="tools:\n  demo_add_note: auto\n")
    async with make_client(_model(), mcp=mcp, workdata=files) as client:
        connects = len(mcp.connected)

        async def ask_soon() -> None:
            await until(lambda: len(mcp.connected) > connects, what="第一个请求开始重连")
            resp = await client.put(
                "/api/settings/approval-rules/tools/demo_add_note", json={"action": "ask"}
            )
            assert resp.status_code == 200

        await asyncio.gather(
            client.post("/api/settings/mcp-servers", json={"servers": [_memo()]}), ask_soon()
        )
        approvals = (await client.get("/api/settings/approval-rules")).json()
        tools = {row["name"]: row["action"] for row in approvals["tools"]}
        assert tools["demo_add_note"] == "ask"


async def test_approval_view_has_no_budget(make_client: ClientFactory) -> None:
    """预算刹车已去掉（D23）：审批设置里不再有预算。"""
    async with make_client(ScriptedChatModel(responses=[])) as client:
        view = (await client.get("/api/settings/approval-rules")).json()
        assert "budget" not in view


async def test_any_server_can_be_removed(make_client: ClientFactory, tmp_path: Path) -> None:
    """不再有"自带"的服务（D22）：首次写入的 files 服务也能删，它的审批规则一并删掉。"""
    wd = _files(
        tmp_path,
        servers="servers:\n  files:\n    command: echo\n",
        rules="tools:\n  files_write_file: auto\n  demo_add_note: ask\n",
    )
    async with make_client(_model(), mcp=_mcp(), workdata=wd) as client:
        assert (await client.delete("/api/settings/mcp-servers/files")).status_code == 204
    assert "files" not in (_user_file(wd).get("servers") or {})
    assert _user_file(wd, "approval_rules.yaml")["tools"] == {"demo_add_note": "ask"}


async def test_any_skill_can_be_deleted(make_client: ClientFactory, tmp_path: Path) -> None:
    """首次写入的 excel 技能也能删（D22）。"""
    skills = tmp_path / "skills"
    (skills / "excel").mkdir(parents=True)
    (skills / "excel" / "SKILL.md").write_text(
        "---\nname: excel\ndescription: 处理表格\n---\n正文\n", encoding="utf-8"
    )
    catalog = SkillCatalog(skills, state_file=tmp_path / "skills.yaml")
    async with make_client(_model(), skills=catalog) as client:
        assert (await client.delete("/api/settings/skills/excel")).status_code == 204
    assert not (skills / "excel").exists()


async def test_data_files_report_state(make_client: ClientFactory, tmp_path: Path) -> None:
    """设置页列出 .workdata 里各文件的位置与状态（D22）：写坏时给出原因。"""
    wd = _files(tmp_path, servers="servers: [\n")
    excel = wd / "skills" / "excel"
    excel.mkdir(parents=True)
    (excel / "SKILL.md").write_text("---\nname: excel\ndescription: 表格\n---\n", encoding="utf-8")
    catalog = SkillCatalog(wd / "skills", wd / "config" / "skills.yaml")
    async with make_client(_model(), mcp=_mcp(), workdata=wd, skills=catalog) as client:
        resp = await client.get("/api/settings/files")
    assert resp.status_code == 200
    files = {item["purpose"]: item for item in resp.json()}
    assert list(files) == ["MCP 服务清单", "审批规则", "停用的技能", "技能（1 个）"]
    servers = files["MCP 服务清单"]
    assert servers["path"].endswith("config/mcp_servers.yaml")
    assert servers["state"] == "error"
    assert "mcp_servers.yaml" in (servers["detail"] or "")
    assert (files["审批规则"]["state"], files["审批规则"]["detail"]) == ("ok", None)
    assert files["停用的技能"]["state"] == "missing"
    assert files["技能（1 个）"]["state"] == "ok"
