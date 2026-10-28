"""模型页接口（D21、D22）：模型存进网关（这里是假网关），都能改能删；删掉后会话改用默认模型。"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agents.main_agent.models import ModelInfo
from agents.main_agent.runtime import UsageTotals
from agents.tests.fakes import FakeGateway, ScriptedChatModel
from backend.runs import RunRepo
from backend.settings.app_settings import AppSettingsRepo
from backend.tests.conftest import ClientFactory
from backend.threads import ThreadRepo
from common.db import Pool

pytestmark = pytest.mark.integration


def _gateway() -> FakeGateway:
    return FakeGateway(
        ScriptedChatModel(responses=[AIMessage(content="好")]),
        models=[ModelInfo(name="fake-model"), ModelInfo(name="embed-fake", mode="embedding")],
    )


def _input(name: str = "glm-5", **fields: Any) -> dict[str, Any]:
    return {
        "name": name,
        "source": "upstream",
        "upstream_id": name,
        "mode": "chat",
        "max_input_tokens": 200000,
        "max_output_tokens": 32000,
        "price_input": 1,
        "price_output": 2,
        "supports_reasoning": False,
        "supports_vision": False,
        "supports_function_calling": True,
        **fields,
    }


async def test_add_list_and_price_unit(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input())
        assert resp.status_code == 201
        assert (resp.json()["id"], resp.json()["source_label"]) == ("id-1", "公司 LiteLLM 网关")
        assert "builtin" not in resp.json()
        [spec] = gateway.added
        assert (spec.upstream, spec.input_cost_per_token, spec.output_cost_per_token) == (
            "litellm_proxy/glm-5",
            1e-06,
            2e-06,
        )
        assert spec.api_key == "os.environ/UPSTREAM_GATEWAY_KEY"
        listed = (await client.get("/api/settings/models")).json()
        assert [m["name"] for m in listed["models"]] == ["fake-model", "embed-fake", "glm-5"]
        assert (listed["default_chat"], listed["models"][0]["is_default_chat"]) == (
            "fake-model",
            True,
        )


async def test_claude_with_thinking_gets_adaptive_params(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        body = _input("claude-x", supports_reasoning=True, max_output_tokens=128000)
        assert (await client.post("/api/settings/models", json=body)).status_code == 201
        assert gateway.added[0].extra_params == {
            "thinking": {"type": "adaptive"},
            "max_tokens": 64000,
        }


async def test_prompt_caching_only_applies_to_claude(make_client: ClientFactory) -> None:
    """提示缓存只对 Claude 生效（设计 2026-10-23 4.1）：别的模型勾了也不写进网关。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        for body in (
            _input("glm-5", supports_prompt_caching=True),
            _input("claude-x", supports_prompt_caching=True),
        ):
            assert (await client.post("/api/settings/models", json=body)).status_code == 201
        glm, claude = gateway.added
        assert (glm.supports_prompt_caching, claude.supports_prompt_caching) == (False, True)
        listed = (await client.get("/api/settings/models")).json()["models"]
        by_name = {m["name"]: m for m in listed}
        assert by_name["claude-x"]["supports_prompt_caching"] is True
        assert by_name["glm-5"]["supports_prompt_caching"] is False


async def test_add_model_with_existing_name_conflicts(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input("fake-model"))
        assert (resp.status_code, resp.json()["detail"]) == (409, "已有同名模型：fake-model")


@pytest.mark.parametrize("price", [-1, "Infinity"])
async def test_price_must_be_finite_and_not_negative(
    make_client: ClientFactory, price: object
) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input(price_input=price))
        assert resp.status_code == 422
        assert gateway.added == []


async def test_source_must_match_mode(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input(mode="embedding"))
        assert resp.status_code == 422
        assert "来源" in resp.json()["detail"]


