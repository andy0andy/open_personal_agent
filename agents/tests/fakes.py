"""测试替身：按剧本回复的假模型与假网关。"""

import asyncio
import itertools
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

from agents.main_agent.conversations import (
    ConversationHit,
    ConversationTurn,
    NewConversationTurn,
    hit_terms,
    snippet,
)
from agents.main_agent.integrations import McpProbeResult, McpServerStatus, McpTool
from agents.main_agent.integrations.mcp import McpServerState
from agents.main_agent.knowledge import (
    Chunk,
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    NewKnowledge,
    search_tokens,
    suspicious_reason,
)
from agents.main_agent.models import (
    EMBEDDING_DIMENSIONS,
    CallContext,
    ModelInfo,
    ModelSpec,
    ModelStalledError,
    ModelTestResult,
    current_call,
)
from agents.main_agent.runtime.knowledge import user_words
from agents.main_agent.workspace import CommandResult
from common.errors import NotFoundError, UpstreamError
from config import McpServerConfig


class ScriptedChatModel(BaseChatModel):
    """按剧本依次返回预设回复；支持工具调用、思考过程、用量与逐字流式输出。

    LangChain 自带的 GenericFakeChatModel 在流式模式下不支持工具调用，所以自写这个替身。
    回复里的 additional_kwargs["reasoning_content"] 会像网关一样逐字作为思考片段输出；
    usage_metadata 与 response_metadata 放在最后一个片段里（与网关开启 include_usage 时一致）。
    """

    responses: list[AIMessage]
    cursor: int = 0
    received: list[list[BaseMessage]] = Field(default_factory=list)  # 每次调用收到的消息
    bound: list[str] = Field(default_factory=list)
    calls_in: list[CallContext | None] = Field(default_factory=list)  # 每次调用时的调用归属

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        # 记下绑定给模型的工具名（智能体实际带着哪些工具）
        self.bound = [t["name"] if isinstance(t, dict) else t.name for t in tools]
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.received.append(messages)
        self.calls_in.append(current_call())
        message = self.responses[self.cursor]
        self.cursor += 1
        return message

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        yield from _chunks_of(self._next(messages))


