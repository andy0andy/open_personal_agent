"""先行验证 V1 / V2 / V3 / V6：调用真实模型，会产生少量费用。运行：make smoke。

前提：make infra-up 已启动网关与 Ollama；.env 里填好了 Anthropic 与 SMOKE_ALT_MODEL 对应厂商的密钥。
每个测试用 print 输出观察到的事实（-s 模式可见），据此填写 docs/decisions/M0-先行验证结论.md。
"""

import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.integrations import McpAdaptersClient
from agents.main_agent.knowledge import (
    DocumentLibrary,
    DocumentRepo,
    LocalDiskBlobStore,
    MarkItDownParser,
    NewKnowledge,
    PgKnowledgeStore,
)
from agents.main_agent.models import EMBEDDING_DIMENSIONS, LiteLLMProxyEmbedder, LiteLLMProxyGateway
from agents.main_agent.models.litellm_proxy import CACHE_POINTS
from agents.main_agent.runtime import (
    ApprovalAnswer,
    ApprovalRequired,
    Event,
    MainAgent,
    MessageDelta,
    RunFinished,
    ToolDecision,
    ToolStarted,
)
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeKnowledgeStore, FakeSandbox
from common.db import Pool
from config import McpServerConfig, get_settings

pytestmark = pytest.mark.live

CLAUDE = os.environ.get("SMOKE_CLAUDE_MODEL", "claude-opus-4-6")
ALT = os.environ.get("SMOKE_ALT_MODEL", "gemini-3.5-flash")
EMBED = "embed-qwen3-0.6b"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
_SYSTEM_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "system.md"
_DEMO_MCP = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "demo_server.py"


@pytest.fixture(scope="module")
async def gateway() -> LiteLLMProxyGateway:
    settings = get_settings()
    gw = LiteLLMProxyGateway(
        settings.litellm_base_url, settings.litellm_master_key.get_secret_value()
    )
    await gw.list_models()
    return gw


def _agent(gateway: LiteLLMProxyGateway) -> MainAgent:
    return MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt="你是测试助手，严格按用户要求使用工具，回答尽量简短。",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )


def _short_id(thread_id: str) -> str:
    return "c_" + hashlib.md5(thread_id.encode()).hexdigest()[:8]


async def _run(agent: MainAgent, thread_id: str, message: str, model: str) -> list[Event]:
    return [
        e
        async for e in agent.run(
            thread_id=thread_id,
            thread_short_id=_short_id(thread_id),
            run_id="smoke",
            message=message,
            model=model,
        )
    ]


async def _ai_messages(agent: MainAgent, model: str, thread_id: str) -> list[AIMessage]:
    # 冒烟测试需要查看存档里的原始消息，这里直接访问内部组装好的图
    graph = agent._graph_for(model, "ask")
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return [m for m in state.values["messages"] if isinstance(m, AIMessage)]


def _assert_completed(events: list[Event], label: str) -> None:
    last = events[-1]
    print(f"{label} 结束事件：{last}")
    assert isinstance(last, RunFinished)
    assert last.status == "completed", last.error


async def test_v1_claude_thinking_with_multi_turn_tools(gateway: LiteLLMProxyGateway) -> None:
    agent = _agent(gateway)
    first = await _run(
        agent,
        "v1",
        "先用 write_file 把 hello 写入 /notes.txt，再用 read_file 读回来，告诉我文件内容。",
        CLAUDE,
    )
    _assert_completed(first, "V1 第 1 轮")
    tools = {e.name for e in first if isinstance(e, ToolStarted)}
    print("V1 第 1 轮工具调用：", tools)
    assert {"write_file", "read_file"} <= tools

    second = await _run(agent, "v1", "把 /notes.txt 改成 world，再读回来确认。", CLAUDE)
    _assert_completed(second, "V1 第 2 轮（历史里带着第 1 轮的思考内容）")

    def _has_thinking(message: AIMessage) -> bool:
        blocks = message.content if isinstance(message.content, list) else []
        in_blocks = any(isinstance(b, dict) and b.get("type") == "thinking" for b in blocks)
        extra = message.additional_kwargs
        return in_blocks or bool(extra.get("thinking_blocks") or extra.get("reasoning_content"))

    ai = await _ai_messages(agent, CLAUDE, "v1")
    print("V1 存档中带思考内容的回复数：", sum(_has_thinking(m) for m in ai), "/", len(ai))