async def test_model_outside_the_gateway_db_is_read_only(make_client: ClientFactory) -> None:
    """写在网关配置文件里的模型没有部署编号（D22 之后只有手加的才会）：页面上改不了，说明原因。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        for resp in (
            await client.put("/api/settings/models/embed-fake", json=_input("embed-fake")),
            await client.delete("/api/settings/models/embed-fake"),
        ):
            assert resp.status_code == 409
            assert "config/models.yaml" in resp.json()["detail"]


async def test_cannot_delete_default(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        await client.put("/api/settings/models/default", json={"name": "glm-5"})
        resp = await client.delete("/api/settings/models/glm-5")
        assert (resp.status_code, resp.json()["detail"]) == (409, "先换掉默认再删")


async def test_delete_reassigns_threads_to_default(make_client: ClientFactory, db: Pool) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        threads = ThreadRepo(db)
        for _ in range(2):
            await threads.create(model="glm-5")
        listed = (await client.get("/api/settings/models")).json()
        assert next(m for m in listed["models"] if m["name"] == "glm-5")["sessions"] == 2
        resp = await client.delete("/api/settings/models/glm-5")
        assert resp.json() == {"reassigned": 2}
        assert {t.model for t in await threads.list_active()} == {"fake-model"}
        assert [m["name"] for m in (await client.get("/api/settings/models")).json()["models"]] == [
            "fake-model",
            "embed-fake",
        ]


async def test_gateway_failure_leaves_nothing(make_client: ClientFactory) -> None:
    gateway = _gateway()
    gateway.fail_next_add = True
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input())
        assert resp.status_code == 503
        names = [m["name"] for m in (await client.get("/api/settings/models")).json()["models"]]
        assert "glm-5" not in names


async def test_set_default_chat_persists_and_applies(make_client: ClientFactory, db: Pool) -> None:
    """默认对话模型存进设置表（D22），立即生效。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        resp = await client.put("/api/settings/models/default", json={"name": "glm-5"})
        assert resp.json()["default_chat"] == "glm-5"
        assert (await AppSettingsRepo(db).all())["agent.default_model"] == "glm-5"
        assert (await client.post("/api/threads", json={})).json()["model"] == "glm-5"
        for name in ("embed-fake", "nope"):
            bad = await client.put("/api/settings/models/default", json={"name": name})
            assert bad.status_code == 422


async def test_test_model_reports_result(make_client: ClientFactory) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        ok = (await client.post("/api/settings/models/fake-model/test", json={})).json()
        assert ok["ok"] is True
        await client.post("/api/settings/models", json=_input("broken-1"))
        failed = (await client.post("/api/settings/models/broken-1/test", json={})).json()
        assert (failed["ok"], failed["error"]) == (False, "调用失败：模拟的失败")


async def test_every_model_is_editable(make_client: ClientFactory) -> None:
    """模型全部在网关数据库里（D22）：没有只读的"自带模型"，导入的也能改、能删。"""
    gateway = FakeGateway(
        ScriptedChatModel(responses=[AIMessage(content="好")]),
        models=[
            ModelInfo(name="fake-model", id="id-0", upstream="litellm_proxy/fake-model"),
            ModelInfo(name="glm-5", id="id-1", upstream="litellm_proxy/glm-5"),
        ],
    )
    async with make_client(gateway.model, gateway=gateway) as client:
        updated = await client.put("/api/settings/models/glm-5", json=_input("glm-5"))
        assert updated.status_code == 200
        assert (await client.delete("/api/settings/models/glm-5")).status_code == 200


async def test_model_cannot_be_named_default(make_client: ClientFactory) -> None:
    """名叫 default 的模型改不了（PUT /default 是"设默认模型"的地址，F4）：新增时就拒绝。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        resp = await client.post("/api/settings/models", json=_input("default"))
        assert resp.status_code == 422
        assert resp.json()["detail"] == "模型名不能叫 default：和“设默认模型”的接口地址冲突"
        assert gateway.added == []


@pytest.mark.parametrize("status", ["running", "interrupted"])
async def test_delete_model_in_use_conflicts(
    make_client: ClientFactory, db: Pool, status: str
) -> None:
    """有运行正在用（运行中、等审批）的模型不能删（积压小问题 F9）：删了它后面的调用都会失败。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        thread = await ThreadRepo(db).create(model="glm-5")
        run = await RunRepo(db).create(thread_id=thread.id, model="glm-5", message="hi")
        async with db.connection() as conn:
            await conn.execute("UPDATE runs SET status = %s WHERE id = %s", (status, run.id))
        resp = await client.delete("/api/settings/models/glm-5")
        assert resp.status_code == 409
        assert resp.json()["detail"] == (
            "有对话正在用这个模型（运行中或等审批），等它结束或停止后再删"
        )
        assert "glm-5" in [m.name for m in await gateway.list_models()]  # 网关里没删
        assert (await ThreadRepo(db).get(thread.id)).model == "glm-5"


async def test_finished_runs_do_not_block_deleting_a_model(
    make_client: ClientFactory, db: Pool
) -> None:
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        thread = await ThreadRepo(db).create(model="glm-5")
        runs = RunRepo(db)
        run = await runs.create(thread_id=thread.id, model="glm-5", message="hi")
        await runs.finish(run.id, status="completed", error=None, usage=UsageTotals())
        resp = await client.delete("/api/settings/models/glm-5")
        assert resp.status_code == 200


async def test_default_chat_model_cannot_become_embedding(make_client: ClientFactory) -> None:
    """默认对话模型改成向量模型后，默认值与下拉框对不上（积压小问题 F12）：先换默认再改类型。"""
    gateway = _gateway()
    async with make_client(gateway.model, gateway=gateway) as client:
        await client.post("/api/settings/models", json=_input())
        await client.put("/api/settings/models/default", json={"name": "glm-5"})
        resp = await client.put(
            "/api/settings/models/glm-5",
            json=_input(mode="embedding", source="ollama", upstream_id="bge-m3"),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "这是默认对话模型，不能改成向量模型：先换一个默认对话模型"