def _chunks_of(message: AIMessage, delay: float = 0.0) -> Iterator[ChatGenerationChunk]:
    """一条回复 → 逐字片段（思考、文字、工具调用、最后带用量）；delay 是逐字之间的等待。"""
    reasoning = message.additional_kwargs.get("reasoning_content")
    for char in reasoning if isinstance(reasoning, str) else "":
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": char})
        yield ChatGenerationChunk(message=chunk)
    text = message.content if isinstance(message.content, str) else ""
    for char in text:
        yield ChatGenerationChunk(message=AIMessageChunk(content=char))
        if delay:
            # 同步生成器由 LangChain 放在线程里逐个取，不会挡住事件循环
            time.sleep(delay)  # 允许等待：替身模拟慢慢输出
    if message.tool_calls:
        chunks = [
            {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
            for i, c in enumerate(message.tool_calls)
        ]
        yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
    if message.usage_metadata:
        last = AIMessageChunk(
            content="",
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
        )
        yield ChatGenerationChunk(message=last)


type ScriptStep = AIMessage | Callable[[list[BaseMessage]], AIMessage]

# 不是在回答用户、不该走剧本的调用（运行之外的后台小事）：标题回空（保留自动标题）
_BACKGROUND_CALLERS = frozenset({"title", "memory_extraction"})


class KeywordChatModel(ScriptedChatModel):
    """端到端测试用：按最后一条用户消息里第一个出现的关键词选剧本，第几步看那之后已有几条回复。

    与调用顺序无关（几个会话交错、后台任务插进来都不会乱）；没有命中、剧本走完时回 default；
    标题生成回空字符串（会话保留首条消息做标题，测试按它找会话）。每条回复带固定的用量
    （也带网关报的费用，后台不读）。
    delays：关键词 → 这个剧本逐字之间的等待秒数（"慢慢回答"）。
    """

    responses: list[AIMessage] = Field(default_factory=list)
    # 每步是 ScriptStep；写成 Any：pydantic 校验时会试图把函数转成 AIMessage
    scripts: list[tuple[str, list[Any]]]
    default: str = "好的"
    delays: dict[str, float] = Field(default_factory=dict)

    def _reply(
        self, messages: list[BaseMessage], run_manager: CallbackManagerForLLMRun | None
    ) -> tuple[AIMessage, float]:
        self.received.append(messages)
        self.calls_in.append(current_call())
        caller = (run_manager.metadata or {}).get("lc_agent_name") if run_manager else None
        if caller in _BACKGROUND_CALLERS:
            return self._with_usage(AIMessage(content="")), 0.0
        humans = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        if not humans:
            return self._with_usage(AIMessage(content=self.default)), 0.0
        # 只看用户原话：系统附加的相关记忆里的字不能误中剧本关键词（D24）
        text = user_words(str(messages[humans[-1]].content))
        step = sum(isinstance(m, AIMessage) for m in messages[humans[-1] + 1 :])
        for keyword, script in self.scripts:
            if keyword in text and step < len(script):
                item = script[step]
                reply = item(messages) if callable(item) else item
                return self._with_usage(reply), self.delays.get(keyword, 0.0)
            if keyword in text:
                break
        return self._with_usage(AIMessage(content=self.default)), 0.0

    @staticmethod
    def _with_usage(message: AIMessage) -> AIMessage:
        # 每次调用新的工具调用 ID：同一剧本在一个会话里走两遍时，卡片不会串
        calls = [{**c, "id": f"call_{uuid4().hex[:12]}"} for c in message.tool_calls]
        return message.model_copy(
            update={
                "tool_calls": calls,
                "usage_metadata": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "response_metadata": {"response_cost": 0.001},
            }
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reply, _ = self._reply(messages, run_manager)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply, delay = self._reply(messages, run_manager)
        yield from _chunks_of(reply, delay)


class HangingChatModel(ScriptedChatModel):
    """第一次调用先输出一个字然后一直等待（用于验证取消），之后按剧本回复。"""

    hung: bool = False

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if not self.hung:
            self.hung = True
            yield ChatGenerationChunk(message=AIMessageChunk(content="想"))
            await asyncio.Event().wait()
        for chunk in self._stream(messages, stop, **kwargs):
            yield chunk


class StallingChatModel(ScriptedChatModel):
    """第一次调用先输出一个字，然后像网络断了一样超过空闲时限（ModelStalledError），之后按剧本回复。"""

    stalled: bool = False

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if not self.stalled:
            self.stalled = True
            yield ChatGenerationChunk(message=AIMessageChunk(content="想"))
            raise ModelStalledError(120)
        for chunk in self._stream(messages, stop, **kwargs):
            yield chunk


class BreakingChatModel(ScriptedChatModel):
    """第一次调用先输出 partial（可为空），然后抛出 error（上游报错、额度用完），之后按剧本回复。"""

    error: Any
    partial: str = "前半段"
    broke: bool = False

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if not self.broke:
            self.broke = True
            if self.partial:
                yield ChatGenerationChunk(message=AIMessageChunk(content=self.partial))
            raise self.error
        for chunk in self._stream(messages, stop, **kwargs):
            yield chunk


class FailingAtChatModel(ScriptedChatModel):
    """按剧本回复，但第 fail_at 次调用（从 0 数）抛出 error；之后接着按剧本（用于失败后重试）。"""

    fail_at: int
    error: Any = None
    calls: int = 0

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        index, self.calls = self.calls, self.calls + 1
        if index == self.fail_at:
            raise self.error or RuntimeError("boom")
        return super()._next(messages)


class FailingChatModel(ScriptedChatModel):
    """每次调用都失败，用于验证失败路径。"""

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        raise RuntimeError("模型调用失败")


class FakeGateway:
    """返回预设模型对象的假网关；增删改模型记在内存里（管理页面，D21）。

    名字含 broken 的模型测试失败；fail_next_add 为真时下一次新增模拟网关出错。
    """

    def __init__(
        self,
        model: BaseChatModel,
        *,
        vision_models: frozenset[str] = frozenset(),
        models: list[ModelInfo] | None = None,
        max_input_tokens: int | None = None,
    ) -> None:
        self.model = model
        self.vision_models = vision_models  # 这些模型版本"能看图"（测试可以中途修改）
        self.max_input_tokens = max_input_tokens  # 模型信息里的上下文上限（没有时智能体不缓存）
        self.models = list(models) if models is not None else [ModelInfo(name="fake-model")]
        self.added: list[ModelSpec] = []
        self.fail_next_add = False

    async def list_models(self) -> list[ModelInfo]:
        return list(self.models)

    def chat_model(self, name: str) -> BaseChatModel:
        return self.model

    def model_info(self, name: str) -> ModelInfo | None:
        return ModelInfo(
            name=name,
            supports_vision=name in self.vision_models,
            max_input_tokens=self.max_input_tokens,
        )

    async def add_model(self, spec: ModelSpec) -> ModelInfo:
        if self.fail_next_add:
            self.fail_next_add = False
            raise UpstreamError("网关拒绝了：模拟的失败")
        self.added.append(spec)
        info = _spec_info(spec, f"id-{len(self.added)}")
        self.models.append(info)
        return info

    async def update_model(self, model_id: str, spec: ModelSpec) -> ModelInfo:
        info = _spec_info(spec, model_id)
        self.models = [info if m.id == model_id else m for m in self.models]
        return info

    async def delete_model(self, model_id: str) -> None:
        self.models = [m for m in self.models if m.id != model_id]

    async def test_model(self, name: str) -> ModelTestResult:
        if "broken" in name:
            return ModelTestResult(ok=False, latency_ms=1, error="调用失败：模拟的失败")
        return ModelTestResult(ok=True, latency_ms=1)


def _spec_info(spec: ModelSpec, model_id: str) -> ModelInfo:
    return ModelInfo(
        name=spec.name,
        mode=spec.mode,
        max_input_tokens=spec.max_input_tokens,
        input_cost_per_token=spec.input_cost_per_token,
        output_cost_per_token=spec.output_cost_per_token,
        supports_reasoning=spec.supports_reasoning,
        supports_vision=spec.supports_vision,
        id=model_id,
        upstream=spec.upstream,
        max_output_tokens=spec.max_output_tokens,
        supports_function_calling=spec.supports_function_calling,
        supports_prompt_caching=spec.supports_prompt_caching,
    )


class UnavailableGateway(FakeGateway):
    """模拟模型网关不可用。"""

    async def list_models(self) -> list[ModelInfo]:
        raise UpstreamError("模型网关不可用：connection refused")


class FakeSandbox:
    """假沙箱：记下每次执行（会话、命令、时限），按预设返回结果；可设为一直等待（验证停止）。"""

    def __init__(
        self,
        output: str = "ok",
        exit_code: int = 0,
        *,
        stderr: str = "",
        hang: bool = False,
        effect: Callable[[str, str], None] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, int | None]] = []
        self._result = CommandResult(output=output, exit_code=exit_code, stderr=stderr)
        self._hang = hang
        self._effect = effect  # 模拟命令的副作用（如代码在 outputs/ 里生成文件）：参数为会话、命令
        self.cancelled = False

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult:
        self.calls.append((session, command, time_limit))
        if self._effect is not None:
            self._effect(session, command)
        if self._hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self._result


def call(name: str, args: dict[str, Any], call_id: str | None = None) -> AIMessage:
    """一条只调用一个工具的模型回复（剧本里常用）。"""
    tool_call = {"name": name, "args": args, "id": call_id or f"call-{name}-{next(_ids)}"}
    return AIMessage(content="", tool_calls=[{**tool_call, "type": "tool_call"}])


_ids = itertools.count(1)


class FakeEmbedder:
    """假向量模型：词表里的每个词占一个维度，文字含有这个词则该维为 1。

    含有相同词的文字向量相近、没有共同词的几乎正交，便于验证"按意思检索""相关记忆召回"。
    最后一维固定一个小值，任何文字都不会是零向量。
    """

    model = "fake-embedding"

    def __init__(self, vocabulary: Sequence[str] = ()) -> None:
        self._vocabulary = list(vocabulary)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            for index, word in enumerate(self._vocabulary):
                if word in text:
                    vector[index] = 1.0
            vector[-1] = 0.1 + 0.001 * len(text)  # 没有词表词的不同文字也略有区别
            vectors.append(vector)
        return vectors


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


class FakeKnowledgeStore:
    """内存里的知识存储（单元测试用，不需要数据库与向量模型）。

    检索与召回：内容与查询有相同的两个连续字（如"狗叫"）就算相关，得分为相同的个数。
    broken_recall=True 时召回抛出 UpstreamError，模拟向量化服务不可用。
    文档片段只能写进登记过的文档（documents：文档 ID → 标题）。
    """

    def __init__(self, *, broken_recall: bool = False) -> None:
        self.items: dict[UUID, KnowledgeItem] = {}
        self.documents: dict[UUID, str] = {}
        self._broken_recall = broken_recall

    async def add(self, new: NewKnowledge) -> KnowledgeItem:
        now = datetime.now(UTC)
        item = KnowledgeItem(
            id=uuid4(),
            kind=new.kind,
            tags=new.tags,
            pinned=new.pinned,
            content=new.content,
            source=new.source,
            source_thread_id=new.source_thread_id,
            source_run_id=new.source_run_id,
            document_id=None,
            seq=None,
            section_path=None,
            page=None,
            document_title=None,
            token_count=len(new.content),
            suspicious=suspicious_reason(new.content) if new.kind == "memory" else None,
            embedding_model="fake-embedding",
            created_at=now,
            updated_at=now,
        )
        self.items[item.id] = item
        return item

    async def add_chunks(
        self, document_id: UUID, title: str, chunks: Sequence[Chunk]
    ) -> list[KnowledgeItem]:
        if document_id not in self.documents:
            raise NotFoundError(f"文档不存在：{document_id}")
        now = datetime.now(UTC)
        added = [
            KnowledgeItem(
                id=uuid4(),
                kind="document_chunk",
                tags=[],
                pinned=False,
                content=chunk.content,
                source="document",
                source_thread_id=None,
                source_run_id=None,
                document_id=document_id,
                seq=chunk.seq,
                section_path=chunk.section_path,
                page=chunk.page,
                document_title=self.documents[document_id],
                token_count=len(chunk.content),
                embedding_model="fake-embedding",
                created_at=now,
                updated_at=now,
            )
            for chunk in chunks
        ]
        self.items.update((item.id, item) for item in added)
        return added

    async def delete_chunks(self, document_id: UUID) -> int:
        doomed = [key for key, item in self.items.items() if item.document_id == document_id]
        for key in doomed:
            del self.items[key]
        return len(doomed)

    async def around(self, item_id: UUID, window: int) -> list[KnowledgeItem]:
        item = await self.get(item_id)
        if item.document_id is None or item.seq is None:
            return [item]
        low, high = item.seq - window, item.seq + window
        return sorted(
            (
                other
                for other in self.items.values()
                if other.document_id == item.document_id
                and other.seq is not None
                and low <= other.seq <= high
            ),
            key=lambda other: other.seq or 0,
        )

    async def get(self, item_id: UUID) -> KnowledgeItem:
        if item_id not in self.items:
            raise NotFoundError(f"知识条目不存在：{item_id}")
        return self.items[item_id]

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
        trusted: bool | None = None,
    ) -> KnowledgeItem:
        item = await self.get(item_id)
        changes: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if content is not None and content != item.content:
            changes["content"] = content
            changes["token_count"] = len(content)
            if item.kind == "memory":
                changes["suspicious"] = suspicious_reason(content)
                changes["trusted"] = False
        if trusted is not None:
            changes["trusted"] = trusted
        if tags is not None:
            changes["tags"] = tags
        if pinned is not None:
            changes["pinned"] = pinned
        self.items[item_id] = item.model_copy(update=changes)
        return self.items[item_id]

    async def delete(self, item_id: UUID) -> None:
        await self.get(item_id)
        del self.items[item_id]

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        found = [
            item
            for item in reversed(self.items.values())
            if (kind is None or item.kind == kind)
            and set(tags) <= set(item.tags)
            and (pinned is None or item.pinned == pinned)
            and (flagged is None or item.flagged == flagged)
        ]
        return found[offset : offset + limit]

    async def pinned(self) -> list[KnowledgeItem]:
        return [item for item in self.items.values() if item.pinned]

    async def find_memories(self, fragment: str, *, limit: int = 6) -> list[KnowledgeItem]:
        needle = fragment.lower()
        found = [
            item
            for item in self.items.values()
            if item.kind == "memory" and needle in item.content.lower()
        ]
        return found[:limit]

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
        include_suspicious: bool = False,
    ) -> list[KnowledgeHit]:
        hits = [
            KnowledgeHit(item=item, score=float(len(_bigrams(query) & _bigrams(item.content))))
            for item in self.items.values()
            if (kinds is None or item.kind in kinds)
            and set(tags) <= set(item.tags)
            and (include_suspicious or not item.flagged)
        ]
        hits = [hit for hit in hits if hit.score > 0]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        if self._broken_recall:
            raise UpstreamError("向量化服务不可用：connection refused")
        hits = await self.search(query, kinds=["memory"], top_k=len(self.items) or 1)
        return [hit for hit in hits if not hit.item.pinned][:top_k]