async def test_v2_usage_reported_while_streaming(gateway: LiteLLMProxyGateway) -> None:
    agent = _agent(gateway)
    _assert_completed(await _run(agent, "v2", "用一句话介绍你自己。", CLAUDE), "V2")
    usage: list[Any] = [m.usage_metadata for m in await _ai_messages(agent, CLAUDE, "v2")]
    print("V2 每次调用的用量：", usage)
    last = usage[-1]
    assert last is not None
    assert last["input_tokens"] > 0
    assert last["output_tokens"] > 0
    print("V2 输入明细（缓存）：", last.get("input_token_details"))
    print("V2 输出明细（思考）：", last.get("output_token_details"))


async def test_v3_switch_models_mid_thread(gateway: LiteLLMProxyGateway) -> None:
    agent = _agent(gateway)
    for index, model in enumerate([CLAUDE, ALT, CLAUDE], start=1):
        events = await _run(
            agent, "v3", f"第 {index} 轮：记住数字 {index}，然后复述你记住的所有数字。", model
        )
        _assert_completed(events, f"V3 第 {index} 轮（{model}）")


async def test_v6_local_embedding_dims_and_speed() -> None:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.litellm_master_key.get_secret_value()}"}
    async with httpx.AsyncClient(
        base_url=settings.litellm_base_url, headers=headers, timeout=120
    ) as client:

        async def embed(texts: list[str]) -> dict[str, Any]:
            resp = await client.post("/v1/embeddings", json={"model": EMBED, "input": texts})
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
            return body

        warmup = await embed(["预热"])
        dims = len(warmup["data"][0]["embedding"])
        print("V6 向量维度：", dims, "用量字段：", warmup.get("usage"))
        assert dims == 1024

        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            await embed(["今天下午三点和产品经理开会讨论需求"])
            latencies.append(time.perf_counter() - start)
        median_ms = statistics.median(latencies) * 1000
        print(f"V6 单条查询中位耗时：{median_ms:.0f} 毫秒")

        chunk = "个人知识库中的一段文档内容，用于测试批量向量化的速度。" * 25  # 约 600 token
        start = time.perf_counter()
        for _ in range(10):
            await embed([chunk] * 30)
        batch_seconds = time.perf_counter() - start
        print(f"V6 300 个片段耗时：{batch_seconds:.1f} 秒")

        assert median_ms < 300
        assert batch_seconds < 60


async def test_embedder_through_gateway() -> None:
    """M3a：知识库用的向量化接口经网关调用本机向量模型，维度为 1024。"""
    settings = get_settings()
    embedder = LiteLLMProxyEmbedder(
        settings.litellm_base_url, settings.litellm_master_key.get_secret_value(), EMBED
    )
    vectors = await embedder.embed(["用户喜欢喝茶", "今天天气不错"])
    assert [len(v) for v in vectors] == [EMBEDDING_DIMENSIONS, EMBEDDING_DIMENSIONS]


async def test_memory_extraction_and_title_with_real_model(gateway: LiteLLMProxyGateway) -> None:
    """M3a：会后提取记忆、生成标题用会话所选的模型；模型只回 JSON，由我们自己解析。"""
    store = FakeKnowledgeStore()
    await store.add(NewKnowledge(content="用户每天早上喝美式咖啡", source="manual"))
    agent = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        knowledge=store,
    )
    message = "我上个月换工作了，现在在字节做数据平台。另外我不喝咖啡了，改喝茶。帮我写个周报模板。"
    answer = "好的，下面是周报模板……"
    usage = [
        u
        async for u in agent.extract_memories(
            thread_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            model=CLAUDE,
            message=message,
            answer=answer,
        )
    ]
    contents = [item.content for item in store.items.values()]
    print(f"提取后的记忆：{contents}；用量：{usage}")
    assert any("字节" in content for content in contents)
    assert not any("美式咖啡" in content for content in contents)  # 过时的记忆被更新或删除
    assert [u.caller for u in usage] == ["memory_extraction"]

    title, title_usage = await agent.generate_title(
        thread_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        model=CLAUDE,
        message=message,
        answer=answer,
    )
    print(f"标题：{title}；用量：{title_usage}")
    assert 0 < len(title) <= 30
    assert [u.caller for u in title_usage] == ["title"]


