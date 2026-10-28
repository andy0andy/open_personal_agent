"""设置页的设置（D22）：存在数据库的 app_settings 表，同名环境变量优先。"""

from typing import Any

import pytest
from httpx import AsyncClient

from agents.main_agent.models import ModelInfo
from agents.tests.fakes import FakeGateway, ScriptedChatModel
from backend.settings.app_settings import AppSettingsRepo
from backend.tests.conftest import ClientFactory
from common.db import Pool
from config.settings import load_settings

pytestmark = pytest.mark.integration


def _model() -> ScriptedChatModel:
    return ScriptedChatModel(responses=[])


async def _views(client: AsyncClient) -> dict[str, dict[str, Any]]:
    resp = await client.get("/api/settings/app")
    assert resp.status_code == 200
    return {view["key"]: view for view in resp.json()}


async def test_lists_settings_with_sources(
    make_client: ClientFactory, db: Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT__STREAM_IDLE_TIMEOUT", "99")
    await AppSettingsRepo(db).put("knowledge.recall_top_k", 3)
    async with make_client(_model()) as client:
        views = await _views(client)
    idle = views["agent.stream_idle_timeout"]
    assert (idle["source"], idle["editable"], idle["env_name"]) == (
        "env",
        False,
        "AGENT__STREAM_IDLE_TIMEOUT",
    )
    assert views["knowledge.recall_top_k"]["source"] == "db"
    chunk = views["knowledge.chunk_tokens"]
    assert (chunk["source"], chunk["value"], chunk["default"]) == ("default", 600, 600)
    assert views["agent.default_model"]["apply"] == "now"
    assert views["knowledge.embedding_model"]["editable"] is False
    assert views["models.sources"]["editable"] is False


async def test_update_saves_and_marks_restart_pending(make_client: ClientFactory) -> None:
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/knowledge.recall_top_k", json={"value": 3})
        assert resp.status_code == 200
        view = resp.json()
        assert (view["source"], view["restart_pending"]) == ("db", True)
        assert (view["value"], view["upcoming"]) == (5, 3)  # 运行中的还是旧值，重启后才用 3
        again = (await _views(client))["knowledge.recall_top_k"]
        assert (again["source"], again["restart_pending"]) == ("db", True)


async def test_update_stores_validated_value(make_client: ClientFactory, db: Pool) -> None:
    """存的是校验后的值（积压小问题 F17）：开关项传 "false" 存成 False，重启后读出来就是关，
    不会因为"false"与 False 不相等一直显示"待重启"。"""
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/knowledge.auto_extract", json={"value": "false"})
        assert resp.status_code == 200
        assert resp.json()["upcoming"] is False
    assert (await AppSettingsRepo(db).all())["knowledge.auto_extract"] is False


async def test_update_default_model_applies_now(make_client: ClientFactory) -> None:
    gateway = FakeGateway(
        _model(), models=[ModelInfo(name="fake-model"), ModelInfo(name="fake-model-2")]
    )
    async with make_client(_model(), gateway=gateway) as client:
        resp = await client.put(
            "/api/settings/app/agent.default_model", json={"value": "fake-model-2"}
        )
        assert resp.status_code == 200
        view = resp.json()
        assert (view["value"], view["source"], view["restart_pending"]) == (
            "fake-model-2",
            "db",
            False,
        )
        created = (await client.post("/api/threads", json={})).json()
        assert created["model"] == "fake-model-2"


async def test_update_rejects_env_overridden_setting(
    make_client: ClientFactory, db: Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT__STREAM_IDLE_TIMEOUT", "99")
    await AppSettingsRepo(db).put("agent.stream_idle_timeout", 30)
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/agent.stream_idle_timeout", json={"value": 60})
    assert resp.status_code == 409
    assert "AGENT__STREAM_IDLE_TIMEOUT" in resp.json()["detail"]
    assert "make restart" in resp.json()["detail"]
    assert (await AppSettingsRepo(db).all())["agent.stream_idle_timeout"] == 30


async def test_update_rejects_invalid_value(make_client: ClientFactory) -> None:
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/workspace.command_timeout", json={"value": 0})
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("取值不合规")


async def test_update_rejects_out_of_range_value(make_client: ClientFactory) -> None:
    """超出范围的值会让对话或文档整体失效（终审 I3）：页面上就拒绝，用中文说明。"""
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/knowledge.recall_top_k", json={"value": -1})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "取值不合规：不能小于 0"
        resp = await client.put(
            "/api/settings/app/knowledge.recall_min_similarity", json={"value": 7}
        )
        assert resp.json()["detail"] == "取值不合规：不能大于 1"
        resp = await client.put("/api/settings/app/knowledge.ingest_batch_size", json={"value": 0})
        assert resp.json()["detail"] == "取值不合规：应大于 0"
        views = await _views(client)
    assert views["knowledge.recall_top_k"]["source"] == "default"  # 被拒的值没有存下


async def test_update_checks_against_saved_values(make_client: ClientFactory) -> None:
    """跨项检查要和库里已存、还没生效的值一起看（终审 I3）。"""
    async with make_client(_model()) as client:
        timeout = "/api/settings/app/workspace.command_timeout"
        resp = await client.put(timeout, json={"value": 900})  # 运行中的最长时限是 600
        assert resp.status_code == 422
        assert resp.json()["detail"] == "取值不合规：命令默认时限不能超过最长时限"
        assert (await client.put(timeout, json={"value": 500})).status_code == 200
        # 运行中的默认时限还是 120，但重启后是 500
        resp = await client.put(
            "/api/settings/app/workspace.max_command_timeout", json={"value": 400}
        )
        assert resp.status_code == 422
        overlap = "/api/settings/app/knowledge.chunk_overlap_tokens"
        resp = await client.put(overlap, json={"value": 600})
        assert resp.json()["detail"] == "取值不合规：相邻两块的重叠要小于每块的大小"


async def test_reset_checks_against_saved_values(make_client: ClientFactory) -> None:
    """恢复默认后与库里存的其他项不一致时也拒绝（终审 I3）：否则重启后这一节全按默认值。"""
    async with make_client(_model()) as client:
        await client.put("/api/settings/app/workspace.max_command_timeout", json={"value": 1000})
        await client.put("/api/settings/app/workspace.command_timeout", json={"value": 800})
        resp = await client.delete("/api/settings/app/workspace.max_command_timeout")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "取值不合规：命令默认时限不能超过最长时限"
        views = await _views(client)
    assert views["workspace.max_command_timeout"]["upcoming"] == 1000


async def test_update_rejects_read_only(make_client: ClientFactory) -> None:
    async with make_client(_model()) as client:
        resp = await client.put(
            "/api/settings/app/knowledge.embedding_model", json={"value": "other"}
        )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "这一项不能在页面上改"


async def test_unknown_key_is_404(make_client: ClientFactory) -> None:
    async with make_client(_model()) as client:
        resp = await client.put("/api/settings/app/no.such_key", json={"value": 1})
    assert resp.status_code == 404


async def test_reset_returns_to_default(make_client: ClientFactory) -> None:
    async with make_client(_model()) as client:
        await client.put("/api/settings/app/knowledge.recall_top_k", json={"value": 3})
        resp = await client.delete("/api/settings/app/knowledge.recall_top_k")
        assert resp.status_code == 200
        view = resp.json()
        assert (view["source"], view["restart_pending"]) == ("default", False)


async def test_startup_reads_stored_settings(db: Pool, monkeypatch: pytest.MonkeyPatch) -> None:
    # 测试不读 .env（设计 2026-10-23 7.6）：必填的库地址与网关密钥显式给假值
    monkeypatch.setenv("DATABASE_URL", "postgresql://agent:agent@127.0.0.1:55432/agent_test")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    repo = AppSettingsRepo(db)
    await repo.put("max_upload_mb", 20)
    await repo.put("max_upload_mb", 30)  # 再存一次是更新，不是新增
    assert await repo.all() == {"max_upload_mb": 30}
    assert load_settings(await repo.all()).max_upload_mb == 30


async def test_untouched_setting_is_not_pending(make_client: ClientFactory) -> None:
    """没在页面上改过的项：重启后还是运行中的值，不显示"重启后生效"（只读项也一样）。"""
    async with make_client(_model(), upload_limit_mb=1) as client:
        views = await _views(client)
    upload = views["max_upload_mb"]
    assert (upload["value"], upload["upcoming"], upload["restart_pending"]) == (1, 1, False)
    assert views["knowledge.embedding_model"]["restart_pending"] is False


async def test_reset_default_model_set_by_env_does_not_need_the_code_default(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认对话模型由环境变量指定时，"恢复默认"回到的是环境变量的值：不再要求代码里的默认模型
    在网关里（积压小问题 F17）。"""
    monkeypatch.setenv("AGENT__DEFAULT_MODEL", "fake-model")
    async with make_client(_model()) as client:
        resp = await client.delete("/api/settings/app/agent.default_model")
    assert resp.status_code == 200