def mcp_tool(tool: BaseTool, *, server: str = "demo", read_only: bool | None = None) -> McpTool:
    """把一个 LangChain 工具包装成某个 MCP 服务的工具（工具名应已带服务名前缀）。"""
    return McpTool(
        server=server, name=tool.name, description=tool.description, read_only=read_only, tool=tool
    )


class FakeMcpClient:
    """按预设返回工具的假 MCP 客户端：记下每次 connect 收到的服务清单。

    设置 next_tools 后，下一次 connect 起改为返回它（模拟改了配置后重新加载）。
    没给状态时，每个出现过的服务都是"已连接"。
    """

    def __init__(
        self,
        tools: list[McpTool] | None = None,
        statuses: list[McpServerStatus] | None = None,
        *,
        connect_delay: float = 0.0,
    ) -> None:
        self._tools = list(tools or [])
        self._statuses = statuses
        self._connect_delay = connect_delay  # 模拟连接要花一段时间（如重启后 npx 启动服务）
        self.connected: list[list[McpServerConfig]] = []
        self.next_tools: list[McpTool] | None = None
        self.closed = False
        self._on_tools_changed: Callable[[], None] | None = None

    async def connect(self, servers: Sequence[McpServerConfig]) -> None:
        self.connected.append(list(servers))
        await asyncio.sleep(self._connect_delay)  # 允许等待：替身模拟连接慢
        if self.next_tools is not None:
            self._tools = self.next_tools

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    def on_tools_changed(self, callback: Callable[[], None]) -> None:
        self._on_tools_changed = callback

    def change_tools(self, tools: list[McpTool]) -> None:
        """模拟断线重连后服务的工具变了（不经过 connect）。"""
        self._tools = list(tools)
        if self._on_tools_changed is not None:
            self._on_tools_changed()

    def statuses(self) -> list[McpServerStatus]:
        """预设的工具所属的服务，加上最近一次 connect 收到的清单。

        停用的、缺环境变量的照实显示。
        """
        if self._statuses is not None:
            return list(self._statuses)
        configs = {server.name: server for server in (self.connected[-1] if self.connected else [])}
        names = dict.fromkeys([*(tool.server for tool in self._tools), *configs])
        statuses: list[McpServerStatus] = []
        for name in names:
            config = configs.get(name)
            state: McpServerState = "connected"
            error = None
            if config is not None and not config.enabled:
                state = "disabled"
            elif config is not None and config.missing_env:
                state, error = "failed", f"缺少环境变量 {'、'.join(config.missing_env)}"
            statuses.append(
                McpServerStatus(
                    name=name,
                    description=config.description if config else "",
                    transport=config.transport if config else "stdio",
                    state=state,
                    error=error,
                    tools=[t.name for t in self._tools if t.server == name]
                    if state == "connected"
                    else [],
                )
            )
        return statuses

    async def probe(self, server: McpServerConfig) -> McpProbeResult:
        """预设工具里属于这个服务的；命令叫 missing 时模拟找不到命令。"""
        if server.command == "missing":
            return McpProbeResult(ok=False, error="找不到命令 missing")
        return McpProbeResult(
            ok=True, tools=[t.name for t in self._tools if t.server == server.name]
        )

    async def close(self) -> None:
        self.closed = True