async def test_document_ingest_and_cited_answer(
    gateway: LiteLLMProxyGateway, db: Pool, tmp_path: Path
) -> None:
    """M3b：真实向量模型把文档入库；真实模型回答时照抄检索结果给出的出处链接。需要 make test-up。"""
    settings = get_settings()
    embedder = LiteLLMProxyEmbedder(
        settings.litellm_base_url, settings.litellm_master_key.get_secret_value(), EMBED
    )
    store = PgKnowledgeStore(db, embedder)
    library = DocumentLibrary(
        DocumentRepo(db),
        store,
        MarkItDownParser(),
        LocalDiskBlobStore(tmp_path / "knowledge"),
        max_bytes=10 * 1024 * 1024,
    )
    data = await asyncio.to_thread((_FIXTURES / "handbook.docx").read_bytes)

    async def stream() -> Any:
        yield data

    document = await library.add("员工手册.docx", stream(), media_type="application/octet-stream")
    started = time.monotonic()
    await library.ingest(document.id)
    done = await library.get(document.id)
    print(f"入库：{done.item_count} 段，{time.monotonic() - started:.1f} 秒")
    assert done.status == "done"

    system_prompt = await asyncio.to_thread(_SYSTEM_PROMPT.read_text, encoding="utf-8")
    agent = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt=system_prompt,
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
        knowledge=store,
        documents=library,
    )
    events = await _run(
        agent, str(uuid.uuid4()), "公司年假几天？请查一下知识库，并注明出处。", CLAUDE
    )
    _assert_completed(events, "带出处的回答")
    answer = "".join(
        e.text for e in events if isinstance(e, MessageDelta) and e.agent_path == ["main"]
    )
    print(f"回答：{answer}")
    links = re.findall(r"\(#kb-([0-9a-f-]{36})\)", answer)
    assert links, "回答里没有出处链接"
    cited = [await store.get(uuid.UUID(link)) for link in links]
    assert any("年假" in item.content for item in cited)


async def test_mcp_side_effect_needs_approval(gateway: LiteLLMProxyGateway) -> None:
    """M4 完成标准：接入一个 MCP 服务，有副作用的操作先请你审批；同意后在同一次运行里接着做完。

    用测试用的 demo 服务：list_notes 声明只读（自动执行），add_note 没有声明（先问你）。
    """
    mcp = McpAdaptersClient()
    await mcp.connect([McpServerConfig(name="demo", command=sys.executable, args=[str(_DEMO_MCP)])])
    try:
        agent = MainAgent(
            gateway=gateway,
            checkpointer=InMemorySaver(),
            system_prompt=_SYSTEM_PROMPT.read_text(encoding="utf-8"),
            workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
            mcp=mcp,
        )
        thread = str(uuid.uuid4())
        message = "用 demo 的工具记一条笔记：买牛奶，然后告诉我现在有哪些笔记"
        events = await _run(agent, thread, message, CLAUDE)
        paused = events[-1]
        print(f"暂停：{paused}")
        assert isinstance(paused, ApprovalRequired)
        [request] = paused.requests
        assert [action.name for action in request.actions] == ["demo_add_note"]
        assert "买牛奶" in json.dumps(request.actions[0].args, ensure_ascii=False)
        assert request.actions[0].call_id  # 能对上工具卡片
        answers = [
            ApprovalAnswer(
                interrupt_id=request.interrupt_id, decisions=[ToolDecision(type="approve")]
            )
        ]
        await agent.check_answers(thread_id=thread, model=CLAUDE, answers=answers)
        resumed = [
            e
            async for e in agent.resume(
                thread_id=thread,
                thread_short_id=_short_id(thread),
                run_id="smoke",
                model=CLAUDE,
                message=message,
                answers=answers,
            )
        ]
        _assert_completed(resumed, "审批后")
        answer = "".join(
            e.text for e in resumed if isinstance(e, MessageDelta) and e.agent_path == ["main"]
        )
        print(f"回答：{answer}")
        assert "买牛奶" in answer
    finally:
        await mcp.close()


