"""模型网关契约测试：所有 ModelGateway 实现都必须通过同一套测试。"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel

from agents.main_agent.models import LiteLLMProxyGateway, ModelGateway, ModelSpec
from common.errors import UpstreamError

MODEL_INFO_PAYLOAD = {
    "data": [
        {
            "model_name": "claude-opus-5-5",
            "litellm_params": {"model": "anthropic/claude-opus-5-5"},
            "model_info": {
                "mode": "chat",
                "max_input_tokens": 1000000,
                "input_cost_per_token": 4e-06,
                "output_cost_per_token": 2e-05,
                "supports_reasoning": True,
                "supports_vision": True,
            },
        },
        {
            "model_name": "embed-qwen3-0.6b",
            "litellm_params": {"model": "ollama/qwen3-embedding:0.6b"},
            "model_info": {"mode": "embedding"},
        },
    ]
}


def _healthy(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/model/info"
    return httpx.Response(200, json=MODEL_INFO_PAYLOAD)


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _litellm(handler: Callable[[httpx.Request], httpx.Response]) -> ModelGateway:
    return LiteLLMProxyGateway(
        "http://gateway:4000", "sk-test", transport=httpx.MockTransport(handler)
    )


IMPLEMENTATIONS = [_litellm]


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_list_models_returns_versions(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    models = await make(_healthy).list_models()
    by_name = {model.name: model for model in models}
    assert by_name["claude-opus-5-5"].mode == "chat"
    assert by_name["claude-opus-5-5"].max_input_tokens == 1000000
    assert by_name["embed-qwen3-0.6b"].mode == "embedding"


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_list_models_raises_upstream_error_when_down(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    with pytest.raises(UpstreamError):
        await make(_down).list_models()


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_chat_model_works_before_listing(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    assert isinstance(make(_down).chat_model("claude-opus-5-5"), BaseChatModel)


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_model_info_comes_from_last_listing(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    gateway = make(_healthy)
    assert (
        gateway.model_info("claude-opus-5-5") is None
    )  # 还没拉取过清单：不发起网络请求，直接返回空
    await gateway.list_models()
    info = gateway.model_info("claude-opus-5-5")
    assert info is not None
    assert (info.input_cost_per_token, info.output_cost_per_token) == (4e-06, 2e-05)
    assert gateway.model_info("not-registered") is None


# ---- 管理页面增删改模型：走网关的模型管理接口（D21，先行验证 2026-10-18） ----

SPEC = ModelSpec(
    name="glm-5",
    upstream="litellm_proxy/glm-5",
    api_base="os.environ/UPSTREAM_GATEWAY_URL",
    api_key="os.environ/UPSTREAM_GATEWAY_KEY",
    mode="chat",
    max_input_tokens=200000,
    max_output_tokens=32000,
    input_cost_per_token=1e-06,
    output_cost_per_token=2e-06,
    supports_function_calling=True,
)


class _Recorder:
    """记下发给网关的请求；status 不是 200 时模拟网关拒绝。"""

    def __init__(self, status: int = 200, fail: tuple[str, ...] = ()) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.fail = fail  # 这些路径（按顺序第一次请求时）模拟网关拒绝

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/model/info":
            return httpx.Response(200, json=MODEL_INFO_PAYLOAD)
        if self.status != 200 or path in self.fail:
            self.fail = tuple(p for p in self.fail if p != path)
            return httpx.Response(
                self.status if self.status != 200 else 400,
                json={"error": {"message": "model name exists"}},
            )
        if path in ("/model/new", "/model/delete") or path.endswith("/update"):
            return httpx.Response(200, json={"model_id": "new-1", "model_name": "glm-5"})
        if path == "/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "p"}}]})
        if path == "/embeddings":
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        return httpx.Response(404)

    def body(self, path: str) -> dict[str, Any]:
        [request] = [r for r in self.requests if r.url.path == path]
        return dict(json.loads(request.content))


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_add_model_puts_price_in_litellm_params(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    recorder = _Recorder()
    await make(recorder).add_model(SPEC)
    body = recorder.body("/model/new")
    params, info = body["litellm_params"], body["model_info"]
    assert body["model_name"] == "glm-5"
    assert (params["model"], params["api_key"]) == (
        "litellm_proxy/glm-5",
        "os.environ/UPSTREAM_GATEWAY_KEY",
    )
    assert (params["input_cost_per_token"], params["output_cost_per_token"]) == (1e-06, 2e-06)
    assert "input_cost_per_token" not in info
    assert (info["mode"], info["max_input_tokens"], info["supports_function_calling"]) == (
        "chat",
        200000,
        True,
    )


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_update_replaces_the_deployment(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    """先行验证（2026-10-18）：网关的 PATCH 是合并写入，传 null 也去不掉 thinking、max_tokens。

    所以修改 = 先按新内容新增一份、再删掉旧的；关掉"思考"后网关里就真的没有了
    （审查 Important 6）。
    """
    recorder = _Recorder()
    await make(recorder).update_model("old-1", SPEC)
    paths = [(r.method, r.url.path) for r in recorder.requests if r.url.path != "/model/info"]
    assert paths == [("POST", "/model/new"), ("POST", "/model/delete")]
    assert "thinking" not in recorder.body("/model/new")["litellm_params"]
    assert recorder.body("/model/delete") == {"id": "old-1"}


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_update_rolls_back_when_old_cannot_be_deleted(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    """删旧的失败时把刚加的新的删掉，不留同名的两份（网关会把调用分摊到两份上）。"""
    recorder = _Recorder(fail=("/model/delete",))
    with pytest.raises(UpstreamError):
        await make(recorder).update_model("old-1", SPEC)
    deletes = [json.loads(r.content) for r in recorder.requests if r.url.path == "/model/delete"]
    assert deletes == [{"id": "old-1"}, {"id": "new-1"}]


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_delete_model(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    recorder = _Recorder()
    await make(recorder).delete_model("id-1")
    assert recorder.body("/model/delete") == {"id": "id-1"}


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_listing_marks_db_models(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    payload = {
        "data": [
            {**MODEL_INFO_PAYLOAD["data"][0]},
            {
                "model_name": "glm-5",
                "litellm_params": {"model": "litellm_proxy/glm-5"},
                "model_info": {"id": "id-1", "db_model": True, "mode": "chat"},
            },
        ]
    }
    gateway = make(lambda _: httpx.Response(200, json=payload))
    in_file, added = await gateway.list_models()
    # 写在网关配置文件里的模型没有编号（页面上不能改）；网关数据库里的有
    assert (in_file.id, in_file.upstream) == (None, "anthropic/claude-opus-5-5")
    assert added.id == "id-1"


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_gateway_rejection_becomes_upstream_error(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    with pytest.raises(UpstreamError, match="model name exists"):
        await make(_Recorder(status=400)).add_model(SPEC)


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_test_model_reports_latency_or_reason(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    recorder = _Recorder()
    gateway = make(recorder)
    await gateway.list_models()
    chat = await gateway.test_model("claude-opus-5-5")
    assert (chat.ok, chat.error) == (True, None)
    assert chat.latency_ms >= 0
    assert recorder.body("/chat/completions")["max_tokens"] == 1
    embedding = await gateway.test_model("embed-qwen3-0.6b")
    assert embedding.ok is True
    assert recorder.body("/embeddings")["model"] == "embed-qwen3-0.6b"
    failed = await make(_Recorder(status=500)).test_model("claude-opus-5-5")
    assert failed.ok is False
    assert (failed.error or "").startswith("调用失败")


# ---- 提示缓存（设计 2026-10-23 4.1）：开关写成网关的缓存断点参数 ----

CACHE_POINTS = [{"location": "message", "role": "system"}, {"location": "message", "index": -1}]


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_prompt_caching_is_saved_as_injection_points(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    cached = _Recorder()
    info = await make(cached).add_model(SPEC.model_copy(update={"supports_prompt_caching": True}))
    assert cached.body("/model/new")["litellm_params"]["cache_control_injection_points"] == (
        CACHE_POINTS
    )
    assert info.supports_prompt_caching
    plain = _Recorder()
    await make(plain).add_model(SPEC)
    assert "cache_control_injection_points" not in plain.body("/model/new")["litellm_params"]


@pytest.mark.parametrize("make", IMPLEMENTATIONS)
async def test_model_info_reads_caching_from_litellm_params(
    make: Callable[[Callable[[httpx.Request], httpx.Response]], ModelGateway],
) -> None:
    """以网关里真正生效的参数为准：有缓存断点才算开着。"""
    payload = {
        "data": [
            {
                "model_name": "cached",
                "litellm_params": {
                    "model": "litellm_proxy/claude-x",
                    "cache_control_injection_points": CACHE_POINTS,
                },
                "model_info": {"mode": "chat"},
            },
            {
                "model_name": "plain",
                "litellm_params": {"model": "litellm_proxy/claude-y"},
                "model_info": {"mode": "chat", "supports_prompt_caching": True},
            },
        ]
    }
    models = await make(lambda _: httpx.Response(200, json=payload)).list_models()
    assert {m.name: m.supports_prompt_caching for m in models} == {"cached": True, "plain": False}