class FakeConversationIndex:
    """内存里的会话索引：分词同真实实现（jieba），按命中的词数排序。"""

    def __init__(self) -> None:
        self.rows: dict[UUID, NewConversationTurn] = {}

    async def index(self, turn: NewConversationTurn, *, replaces: UUID | None = None) -> None:
        if replaces is not None:
            self.rows.pop(replaces, None)
        self.rows[turn.run_id] = turn

    async def retitle(self, thread_id: UUID, title: str) -> None:
        for run_id, row in list(self.rows.items()):
            if row.thread_id == thread_id:
                self.rows[run_id] = row.model_copy(update={"title": title})

    async def delete_thread(self, thread_id: UUID) -> None:
        self.rows = {k: v for k, v in self.rows.items() if v.thread_id != thread_id}

    def _numbered(self) -> list[ConversationTurn]:
        by_thread: dict[UUID, list[NewConversationTurn]] = defaultdict(list)
        for row in self.rows.values():
            by_thread[row.thread_id].append(row)
        numbered: list[ConversationTurn] = []
        for rows in by_thread.values():
            ordered = sorted(rows, key=lambda r: (r.started_at, str(r.run_id)))
            numbered += [
                ConversationTurn(**row.model_dump(), turn=n) for n, row in enumerate(ordered, 1)
            ]
        return numbered

    async def search(self, query: str, *, limit: int = 10) -> list[ConversationHit]:
        words = search_tokens(query)
        if not words:
            return []
        text = query.strip().lower()
        exact: list[ConversationTurn] = []
        scored: list[tuple[int, ConversationTurn]] = []
        for turn in self._numbered():
            if text in turn.user_text.lower() or text in turn.answer_text.lower():
                exact.append(turn)
                continue
            present = set(search_tokens(f"{turn.user_text}\n{turn.answer_text}"))
            if score := sum(1 for word in words if word in present):
                scored.append((score, turn))
        exact.sort(key=lambda t: -t.started_at.timestamp())
        scored.sort(key=lambda pair: (-pair[0], -pair[1].started_at.timestamp()))
        found = [*exact, *(t for _, t in scored)][:limit]
        terms = [text, *words]
        return [
            ConversationHit(turn=t, snippet=snippet(t, terms), terms=hit_terms(terms))
            for t in found
        ]

    async def around(self, thread_id: UUID, run_id: UUID, window: int) -> list[ConversationTurn]:
        turns = sorted(
            (t for t in self._numbered() if t.thread_id == thread_id), key=lambda t: t.turn
        )
        target = next((t for t in turns if t.run_id == run_id), None)
        if target is None:
            return []
        return [t for t in turns if abs(t.turn - target.turn) <= window]

    async def turn(self, thread_id: UUID, run_id: UUID) -> ConversationTurn | None:
        return next(
            (t for t in self._numbered() if t.thread_id == thread_id and t.run_id == run_id), None
        )

    async def recent(self, limit: int) -> list[ConversationTurn]:
        latest: dict[UUID, ConversationTurn] = {}
        for turn in self._numbered():
            if turn.thread_id not in latest or turn.started_at > latest[turn.thread_id].started_at:
                latest[turn.thread_id] = turn
        return sorted(latest.values(), key=lambda t: t.started_at, reverse=True)[:limit]

    async def missing(self, run_ids: Sequence[UUID]) -> set[UUID]:
        return set(run_ids) - set(self.rows)