async def test_edited_call_is_reported_with_the_new_args(gateway: LiteLLMProxyGateway) -> None:
    """R23：审批时把"买牛奶"改成"买豆浆"后执行，智能体汇报的是实际执行的"买豆浆"。"""
    mcp = McpAdaptersClient()
    await mcp.connect([McpServerConfig(name="demo", command=sys.executable, args=[str(_DEMO_MCP)])])
    try:
        agent = MainAgent(
            gateway=gateway,
            checkpointer=InMemorySaver(),
            system_prompt=_SYSTEM_PROMPT.read_text(encoding="utf-8"),
            workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
            mcp=mcp,
        )
        thread = str(uuid.uuid4())
        message = "用 demo 的工具记一条笔记：买牛奶。记完告诉我记下的内容"
        paused = (await _run(agent, thread, message, CLAUDE))[-1]
        assert isinstance(paused, ApprovalRequired)
        [request] = paused.requests
        answers = [
            ApprovalAnswer(
                interrupt_id=request.interrupt_id,
                decisions=[ToolDecision(type="edit", args={"text": "买豆浆"})],
            )
        ]
        await agent.check_answers(
            thread_id=thread, model=CLAUDE, answers=answers, tools_version=paused.tools_version
        )
        resumed = [
            e
            async for e in agent.resume(
                thread_id=thread,
                thread_short_id=_short_id(thread),
                run_id="smoke",
                model=CLAUDE,
                message=message,
                answers=answers,
            )
        ]
        _assert_completed(resumed, "修改参数后")
        answer = "".join(
            e.text for e in resumed if isinstance(e, MessageDelta) and e.agent_path == ["main"]
        )
        print(f"回答：{answer}")
        assert "买豆浆" in answer
    finally:
        await mcp.close()


# ---- 提示缓存（设计 2026-10-23 4.1）：公司网关会不会转发缓存标记 ----


def _cache_read(message: Any) -> int:
    details = (message.usage_metadata or {}).get("input_token_details") or {}
    return int(details.get("cache_read") or 0)


async def test_prompt_caching_request_level() -> None:
    """部署前先验：请求里带上缓存断点，同样的内容连调两次，第二次应读到缓存。

    系统消息约 6000 token（超过各型号的最小缓存长度）；约花 0.05 美元。
    """
    settings = get_settings()
    model = ChatLiteLLM(
        model=f"litellm_proxy/{CLAUDE}",
        api_base=settings.litellm_base_url,
        api_key=settings.litellm_master_key.get_secret_value(),
        model_kwargs={"cache_control_injection_points": CACHE_POINTS},
    )
    base = _SYSTEM_PROMPT.read_text(encoding="utf-8")
    system = "\n\n".join(f"（第 {i} 份副本）\n{base}" for i in range(1, 9))
    messages = [SystemMessage(system), HumanMessage("只回复一个字：好")]
    first = await model.ainvoke(messages)
    second = await model.ainvoke(messages)
    for label, reply in (("第 1 次", first), ("第 2 次", second)):
        print(f"缓存先验 {label}：", reply.usage_metadata)
    assert _cache_read(second) > 0


async def test_agent_second_turn_reads_cache(gateway: LiteLLMProxyGateway) -> None:
    """部署后再验：网关里的 Claude 已带缓存断点，同一会话第二轮的第一次主调用读到缓存。

    约花 0.1 美元。
    """
    info = gateway.model_info(CLAUDE)
    assert info is not None
    assert info.supports_prompt_caching, "先 make build：启动时会给 Claude 打开缓存"
    agent = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt=_SYSTEM_PROMPT.read_text(encoding="utf-8"),
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )
    usages: list[list[Any]] = []
    for index, message in enumerate(["用一句话介绍你自己。", "再用一句话说说你能做什么。"]):
        events = [
            e
            async for e in agent.run(
                thread_id="cache",
                thread_short_id=_short_id("cache"),
                run_id=f"cache-{index}",
                message=message,
                model=CLAUDE,
            )
        ]
        _assert_completed(events, f"缓存第 {index + 1} 轮")
        usages.append([e for e in events if type(e).__name__ == "UsageReported"])
    for index, usage in enumerate(usages, start=1):
        print(f"缓存第 {index} 轮用量：", usage)
    assert usages[1][0].cache_read_tokens > 0
