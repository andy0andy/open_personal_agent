# M1b 运行体验 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** 让一次对话"看得见、停得下、算得清"——运行中可以停止；界面显示深度思考过程、子智能体的每一步、待办清单；每次模型调用的用量写入数据库并在每轮回答下方与顶栏展示；运行事件分批写库；会话中途换模型时不把旧模型的思考内容交给新模型；服务停止时进行中的运行能正确收尾。

**架构：** agents 侧扩展事件协议，并新增"运行跟踪器"（挂在每次运行回调上的 LangChain 回调对象）：它从"工具开始"回调里取得"子智能体命名空间 → task 调用 ID"的对应关系，并在每次模型调用结束时生成用量事件；翻译器据此给子智能体内部事件标上 `agent_path`。用量表 `llm_usage` 归 agents 的 `usage` 模块所有，由 backend 在收到用量事件时写入。backend 新增运行时替换点③"运行控制"负责停止与服务停止时的收尾，并用"事件分批写入器"每 200 毫秒写库、结束时整体替换为合并版本。前端的事件处理器与转换函数接住新事件：思考 → assistant-ui 的思考片段；子智能体 → 工具调用片段（内部步骤放在 `artifact`）；待办 → 自定义数据片段；用量 → 消息的自定义信息。

**技术栈：** 不新增任何依赖。用到的现有能力：LangChain `AsyncCallbackHandler`（回调）、`AgentMiddleware.wrap_model_call`（中间件）；assistant-ui 0.15.28 的 `Reasoning` / `tools.by_name` / `data.by_name` 片段组件、`AuiIf`、`ComposerPrimitive.Cancel`、`useAuiState`；uvicorn `--timeout-graceful-shutdown`。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）第 7.1、7.7、10.2～10.4、10.6、10.9、11.1、12.1、13.1、13.3 节与第 21 节 M1 行。第 21 节 M1 拆成三份：M1a（已完成）、**M1b 运行体验（本计划）**、M1c（本机安全防护、前端类型自动生成、决策记录 D1～D15、M1a 遗留小问题，另写计划）。

> 本计划的全部代码在写计划时已于临时目录实际运行验证：Python 测试 79 个（单元 48 个 + 集成 31 个）、前端测试 8 个文件 36 个、`make check` 全部通过；用真实模型在浏览器中验证了思考过程、待办、子智能体卡片、停止、刷新重现、中途换模型、用量展示；用实际镜像验证了容器停止时运行能正确收尾。计划中的每段代码由脚本从验证过的文件直接嵌入，并已从改动前的项目出发按本计划逐任务重放、逐字核对。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查，内部模块要登记到 `pyproject.toml` 的禁止列表）。
- 不新增任何第三方依赖（Python 与前端都不加）。
- 第三方服务一律由 `deploy/docker-compose.yml` 管理（D13）；密钥只在 `.env`。
- 表结构变更用 Alembic、一律写原生 SQL，文件名带归属模块前缀；所有表带 `user_id`。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 前端类型本期仍手写在 `frontend/src/api/types.ts`（M1c 改为自动生成）。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 直接运行 Python 测试时要有环境变量 `LITELLM_LOCAL_MODEL_COST_MAP=True`（Makefile 已导出；否则导入 LiteLLM 时会联网拉价格表、卡十几秒）。集成测试先 `make test-up`。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **并行派出多个子智能体** → 每个子智能体的步骤只出现在它自己的卡片里，不串到别的卡片。测试：任务 1 `test_parallel_subagents_keep_their_own_steps`。
2. **模型正在输出或工具正在执行时点停止** → 立即停止、记为已停止，同一会话马上可以继续对话。测试：任务 4 `test_cancel_stops_run_and_frees_the_thread`、`test_thread_continues_normally_after_cancel` + 任务 8 浏览器验证第 3 步。
3. **服务停止（`make down`、容器重启、改代码触发自动重载）时有运行在进行** → 运行记为失败并写明"服务停止，运行被中断"，已输出的内容保留。测试：任务 4 `test_shutdown_interrupts_runs_and_records_reason` + 任务 4 步骤 6（启动命令）+ 任务 8 浏览器验证第 6 步。
4. **进程中途退出（崩溃、强制结束）** → 已推送的内容在界面历史里；重新打开时显示失败原因，浏览器不会无限重连。测试：任务 5 `test_events_reach_history_while_running_then_get_compacted`、`test_replay_of_partial_history_ends_with_failure`。
5. **用量写库失败或模型价格未知** → 对话不受影响；未知费用显示"—"，合计只加已知部分。测试：任务 3 `test_thread_usage_is_split_by_model`、任务 6「未知费用不计入」、任务 7 `formatCost(null)`。

## 先行探测结论（2026-10-13 写计划时实测）

| 问题 | 结论 |
|---|---|
| 经网关的 Claude 深度思考，逐字输出里是什么样 | `AIMessageChunk.content` 为空串，思考文字在 `additional_kwargs["reasoning_content"]`；结尾单独一个片段带签名（`provider_specific_fields`）。Gemini 不输出思考文字（只报告思考 token 数） |
| 用量从哪里取 | 最后一个片段带 `usage_metadata`（输入 / 输出、缓存读写、思考 token）；`response_metadata["response_cost"]` 是网关按 `config/models.yaml` 价格算好的美元费用；回调 `on_llm_end` 里同样能拿到。模型名为 `litellm_proxy/<版本名>` |
| 子智能体事件怎么归属 | 输出流命名空间是 `("tools:<随机ID>",)`，**与 task 调用 ID 无关**（更正 M0 V5 的结论）。工具开始回调 `on_tool_start` 同时给出 `tool_call_id` 与元数据 `langgraph_checkpoint_ns = "tools:<同一个随机ID>"`；并行派出的子智能体各有不同的命名空间。子智能体内的模型调用元数据带 `lc_agent_name`（子智能体名） |
| 自动压缩（生成摘要）的模型调用 | 元数据带 `lc_source = "summarization"`，据此记为 `compaction`，并且不把摘要文字当成回答显示 |
| 待办清单 | `updates` 里 `tools` 节点的更新带完整的 `todos` 列表 |
| 停止后同一会话能否继续 | 能。工具执行中途被取消时，存档里留下"有调用、无结果"的消息，下一次运行由 deepagents 的 `PatchToolCallsMiddleware` 自动修补 |
| 推送心跳 | FastAPI 自带的 SSE 每 15 秒发一次 `: ping`，已满足设计文档 10.3，无需另写 |
| 服务停止时收尾 | 两个条件缺一不可：① uvicorn 带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开，15 秒后被强制结束）；② 容器启动命令用 `exec` 启动 uvicorn（`sh -c` 作为 1 号进程不会转发停止信号，10 秒后被强制结束）。两者都加上后，容器 3～4 秒内退出且运行记为"服务停止，运行被中断" |
| 被停止的那次模型调用的用量 | 拿不到（中断后网关不再返回用量），不计入——已知限制 |

## 文件结构（本计划涉及）

```
agents/main_agent/
├── runtime/events.py            # 改：新增思考、子智能体、待办、用量事件；run.finished 增加 cancelled 与用量合计
├── runtime/tracker.py           # 新：运行跟踪器（子智能体命名空间 → 调用 ID；每次模型调用的用量）
├── runtime/translator.py        # 改：改为每次运行一个翻译器对象，翻译新事件
├── runtime/agent.py             # 改：挂上运行跟踪器；装配换模型清理中间件
├── models/base.py               # 改：version_name()（去掉 litellm_proxy/ 前缀）
├── models/cleanup.py            # 新：换模型清理中间件
└── usage/                       # 新：用量模块（schemas / repo）
agents/tests/                    # 改：fakes（思考、用量、收到的消息、HangingChatModel）；新测试
backend/
├── migrations/versions/0002_agents_usage.py   # 新：llm_usage 表
├── runtime/run_control.py       # 新：运行时替换点③ 运行控制
├── runs/manager.py              # 改：用量入库、停止、服务停止收尾、分批写库、补发修正
├── runs/writer.py               # 新：事件分批写入器
├── runs/compaction.py           # 改：思考片段也合并；区分智能体
├── runs/repo.py                 # 改：finish 记录用量合计；replace_events
├── api/router.py / deps.py      # 改：停止接口、用量接口
└── main.py                      # 改：服务停止时先让运行收尾
deploy/docker-compose.yml、deploy/backend.Dockerfile   # 改：exec + --timeout-graceful-shutdown 3
frontend/src/
├── api/types.ts / client.ts / queries.ts       # 改：新事件与用量类型；停止、用量接口
├── features/chat/reducer.ts     # 改：思考、子智能体嵌套、待办、用量、已停止
├── components/chat/adapter.ts   # 改：映射到思考片段、子智能体工具片段、待办数据片段、用量信息
├── components/chat/parts.tsx    # 改：思考、子智能体卡片、待办、每轮用量
├── components/chat/ChatThread.tsx  # 改：停止按钮
├── features/chat/ChatView.tsx   # 改：停止、刷新会话用量、顶栏用量
└── features/usage/              # 新：数字格式化、顶栏会话用量
docs/                            # 改：架构规范第 9 节、测试规范、需求池、变更记录等
```

---

### 任务 1：事件协议扩展与运行跟踪器

**文件：**
- 修改：`agents/main_agent/runtime/events.py`、`translator.py`、`agent.py`、`__init__.py`；`agents/main_agent/models/base.py`、`__init__.py`；`pyproject.toml`；`docs/decisions/M0-先行验证结论.md`
- 新建：`agents/main_agent/runtime/tracker.py`
- 测试：`agents/tests/fakes.py`、`test_translator.py`、`test_tracker.py`（新）、`test_main_agent.py`、`spikes/test_v5_subagent_namespace.py`；`backend/tests/test_event_bus.py`、`test_api.py`

**接口：**
- 产出（`agents.main_agent.runtime` 公开）：`ThinkingDelta(message_id, text)`、`SubagentStarted(call_id, name, description)`、`SubagentFinished(call_id, name, status, output)`、`TodoItem(content, status)`、`TodosUpdated(todos)`、`UsageReported(caller, requested_model, actual_model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, cost: float | None, duration_ms)`、`UsageTotals(calls, input_tokens, output_tokens, cost).add(usage) -> UsageTotals`；`RunFinished.status` 增加 `"cancelled"`，新增 `usage: UsageTotals | None`。
- 产出（内部）：`RunTracker().agent_path(namespace) -> list[str]`、`.drain_usage() -> list[UsageReported]`；`Translator(tracker).translate(part) -> Iterator[Event]`；`agents.main_agent.models.version_name(name) -> str`。
- 产出（测试替身）：`ScriptedChatModel` 支持 `additional_kwargs["reasoning_content"]`（逐字思考）与 `usage_metadata` / `response_metadata`（最后一个片段），并在 `received` 里记下每次调用收到的消息。
- 事件约定：`agent_path` 主智能体为 `["main"]`，子智能体内部为 `["main", "<task 调用 ID>"]`；`write_todos` 只以 `todos.updated` 显示，不产生工具事件。

- [ ] **步骤 1：写失败的测试**

测试替身先支持思考与用量（并记下收到的消息，任务 2 要用）：

`agents/tests/fakes.py`（整个替换）：

```python
"""测试替身：按剧本回复的假模型与假网关。"""

import json
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from agents.main_agent.models import ModelInfo
from common.errors import UpstreamError


class ScriptedChatModel(BaseChatModel):
    """按剧本依次返回预设回复；支持工具调用、思考过程、用量与逐字流式输出。

    LangChain 自带的 GenericFakeChatModel 在流式模式下不支持工具调用，所以自写这个替身。
    回复里的 additional_kwargs["reasoning_content"] 会像网关一样逐字作为思考片段输出；
    usage_metadata 与 response_metadata 放在最后一个片段里（与网关开启 include_usage 时一致）。
    """

    responses: list[AIMessage]
    cursor: int = 0
    received: list[list[BaseMessage]] = Field(default_factory=list)  # 每次调用收到的消息

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.received.append(messages)
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
        message = self._next(messages)
        reasoning = message.additional_kwargs.get("reasoning_content")
        for char in reasoning if isinstance(reasoning, str) else "":
            chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": char})
            yield ChatGenerationChunk(message=chunk)
        text = message.content if isinstance(message.content, str) else ""
        for char in text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=char))
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


class FailingChatModel(ScriptedChatModel):
    """每次调用都失败，用于验证失败路径。"""

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        raise RuntimeError("模型调用失败")


class FakeGateway:
    """返回预设模型对象的假网关。"""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="fake-model")]

    def chat_model(self, name: str) -> BaseChatModel:
        return self._model


class UnavailableGateway(FakeGateway):
    """模拟模型网关不可用。"""

    async def list_models(self) -> list[ModelInfo]:
        raise UpstreamError("模型网关不可用：connection refused")
```

`agents/tests/test_translator.py`（整个替换）：

```python
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import MessagesStreamPart, UpdatesStreamPart

from agents.main_agent.runtime import (
    MessageDelta,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    TodoItem,
    TodosUpdated,
    ToolFinished,
    ToolStarted,
)
from agents.main_agent.runtime.tracker import RunTracker
from agents.main_agent.runtime.translator import TOOL_OUTPUT_LIMIT, Translator


def _messages(
    chunk: AIMessageChunk, ns: tuple[str, ...] = (), metadata: dict[str, Any] | None = None
) -> MessagesStreamPart:
    return {"type": "messages", "ns": ns, "data": (chunk, metadata or {})}


def _updates(data: dict[str, Any], ns: tuple[str, ...] = ()) -> UpdatesStreamPart:
    return {"type": "updates", "ns": ns, "data": data}


def _translator() -> Translator:
    return Translator(RunTracker())


def test_message_chunk_becomes_delta() -> None:
    part = _messages(AIMessageChunk(content="你", id="m1"))
    assert list(_translator().translate(part)) == [MessageDelta(message_id="m1", text="你")]


def test_content_blocks_split_into_thinking_and_text() -> None:
    chunk = AIMessageChunk(
        content=[{"type": "thinking", "thinking": "想"}, {"type": "text", "text": "好"}], id="m1"
    )
    assert list(_translator().translate(_messages(chunk))) == [
        ThinkingDelta(message_id="m1", text="想"),
        MessageDelta(message_id="m1", text="好"),
    ]


def test_reasoning_content_from_gateway_becomes_thinking() -> None:
    chunk = AIMessageChunk(content="", id="m1", additional_kwargs={"reasoning_content": "先"})
    assert list(_translator().translate(_messages(chunk))) == [
        ThinkingDelta(message_id="m1", text="先")
    ]


def test_missing_chunk_id_falls_back_to_model_call_namespace() -> None:
    part = _messages(AIMessageChunk(content="x"), metadata={"langgraph_checkpoint_ns": "model:1"})
    assert list(_translator().translate(part)) == [MessageDelta(message_id="model:1", text="x")]


def test_compaction_summary_is_not_shown_as_answer() -> None:
    part = _messages(
        AIMessageChunk(content="摘要", id="s"), metadata={"lc_source": "summarization"}
    )
    assert list(_translator().translate(part)) == []


def test_empty_chunk_is_skipped() -> None:
    assert list(_translator().translate(_messages(AIMessageChunk(content="", id="m1")))) == []


def test_tool_call_and_result_from_updates() -> None:
    call = {"name": "ls", "args": {"path": "/"}, "id": "c1", "type": "tool_call"}
    started = _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    result_message = ToolMessage(content="x" * 5000, tool_call_id="c1", name="ls")
    finished = _updates({"tools": {"messages": [result_message]}})
    translator = _translator()

    assert list(translator.translate(started)) == [
        ToolStarted(call_id="c1", name="ls", args={"path": "/"})
    ]
    [result] = list(translator.translate(finished))
    assert isinstance(result, ToolFinished)
    assert (result.call_id, result.status) == ("c1", "success")
    assert len(result.output) == TOOL_OUTPUT_LIMIT


def test_task_tool_becomes_subagent_events() -> None:
    args = {"description": "查一下天气", "subagent_type": "general-purpose"}
    call = {"name": "task", "args": args, "id": "c1", "type": "tool_call"}
    translator = _translator()

    [started] = translator.translate(
        _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    )
    [finished] = translator.translate(
        _updates(
            {"tools": {"messages": [ToolMessage(content="晴", tool_call_id="c1", name="task")]}}
        )
    )

    assert started == SubagentStarted(
        call_id="c1", name="general-purpose", description="查一下天气"
    )
    assert finished == SubagentFinished(
        call_id="c1", name="general-purpose", status="success", output="晴"
    )


async def test_subagent_events_carry_agent_path_of_their_task_call() -> None:
    tracker = RunTracker()
    await tracker.on_tool_start(
        {},
        "",
        run_id=uuid4(),
        metadata={"langgraph_checkpoint_ns": "tools:ns-a"},
        tool_call_id="c1",
    )
    translator = Translator(tracker)
    part = _messages(AIMessageChunk(content="子", id="m2"), ns=("tools:ns-a",))
    assert list(translator.translate(part)) == [
        MessageDelta(agent_path=["main", "c1"], message_id="m2", text="子")
    ]


def test_todos_update_becomes_full_list() -> None:
    todos = [
        {"content": "查资料", "status": "in_progress"},
        {"content": "写总结", "status": "pending"},
    ]
    part = _updates({"tools": {"todos": todos, "messages": []}})
    assert list(_translator().translate(part)) == [
        TodosUpdated(
            todos=[
                TodoItem(content="查资料", status="in_progress"),
                TodoItem(content="写总结", status="pending"),
            ]
        )
    ]


def test_write_todos_tool_is_shown_only_as_todo_list() -> None:
    todos = [{"content": "查资料", "status": "pending"}]
    call = {"name": "write_todos", "args": {"todos": todos}, "id": "t1", "type": "tool_call"}
    translator = _translator()
    started = _updates({"model": {"messages": [AIMessage(content="", tool_calls=[call])]}})
    result = ToolMessage(content="Updated todo list", tool_call_id="t1", name="write_todos")
    finished = _updates({"tools": {"todos": todos, "messages": [result]}})

    assert list(translator.translate(started)) == []
    assert [type(e) for e in translator.translate(finished)] == [TodosUpdated]


def test_other_nodes_are_ignored() -> None:
    part = _updates({"PatchToolCallsMiddleware.before_agent": None})
    assert list(_translator().translate(part)) == []
```

新建 `agents/tests/test_tracker.py`：

```python
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agents.main_agent.runtime import UsageReported
from agents.main_agent.runtime.tracker import RunTracker


def _result(usage: dict[str, Any] | None, response_metadata: dict[str, Any]) -> LLMResult:
    message = AIMessage(content="x", usage_metadata=usage, response_metadata=response_metadata)
    return LLMResult(generations=[[ChatGeneration(message=message)]])


USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "total_tokens": 120,
    "input_token_details": {"cache_read": 30, "cache_creation": 5},
    "output_token_details": {"reasoning": 7},
}


async def _call(tracker: RunTracker, metadata: dict[str, Any], result: LLMResult) -> None:
    run_id = uuid4()
    await tracker.on_chat_model_start({}, [[]], run_id=run_id, metadata=metadata)
    await tracker.on_llm_end(result, run_id=run_id)


async def test_model_call_produces_usage_event() -> None:
    tracker = RunTracker()
    metadata = {
        "ls_model_name": "litellm_proxy/claude-opus-4-6",
        "langgraph_checkpoint_ns": "model:1",
    }
    response_metadata = {"model_name": "litellm_proxy/claude-opus-4-6", "response_cost": 0.05}
    await _call(tracker, metadata, _result(USAGE, response_metadata))

    [usage] = tracker.drain_usage()
    assert usage.model_dump(exclude={"duration_ms"}) == UsageReported(
        caller="main",
        requested_model="claude-opus-4-6",
        actual_model="claude-opus-4-6",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=30,
        cache_write_tokens=5,
        reasoning_tokens=7,
        cost=0.05,
    ).model_dump(exclude={"duration_ms"})
    assert tracker.drain_usage() == []  # 取走后清空


async def test_subagent_call_is_attributed_to_its_task_call() -> None:
    tracker = RunTracker()
    # 工具开始回调同时给出调用 ID 与子智能体将使用的命名空间
    await tracker.on_tool_start(
        {"name": "task"},
        "",
        run_id=uuid4(),
        metadata={"langgraph_checkpoint_ns": "tools:ns-a"},
        tool_call_id="c1",
    )
    metadata = {
        "lc_agent_name": "general-purpose",
        "ls_model_name": "m",
        "langgraph_checkpoint_ns": "tools:ns-a|model:2",
    }
    await _call(tracker, metadata, _result(USAGE, {}))

    [usage] = tracker.drain_usage()
    assert (usage.caller, usage.agent_path, usage.cost) == ("general-purpose", ["main", "c1"], None)
    assert tracker.agent_path(("tools:ns-a",)) == ["main", "c1"]


async def test_compaction_call_is_labeled() -> None:
    tracker = RunTracker()
    await _call(tracker, {"lc_source": "summarization", "ls_model_name": "m"}, _result(USAGE, {}))
    assert tracker.drain_usage()[0].caller == "compaction"


async def test_call_without_usage_is_skipped() -> None:
    tracker = RunTracker()
    await _call(tracker, {}, _result(None, {}))
    assert tracker.drain_usage() == []
```

`agents/tests/test_main_agent.py`（整个替换）：

```python
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import (
    MainAgent,
    MessageDelta,
    RunFinished,
    RunStarted,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    TodosUpdated,
    ToolFinished,
    ToolStarted,
    UsageReported,
)
from agents.tests.fakes import FailingChatModel, FakeGateway, ScriptedChatModel


def _agent(model: ScriptedChatModel) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model), checkpointer=InMemorySaver(), system_prompt="测试助手"
    )


async def test_run_streams_tool_and_answer_events() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="你好"),
        ]
    )
    agent = _agent(model)
    events = [e async for e in agent.run(thread_id="t1", run_id="r1", message="hi", model="fake")]

    assert isinstance(events[0], RunStarted)
    assert [type(e) for e in events[1:3]] == [ToolStarted, ToolFinished]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "你好"
    assert events[-1] == RunFinished(status="completed")


async def test_run_turns_model_failure_into_failed_event() -> None:
    events = [
        e
        async for e in _agent(FailingChatModel(responses=[])).run(
            thread_id="t1", run_id="r1", message="hi", model="fake"
        )
    ]
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "failed"
    assert "模型调用失败" in (events[-1].error or "")


async def test_second_run_on_same_thread_keeps_history() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="一"), AIMessage(content="二")])
    agent = _agent(model)
    _ = [e async for e in agent.run(thread_id="t1", run_id="r1", message="a", model="fake")]
    _ = [e async for e in agent.run(thread_id="t1", run_id="r2", message="b", model="fake")]

    graph = agent._graph_for("fake")
    state = await graph.aget_state({"configurable": {"thread_id": "t1"}})
    assert [m.content for m in state.values["messages"] if m.type == "human"] == ["a", "b"]


USAGE = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}


async def test_run_streams_thinking_todos_subagent_and_usage() -> None:
    todos = [{"content": "派人去查", "status": "in_progress"}]
    task = {"description": "查一下", "subagent_type": "general-purpose"}
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "先拆"},
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": todos},
                        "id": "t1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata=USAGE,
                response_metadata={"model_name": "litellm_proxy/fake", "response_cost": 0.01},
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "task", "args": task, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="子结果", usage_metadata=USAGE),  # 子智能体（共用同一个假模型）
            AIMessage(content="完成"),
        ]
    )
    events = [
        e async for e in _agent(model).run(thread_id="t1", run_id="r1", message="hi", model="fake")
    ]

    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    assert "".join(e.text for e in thinking) == "先拆"
    assert any(isinstance(e, TodosUpdated) and e.todos[0].content == "派人去查" for e in events)
    started = next(e for e in events if isinstance(e, SubagentStarted))
    assert (started.call_id, started.name) == ("c1", "general-purpose")
    inner = [e for e in events if isinstance(e, MessageDelta) and e.agent_path == ["main", "c1"]]
    assert "".join(e.text for e in inner) == "子结果"
    finished = next(e for e in events if isinstance(e, SubagentFinished))
    assert (finished.call_id, finished.output) == ("c1", "子结果")
    usage = [e for e in events if isinstance(e, UsageReported)]
    assert [(u.caller, u.agent_path, u.cost) for u in usage] == [
        ("main", ["main"], 0.01),
        ("general-purpose", ["main", "c1"], None),
    ]
    assert events[-1] == RunFinished(status="completed")


async def test_parallel_subagents_keep_their_own_steps() -> None:
    def task(call_id: str, description: str) -> dict[str, object]:
        args = {"description": description, "subagent_type": "general-purpose"}
        return {"name": "task", "args": args, "id": call_id, "type": "tool_call"}

    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task("cA", "任务甲"), task("cB", "任务乙")]),
            AIMessage(content="甲结果"),  # 两个子智能体并行，谁先取到哪条回复不确定
            AIMessage(content="乙结果"),
            AIMessage(content="完成"),
        ]
    )
    events = [
        e async for e in _agent(model).run(thread_id="t1", run_id="r1", message="hi", model="fake")
    ]

    for call_id in ("cA", "cB"):
        inner = [
            e for e in events if isinstance(e, MessageDelta) and e.agent_path == ["main", call_id]
        ]
        finished = next(
            e for e in events if isinstance(e, SubagentFinished) and e.call_id == call_id
        )
        # 每个子智能体卡片里的文字，正是它自己交回的结果（没有和另一个混在一起）
        assert "".join(e.text for e in inner) == finished.output
    assert {e.output for e in events if isinstance(e, SubagentFinished)} == {"甲结果", "乙结果"}
```

运行结束事件新增了 `usage` 字段，两处旧断言同步更新：

在 `backend/tests/test_event_bus.py` 中，把：

```python
    assert (envelope.type, envelope.agent_path, envelope.seq) == ("run.finished", ["main"], 7)
    assert envelope.data == {"status": "completed", "error": None}
```

改为：

```python
    assert (envelope.type, envelope.agent_path, envelope.seq) == ("run.finished", ["main"], 7)
    assert envelope.data == {"status": "completed", "error": None, "usage": None}
```

在 `backend/tests/test_api.py` 中，把：

```python
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"] == {"status": "failed", "error": "服务重启中断"}

```

改为：

```python
        assert events[-1]["type"] == "run.finished"
        assert events[-1]["data"] == {"status": "failed", "error": "服务重启中断", "usage": None}

```

更正先行验证 V5 的结论（子智能体命名空间与调用 ID 无关）：

在 `agents/tests/spikes/test_v5_subagent_namespace.py` 中，把：

```python

结论：子智能体的片段 ns 为 ("tools:<调用ID>",)；task 工具的最终结果以 ToolMessage
出现在主命名空间。M1 据此推导 agent_path，并只从 updates 取工具结果以避免重复。
"""
```

改为：

```python

结论：子智能体的片段 ns 为 ("tools:<随机ID>",)，与 task 调用 ID 无关（M1b 更正）；
task 工具的最终结果以 ToolMessage 出现在主命名空间。命名空间与调用 ID 的对应关系由
运行跟踪器从工具开始回调中取得（见 agents/main_agent/runtime/tracker.py）。
"""
```

在 `docs/decisions/M0-先行验证结论.md` 中，把：

```markdown
| V4 | 工作区后端作为默认后端（离线） | 通过 | 须显式继承 SandboxBackendProtocol（抽象基类）才有 execute；CompositeBackend 只把执行交给默认后端；`get_runtime(上下文类型).context` 可取会话短 ID；`/skills/` 路由可读；虚拟根映射到 root_dir | M2 按此实现工作区（设计文档 7.3 / 9.1 已修正） |
| V5 | 子智能体事件归属（离线） | 通过 | 子智能体片段 ns 为 `("tools:<调用ID>",)`；task 工具结果以 ToolMessage 出现在主命名空间 | M1 据此推导 agent_path；工具结果只从 updates 取 |
| V6 | 本地向量模型维度与速度 | 部分通过 | 1024 维 ✅；单条查询中位 30 毫秒 ✅（目标 < 300 毫秒）；300 个约 600 token 的片段耗时 312 秒 ❌（目标 < 60 秒；容器内 Ollama 仅用 CPU，约 1 秒 / 片段） | 计划退路「改用云端向量模型」当前不可用（公司网关无向量模型、无直连厂商密钥）；**用户决定（2026-10-12）：先接受当前速度**（入库在后台进行、查询已足够快）；后续改用云端向量模型（届时修改 config/models.yaml 并运行重建向量脚本，维度保持 1024） |
```

改为：

```markdown
| V4 | 工作区后端作为默认后端（离线） | 通过 | 须显式继承 SandboxBackendProtocol（抽象基类）才有 execute；CompositeBackend 只把执行交给默认后端；`get_runtime(上下文类型).context` 可取会话短 ID；`/skills/` 路由可读；虚拟根映射到 root_dir | M2 按此实现工作区（设计文档 7.3 / 9.1 已修正） |
| V5 | 子智能体事件归属（离线） | 通过 | 子智能体片段 ns 为 `("tools:<随机ID>",)`（M1b 更正：与 task 调用 ID 无关，对应关系由工具开始回调取得）；task 工具结果以 ToolMessage 出现在主命名空间 | M1b 由运行跟踪器推导 agent_path；工具结果只从 updates 取 |
| V6 | 本地向量模型维度与速度 | 部分通过 | 1024 维 ✅；单条查询中位 30 毫秒 ✅（目标 < 300 毫秒）；300 个约 600 token 的片段耗时 312 秒 ❌（目标 < 60 秒；容器内 Ollama 仅用 CPU，约 1 秒 / 片段） | 计划退路「改用云端向量模型」当前不可用（公司网关无向量模型、无直连厂商密钥）；**用户决定（2026-10-12）：先接受当前速度**（入库在后台进行、查询已足够快）；后续改用云端向量模型（届时修改 config/models.yaml 并运行重建向量脚本，维度保持 1024） |
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_translator.py agents/tests/test_tracker.py agents/tests/test_main_agent.py backend/tests/test_event_bus.py -q`

预期：收集阶段报错 `ImportError: cannot import name 'SubagentFinished' from 'agents.main_agent.runtime'`（以及 `UsageReported`、`TodosUpdated` 等同类错误）。

- [ ] **步骤 3：实现**

在 `agents/main_agent/models/base.py` 中，把：

```python
from pydantic import BaseModel

```

改为：

```python
from pydantic import BaseModel


def version_name(name: str) -> str:
    """去掉网关返回的模型名里的接入方式前缀（如 litellm_proxy/），得到版本名。"""
    return name.rsplit("/", 1)[-1]

```

`agents/main_agent/models/__init__.py`（整个替换）：

```python
"""模型能力模块：对外公开模型网关接口、模型信息与网关实现。"""

from agents.main_agent.models.base import ModelGateway, ModelInfo, version_name
from agents.main_agent.models.litellm_proxy import LiteLLMProxyGateway

__all__ = ["LiteLLMProxyGateway", "ModelGateway", "ModelInfo", "version_name"]
```

`agents/main_agent/runtime/events.py`（整个替换）：

```python
"""智能体对外推送的事件协议（设计文档 10.3）。backend 原样转发，只在外层加序号等信封字段。

agent_path 表示事件属于哪个智能体：主智能体为 ["main"]；子智能体内部的事件为
["main", "<派出它的 task 调用 ID>"]，前端据此把它们嵌套显示在对应的子智能体卡片里。
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

MAIN = "main"


class _BaseEvent(BaseModel):
    agent_path: list[str] = Field(default_factory=lambda: [MAIN])


class RunStarted(_BaseEvent):
    type: Literal["run.started"] = "run.started"
    model: str


class MessageDelta(_BaseEvent):
    type: Literal["message.delta"] = "message.delta"
    message_id: str
    text: str


class ThinkingDelta(_BaseEvent):
    """深度思考过程的逐字片段（前端默认折叠显示）。"""

    type: Literal["thinking.delta"] = "thinking.delta"
    message_id: str
    text: str


class ToolStarted(_BaseEvent):
    type: Literal["tool.started"] = "tool.started"
    call_id: str
    name: str
    args: dict[str, Any]


class ToolFinished(_BaseEvent):
    type: Literal["tool.finished"] = "tool.finished"
    call_id: str
    name: str
    status: Literal["success", "error"]
    output: str


class SubagentStarted(_BaseEvent):
    """派出子智能体（deepagents 的 task 工具调用）。call_id 即其内部事件 agent_path 的第二段。"""

    type: Literal["subagent.started"] = "subagent.started"
    call_id: str
    name: str
    description: str


class SubagentFinished(_BaseEvent):
    type: Literal["subagent.finished"] = "subagent.finished"
    call_id: str
    name: str
    status: Literal["success", "error"]
    output: str


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "completed"]


class TodosUpdated(_BaseEvent):
    """待办清单变化，带完整清单。"""

    type: Literal["todos.updated"] = "todos.updated"
    todos: list[TodoItem]


class UsageReported(_BaseEvent):
    """一次模型调用的用量（设计文档 7.7）。cost 为网关按当时价格算出的美元费用，未知时为空。"""

    type: Literal["usage"] = "usage"
    caller: str
    requested_model: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float | None = None
    duration_ms: int = 0


class UsageTotals(BaseModel):
    """一次运行的用量合计。"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None

    def add(self, usage: UsageReported) -> "UsageTotals":
        cost = self.cost
        if usage.cost is not None:
            cost = (cost or 0.0) + usage.cost
        return UsageTotals(
            calls=self.calls + 1,
            input_tokens=self.input_tokens + usage.input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
            cost=cost,
        )


class RunFinished(_BaseEvent):
    type: Literal["run.finished"] = "run.finished"
    status: Literal["completed", "failed", "cancelled"]
    error: str | None = None
    usage: UsageTotals | None = None


type Event = Annotated[
    RunStarted
    | MessageDelta
    | ThinkingDelta
    | ToolStarted
    | ToolFinished
    | SubagentStarted
    | SubagentFinished
    | TodosUpdated
    | UsageReported
    | RunFinished,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
```

新建 `agents/main_agent/runtime/tracker.py`：

```python
"""运行跟踪器：挂在一次运行的回调上（设计文档 7.7），覆盖主智能体、子智能体、自动压缩的模型调用。

两件事：
1. 记下"子智能体命名空间 → 派出它的 task 调用 ID"。输出流里子智能体片段的命名空间形如
   "tools:<随机ID>"，与调用 ID 无关；只有工具开始回调同时给出两者，并行派出多个子智能体也不会混淆。
2. 每次模型调用结束时生成一条用量事件，等运行循环取走后推送。
"""

import time
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agents.main_agent.models import version_name
from agents.main_agent.runtime.events import MAIN, UsageReported


class RunTracker(AsyncCallbackHandler):
    def __init__(self) -> None:
        self._calls: dict[str, str] = {}
        self._started: dict[UUID, tuple[float, dict[str, Any]]] = {}
        self._usage: list[UsageReported] = []

    def agent_path(self, namespace: Sequence[str]) -> list[str]:
        """由输出流的命名空间推导 agent_path；未登记的段原样保留。"""
        return [MAIN, *(self._calls.get(segment, segment) for segment in namespace)]

    def drain_usage(self) -> list[UsageReported]:
        """取走目前收集到的用量事件。"""
        usage, self._usage = self._usage, []
        return usage

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        call_id = kwargs.get("tool_call_id")
        namespace = (metadata or {}).get("langgraph_checkpoint_ns", "")
        if call_id and namespace:
            # 形如 "tools:<父>|tools:<本次>"，最后一段就是这次工具调用（子智能体）所在的命名空间
            self._calls[namespace.split("|")[-1]] = call_id

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._started[run_id] = (time.monotonic(), metadata or {})

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        started, metadata = self._started.pop(run_id, (time.monotonic(), {}))
        generation = response.generations[0][0] if response.generations else None
        if not isinstance(generation, ChatGeneration):
            return
        message = generation.message
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            return
        input_details = usage.get("input_token_details") or {}
        output_details = usage.get("output_token_details") or {}
        requested = version_name(metadata.get("ls_model_name") or "")
        # 命名空间形如 "tools:<子智能体>|model:<本次调用>"，去掉最后一段即调用方所在的智能体
        namespace = metadata.get("langgraph_checkpoint_ns", "").split("|")[:-1]
        self._usage.append(
            UsageReported(
                agent_path=self.agent_path(namespace),
                caller=_caller(metadata),
                requested_model=requested,
                actual_model=version_name(message.response_metadata.get("model_name") or requested),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_read_tokens=input_details.get("cache_read", 0),
                cache_write_tokens=input_details.get("cache_creation", 0),
                reasoning_tokens=output_details.get("reasoning", 0),
                cost=message.response_metadata.get("response_cost"),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )


def is_compaction(metadata: dict[str, Any]) -> bool:
    """上下文自动压缩（生成摘要）时的模型调用：LangChain 给它打了 lc_source 标记。"""
    return metadata.get("lc_source") == "summarization"


def _caller(metadata: dict[str, Any]) -> str:
    """调用方：主智能体为 main，子智能体为其名称，上下文自动压缩为 compaction。"""
    if is_compaction(metadata):
        return "compaction"
    return str(metadata.get("lc_agent_name") or MAIN)
```

`agents/main_agent/runtime/translator.py`（整个替换）：

```python
"""把 deepagents（LangGraph v2 输出流）的原始片段翻译成我们的事件。

- 回答与思考的逐字片段取自 `messages` 模式的 AIMessageChunk。
- 工具、子智能体的开始 / 结束和待办清单取自 `updates` 模式里 `model` / `tools` 节点的完整内容
  （`messages` 模式里的工具参数是分片的，不适合直接展示）。
- deepagents 的 task 工具就是"派出子智能体"，翻译成 subagent.* 事件；子智能体内部的事件
  通过运行跟踪器把命名空间换算成 agent_path。
"""

from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import StreamPart

from agents.main_agent.runtime.events import (
    Event,
    MessageDelta,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    TodoItem,
    TodosUpdated,
    ToolFinished,
    ToolStarted,
)
from agents.main_agent.runtime.tracker import RunTracker, is_compaction

TOOL_OUTPUT_LIMIT = 2000
SUBAGENT_TOOL = "task"
TODO_TOOL = "write_todos"  # 只以 todos.updated（完整清单）显示，不再另显示工具卡片


class Translator:
    """一次运行一个翻译器。"""

    def __init__(self, tracker: RunTracker) -> None:
        self._tracker = tracker
        self._subagents: dict[str, str] = {}  # task 调用 ID → 子智能体名

    def translate(self, part: StreamPart[Any, Any]) -> Iterator[Event]:
        path = self._tracker.agent_path(part["ns"])
        if part["type"] == "messages":
            chunk, metadata = part["data"]
            if isinstance(chunk, AIMessageChunk) and not is_compaction(metadata):
                # 片段 ID 一般总有；缺失时用本次模型调用的命名空间，同一次调用内保持不变
                message_id = chunk.id or metadata.get("langgraph_checkpoint_ns", "")
                if thinking := _thinking_of(chunk):
                    yield ThinkingDelta(agent_path=path, message_id=message_id, text=thinking)
                if text := _text_of(chunk.content):
                    yield MessageDelta(agent_path=path, message_id=message_id, text=text)
        elif part["type"] == "updates":
            yield from self._translate_updates(part["data"], path)

    def _translate_updates(self, data: dict[str, Any], path: list[str]) -> Iterator[Event]:
        for node, update in data.items():
            if node not in ("model", "tools") or not isinstance(update, dict):
                continue
            if "todos" in update:
                todos = [TodoItem.model_validate(item) for item in update["todos"]]
                yield TodosUpdated(agent_path=path, todos=todos)
            for message in update.get("messages", []):
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        if call["name"] != TODO_TOOL:
                            yield self._started(call, path)
                elif isinstance(message, ToolMessage) and message.name != TODO_TOOL:
                    yield self._finished(message, path)

    def _started(self, call: Any, path: list[str]) -> Event:
        call_id, name, args = call["id"] or "", call["name"], call["args"]
        if name == SUBAGENT_TOOL:
            subagent = str(args.get("subagent_type", ""))
            self._subagents[call_id] = subagent
            return SubagentStarted(
                agent_path=path,
                call_id=call_id,
                name=subagent,
                description=str(args.get("description", "")),
            )
        return ToolStarted(agent_path=path, call_id=call_id, name=name, args=args)

    def _finished(self, message: ToolMessage, path: list[str]) -> Event:
        call_id = message.tool_call_id
        status = "error" if message.status == "error" else "success"
        output = _text_of(message.content)[:TOOL_OUTPUT_LIMIT]
        if message.name == SUBAGENT_TOOL:
            name = self._subagents.get(call_id, "")
            return SubagentFinished(
                agent_path=path, call_id=call_id, name=name, status=status, output=output
            )
        return ToolFinished(
            agent_path=path, call_id=call_id, name=message.name or "", status=status, output=output
        )


def _thinking_of(chunk: AIMessageChunk) -> str:
    """思考片段：经 LiteLLM 时在 reasoning_content 附加字段；Anthropic 原生格式是 thinking 块。"""
    reasoning = chunk.additional_kwargs.get("reasoning_content")
    text = reasoning if isinstance(reasoning, str) else ""
    if isinstance(chunk.content, list):
        text += "".join(
            str(block.get("thinking", ""))
            for block in chunk.content
            if isinstance(block, dict) and block.get("type") == "thinking"
        )
    return text


def _text_of(content: str | list[Any]) -> str:
    """取出消息内容中的纯文本；内容块形式（如 Anthropic）只拼接 text 块。"""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
```

`agents/main_agent/runtime/agent.py`（整个替换）：

```python
"""主智能体总入口：按模型版本组装 deepagents，运行并输出我们自己的事件流。"""

from collections.abc import AsyncIterator
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from agents.main_agent.models import ModelGateway
from agents.main_agent.runtime.events import Event, RunFinished, RunStarted
from agents.main_agent.runtime.tracker import RunTracker
from agents.main_agent.runtime.translator import Translator


class MainAgent:
    """backend 只通过它与智能体交互。"""

    def __init__(
        self, *, gateway: ModelGateway, checkpointer: BaseCheckpointSaver[Any], system_prompt: str
    ) -> None:
        self.models = gateway
        self._checkpointer = checkpointer
        self._system_prompt = system_prompt
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}

    async def run(
        self, *, thread_id: str, run_id: str, message: str, model: str
    ) -> AsyncIterator[Event]:
        """执行一次运行。任何异常都转成 `run.finished(failed)`，不向调用方抛出。

        取消（调用方取消所在任务）时 CancelledError 照常向外传播，由调用方收尾。
        """
        yield RunStarted(model=model)
        tracker = RunTracker()
        translator = Translator(tracker)
        try:
            graph = self._graph_for(model)
            async for part in graph.astream(
                {"messages": [{"role": "user", "content": message}]},
                {
                    "configurable": {"thread_id": thread_id},
                    "metadata": {"run_id": run_id},
                    "callbacks": [tracker],
                },
                stream_mode=["messages", "updates"],
                subgraphs=True,
                version="v2",
            ):
                for event in translator.translate(part):
                    yield event
                for usage in tracker.drain_usage():
                    yield usage
        except Exception as exc:  # noqa: BLE001 - 运行边界：模型 / 工具链路的任何失败都要变成失败事件
            for usage in tracker.drain_usage():
                yield usage
            yield RunFinished(status="failed", error=f"{type(exc).__name__}: {exc}")
            return
        for usage in tracker.drain_usage():
            yield usage
        yield RunFinished(status="completed")

    def _graph_for(self, model: str) -> CompiledStateGraph[Any, Any, Any, Any]:
        """按模型版本缓存组装好的智能体，避免每次请求重新组装。"""
        if model not in self._graphs:
            self._graphs[model] = create_deep_agent(
                model=self.models.chat_model(model),
                system_prompt=self._system_prompt,
                middleware=[TodoListMiddleware()],
                checkpointer=self._checkpointer,
            )
        return self._graphs[model]
```

`agents/main_agent/runtime/__init__.py`（整个替换）：

```python
"""运行模块：对外公开主智能体总入口与事件协议。"""

from agents.main_agent.runtime.agent import MainAgent
from agents.main_agent.runtime.events import (
    EVENT_ADAPTER,
    Event,
    MessageDelta,
    RunFinished,
    RunStarted,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    TodoItem,
    TodosUpdated,
    ToolFinished,
    ToolStarted,
    UsageReported,
    UsageTotals,
)

__all__ = [
    "EVENT_ADAPTER",
    "Event",
    "MainAgent",
    "MessageDelta",
    "RunFinished",
    "RunStarted",
    "SubagentFinished",
    "SubagentStarted",
    "ThinkingDelta",
    "TodoItem",
    "TodosUpdated",
    "ToolFinished",
    "ToolStarted",
    "UsageReported",
    "UsageTotals",
]
```

运行跟踪器是 runtime 的内部模块，登记到 backend 的禁止引用列表：

在 `pyproject.toml` 中，把：

```toml
    "agents.main_agent.runtime.agent",
    "agents.main_agent.runtime.translator",
```

改为：

```toml
    "agents.main_agent.runtime.agent",
    "agents.main_agent.runtime.tracker",
    "agents.main_agent.runtime.translator",
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_translator.py agents/tests/test_tracker.py agents/tests/test_main_agent.py backend/tests/test_event_bus.py -q`

预期：全部通过（25 个通过）。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 40 个、前端 26 个）；`make test-int` 全部通过（集成测试 20 个）。

---

### 任务 2：换模型清理

**文件：**
- 新建：`agents/main_agent/models/cleanup.py`
- 修改：`agents/main_agent/models/__init__.py`、`agents/main_agent/runtime/agent.py`、`pyproject.toml`
- 测试：`agents/tests/test_model_cleanup.py`（新）、`agents/tests/test_main_agent.py`

**接口：**
- 消费：任务 1 的 `version_name`、`ScriptedChatModel.received`。
- 产出：`ModelSwitchCleanupMiddleware(model: str)`（`agents.main_agent.models` 公开）；`strip_foreign_thinking(message, model) -> AnyMessage`（内部）。
- 规则：消息的 `response_metadata["model_name"]`（去掉前缀后）与当前模型版本不同时，去掉 `additional_kwargs` 里的 `reasoning_content` / `thinking_blocks` / `provider_specific_fields` 和内容块里的 `thinking` / `redacted_thinking` / `reasoning`；不知道来自哪个模型的消息不动；只改发给模型的请求，不改对话存档。

- [ ] **步骤 1：写失败的测试**

新建 `agents/tests/test_model_cleanup.py`：

```python
from langchain_core.messages import AIMessage, HumanMessage

from agents.main_agent.models.cleanup import strip_foreign_thinking

THINKING = {"reasoning_content": "想一想", "provider_specific_fields": {"signature": "s"}}


def _answer(model: str) -> AIMessage:
    return AIMessage(
        content=[{"type": "thinking", "thinking": "想"}, {"type": "text", "text": "好"}],
        additional_kwargs={**THINKING, "other": 1},
        response_metadata={"model_name": f"litellm_proxy/{model}"},
    )


def test_thinking_from_another_model_is_removed() -> None:
    cleaned = strip_foreign_thinking(_answer("claude-opus-4-6"), "gemini-3.5-flash")
    assert cleaned.additional_kwargs == {"other": 1}
    assert cleaned.content == [{"type": "text", "text": "好"}]


def test_same_model_and_other_messages_are_untouched() -> None:
    answer = _answer("claude-opus-4-6")
    assert strip_foreign_thinking(answer, "claude-opus-4-6") is answer
    question = HumanMessage(content="hi")
    assert strip_foreign_thinking(question, "gemini-3.5-flash") is question
    unknown = AIMessage(content="x", additional_kwargs=THINKING)  # 不知道来自哪个模型时不动
    assert strip_foreign_thinking(unknown, "gemini-3.5-flash") is unknown
```

在 `agents/tests/test_main_agent.py` 末尾追加：

```python


async def test_switching_model_hides_previous_model_thinking_from_new_model() -> None:
    first = AIMessage(
        content="一",
        additional_kwargs={"reasoning_content": "旧模型的思考"},
        usage_metadata=USAGE,
        response_metadata={"model_name": "litellm_proxy/model-a"},
    )
    model = ScriptedChatModel(responses=[first, AIMessage(content="二")])
    agent = _agent(model)
    _ = [e async for e in agent.run(thread_id="t1", run_id="r1", message="a", model="model-a")]
    _ = [e async for e in agent.run(thread_id="t1", run_id="r2", message="b", model="model-b")]

    previous = [m for m in model.received[-1] if isinstance(m, AIMessage)]
    assert [m.content for m in previous] == ["一"]
    assert "reasoning_content" not in previous[0].additional_kwargs
    # 对话存档保持原样
    state = await agent._graph_for("model-a").aget_state({"configurable": {"thread_id": "t1"}})
    stored = next(m for m in state.values["messages"] if m.type == "ai")
    assert stored.additional_kwargs["reasoning_content"] == "旧模型的思考"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_model_cleanup.py agents/tests/test_main_agent.py -q`

预期：`test_model_cleanup.py` 收集阶段报错 `ModuleNotFoundError: No module named 'agents.main_agent.models.cleanup'`。

- [ ] **步骤 3：实现**

新建 `agents/main_agent/models/cleanup.py`：

```python
"""换模型清理（设计文档 7.1）：会话中途换了模型时，旧模型产生的思考内容不交给新模型。

思考内容（含签名）只对产生它的模型有效，交给别家模型可能被拒绝。只在发给模型的请求里剥除，
对话存档保持原样，换回原模型时仍然完整。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage

from agents.main_agent.models.base import version_name

_THINKING_KWARGS = frozenset({"reasoning_content", "thinking_blocks", "provider_specific_fields"})
_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking", "reasoning"})


def strip_foreign_thinking(message: AnyMessage, model: str) -> AnyMessage:
    """message 由其他模型版本产生时，去掉其中的思考内容；否则原样返回。"""
    if not isinstance(message, AIMessage):
        return message
    produced_by = message.response_metadata.get("model_name")
    if not produced_by or version_name(produced_by) == model:
        return message
    kwargs = {k: v for k, v in message.additional_kwargs.items() if k not in _THINKING_KWARGS}
    content: Any = message.content
    if isinstance(content, list):
        content = [
            block
            for block in content
            if not (isinstance(block, dict) and block.get("type") in _THINKING_BLOCKS)
        ]
    return message.model_copy(update={"additional_kwargs": kwargs, "content": content})


class ModelSwitchCleanupMiddleware(AgentMiddleware):
    """每次调用模型前清理请求里的消息；model 为当前使用的模型版本名。"""

    def __init__(self, model: str) -> None:
        super().__init__()
        self._model = model

    def _clean(self, request: ModelRequest) -> ModelRequest:
        messages = [strip_foreign_thinking(m, self._model) for m in request.messages]
        return request.override(messages=messages)

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._clean(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._clean(request))
```

`agents/main_agent/models/__init__.py`（整个替换）：

```python
"""模型能力模块：对外公开模型网关接口、模型信息、网关实现与换模型清理。"""

from agents.main_agent.models.base import ModelGateway, ModelInfo, version_name
from agents.main_agent.models.cleanup import ModelSwitchCleanupMiddleware
from agents.main_agent.models.litellm_proxy import LiteLLMProxyGateway

__all__ = [
    "LiteLLMProxyGateway",
    "ModelGateway",
    "ModelInfo",
    "ModelSwitchCleanupMiddleware",
    "version_name",
]
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
```

改为：

```python
from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

from agents.main_agent.models import ModelGateway
from agents.main_agent.runtime.events import Event, RunFinished, RunStarted
```

改为：

```python

from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
from agents.main_agent.runtime.events import Event, RunFinished, RunStarted
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
        if model not in self._graphs:
            self._graphs[model] = create_deep_agent(
```

改为：

```python
        if model not in self._graphs:
            middleware: list[AgentMiddleware[Any, Any, Any]] = [
                TodoListMiddleware(),  # deepagents 0.7 默认不带待办清单，手动加回
                ModelSwitchCleanupMiddleware(model),
            ]
            self._graphs[model] = create_deep_agent(
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                system_prompt=self._system_prompt,
                middleware=[TodoListMiddleware()],
                checkpointer=self._checkpointer,
```

改为：

```python
                system_prompt=self._system_prompt,
                middleware=middleware,
                checkpointer=self._checkpointer,
```

在 `pyproject.toml` 中，把：

```toml
forbidden_modules = [
    "agents.main_agent.models.litellm_proxy",
```

改为：

```toml
forbidden_modules = [
    "agents.main_agent.models.cleanup",
    "agents.main_agent.models.litellm_proxy",
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_model_cleanup.py agents/tests/test_main_agent.py -q`

预期：全部通过（8 个通过）。

- [ ] **步骤 5：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 43 个、前端 26 个）。

---

### 任务 3：用量入库与查询接口

**文件：**
- 新建：`agents/main_agent/usage/__init__.py`、`schemas.py`、`repo.py`；`backend/migrations/versions/0002_agents_usage.py`
- 修改：`backend/runs/repo.py`、`backend/runs/manager.py`、`backend/api/deps.py`、`backend/api/router.py`、`conftest.py`、`pyproject.toml`
- 测试：`agents/tests/test_usage_repo.py`（新）、`backend/tests/test_migrations.py`、`backend/tests/test_manager.py`、`backend/tests/test_api.py`

**接口：**
- 消费：任务 1 的 `UsageReported`、`UsageTotals`、`RunFinished.usage`。
- 产出：`UsageRepo(pool)`：`add(*, thread_id, run_id, usage)`、`for_run(run_id) -> list[UsageRecord]`、`for_thread(thread_id) -> ThreadUsage`；`UsageRecord`、`ModelUsage(model, calls, input_tokens, output_tokens, cost)`、`ThreadUsage(total: UsageTotals, by_model: list[ModelUsage])`（`agents.main_agent.usage` 公开）。
- 产出：`RunManager(*, runs, threads, usage, agent, bus)`；`RunRepo.finish(run_id, *, status, error, usage=None)`；`Services.usage`；`GET /api/threads/{id}/usage -> ThreadUsage`（会话不存在 404）、`GET /api/runs/{id}/usage -> list[UsageRecord]`；`run.finished` 的 `usage` 为本次合计并写入 `runs.usage`。
- 表 `llm_usage`：不对会话、运行设外键（删除会话后费用统计仍保留）；`cost` 为 `numeric(12, 6)`，未知为空。

- [ ] **步骤 1：写失败的测试**

新建 `agents/tests/test_usage_repo.py`：

```python
import uuid

import pytest

from agents.main_agent.runtime import UsageReported, UsageTotals
from agents.main_agent.usage import ModelUsage, UsageRepo
from common.db import Pool

pytestmark = pytest.mark.integration


def _usage(model: str, tokens: int, cost: float | None, caller: str = "main") -> UsageReported:
    return UsageReported(
        caller=caller,
        requested_model=model,
        actual_model=model,
        input_tokens=tokens,
        output_tokens=tokens // 10,
        cost=cost,
        duration_ms=5,
    )


async def test_run_details_in_call_order(db: Pool) -> None:
    repo = UsageRepo(db)
    thread_id, run_id = uuid.uuid4(), uuid.uuid4()
    await repo.add(thread_id=thread_id, run_id=run_id, usage=_usage("a", 100, 0.5))
    await repo.add(thread_id=thread_id, run_id=run_id, usage=_usage("a", 10, None, "子助手"))

    records = await repo.for_run(run_id)
    assert [(r.caller, r.input_tokens, r.cost) for r in records] == [
        ("main", 100, 0.5),
        ("子助手", 10, None),
    ]


async def test_thread_usage_is_split_by_model(db: Pool) -> None:
    repo = UsageRepo(db)
    thread_id = uuid.uuid4()
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("a", 100, 0.5))
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("a", 100, 0.25))
    await repo.add(thread_id=thread_id, run_id=uuid.uuid4(), usage=_usage("b", 10, None))
    await repo.add(thread_id=uuid.uuid4(), run_id=uuid.uuid4(), usage=_usage("a", 999, 9.0))

    usage = await repo.for_thread(thread_id)
    assert usage.by_model == [
        ModelUsage(model="a", calls=2, input_tokens=200, output_tokens=20, cost=0.75),
        ModelUsage(model="b", calls=1, input_tokens=10, output_tokens=1, cost=None),
    ]
    assert usage.total == UsageTotals(calls=3, input_tokens=210, output_tokens=21, cost=0.75)


async def test_empty_thread_has_zero_usage(db: Pool) -> None:
    usage = await UsageRepo(db).for_thread(uuid.uuid4())
    assert usage.total == UsageTotals()
    assert usage.by_model == []
```

在 `backend/tests/test_migrations.py` 末尾追加：

```python


async def test_agents_usage_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.llm_usage')::text AS usage")
        row = await cur.fetchone()
    assert row == {"usage": "llm_usage"}
```

在 `backend/tests/test_manager.py` 中，把：

```python
from agents.main_agent.runtime import MainAgent
from agents.tests.fakes import FakeGateway, ScriptedChatModel
```

改为：

```python
from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from agents.tests.fakes import FakeGateway, ScriptedChatModel
```

在 `backend/tests/test_manager.py` 中，把：

```python
    )
    return RunManager(runs=runs, threads=ThreadRepo(db), agent=agent, bus=InMemoryEventBus())

```

改为：

```python
    )
    return RunManager(
        runs=runs, threads=ThreadRepo(db), usage=UsageRepo(db), agent=agent, bus=InMemoryEventBus()
    )

```

在 `backend/tests/test_api.py` 末尾追加：

```python


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
        assert (usage_event["data"]["input_tokens"], usage_event["data"]["cost"]) == (100, 0.02)
        totals = {"calls": 1, "input_tokens": 100, "output_tokens": 10, "cost": 0.02}
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
```

`db` 夹具清空表时带上新表：

在 `conftest.py` 中，把：

```python
async def db(pg_pool: Pool) -> Pool:
    """每个测试前清空 backend 的表。"""
    async with pg_pool.connection() as conn:
```

改为：

```python
async def db(pg_pool: Pool) -> Pool:
    """每个测试前清空业务表。"""
    async with pg_pool.connection() as conn:
```

在 `conftest.py` 中，把：

```python
    async with pg_pool.connection() as conn:
        await conn.execute("TRUNCATE threads, runs, run_events CASCADE")
    return pg_pool
```

改为：

```python
    async with pg_pool.connection() as conn:
        await conn.execute("TRUNCATE threads, runs, run_events, llm_usage CASCADE")
    return pg_pool
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`make test-up`

运行：`uv run pytest -m integration agents/tests/test_usage_repo.py backend/tests/test_migrations.py backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：收集阶段报错 `ModuleNotFoundError: No module named 'agents.main_agent.usage'`。

- [ ] **步骤 3：实现**

新建 `agents/main_agent/usage/schemas.py`：

```python
"""用量的数据结构。"""

from datetime import datetime

from pydantic import BaseModel

from agents.main_agent.runtime import UsageTotals


class UsageRecord(BaseModel):
    """一次模型调用的明细。"""

    caller: str
    requested_model: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    cost: float | None
    duration_ms: int
    created_at: datetime


class ModelUsage(BaseModel):
    """按实际模型版本汇总。"""

    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float | None


class ThreadUsage(BaseModel):
    """一个会话的累计用量：合计与按模型版本拆分。"""

    total: UsageTotals
    by_model: list[ModelUsage]
```

新建 `agents/main_agent/usage/repo.py`：

```python
"""llm_usage 表的数据访问。"""

from uuid import UUID

from agents.main_agent.runtime import UsageReported, UsageTotals
from agents.main_agent.usage.schemas import ModelUsage, ThreadUsage, UsageRecord
from common.db import Pool
from common.ids import new_id

_RECORD_COLUMNS = (
    "caller, requested_model, actual_model, input_tokens, output_tokens, cache_read_tokens, "
    "cache_write_tokens, reasoning_tokens, cost, duration_ms"
)


class UsageRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def add(self, *, thread_id: UUID, run_id: UUID, usage: UsageReported) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO llm_usage (id, thread_id, run_id, {_RECORD_COLUMNS}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    new_id(),
                    thread_id,
                    run_id,
                    usage.caller,
                    usage.requested_model,
                    usage.actual_model,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_write_tokens,
                    usage.reasoning_tokens,
                    usage.cost,
                    usage.duration_ms,
                ),
            )

    async def for_run(self, run_id: UUID) -> list[UsageRecord]:
        """一次运行里每次模型调用的明细，按时间顺序。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_RECORD_COLUMNS}, created_at FROM llm_usage "
                "WHERE run_id = %s ORDER BY created_at",
                (run_id,),
            )
            rows = await cur.fetchall()
        return [UsageRecord.model_validate(row) for row in rows]

    async def for_thread(self, thread_id: UUID) -> ThreadUsage:
        """一个会话的累计用量，按实际模型版本拆分（用量大的在前）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT actual_model AS model, count(*) AS calls, "
                "sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, "
                "sum(cost) AS cost FROM llm_usage WHERE thread_id = %s "
                "GROUP BY actual_model ORDER BY sum(input_tokens + output_tokens) DESC",
                (thread_id,),
            )
            rows = await cur.fetchall()
        by_model = [ModelUsage.model_validate(row) for row in rows]
        costs = [m.cost for m in by_model if m.cost is not None]
        total = UsageTotals(
            calls=sum(m.calls for m in by_model),
            input_tokens=sum(m.input_tokens for m in by_model),
            output_tokens=sum(m.output_tokens for m in by_model),
            cost=sum(costs) if costs else None,
        )
        return ThreadUsage(total=total, by_model=by_model)
```

新建 `agents/main_agent/usage/__init__.py`：

```python
"""用量模块：每次模型调用的用量记录与查询（设计文档 7.7、11.1）。"""

from agents.main_agent.usage.repo import UsageRepo
from agents.main_agent.usage.schemas import ModelUsage, ThreadUsage, UsageRecord

__all__ = ["ModelUsage", "ThreadUsage", "UsageRecord", "UsageRepo"]
```

新建 `backend/migrations/versions/0002_agents_usage.py`：

```python
"""agents 用量表：每次模型调用一行（设计文档 7.7、11.1）。

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 会话、运行不设外键：删除会话后用量记录仍保留，费用统计不受影响
    op.execute(
        """
        CREATE TABLE llm_usage (
            id                  uuid PRIMARY KEY,
            user_id             text NOT NULL DEFAULT 'me',
            thread_id           uuid,
            run_id              uuid,
            caller              text NOT NULL,
            requested_model     text NOT NULL,
            actual_model        text NOT NULL,
            input_tokens        integer NOT NULL,
            output_tokens       integer NOT NULL,
            cache_read_tokens   integer NOT NULL DEFAULT 0,
            cache_write_tokens  integer NOT NULL DEFAULT 0,
            reasoning_tokens    integer NOT NULL DEFAULT 0,
            cost                numeric(12, 6),
            duration_ms         integer NOT NULL DEFAULT 0,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX llm_usage_thread ON llm_usage (thread_id)")
    op.execute("CREATE INDEX llm_usage_run ON llm_usage (run_id)")
    op.execute("CREATE INDEX llm_usage_created ON llm_usage (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE llm_usage")
```

在 `backend/runs/repo.py` 中，把：

```python

from backend.runs.schemas import RunHistory, RunRecord
```

改为：

```python

from agents.main_agent.runtime import UsageTotals
from backend.runs.schemas import RunHistory, RunRecord
```

在 `backend/runs/repo.py` 中，把：

```python

    async def finish(self, run_id: UUID, *, status: str, error: str | None) -> None:
        async with self._pool.connection() as conn:
```

改为：

```python

    async def finish(
        self, run_id: UUID, *, status: str, error: str | None, usage: UsageTotals | None = None
    ) -> None:
        async with self._pool.connection() as conn:
```

在 `backend/runs/repo.py` 中，把：

```python
            await conn.execute(
                "UPDATE runs SET status = %s, error = %s, finished_at = now() WHERE id = %s",
                (status, error, run_id),
            )
```

改为：

```python
            await conn.execute(
                "UPDATE runs SET status = %s, error = %s, usage = %s, finished_at = now() "
                "WHERE id = %s",
                (status, error, Jsonb(usage.model_dump()) if usage else None, run_id),
            )
```

`backend/runs/manager.py`（整个替换）：

```python
"""运行管理：在后台执行运行，把事件推给事件总线，结束后写入界面历史。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from agents.main_agent.runtime import Event, MainAgent, RunFinished, UsageReported, UsageTotals
from agents.main_agent.usage import UsageRepo
from backend.runs.compaction import compact
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunCreate, RunRecord
from backend.runtime import EventBus, EventEnvelope
from backend.threads import ThreadRepo

logger = logging.getLogger(__name__)

_ACTIVE = ("queued", "running", "interrupted")


class RunManager:
    def __init__(
        self,
        *,
        runs: RunRepo,
        threads: ThreadRepo,
        usage: UsageRepo,
        agent: MainAgent,
        bus: EventBus,
    ) -> None:
        self._runs = runs
        self._threads = threads
        self._usage = usage
        self._agent = agent
        self._bus = bus
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, thread_id: UUID, body: RunCreate) -> RunRecord:
        """发起一次运行并立即返回；运行在后台进行。"""
        thread = await self._threads.get(thread_id)
        run = await self._runs.create(
            thread_id=thread.id, model=body.model or thread.model, message=body.message
        )
        await self._threads.touch(thread.id, first_message=body.message)
        self._bus.open(str(run.id))
        task = asyncio.create_task(self._execute(run))
        self._tasks.add(task)  # 持有引用，防止任务被垃圾回收
        task.add_done_callback(self._tasks.discard)
        return run

    async def stream(self, run_id: UUID, *, after_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        """推送某次运行在 after_seq 之后的事件：运行还在内存中则实时推送，否则从界面历史补发。"""
        key = str(run_id)
        if self._bus.has(key):
            async for event in self._bus.subscribe(key, after_seq):
                yield event
            return
        stored = await self._runs.events(run_id)
        for event in stored:
            if event.seq > after_seq:
                yield event
        if not stored:
            # 进程在运行途中退出时事件来不及落库；补一个结束事件，前端才会停止重连并显示原因
            run = await self._runs.get(run_id)
            if run.status not in _ACTIVE:
                ending = RunFinished(status="failed", error=run.error or "运行未正常结束")
                yield EventEnvelope.wrap(ending, seq=after_seq + 1, run_id=key)

    async def _execute(self, run: RunRecord) -> None:
        run_id = str(run.id)
        published: list[EventEnvelope] = []
        totals = UsageTotals()
        finished = RunFinished(status="failed", error="运行意外中止")
        try:
            async for event in self._agent.run(
                thread_id=str(run.thread_id), run_id=run_id, message=run.message, model=run.model
            ):
                if isinstance(event, RunFinished):
                    finished = event  # 先落库、后推送，保证前端收到时数据库已是最终状态
                    continue
                if isinstance(event, UsageReported):
                    totals = totals.add(event)
                    await self._record_usage(run, event)
                published.append(await self._publish(run_id, event, seq=len(published) + 1))
        finally:
            finished = finished.model_copy(update={"usage": totals})
            tail = EventEnvelope.wrap(finished, seq=len(published) + 1, run_id=run_id)
            try:
                await self._runs.add_events(run.id, compact([*published, tail]))
                await self._runs.finish(
                    run.id, status=finished.status, error=finished.error, usage=totals
                )
            except Exception:  # 后台任务边界：落库失败也必须结束推送，并留下日志
                logger.exception("运行 %s 的结果写入数据库失败", run_id)
            finally:
                await self._bus.publish(run_id, tail)
                await self._bus.close(run_id)

    async def _record_usage(self, run: RunRecord, usage: UsageReported) -> None:
        """用量写库失败不影响运行本身，只留下日志。"""
        try:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)
        except Exception:  # 后台任务边界：用量记录失败不能中断对话
            logger.exception("运行 %s 的用量写入数据库失败", run.id)

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
        envelope = EventEnvelope.wrap(event, seq=seq, run_id=run_id)
        await self._bus.publish(run_id, envelope)
        return envelope
```

`backend/api/deps.py`（整个替换）：

```python
"""接口层依赖：服务对象在启动时装配到 app.state.services。"""

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from backend.runs import RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus
from backend.threads import ThreadRepo
from common.db import Pool
from config import Settings


@dataclass(frozen=True)
class Services:
    settings: Settings
    agent: MainAgent
    threads: ThreadRepo
    runs: RunRepo
    usage: UsageRepo
    manager: RunManager


def build_services(
    settings: Settings, pool: Pool, agent: MainAgent, *, bus: EventBus | None = None
) -> Services:
    threads = ThreadRepo(pool)
    runs = RunRepo(pool)
    usage = UsageRepo(pool)
    manager = RunManager(
        runs=runs, threads=threads, usage=usage, agent=agent, bus=bus or InMemoryEventBus()
    )
    return Services(
        settings=settings, agent=agent, threads=threads, runs=runs, usage=usage, manager=manager
    )


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


ServicesDep = Annotated[Services, Depends(get_services)]
```

在 `backend/api/router.py` 中，把：

```python
"""接口路由：会话、运行（含推送）、模型、健康检查。"""

```

改为：

```python
"""接口路由：会话、运行（含推送）、用量、模型、健康检查。"""

```

在 `backend/api/router.py` 中，把：

```python
from agents.main_agent.models import ModelInfo
from backend.api.deps import ServicesDep
```

改为：

```python
from agents.main_agent.models import ModelInfo
from agents.main_agent.usage import ThreadUsage, UsageRecord
from backend.api.deps import ServicesDep
```

在 `backend/api/router.py` 中，把：

```python

@api_router.post("/threads/{thread_id}/runs", status_code=status.HTTP_202_ACCEPTED)
```

改为：

```python

@api_router.get("/threads/{thread_id}/usage")
async def thread_usage(thread_id: UUID, services: ServicesDep) -> ThreadUsage:
    await services.threads.get(thread_id)
    return await services.usage.for_thread(thread_id)


@api_router.post("/threads/{thread_id}/runs", status_code=status.HTTP_202_ACCEPTED)
```

在 `backend/api/router.py` 中，把：

```python
    return await services.runs.get(run_id)

```

改为：

```python
    return await services.runs.get(run_id)


@api_router.get("/runs/{run_id}/usage")
async def run_usage(
    run: Annotated[RunRecord, Depends(existing_run)], services: ServicesDep
) -> list[UsageRecord]:
    """一次运行里每次模型调用的明细。"""
    return await services.usage.for_run(run.id)

```

在 `pyproject.toml` 中，把：

```toml
    "agents.main_agent.runtime.translator",
]
```

改为：

```toml
    "agents.main_agent.runtime.translator",
    "agents.main_agent.usage.repo",
]
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest -m integration agents/tests/test_usage_repo.py backend/tests/test_migrations.py backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：全部通过（19 个通过）。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：全部通过（`make check` Python 单元测试 43 个、前端 26 个；`make test-int` 集成测试 25 个）。

---

### 任务 4：停止与服务停止时收尾

**文件：**
- 新建：`backend/runtime/run_control.py`
- 修改：`backend/runtime/__init__.py`、`backend/runs/manager.py`、`backend/api/deps.py`、`backend/api/router.py`、`backend/main.py`、`deploy/docker-compose.yml`、`deploy/backend.Dockerfile`
- 测试：`agents/tests/fakes.py`、`agents/tests/test_main_agent.py`、`backend/tests/test_run_control.py`（新）、`backend/tests/test_manager.py`、`backend/tests/test_api.py`

**接口：**
- 产出（运行时替换点③，设计文档 10.9）：`RunControl` 接口——`track(run_id, task)`、`cancel(run_id) -> bool`（不在执行中返回 False）、`async cancel_all()`（取消全部并等它们收尾）；单进程实现 `InProcessRunControl`；契约测试 `backend/tests/test_run_control.py`（参数化列出全部实现）。
- 产出：`RunManager(..., control: RunControl)`；`RunManager.cancel(run_id) -> RunRecord`（已结束抛 `ConflictError` → 409；不在执行中的进行中运行直接记为 cancelled）；`RunManager.shutdown()`；`STOPPED_BY_SHUTDOWN = "服务停止，运行被中断"`；`POST /api/runs/{id}/cancel`（202，返回运行记录；不存在 404）。
- 产出（测试替身）：`HangingChatModel`——第一次调用输出一个字后一直等待，之后按剧本回复。
- 停止 → `run.finished(status="cancelled")`；服务停止 → `run.finished(status="failed", error=STOPPED_BY_SHUTDOWN)`。`CancelledError` 由 `MainAgent.run` 照常向外传播，backend 收尾后再抛出。
- 本任务同时修复 M0 遗留 M3（停机时未回收后台运行任务）。

- [ ] **步骤 1：写失败的测试**

在 `agents/tests/fakes.py` 中，把：

```python

import json
```

改为：

```python

import asyncio
import json
```

在 `agents/tests/fakes.py` 中，把：

```python
import json
from collections.abc import Iterator, Sequence
from typing import Any
```

改为：

```python
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any
```

在 `agents/tests/fakes.py` 中，把：

```python

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
```

改为：

```python

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
```

在 `agents/tests/fakes.py` 中，把：

```python

class FailingChatModel(ScriptedChatModel):
```

改为：

```python

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


class FailingChatModel(ScriptedChatModel):
```

新建 `backend/tests/test_run_control.py`：

```python
"""运行控制的契约测试：每个实现都要通过同一套测试。"""

import asyncio

import pytest

from backend.runtime import InProcessRunControl, RunControl


async def _wait_forever() -> None:
    await asyncio.Event().wait()


@pytest.fixture(params=[InProcessRunControl])
def control(request: pytest.FixtureRequest) -> RunControl:
    implementation: type[RunControl] = request.param
    return implementation()


async def test_cancel_running_task(control: RunControl) -> None:
    task = asyncio.create_task(_wait_forever())
    control.track("r1", task)

    assert control.cancel("r1") is True
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_unknown_or_finished_run_returns_false(control: RunControl) -> None:
    task = asyncio.create_task(asyncio.sleep(0))
    control.track("r1", task)
    await task

    assert control.cancel("r1") is False
    assert control.cancel("missing") is False


async def test_cancel_all_waits_for_cleanup(control: RunControl) -> None:
    cleaned: list[str] = []

    async def run() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)  # 收尾时还要写数据库
            cleaned.append("done")

    control.track("r1", asyncio.create_task(run()))
    await asyncio.sleep(0)
    await control.cancel_all()

    assert cleaned == ["done"]
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
from langchain_core.messages import AIMessage
```

改为：

```python
import asyncio

import pytest
from langchain_core.messages import AIMessage
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
)
from agents.tests.fakes import FailingChatModel, FakeGateway, ScriptedChatModel

```

改为：

```python
)
from agents.tests.fakes import FailingChatModel, FakeGateway, HangingChatModel, ScriptedChatModel

```

在 `agents/tests/test_main_agent.py` 末尾追加：

```python


async def test_thread_continues_normally_after_cancel() -> None:
    model = HangingChatModel(responses=[AIMessage(content="第二次的回答")])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(thread_id="t1", run_id="r1", message="一", model="fake"):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task  # 取消照常向外传播，由调用方收尾

    events = [e async for e in agent.run(thread_id="t1", run_id="r2", message="二", model="fake")]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "第二次的回答"
    assert events[-1] == RunFinished(status="completed")
```

`backend/tests/test_manager.py`（整个替换）：

```python
import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from agents.tests.fakes import FakeGateway, HangingChatModel, ScriptedChatModel
from backend.runs import RunCreate, RunManager, RunRepo
from backend.runtime import EventEnvelope, InMemoryEventBus, InProcessRunControl
from backend.threads import ThreadRepo
from common.db import Pool
from common.errors import ConflictError

pytestmark = pytest.mark.integration


class _BrokenRunRepo(RunRepo):
    """模拟运行结束时数据库写入失败。"""

    async def add_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        raise RuntimeError("数据库暂时不可用")


def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
    model = model or ScriptedChatModel(responses=[AIMessage(content="好")])
    agent = MainAgent(
        gateway=FakeGateway(model), checkpointer=InMemorySaver(), system_prompt="测试助手"
    )
    return RunManager(
        runs=runs,
        threads=ThreadRepo(db),
        usage=UsageRepo(db),
        agent=agent,
        bus=InMemoryEventBus(),
        control=InProcessRunControl(),
    )


async def _drain(manager: RunManager, run_id: UUID) -> list[EventEnvelope]:
    return [event async for event in manager.stream(run_id)]


async def test_final_event_is_published_after_run_is_persisted(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))

    statuses_when_finished = []
    async for event in manager.stream(run.id):
        if event.type == "run.finished":
            statuses_when_finished.append((await runs.get(run.id)).status)

    # 前端一收到 run.finished 就会启用输入框，此时数据库必须已是最终状态，否则马上再发会 409
    assert statuses_when_finished == ["completed"]


async def test_stream_ends_and_error_is_logged_when_persisting_fails(
    db: Pool, caplog: pytest.LogCaptureFixture
) -> None:
    manager = _manager(db, _BrokenRunRepo(db))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))

    events = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    assert events[-1].type == "run.finished"
    assert "写入数据库失败" in caplog.text


async def _until_first_delta(manager: RunManager, run_id: UUID) -> AsyncIterator[EventEnvelope]:
    """读取推送直到第一个回答片段（此时模型正"卡"在输出中），然后交给调用方继续读。"""
    events = manager.stream(run_id)
    async for event in events:
        if event.type == "message.delta":
            break
    return events


async def test_cancel_stops_run_and_frees_the_thread(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await manager.cancel(run.id)
    events = [event async for event in rest]

    assert events[-1].type == "run.finished"
    assert events[-1].data["status"] == "cancelled"
    assert (await runs.get(run.id)).status == "cancelled"
    with pytest.raises(ConflictError):
        await manager.cancel(run.id)  # 已结束的运行不能再停止
    await runs.create(thread_id=thread.id, model="m", message="下一条")  # 会话已释放，不再 409


async def test_shutdown_interrupts_runs_and_records_reason(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await manager.shutdown()

    stored = await runs.get(run.id)
    assert (stored.status, stored.error) == ("failed", "服务停止，运行被中断")
    assert [event async for event in rest][-1].data["status"] == "failed"
```

在 `backend/tests/test_api.py` 中，把：

```python

from agents.tests.fakes import FailingChatModel, ScriptedChatModel, UnavailableGateway
from backend.runs import RunRepo
```

改为：

```python

from agents.tests.fakes import (
    FailingChatModel,
    HangingChatModel,
    ScriptedChatModel,
    UnavailableGateway,
)
from backend.runs import RunRepo
```

在 `backend/tests/test_api.py` 末尾追加：

```python


async def test_cancel_endpoint(make_client: ClientFactory) -> None:
    async with make_client(HangingChatModel(responses=[])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await asyncio.sleep(0.2)  # 等模型开始输出

        assert (await client.post(f"/api/runs/{run['id']}/cancel", json={})).status_code == 202
        history = await _wait_finished(client, thread["id"])
        assert history[-1]["status"] == "cancelled"
        assert history[-1]["events"][-1]["data"]["status"] == "cancelled"
        again = await client.post(f"/api/runs/{run['id']}/cancel", json={})
        assert again.status_code == 409
        missing = await client.post(f"/api/runs/{uuid.uuid4()}/cancel", json={})
        assert missing.status_code == 404
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_run_control.py agents/tests/test_main_agent.py -q`

运行：`uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：收集阶段报错 `ImportError: cannot import name 'InProcessRunControl' from 'backend.runtime'`。（`test_thread_continues_normally_after_cancel` 单独运行时会通过：智能体侧本来就支持取消，这条测试固定住本任务依赖的行为。）

- [ ] **步骤 3：实现**

新建 `backend/runtime/run_control.py`：

```python
"""运行时替换点③：运行控制（设计文档 10.9）。v1 直接取消本进程里的后台任务；
多进程时改为经事件总线广播取消信号，由持有该运行的进程执行取消。"""

import asyncio
from typing import Protocol


class RunControl(Protocol):
    """登记正在执行的运行，按运行 ID 取消。"""

    def track(self, run_id: str, task: asyncio.Task[None]) -> None: ...

    def cancel(self, run_id: str) -> bool:
        """请求取消；该运行不在执行中（或不在本进程）时返回 False。"""
        ...

    async def cancel_all(self) -> None:
        """服务停止时调用：取消全部运行，并等它们收尾结束。"""
        ...


class InProcessRunControl:
    """单进程运行控制：运行就是本进程里的一个异步任务。"""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def track(self, run_id: str, task: asyncio.Task[None]) -> None:
        self._tasks[run_id] = task  # 同时持有引用，防止任务被垃圾回收
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def cancel_all(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
```

`backend/runtime/__init__.py`（整个替换）：

```python
"""运行时替换点（见设计文档 10.9）：v1 为单进程内存实现。"""

from backend.runtime.envelope import EventEnvelope
from backend.runtime.event_bus import EventBus, InMemoryEventBus
from backend.runtime.run_control import InProcessRunControl, RunControl

__all__ = ["EventBus", "EventEnvelope", "InMemoryEventBus", "InProcessRunControl", "RunControl"]
```

`backend/runs/manager.py`（整个替换）：

```python
"""运行管理：在后台执行运行，把事件推给事件总线，结束后写入界面历史。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from agents.main_agent.runtime import Event, MainAgent, RunFinished, UsageReported, UsageTotals
from agents.main_agent.usage import UsageRepo
from backend.runs.compaction import compact
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunCreate, RunRecord
from backend.runtime import EventBus, EventEnvelope, RunControl
from backend.threads import ThreadRepo
from common.errors import ConflictError

logger = logging.getLogger(__name__)

_ACTIVE = ("queued", "running", "interrupted")
STOPPED_BY_SHUTDOWN = "服务停止，运行被中断"


class RunManager:
    def __init__(
        self,
        *,
        runs: RunRepo,
        threads: ThreadRepo,
        usage: UsageRepo,
        agent: MainAgent,
        bus: EventBus,
        control: RunControl,
    ) -> None:
        self._runs = runs
        self._threads = threads
        self._usage = usage
        self._agent = agent
        self._bus = bus
        self._control = control
        self._stopping = False

    async def start(self, thread_id: UUID, body: RunCreate) -> RunRecord:
        """发起一次运行并立即返回；运行在后台进行。"""
        thread = await self._threads.get(thread_id)
        run = await self._runs.create(
            thread_id=thread.id, model=body.model or thread.model, message=body.message
        )
        await self._threads.touch(thread.id, first_message=body.message)
        self._bus.open(str(run.id))
        self._control.track(str(run.id), asyncio.create_task(self._execute(run)))
        return run

    async def cancel(self, run_id: UUID) -> RunRecord:
        """请求停止一次运行；结果（run.finished: cancelled）随推送到达。"""
        run = await self._runs.get(run_id)
        if run.status not in _ACTIVE:
            raise ConflictError("运行已结束，无需停止")
        if not self._control.cancel(str(run_id)):
            # 不在执行中（如等待审批的运行，M4）：没有后台任务可取消，直接记为已取消
            await self._runs.finish(run_id, status="cancelled", error=None)
        return run

    async def shutdown(self) -> None:
        """服务停止时调用：中断进行中的运行，并等它们把结果写入数据库。"""
        self._stopping = True
        await self._control.cancel_all()

    async def stream(self, run_id: UUID, *, after_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        """推送某次运行在 after_seq 之后的事件：运行还在内存中则实时推送，否则从界面历史补发。"""
        key = str(run_id)
        if self._bus.has(key):
            async for event in self._bus.subscribe(key, after_seq):
                yield event
            return
        stored = await self._runs.events(run_id)
        for event in stored:
            if event.seq > after_seq:
                yield event
        if not stored:
            # 进程在运行途中退出时事件来不及落库；补一个结束事件，前端才会停止重连并显示原因
            run = await self._runs.get(run_id)
            if run.status not in _ACTIVE:
                ending = RunFinished(status="failed", error=run.error or "运行未正常结束")
                yield EventEnvelope.wrap(ending, seq=after_seq + 1, run_id=key)

    async def _execute(self, run: RunRecord) -> None:
        run_id = str(run.id)
        published: list[EventEnvelope] = []
        totals = UsageTotals()
        finished = RunFinished(status="failed", error="运行意外中止")
        try:
            async for event in self._agent.run(
                thread_id=str(run.thread_id), run_id=run_id, message=run.message, model=run.model
            ):
                if isinstance(event, RunFinished):
                    finished = event  # 先落库、后推送，保证前端收到时数据库已是最终状态
                    continue
                if isinstance(event, UsageReported):
                    totals = totals.add(event)
                    await self._record_usage(run, event)
                published.append(await self._publish(run_id, event, seq=len(published) + 1))
        except asyncio.CancelledError:
            if self._stopping:
                finished = RunFinished(status="failed", error=STOPPED_BY_SHUTDOWN)
            else:
                finished = RunFinished(status="cancelled")
            raise
        finally:
            finished = finished.model_copy(update={"usage": totals})
            tail = EventEnvelope.wrap(finished, seq=len(published) + 1, run_id=run_id)
            try:
                await self._runs.add_events(run.id, compact([*published, tail]))
                await self._runs.finish(
                    run.id, status=finished.status, error=finished.error, usage=totals
                )
            except Exception:  # 后台任务边界：落库失败也必须结束推送，并留下日志
                logger.exception("运行 %s 的结果写入数据库失败", run_id)
            finally:
                await self._bus.publish(run_id, tail)
                await self._bus.close(run_id)

    async def _record_usage(self, run: RunRecord, usage: UsageReported) -> None:
        """用量写库失败不影响运行本身，只留下日志。"""
        try:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)
        except Exception:  # 后台任务边界：用量记录失败不能中断对话
            logger.exception("运行 %s 的用量写入数据库失败", run.id)

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
        envelope = EventEnvelope.wrap(event, seq=seq, run_id=run_id)
        await self._bus.publish(run_id, envelope)
        return envelope
```

在 `backend/api/deps.py` 中，把：

```python
from backend.runs import RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus
from backend.threads import ThreadRepo
```

改为：

```python
from backend.runs import RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus, InProcessRunControl
from backend.threads import ThreadRepo
```

在 `backend/api/deps.py` 中，把：

```python
    manager = RunManager(
        runs=runs, threads=threads, usage=usage, agent=agent, bus=bus or InMemoryEventBus()
    )
```

改为：

```python
    manager = RunManager(
        runs=runs,
        threads=threads,
        usage=usage,
        agent=agent,
        bus=bus or InMemoryEventBus(),
        control=InProcessRunControl(),
    )
```

在 `backend/api/router.py` 中，把：

```python

@api_router.get("/runs/{run_id}/usage")
```

改为：

```python

@api_router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run: Annotated[RunRecord, Depends(existing_run)], services: ServicesDep
) -> RunRecord:
    """停止运行；已结束的运行返回 409。"""
    return await services.manager.cancel(run.id)


@api_router.get("/runs/{run_id}/usage")
```

服务停止时先让进行中的运行收尾，再关闭连接池：

在 `backend/main.py` 中，把：

```python
        app.state.services = services
        yield
    finally:
```

改为：

```python
        app.state.services = services
        try:
            yield
        finally:
            await services.manager.shutdown()  # 关闭连接池之前，让进行中的运行写完结果
    finally:
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_run_control.py agents/tests/test_main_agent.py -q`

运行：`uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：全部通过（单元测试 10 个、集成测试 17 个）。

- [ ] **步骤 5：启动命令**（容器停止时 uvicorn 要能收到信号，并且不无限等待浏览器的推送连接）

在 `deploy/docker-compose.yml` 中，把：

```yaml
      dockerfile: deploy/backend.Dockerfile
    # 开发模式：源码以目录挂载，改代码自动重载；启动前先执行数据库迁移
    command:
```

改为：

```yaml
      dockerfile: deploy/backend.Dockerfile
    # 开发模式：源码以目录挂载，改代码自动重载；启动前先执行数据库迁移。
    # 停止时让进行中的运行写完结果：exec 让 uvicorn 直接收到停止信号（sh 作为 1 号进程不会转发）；
    # 最多等 3 秒让连接关闭（浏览器的推送连接不会自己断开），之后中断运行并收尾
    command:
```

在 `deploy/docker-compose.yml` 中，把：

```yaml
        uv run --no-sync alembic upgrade head &&
        uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000
        --reload --reload-dir agents --reload-dir backend --reload-dir common --reload-dir config
```

改为：

```yaml
        uv run --no-sync alembic upgrade head &&
        exec uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000
        --timeout-graceful-shutdown 3
        --reload --reload-dir agents --reload-dir backend --reload-dir common --reload-dir config
```

在 `deploy/backend.Dockerfile` 中，把：

```dockerfile
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
```

改为：

```dockerfile
EXPOSE 8000
# 停止时让进行中的运行写完结果（见 backend/main.py 的 lifespan）：exec 让 uvicorn 直接收到停止信号，
# 最多等 3 秒让连接关闭，之后中断运行并收尾
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 3"]
```

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：全部通过（`make check` Python 单元测试 47 个、前端 26 个；`make test-int` 集成测试 28 个）。启动命令的实际效果在任务 8 浏览器验证第 6 步检查。

---

### 任务 5：事件分批写库

**文件：**
- 新建：`backend/runs/writer.py`
- 修改：`backend/runs/compaction.py`、`backend/runs/repo.py`、`backend/runs/manager.py`
- 测试：`backend/tests/test_compaction.py`、`backend/tests/test_repos.py`、`backend/tests/test_manager.py`、`backend/tests/test_api.py`

**接口：**
- 产出：`compact(events)` 同时合并 `thinking.delta`，且只合并 `agent_path` 相同的片段；`EventWriter(runs, run_id, *, interval=0.2)`：`start()`、`add(event)`、`async finish(events)`（停止定时写入并整体替换为合并版本）；`RunRepo.replace_events(run_id, events)`（一个事务内替换）；`RunManager(..., flush_interval: float = 0.2)`。
- 行为：运行中每 200 毫秒把新事件原样写入一批（写入失败只记日志，结束时的整体替换还会写入）；补发时若界面历史里没有结束事件且运行已结束，补一个失败的结束事件（序号接在最后一个之后）。

- [ ] **步骤 1：写失败的测试**

在 `backend/tests/test_compaction.py` 中，把：

```python
from agents.main_agent.runtime import MessageDelta, RunFinished, ToolStarted
from backend.runs.compaction import compact
```

改为：

```python
from agents.main_agent.runtime import MessageDelta, RunFinished, ThinkingDelta, ToolStarted
from backend.runs.compaction import compact
```

在 `backend/tests/test_compaction.py` 中，把：

```python

def _wrap(seq: int, event: MessageDelta | ToolStarted | RunFinished) -> EventEnvelope:
    return EventEnvelope.wrap(event, seq=seq, run_id="r1")
```

改为：

```python

def _wrap(
    seq: int, event: MessageDelta | ThinkingDelta | ToolStarted | RunFinished
) -> EventEnvelope:
    return EventEnvelope.wrap(event, seq=seq, run_id="r1")
```

在 `backend/tests/test_compaction.py` 末尾追加：

```python


def test_thinking_merges_separately_and_subagent_text_is_not_mixed_in() -> None:
    events = [
        _wrap(1, ThinkingDelta(message_id="m1", text="想")),
        _wrap(2, ThinkingDelta(message_id="m1", text="想")),
        _wrap(3, MessageDelta(message_id="m1", text="答")),
        _wrap(4, MessageDelta(message_id="m1", text="案")),
        _wrap(5, MessageDelta(agent_path=["main", "c1"], message_id="m1", text="子")),
    ]
    result = compact(events)
    assert [(e.seq, e.type, e.data["text"]) for e in result] == [
        (2, "thinking.delta", "想想"),
        (4, "message.delta", "答案"),
        (5, "message.delta", "子"),
    ]
```

在 `backend/tests/test_repos.py` 末尾追加：

```python


async def test_replace_events_swaps_whole_run(db: Pool) -> None:
    thread = await ThreadRepo(db).create(model="m")
    runs = RunRepo(db)
    run = await runs.create(thread_id=thread.id, model="m", message="hi")
    raw = [
        EventEnvelope.wrap(MessageDelta(message_id="m1", text=t), seq=i, run_id=str(run.id))
        for i, t in enumerate("你好", start=1)
    ]
    await runs.add_events(run.id, raw)
    merged = raw[1].model_copy(update={"data": {"message_id": "m1", "text": "你好"}})

    await runs.replace_events(run.id, [merged])

    assert [(e.seq, e.data["text"]) for e in await runs.events(run.id)] == [(2, "你好")]
```

在 `backend/tests/test_manager.py` 中，把：

```python
class _BrokenRunRepo(RunRepo):
    """模拟运行结束时数据库写入失败。"""

```

改为：

```python
class _BrokenRunRepo(RunRepo):
    """模拟运行过程中与结束时数据库写入都失败。"""

```

在 `backend/tests/test_manager.py` 中，把：

```python
        raise RuntimeError("数据库暂时不可用")


def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
```

改为：

```python
        raise RuntimeError("数据库暂时不可用")

    async def replace_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        raise RuntimeError("数据库暂时不可用")


def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
```

在 `backend/tests/test_manager.py` 中，把：

```python
def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
    model = model or ScriptedChatModel(responses=[AIMessage(content="好")])
```

改为：

```python
def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
    """flush_interval 调小，测试里不必等 200 毫秒。"""
    model = model or ScriptedChatModel(responses=[AIMessage(content="好")])
```

在 `backend/tests/test_manager.py` 中，把：

```python
        control=InProcessRunControl(),
    )
```

改为：

```python
        control=InProcessRunControl(),
        flush_interval=0.01,
    )
```

在 `backend/tests/test_manager.py` 末尾追加：

```python


async def test_events_reach_history_while_running_then_get_compacted(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)
    await asyncio.sleep(0.1)  # 等一次分批写入

    # 运行还在进行：已推送的内容已经在界面历史里（进程此时退出也不会丢）
    assert [e.type for e in await runs.events(run.id)] == ["run.started", "message.delta"]

    await manager.cancel(run.id)
    _ = [event async for event in rest]
    stored = await runs.events(run.id)
    assert [e.type for e in stored] == ["run.started", "message.delta", "run.finished"]
    assert stored[1].data["full_text"] is True  # 结束时整体替换为合并后的版本
```

在 `backend/tests/test_api.py` 中，把：

```python

from agents.tests.fakes import (
```

改为：

```python

from agents.main_agent.runtime import MessageDelta
from agents.tests.fakes import (
```

在 `backend/tests/test_api.py` 中，把：

```python
from backend.runs import RunRepo
from backend.tests.conftest import ClientFactory
```

改为：

```python
from backend.runs import RunRepo
from backend.runtime import EventEnvelope
from backend.tests.conftest import ClientFactory
```

在 `backend/tests/test_api.py` 末尾追加：

```python


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
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m "integration or not live" backend/tests/test_compaction.py backend/tests/test_repos.py backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：8 个失败——`test_compaction` 断言不符（思考片段未合并、子智能体的文字被并入主回答）；`test_repos` 报 `AttributeError: 'RunRepo' object has no attribute 'replace_events'`；`test_manager` 5 个报 `TypeError: RunManager.__init__() got an unexpected keyword argument 'flush_interval'`；`test_api` 的 `test_replay_of_partial_history_ends_with_failure` 断言不符（缺少结束事件）。

- [ ] **步骤 3：实现**

`backend/runs/compaction.py`（整个替换）：

```python
"""存入界面历史前合并同一段回答（或思考过程）的连续逐字片段，减少存储量。"""

from backend.runtime import EventEnvelope

_DELTAS = ("message.delta", "thinking.delta")


def compact(events: list[EventEnvelope]) -> list[EventEnvelope]:
    """合并相邻、类型相同、属于同一智能体同一段内容的逐字片段。

    合并后的事件带 full_text=True（text 是这段内容到此为止的全文），序号取该组最后一个：
    断线续传时，只要客户端还没收到这组的最后一个片段，就会收到整段全文并整体替换，
    既不丢字也不重复。
    """
    result: list[EventEnvelope] = []
    for event in events:
        previous = result[-1] if result else None
        if event.type not in _DELTAS:
            result.append(event)
        elif (
            previous is not None
            and previous.type == event.type
            and previous.agent_path == event.agent_path
            and previous.data["message_id"] == event.data["message_id"]
        ):
            merged = {**previous.data, "text": previous.data["text"] + event.data["text"]}
            result[-1] = previous.model_copy(update={"seq": event.seq, "data": merged})
        else:
            result.append(event.model_copy(update={"data": {**event.data, "full_text": True}}))
    return result
```

新建 `backend/runs/writer.py`：

```python
"""运行事件分批写入界面历史（设计文档 10.2 第 4 步）。

运行中每隔一小段时间（默认 200 毫秒）把新事件原样写入一批：进程中途退出时，已推送的内容
仍在界面历史里。运行结束时把这次运行的事件整体替换为合并后的版本（逐字片段合并成整段）。
"""

import asyncio
import contextlib
import logging
from uuid import UUID

from backend.runs.compaction import compact
from backend.runs.repo import RunRepo
from backend.runtime import EventEnvelope

logger = logging.getLogger(__name__)


class EventWriter:
    def __init__(self, runs: RunRepo, run_id: UUID, *, interval: float = 0.2) -> None:
        self._runs = runs
        self._run_id = run_id
        self._interval = interval
        self._pending: list[EventEnvelope] = []
        self._loop: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._loop = asyncio.create_task(self._flush_periodically())

    def add(self, event: EventEnvelope) -> None:
        self._pending.append(event)

    async def finish(self, events: list[EventEnvelope]) -> None:
        """停止定时写入，并用合并后的完整事件替换这次运行已写入的内容。"""
        if self._loop is not None:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop
        await self._runs.replace_events(self._run_id, compact(events))

    async def _flush_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            batch, self._pending = self._pending, []
            if not batch:
                continue
            try:
                await self._runs.add_events(self._run_id, batch)
            except Exception:  # 后台任务边界：这一批写不进去，结束时的整体替换还会写入
                logger.exception("运行 %s 的事件分批写入失败", self._run_id)
```

在 `backend/runs/repo.py` 中，把：

```python

    async def events(self, run_id: UUID, *, after_seq: int = 0) -> list[EventEnvelope]:
```

改为：

```python

    async def replace_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        """在一个事务里用 events 替换这次运行已存的全部事件。"""
        async with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute("DELETE FROM run_events WHERE run_id = %s", (run_id,))
            if events:
                await cur.executemany(
                    "INSERT INTO run_events (run_id, seq, type, payload) VALUES (%s, %s, %s, %s)",
                    [(run_id, e.seq, e.type, Jsonb(e.model_dump(mode="json"))) for e in events],
                )

    async def events(self, run_id: UUID, *, after_seq: int = 0) -> list[EventEnvelope]:
```

`backend/runs/manager.py`（整个替换）：

```python
"""运行管理：在后台执行运行，把事件推给事件总线，结束后写入界面历史。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from agents.main_agent.runtime import Event, MainAgent, RunFinished, UsageReported, UsageTotals
from agents.main_agent.usage import UsageRepo
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunCreate, RunRecord
from backend.runs.writer import EventWriter
from backend.runtime import EventBus, EventEnvelope, RunControl
from backend.threads import ThreadRepo
from common.errors import ConflictError

logger = logging.getLogger(__name__)

_ACTIVE = ("queued", "running", "interrupted")
STOPPED_BY_SHUTDOWN = "服务停止，运行被中断"


class RunManager:
    def __init__(
        self,
        *,
        runs: RunRepo,
        threads: ThreadRepo,
        usage: UsageRepo,
        agent: MainAgent,
        bus: EventBus,
        control: RunControl,
        flush_interval: float = 0.2,
    ) -> None:
        self._runs = runs
        self._threads = threads
        self._usage = usage
        self._agent = agent
        self._bus = bus
        self._control = control
        self._flush_interval = flush_interval
        self._stopping = False

    async def start(self, thread_id: UUID, body: RunCreate) -> RunRecord:
        """发起一次运行并立即返回；运行在后台进行。"""
        thread = await self._threads.get(thread_id)
        run = await self._runs.create(
            thread_id=thread.id, model=body.model or thread.model, message=body.message
        )
        await self._threads.touch(thread.id, first_message=body.message)
        self._bus.open(str(run.id))
        self._control.track(str(run.id), asyncio.create_task(self._execute(run)))
        return run

    async def cancel(self, run_id: UUID) -> RunRecord:
        """请求停止一次运行；结果（run.finished: cancelled）随推送到达。"""
        run = await self._runs.get(run_id)
        if run.status not in _ACTIVE:
            raise ConflictError("运行已结束，无需停止")
        if not self._control.cancel(str(run_id)):
            # 不在执行中（如等待审批的运行，M4）：没有后台任务可取消，直接记为已取消
            await self._runs.finish(run_id, status="cancelled", error=None)
        return run

    async def shutdown(self) -> None:
        """服务停止时调用：中断进行中的运行，并等它们把结果写入数据库。"""
        self._stopping = True
        await self._control.cancel_all()

    async def stream(self, run_id: UUID, *, after_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        """推送某次运行在 after_seq 之后的事件：运行还在内存中则实时推送，否则从界面历史补发。"""
        key = str(run_id)
        if self._bus.has(key):
            async for event in self._bus.subscribe(key, after_seq):
                yield event
            return
        stored = await self._runs.events(run_id)
        for event in stored:
            if event.seq > after_seq:
                yield event
        if not stored or stored[-1].type != "run.finished":
            # 进程在运行途中退出时，界面历史里只有部分事件、没有结束事件；
            # 补一个结束事件，前端才会停止重连并显示原因
            run = await self._runs.get(run_id)
            if run.status not in _ACTIVE:
                ending = RunFinished(status="failed", error=run.error or "运行未正常结束")
                seq = max(after_seq, stored[-1].seq if stored else 0) + 1
                yield EventEnvelope.wrap(ending, seq=seq, run_id=key)

    async def _execute(self, run: RunRecord) -> None:
        run_id = str(run.id)
        published: list[EventEnvelope] = []
        totals = UsageTotals()
        finished = RunFinished(status="failed", error="运行意外中止")
        writer = EventWriter(self._runs, run.id, interval=self._flush_interval)
        writer.start()
        try:
            async for event in self._agent.run(
                thread_id=str(run.thread_id), run_id=run_id, message=run.message, model=run.model
            ):
                if isinstance(event, RunFinished):
                    finished = event  # 先落库、后推送，保证前端收到时数据库已是最终状态
                    continue
                if isinstance(event, UsageReported):
                    totals = totals.add(event)
                    await self._record_usage(run, event)
                envelope = await self._publish(run_id, event, seq=len(published) + 1)
                published.append(envelope)
                writer.add(envelope)
        except asyncio.CancelledError:
            if self._stopping:
                finished = RunFinished(status="failed", error=STOPPED_BY_SHUTDOWN)
            else:
                finished = RunFinished(status="cancelled")
            raise
        finally:
            finished = finished.model_copy(update={"usage": totals})
            tail = EventEnvelope.wrap(finished, seq=len(published) + 1, run_id=run_id)
            try:
                await writer.finish([*published, tail])
                await self._runs.finish(
                    run.id, status=finished.status, error=finished.error, usage=totals
                )
            except Exception:  # 后台任务边界：落库失败也必须结束推送，并留下日志
                logger.exception("运行 %s 的结果写入数据库失败", run_id)
            finally:
                await self._bus.publish(run_id, tail)
                await self._bus.close(run_id)

    async def _record_usage(self, run: RunRecord, usage: UsageReported) -> None:
        """用量写库失败不影响运行本身，只留下日志。"""
        try:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)
        except Exception:  # 后台任务边界：用量记录失败不能中断对话
            logger.exception("运行 %s 的用量写入数据库失败", run.id)

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
        envelope = EventEnvelope.wrap(event, seq=seq, run_id=run_id)
        await self._bus.publish(run_id, envelope)
        return envelope
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest -m "integration or not live" backend/tests/test_compaction.py backend/tests/test_repos.py backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：全部通过（27 个通过）。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：全部通过（`make check` Python 单元测试 48 个、前端 26 个；`make test-int` 集成测试 31 个）。

---

### 任务 6：前端事件处理与转换

**文件：**
- 修改：`frontend/src/api/types.ts`、`frontend/src/features/chat/reducer.ts`、`frontend/src/components/chat/adapter.ts`
- 测试：`frontend/src/features/chat/reducer.test.ts`、`frontend/src/components/chat/adapter.test.ts`

**接口：**
- 消费：任务 1～5 的事件格式（`thinking.delta`、`subagent.*`、`todos.updated`、`usage`、`run.finished` 的 `cancelled` 与 `usage`）。
- 产出（类型）：`UsageTotals`、`UsageData`、`ModelUsage`、`ThreadUsage`、`TodoItem`；`EventEnvelope` 新增对应分支。
- 产出（事件处理器）：`ChatItem` 新增 `thinking`、`subagent`（带内部 `items`）、`todos`、`usage`、`stopped`；`agent_path` 第二段起逐层把事件放进对应子智能体的 `items`；同一次运行的待办清单原地更新（`todos-<运行ID>`）。
- 产出（转换函数）：思考 → `{ type: "reasoning" }`；子智能体 → `{ type: "tool-call", toolName: SUBAGENT_TOOL, artifact: SubagentArtifact }`；待办 → `{ type: "data-todos" }`；本轮用量（含子智能体）→ `metadata.custom.usage: TurnUsage`；停止 → 状态 `incomplete / cancelled` 且 `metadata.custom.stopped = true`。
- 导出：`SUBAGENT_TOOL = "subagent"`、`SubagentArtifact`、`TurnUsage`。

- [ ] **步骤 1：写失败的测试**

在 `frontend/src/features/chat/reducer.test.ts` 末尾追加：

```ts

const usage = {
  caller: "main",
  requested_model: "claude-opus-4-6",
  actual_model: "claude-opus-4-6",
  input_tokens: 100,
  output_tokens: 10,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  cost: 0.01,
  duration_ms: 800,
};

describe("思考过程、子智能体、待办与用量", () => {
  it("思考片段与回答分开累积，带 full_text 的思考整体替换", () => {
    const thinking = (seq: number, text: string, full_text?: boolean): EventEnvelope => ({
      ...base,
      seq,
      type: "thinking.delta",
      data: { message_id: "m1", text, ...(full_text ? { full_text } : {}) },
    });
    const state = [
      thinking(1, "先"),
      thinking(2, "想"),
      thinking(3, "先想", true),
      events[3],
    ].reduce(applyEvent, emptyChat);
    expect(state.items).toEqual([
      { kind: "thinking", id: "think-m1", text: "先想" },
      { kind: "assistant", id: "msg-m1", text: "你" },
    ]);
  });

  it("子智能体内部的事件嵌套进它的卡片，结束时带上结果", () => {
    const inner = { ...base, agent_path: ["main", "c9"] };
    const sequence: EventEnvelope[] = [
      {
        ...base,
        seq: 1,
        type: "subagent.started",
        data: { call_id: "c9", name: "general-purpose", description: "查天气" },
      },
      {
        ...inner,
        seq: 2,
        type: "tool.started",
        data: { call_id: "s1", name: "ls", args: {} },
      },
      { ...inner, seq: 3, type: "message.delta", data: { message_id: "m2", text: "晴" } },
      { ...inner, seq: 4, type: "usage", data: usage },
      {
        ...base,
        seq: 5,
        type: "subagent.finished",
        data: { call_id: "c9", name: "general-purpose", status: "success", output: "晴" },
      },
    ];
    const [card] = sequence.reduce(applyEvent, emptyChat).items;
    expect(card).toMatchObject({ kind: "subagent", id: "sub-c9", status: "success", output: "晴" });
    expect(card?.kind === "subagent" && card.items.map((item) => item.kind)).toEqual([
      "tool",
      "assistant",
      "usage",
    ]);
  });

  it("同一次运行的待办清单原地更新，不重复追加", () => {
    const todos = (seq: number, status: "pending" | "completed"): EventEnvelope => ({
      ...base,
      seq,
      type: "todos.updated",
      data: { todos: [{ content: "查资料", status }] },
    });
    const state = [todos(1, "pending"), events[3], todos(3, "completed")].reduce(
      applyEvent,
      emptyChat,
    );
    expect(state.items).toEqual([
      { kind: "todos", id: "todos-r1", todos: [{ content: "查资料", status: "completed" }] },
      { kind: "assistant", id: "msg-m1", text: "你" },
    ]);
  });

  it("停止后结束运行状态，并留下已停止标记", () => {
    const cancelled: EventEnvelope = {
      ...base,
      seq: 2,
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null },
    };
    const state = applyEvent(applyEvent(emptyChat, events[0]), cancelled);
    expect(state).toEqual({ running: false, items: [{ kind: "stopped", id: "stopped-r1" }] });
  });

  it("用量事件记为用量项", () => {
    const state = applyEvent(emptyChat, { ...base, seq: 7, type: "usage", data: usage });
    expect(state.items).toEqual([{ kind: "usage", id: "usage-r1-7", usage }]);
  });
});
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages } from "./adapter";

```

改为：

```ts
import type { ChatState } from "../../features/chat/reducer";
import { SUBAGENT_TOOL, toThreadMessages } from "./adapter";

```

在 `frontend/src/components/chat/adapter.test.ts` 末尾追加：

```ts

const usage = (input: number, cost: number | null) => ({
  caller: "main",
  requested_model: "m",
  actual_model: "m",
  input_tokens: input,
  output_tokens: 1,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  cost,
  duration_ms: 10,
});

describe("思考、子智能体、待办与用量的映射", () => {
  const state: ChatState = {
    running: false,
    items: [
      { kind: "user", id: "u1", text: "hi" },
      { kind: "thinking", id: "think-m1", text: "想一想" },
      { kind: "todos", id: "todos-r1", todos: [{ content: "查", status: "pending" }] },
      {
        kind: "subagent",
        id: "sub-c1",
        name: "general-purpose",
        description: "查天气",
        status: "success",
        output: "晴",
        items: [{ kind: "usage", id: "usage-2", usage: usage(5, null) }],
      },
      { kind: "assistant", id: "msg-m1", text: "今天晴" },
      { kind: "usage", id: "usage-1", usage: usage(100, 0.02) },
    ],
  };

  it("思考为思考片段，待办为数据片段，子智能体为带内部步骤的工具调用片段", () => {
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.content).toEqual([
      { type: "reasoning", text: "想一想" },
      { type: "data-todos", data: [{ content: "查", status: "pending" }] },
      {
        type: "tool-call",
        toolCallId: "sub-c1",
        toolName: SUBAGENT_TOOL,
        argsText: "查天气",
        artifact: {
          name: "general-purpose",
          description: "查天气",
          items: [{ kind: "usage", id: "usage-2", usage: usage(5, null) }],
        },
        result: "晴",
        isError: false,
      },
      { type: "text", text: "今天晴" },
    ]);
  });

  it("本轮用量合计包含子智能体的调用；未知费用不计入", () => {
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.metadata?.custom?.usage).toEqual({
      input_tokens: 105,
      output_tokens: 2,
      cost: 0.02,
      calls: [usage(5, null), usage(100, 0.02)],
    });
  });

  it("停止的运行映射为已取消的未完成消息", () => {
    const stopped: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "hi" },
        { kind: "assistant", id: "msg-m1", text: "写到一半" },
        { kind: "stopped", id: "stopped-r1" },
      ],
    };
    const [, assistant] = toThreadMessages(stopped);
    expect(assistant?.status).toEqual({ type: "incomplete", reason: "cancelled" });
    expect(assistant?.metadata?.custom?.stopped).toBe(true);
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/chat src/components/chat`

预期：8 个失败——事件处理器遇到新事件返回空值（`TypeError: Cannot read properties of undefined (reading 'items')`），转换函数的断言不符。

- [ ] **步骤 3：实现**

在 `frontend/src/api/types.ts` 中，把：

```ts
// 与 backend 接口对应的类型（M0 手写；M1 改为从接口文档与事件定义自动生成）

```

改为：

```ts
// 与 backend 接口对应的类型（目前手写；M1c 改为从接口文档与事件定义自动生成）

```

在 `frontend/src/api/types.ts` 中，把：

```ts

interface EnvelopeBase {
```

改为：

```ts

export interface UsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
}

/** 一次模型调用的用量（推送事件 usage 的内容）。 */
export interface UsageData {
  caller: string;
  requested_model: string;
  actual_model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  reasoning_tokens: number;
  cost: number | null;
  duration_ms: number;
}

export interface ModelUsage {
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
}

export interface ThreadUsage {
  total: UsageTotals;
  by_model: ModelUsage[];
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

interface EnvelopeBase {
```

在 `frontend/src/api/types.ts` 中，把：

```ts
  | (EnvelopeBase & {
      type: "tool.started";
```

改为：

```ts
  | (EnvelopeBase & {
      type: "thinking.delta";
      data: { message_id: string; text: string; full_text?: boolean };
    })
  | (EnvelopeBase & {
      type: "tool.started";
```

在 `frontend/src/api/types.ts` 中，把：

```ts
  | (EnvelopeBase & {
      type: "run.finished";
```

改为：

```ts
  | (EnvelopeBase & {
      type: "subagent.started";
      data: { call_id: string; name: string; description: string };
    })
  | (EnvelopeBase & {
      type: "subagent.finished";
      data: { call_id: string; name: string; status: "success" | "error"; output: string };
    })
  | (EnvelopeBase & { type: "todos.updated"; data: { todos: TodoItem[] } })
  | (EnvelopeBase & { type: "usage"; data: UsageData })
  | (EnvelopeBase & {
      type: "run.finished";
```

在 `frontend/src/api/types.ts` 中，把：

```ts
      type: "run.finished";
      data: { status: "completed" | "failed"; error: string | null };
    });
```

改为：

```ts
      type: "run.finished";
      data: {
        status: "completed" | "failed" | "cancelled";
        error: string | null;
        usage?: UsageTotals | null;
      };
    });
```

`frontend/src/features/chat/reducer.ts`（整个替换）：

```ts
import type { EventEnvelope, RunHistory, TodoItem, UsageData } from "../../api/types";

export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
  | { kind: "thinking"; id: string; text: string }
  | {
      kind: "tool";
      id: string;
      name: string;
      args: Record<string, unknown>;
      status: "running" | "success" | "error";
      output: string;
    }
  | {
      // 子智能体：items 是它内部的回答、思考、工具调用等（agent_path 指向它的事件）
      kind: "subagent";
      id: string;
      name: string;
      description: string;
      status: "running" | "success" | "error";
      output: string;
      items: ChatItem[];
    }
  | { kind: "todos"; id: string; todos: TodoItem[] }
  | { kind: "usage"; id: string; usage: UsageData }
  | { kind: "stopped"; id: string }
  // transient：发送请求本身失败（不是运行失败），下次发送时清除
  | { kind: "error"; id: string; text: string; transient?: boolean };

export interface ChatState {
  items: ChatItem[];
  running: boolean;
}

export const emptyChat: ChatState = { items: [], running: false };

/** 追加用户消息；同时清除上一次发送失败的提示，免得它一直挂在之前的回答下面。 */
export function addUserMessage(state: ChatState, id: string, text: string): ChatState {
  const items = state.items.filter((item) => !(item.kind === "error" && item.transient));
  return { ...state, items: [...items, { kind: "user", id, text }] };
}

export function removeItem(state: ChatState, id: string): ChatState {
  return { ...state, items: state.items.filter((item) => item.id !== id) };
}

export function addError(state: ChatState, id: string, text: string): ChatState {
  return { items: [...state.items, { kind: "error", id, text }], running: false };
}

/** 发送请求失败（后端连不上、会话已有运行等）的提示；下次发送时自动清除。 */
export function addSendError(state: ChatState, id: string, text: string): ChatState {
  return { items: [...state.items, { kind: "error", id, text, transient: true }], running: false };
}

/** 事件处理器：输入当前状态和一个事件，输出新状态。实时推送与历史重放共用。 */
export function applyEvent(state: ChatState, event: EventEnvelope): ChatState {
  switch (event.type) {
    case "run.started":
      return { ...state, running: true };
    case "run.finished":
      if (event.data.status === "failed") {
        return addError(state, `err-${event.run_id}`, event.data.error ?? "运行失败");
      }
      if (event.data.status === "cancelled") {
        return {
          items: [...state.items, { kind: "stopped", id: `stopped-${event.run_id}` }],
          running: false,
        };
      }
      return { ...state, running: false };
    default:
      // agent_path 第一段是 main，其后每一段是一层子智能体（派出它的调用 ID）
      return { ...state, items: applyToItems(state.items, event, event.agent_path.slice(1)) };
  }
}

type ItemEvent = Exclude<EventEnvelope, { type: "run.started" | "run.finished" }>;

function applyToItems(items: ChatItem[], event: ItemEvent, path: string[]): ChatItem[] {
  const [callId, ...rest] = path;
  if (callId !== undefined) {
    return items.map((item) =>
      item.kind === "subagent" && item.id === `sub-${callId}`
        ? { ...item, items: applyToItems(item.items, event, rest) }
        : item,
    );
  }
  switch (event.type) {
    case "message.delta":
      return appendDelta(items, "assistant", `msg-${event.data.message_id}`, event.data);
    case "thinking.delta":
      return appendDelta(items, "thinking", `think-${event.data.message_id}`, event.data);
    case "tool.started":
      return [
        ...items,
        {
          kind: "tool",
          id: `tool-${event.data.call_id}`,
          name: event.data.name,
          args: event.data.args,
          status: "running",
          output: "",
        },
      ];
    case "tool.finished": {
      const id = `tool-${event.data.call_id}`;
      return items.map((item) =>
        item.kind === "tool" && item.id === id
          ? { ...item, status: event.data.status, output: event.data.output }
          : item,
      );
    }
    case "subagent.started":
      return [
        ...items,
        {
          kind: "subagent",
          id: `sub-${event.data.call_id}`,
          name: event.data.name,
          description: event.data.description,
          status: "running",
          output: "",
          items: [],
        },
      ];
    case "subagent.finished": {
      const id = `sub-${event.data.call_id}`;
      return items.map((item) =>
        item.kind === "subagent" && item.id === id
          ? { ...item, status: event.data.status, output: event.data.output }
          : item,
      );
    }
    case "todos.updated": {
      // 同一次运行只保留一份待办清单，原地更新
      const id = `todos-${event.run_id}`;
      const todos: ChatItem = { kind: "todos", id, todos: event.data.todos };
      return items.some((item) => item.id === id)
        ? items.map((item) => (item.id === id ? todos : item))
        : [...items, todos];
    }
    case "usage":
      return [
        ...items,
        { kind: "usage", id: `usage-${event.run_id}-${event.seq}`, usage: event.data },
      ];
  }
}

/** 逐字片段：接在同一段内容后面；full_text 为 true 时（界面历史里合并过的片段）整体替换。 */
function appendDelta(
  items: ChatItem[],
  kind: "assistant" | "thinking",
  id: string,
  data: { text: string; full_text?: boolean },
): ChatItem[] {
  const last = items.at(-1);
  if (last?.kind === kind && last.id === id) {
    const text = data.full_text ? data.text : last.text + data.text;
    return [...items.slice(0, -1), { ...last, text }];
  }
  return [...items, { kind, id, text: data.text }];
}

/** 由界面历史（每次运行的用户消息 + 已存事件）重建对话状态。 */
export function chatFromHistory(runs: RunHistory[]): ChatState {
  return runs.reduce((state, run) => {
    const replayed = run.events.reduce(
      applyEvent,
      addUserMessage(state, `user-${run.id}`, run.message),
    );
    // 进程在运行途中退出时没有存下结束事件，只能从运行状态得知失败原因
    const ended = run.events.some((event) => event.type === "run.finished");
    return run.status === "failed" && !ended
      ? addError(replayed, `err-${run.id}`, run.error ?? "运行失败")
      : replayed;
  }, emptyChat);
}
```

`frontend/src/components/chat/adapter.ts`（整个替换）：

```ts
import type { ThreadMessageLike } from "@assistant-ui/react";
import type { UsageData } from "../../api/types";
import type { ChatItem, ChatState } from "../../features/chat/reducer";

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

/** 子智能体卡片的工具名；卡片的内部步骤放在 artifact 里。 */
export const SUBAGENT_TOOL = "subagent";

export interface SubagentArtifact {
  name: string;
  description: string;
  items: ChatItem[];
}

/** 一轮回答的用量（含子智能体）：显示在回答下方，可展开每次调用明细。 */
export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  calls: UsageData[];
}

/**
 * 把事件处理器的状态转换成 assistant-ui 的消息（设计文档 13.1 映射表）：
 * 两条用户消息之间的思考、回答、工具调用、子智能体合并为一条助手消息；
 * 运行失败映射为"未完成"并带错误原因，停止映射为"未完成（已取消）"。
 */
export function toThreadMessages(state: ChatState): ThreadMessageLike[] {
  const groups: ChatItem[][] = [];
  for (const item of state.items) {
    const last = groups.at(-1);
    if (item.kind !== "user" && last && last[0]?.kind !== "user") last.push(item);
    else groups.push([item]);
  }
  return groups.map((group, index) => {
    const first = group[0];
    if (first?.kind === "user") {
      return { id: first.id, role: "user", content: [{ type: "text", text: first.text }] };
    }
    const parts = group.flatMap(toPart);
    const error = group.find((item) => item.kind === "error")?.text;
    const stopped = group.some((item) => item.kind === "stopped");
    const usage = turnUsage(group);
    const running = index === groups.length - 1 && state.running;
    return {
      id: `a-${first?.id ?? index}`,
      role: "assistant",
      content: parts,
      status: error
        ? { type: "incomplete", reason: "error", error }
        : stopped
          ? { type: "incomplete", reason: "cancelled" }
          : running
            ? { type: "running" }
            : { type: "complete", reason: "stop" },
      ...(usage || stopped ? { metadata: { custom: { usage, stopped } } } : {}),
    };
  });
}

function toPart(item: ChatItem): AssistantPart[] {
  switch (item.kind) {
    case "assistant":
      return [{ type: "text", text: item.text }];
    case "thinking":
      return [{ type: "reasoning", text: item.text }];
    case "tool":
      return [
        {
          type: "tool-call",
          toolCallId: item.id,
          toolName: item.name,
          argsText: JSON.stringify(item.args, null, 2),
          ...(item.status === "running"
            ? {}
            : { result: item.output, isError: item.status === "error" }),
        },
      ];
    case "subagent": {
      const artifact: SubagentArtifact = {
        name: item.name,
        description: item.description,
        items: item.items,
      };
      return [
        {
          type: "tool-call",
          toolCallId: item.id,
          toolName: SUBAGENT_TOOL,
          argsText: item.description,
          artifact,
          ...(item.status === "running"
            ? {}
            : { result: item.output, isError: item.status === "error" }),
        },
      ];
    }
    case "todos":
      return [{ type: "data-todos", data: item.todos }];
    default:
      return []; // user / usage / stopped / error 不是消息片段
  }
}

/** 汇总一轮里所有模型调用的用量，包括子智能体内部的调用。 */
function turnUsage(group: ChatItem[]): TurnUsage | undefined {
  const calls = collectUsage(group);
  if (calls.length === 0) return undefined;
  const costs = calls.flatMap((call) => (call.cost === null ? [] : [call.cost]));
  return {
    input_tokens: calls.reduce((sum, call) => sum + call.input_tokens, 0),
    output_tokens: calls.reduce((sum, call) => sum + call.output_tokens, 0),
    cost: costs.length > 0 ? costs.reduce((sum, cost) => sum + cost, 0) : null,
    calls,
  };
}

function collectUsage(items: ChatItem[]): UsageData[] {
  return items.flatMap((item) =>
    item.kind === "usage" ? [item.usage] : item.kind === "subagent" ? collectUsage(item.items) : [],
  );
}
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/features/chat src/components/chat`

预期：全部通过（2 个文件 20 个测试）。

- [ ] **步骤 5：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 48 个、前端 7 个文件 34 个）。

---

### 任务 7：前端界面

**文件：**
- 新建：`frontend/src/features/usage/format.ts`、`frontend/src/features/usage/ThreadUsageBadge.tsx`
- 修改：`frontend/src/api/client.ts`、`frontend/src/api/queries.ts`、`frontend/src/components/chat/parts.tsx`、`frontend/src/components/chat/ChatThread.tsx`、`frontend/src/features/chat/ChatView.tsx`
- 测试：`frontend/src/features/usage/format.test.ts`（新）

**接口：**
- 消费：任务 6 的 `SUBAGENT_TOOL`、`SubagentArtifact`、`TurnUsage`、`ChatItem`；任务 3、4 的接口。
- 产出：`api.cancelRun(runId)`、`api.threadUsage(threadId)`；`threadUsageQuery(threadId)`（键 `["thread-usage", threadId]`）；`formatTokens(n)`、`formatCost(cost | null)`；`ThreadUsageBadge({ threadId })`；`ChatThread` 新增属性 `onCancel: () => Promise<void>`。
- 界面：思考过程默认折叠（运行中显示"思考中…"）；子智能体卡片默认折叠，展开看它的每一步与交回的结果；待办清单（完成项划线）；每轮回答下方"输入 · 输出 · 费用"可展开每次调用明细；停止后显示"已停止"；运行中发送按钮变为停止按钮；顶栏显示本会话累计（悬停看按模型拆分），每次运行结束后刷新。

- [ ] **步骤 1：写失败的测试**

新建 `frontend/src/features/usage/format.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { formatCost, formatTokens } from "./format";

describe("用量数字的显示", () => {
  it("token 数超过一千用 k、超过一百万用 M，保留一位小数", () => {
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(4629)).toBe("4.6k");
    expect(formatTokens(12_000)).toBe("12k");
    expect(formatTokens(1_250_000)).toBe("1.3M");
  });

  it("费用以美元显示三位有效数字；未知显示破折号，极小值显示小于号", () => {
    expect(formatCost(0.05797)).toBe("$0.058");
    expect(formatCost(1.2345)).toBe("$1.23");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.0004)).toBe("<$0.001");
    expect(formatCost(null)).toBe("—");
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/usage`

预期：FAIL，`Error: Cannot find module './format'`。

- [ ] **步骤 3：实现**

新建 `frontend/src/features/usage/format.ts`：

```ts
/** token 数：超过一千用 k、超过一百万用 M，保留一位小数（整数时不带小数）。 */
export function formatTokens(tokens: number): string {
  if (tokens < 1000) return String(tokens);
  const [value, unit] = tokens < 1_000_000 ? [tokens / 1000, "k"] : [tokens / 1_000_000, "M"];
  return `${Number(value.toFixed(1))}${unit}`;
}

/** 费用（美元）：三位有效数字；未知为破折号。 */
export function formatCost(cost: number | null): string {
  if (cost === null) return "—";
  if (cost === 0) return "$0";
  if (cost < 0.001) return "<$0.001";
  return `$${Number(cost.toPrecision(3))}`;
}
```

在 `frontend/src/api/client.ts` 中，把：

```ts
import type { ModelInfo, RunHistory, RunRecord, Thread } from "./types";

```

改为：

```ts
import type { ModelInfo, RunHistory, RunRecord, Thread, ThreadUsage } from "./types";

```

在 `frontend/src/api/client.ts` 中，把：

```ts
    }),
};
```

改为：

```ts
    }),
  cancelRun: (runId: string) =>
    request<RunRecord>(`/runs/${runId}/cancel`, { method: "POST", body: "{}" }),
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
};
```

在 `frontend/src/api/queries.ts` 末尾追加：

```ts

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
export function threadUsageQuery(threadId: string) {
  return { queryKey: ["thread-usage", threadId], queryFn: () => api.threadUsage(threadId) };
}
```

新建 `frontend/src/features/usage/ThreadUsageBadge.tsx`：

```tsx
import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { threadUsageQuery } from "../../api/queries";
import { formatCost, formatTokens } from "./format";

/** 顶栏：本会话累计用量；鼠标悬停显示按模型版本的拆分。 */
export function ThreadUsageBadge({ threadId }: { threadId: string }) {
  const usage = useQuery(threadUsageQuery(threadId));
  const total = usage.data?.total;
  if (!total || total.calls === 0) return null;
  const details = (usage.data?.by_model ?? [])
    .map(
      (model) =>
        `${model.model}：${model.calls} 次，输入 ${formatTokens(model.input_tokens)}，` +
        `输出 ${formatTokens(model.output_tokens)}，${formatCost(model.cost)}`,
    )
    .join("\n");
  return (
    <span
      className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground"
      title={details}
    >
      <Gauge className="size-3.5" />
      {formatTokens(total.input_tokens + total.output_tokens)} token · {formatCost(total.cost)}
    </span>
  );
}
```

`frontend/src/components/chat/parts.tsx`（整个替换）：

```tsx
import {
  ActionBarPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  useAuiState,
  type DataMessagePartComponent,
  type ReasoningMessagePartComponent,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import {
  Bot,
  Brain,
  Check,
  ChevronRight,
  Circle,
  CircleStop,
  Copy,
  Gauge,
  ListTodo,
  LoaderCircle,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import remarkGfm from "remark-gfm";
import type { TodoItem } from "../../api/types";
import type { ChatItem } from "../../features/chat/reducer";
import { formatCost, formatTokens } from "../../features/usage/format";
import { SUBAGENT_TOOL, type SubagentArtifact, type TurnUsage } from "./adapter";

const MarkdownText = () => (
  <MarkdownTextPrimitive remarkPlugins={[remarkGfm]} className="markdown" />
);

function StatusLabel({ done, isError }: { done: boolean; isError: boolean | undefined }) {
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">
      {!done && <LoaderCircle className="size-3.5 animate-spin" />}
      {done && isError && <TriangleAlert className="size-3.5 text-danger" />}
      {done && !isError && <Check className="size-3.5 text-success" />}
      {!done ? "运行中" : isError ? "出错" : "完成"}
    </span>
  );
}

/** 工具调用卡片：默认折叠，展开后显示参数与结果。 */
export const ToolCard: ToolCallMessagePartComponent = ({ toolName, argsText, result, isError }) => {
  const done = result !== undefined;
  return (
    <details className="group my-2 rounded-lg border border-border bg-card text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
        <Wrench className="size-3.5" />
        <span className="font-mono text-foreground">{toolName}</span>
        <StatusLabel done={done} isError={isError} />
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        <pre className="overflow-x-auto font-mono text-xs text-muted-foreground">{argsText}</pre>
        {done && (
          <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap">
            {String(result)}
          </pre>
        )}
      </div>
    </details>
  );
};

/** 子智能体内部步骤：回答原文、思考、工具调用，嵌套的子智能体递归显示。 */
function NestedItems({ items }: { items: ChatItem[] }) {
  return (
    <div className="space-y-1.5">
      {items.map((item) => {
        switch (item.kind) {
          case "assistant":
            return (
              <p key={item.id} className="whitespace-pre-wrap">
                {item.text}
              </p>
            );
          case "thinking":
            return (
              <p key={item.id} className="whitespace-pre-wrap text-muted-foreground italic">
                {item.text}
              </p>
            );
          case "tool":
            return (
              <p key={item.id} className="flex items-center gap-2 text-muted-foreground">
                <Wrench className="size-3" />
                <span className="font-mono text-foreground">{item.name}</span>
                <StatusLabel done={item.status !== "running"} isError={item.status === "error"} />
              </p>
            );
          case "subagent":
            return (
              <div key={item.id} className="border-l-2 border-border pl-3">
                <p className="text-muted-foreground">
                  {item.name}：{item.description}
                </p>
                <NestedItems items={item.items} />
              </div>
            );
          default:
            return null;
        }
      })}
    </div>
  );
}

/** 子智能体卡片（设计文档 13.1：工具调用片段里的嵌套内容）：默认折叠，展开看它的每一步。 */
export const SubagentCard: ToolCallMessagePartComponent = ({ artifact, result, isError }) => {
  const subagent = artifact as SubagentArtifact;
  const done = result !== undefined;
  return (
    <details className="group my-2 rounded-lg border border-border bg-card text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground">
        <ChevronRight className="size-3.5 shrink-0 transition-transform group-open:rotate-90" />
        <Bot className="size-3.5 shrink-0 text-warning" />
        <span className="shrink-0 font-mono text-foreground">{subagent.name}</span>
        <span className="truncate">{subagent.description}</span>
        <StatusLabel done={done} isError={isError} />
      </summary>
      <div className="space-y-3 border-t border-border px-3 py-2 text-xs">
        <NestedItems items={subagent.items} />
        {done && (
          <div className="border-t border-border pt-2">
            <p className="mb-1 text-muted-foreground">交回的结果</p>
            <p className="whitespace-pre-wrap">{String(result)}</p>
          </div>
        )}
      </div>
    </details>
  );
};

/** 思考过程：默认折叠。 */
export const ReasoningPart: ReasoningMessagePartComponent = ({ text, status }) => (
  <details className="group my-2 text-sm text-muted-foreground">
    <summary className="flex cursor-pointer list-none items-center gap-2">
      <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" />
      <Brain className="size-3.5" />
      {status.type === "running" ? "思考中…" : "思考过程"}
    </summary>
    <p className="mt-1 border-l-2 border-border pl-3 whitespace-pre-wrap">{text}</p>
  </details>
);

const TODO_ICONS = {
  completed: <Check className="size-3.5 text-success" />,
  in_progress: <LoaderCircle className="size-3.5 animate-spin text-warning" />,
  pending: <Circle className="size-3.5 text-muted-foreground" />,
};

/** 待办清单（智能体用 write_todos 拆分的步骤）。 */
export const TodosPart: DataMessagePartComponent = ({ data }) => {
  const todos = data as TodoItem[];
  return (
    <div className="my-2 rounded-lg border border-border bg-card px-3 py-2 text-sm">
      <p className="mb-1 flex items-center gap-2 text-muted-foreground">
        <ListTodo className="size-3.5" />
        待办
      </p>
      <ul className="space-y-1">
        {todos.map((todo, index) => (
          <li key={index} className="flex items-center gap-2">
            {TODO_ICONS[todo.status]}
            <span
              className={todo.status === "completed" ? "text-muted-foreground line-through" : ""}
            >
              {todo.content}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** 回答下方：已停止标记与本轮用量（可展开每次调用明细）。 */
function AssistantFooter() {
  const custom = useAuiState(({ message }) => message.metadata.custom);
  const usage = custom.usage as TurnUsage | undefined;
  const stopped = custom.stopped === true;
  if (!usage && !stopped) return null;
  return (
    <div className="mt-2 flex flex-wrap items-start gap-3 text-xs text-muted-foreground">
      {stopped && (
        <span className="flex items-center gap-1">
          <CircleStop className="size-3.5" />
          已停止
        </span>
      )}
      {usage && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 font-mono">
            <Gauge className="size-3.5" />
            输入 {formatTokens(usage.input_tokens)} · 输出 {formatTokens(usage.output_tokens)} ·{" "}
            {formatCost(usage.cost)}
          </summary>
          <table className="mt-1 font-mono">
            <tbody>
              {usage.calls.map((call, index) => (
                <tr key={index}>
                  <td className="pr-3">{call.caller}</td>
                  <td className="pr-3">{call.actual_model}</td>
                  <td className="pr-3">
                    {formatTokens(call.input_tokens)} / {formatTokens(call.output_tokens)}
                  </td>
                  <td className="pr-3">{formatCost(call.cost)}</td>
                  <td>{(call.duration_ms / 1000).toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

export const UserMessage = () => (
  <MessagePrimitive.Root className="flex justify-end">
    <div className="max-w-[80%] rounded-xl rounded-br-sm bg-primary px-4 py-2.5 whitespace-pre-wrap text-primary-foreground">
      <MessagePrimitive.Parts />
    </div>
  </MessagePrimitive.Root>
);

export const AssistantMessage = () => (
  <MessagePrimitive.Root className="group relative">
    <MessagePrimitive.Parts
      components={{
        Text: MarkdownText,
        Reasoning: ReasoningPart,
        tools: { by_name: { [SUBAGENT_TOOL]: SubagentCard }, Fallback: ToolCard },
        data: { by_name: { todos: TodosPart } },
      }}
    />
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="mt-2 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <ErrorPrimitive.Message />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
    <AssistantFooter />
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
    >
      <ActionBarPrimitive.Copy
        className="rounded-md p-1 hover:bg-muted hover:text-foreground"
        aria-label="复制"
      >
        <Copy className="size-3.5" />
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  </MessagePrimitive.Root>
);
```

`frontend/src/components/chat/ChatThread.tsx`（整个替换）：

```tsx
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  ThreadPrimitive,
  useExternalStoreRuntime,
  type AppendMessage,
} from "@assistant-ui/react";
import { ArrowUp, Sparkles, Square } from "lucide-react";
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages } from "./adapter";
import { AssistantMessage, UserMessage } from "./parts";

interface ChatThreadProps {
  state: ChatState;
  /** 发送成功返回 true；失败返回 false 时输入框恢复原文，方便直接重试。 */
  onSend: (text: string) => Promise<boolean>;
  /** 停止进行中的运行。 */
  onCancel: () => Promise<void>;
}

/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({ state, onSend, onCancel }: ChatThreadProps) {
  const runtime = useExternalStoreRuntime({
    messages: toThreadMessages(state),
    isRunning: state.running,
    convertMessage: (message) => message,
    onNew: async (message: AppendMessage) => {
      const text = message.content.map((part) => (part.type === "text" ? part.text : "")).join("");
      if (!(await onSend(text))) runtime.thread.composer.setText(text);
    },
    onCancel,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8">
            <ThreadPrimitive.Empty>
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                <Sparkles className="size-8 text-warning" />
                <p className="text-lg text-foreground">今天想做点什么？</p>
                <p className="text-sm">输入问题开始对话，Enter 发送，Shift+Enter 换行</p>
              </div>
            </ThreadPrimitive.Empty>
            <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
          </div>
        </ThreadPrimitive.Viewport>
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
            <ComposerPrimitive.Input
              autoFocus
              rows={1}
              placeholder="给智能体发消息…"
              className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 outline-none placeholder:text-muted-foreground"
            />
            <AuiIf condition={({ thread }) => !thread.isRunning}>
              <ComposerPrimitive.Send
                aria-label="发送"
                className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity disabled:opacity-30"
              >
                <ArrowUp className="size-4" />
              </ComposerPrimitive.Send>
            </AuiIf>
            <AuiIf condition={({ thread }) => thread.isRunning}>
              <ComposerPrimitive.Cancel
                aria-label="停止"
                className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground transition-colors hover:bg-muted"
              >
                <Square className="size-3.5 fill-current" />
              </ComposerPrimitive.Cancel>
            </AuiIf>
          </ComposerPrimitive.Root>
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
```

`frontend/src/features/chat/ChatView.tsx`（整个替换）：

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
import { historyQuery, threadUsageQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
import { ChatThread } from "../../components/chat";
import { ModelSelect } from "../models/ModelSelect";
import { ThreadUsageBadge } from "../usage/ThreadUsageBadge";
import {
  addSendError,
  addUserMessage,
  applyEvent,
  chatFromHistory,
  removeItem,
  type ChatState,
} from "./reducer";

const ACTIVE = new Set(["queued", "running"]);

function ChatSession({ thread, history }: { thread: Thread; history: RunHistory[] }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ChatState>(() => chatFromHistory(history));
  const [model, setModel] = useState(thread.model);
  const [activeRunId, setActiveRunId] = useState<string | null>(
    () => history.find((run) => ACTIVE.has(run.status))?.id ?? null,
  );

  useEffect(() => {
    if (!activeRunId) return;
    return subscribeRun(activeRunId, (event) => {
      setState((current) => applyEvent(current, event));
      if (event.type === "run.finished") {
        setActiveRunId(null);
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
      }
    });
  }, [activeRunId, queryClient, thread.id]);

  /** 发送成功返回 true；失败时撤回乐观显示的消息并显示错误，返回 false 让输入框恢复原文。 */
  const send = async (text: string): Promise<boolean> => {
    const userId = `user-${Date.now()}`;
    setState((current) => ({ ...addUserMessage(current, userId, text), running: true }));
    try {
      const run = await api.startRun(thread.id, text, model);
      setActiveRunId(run.id);
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
      return true;
    } catch (error) {
      setState((current) =>
        addSendError(removeItem(current, userId), `err-${Date.now()}`, readableError(error)),
      );
      return false;
    }
  };

  /** 停止当前运行；结果（已停止）随推送到达。失败时显示原因，运行状态以推送为准。 */
  const cancel = async (): Promise<void> => {
    if (!activeRunId) return;
    try {
      await api.cancelRun(activeRunId);
    } catch (error) {
      setState((current) => ({
        ...addSendError(current, `err-${Date.now()}`, `停止失败：${readableError(error)}`),
        running: current.running,
      }));
    }
  };

  return (
    <>
      <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
        <h1 className="truncate font-medium">{thread.title || "新会话"}</h1>
        <div className="flex shrink-0 items-center gap-4">
          <ThreadUsageBadge threadId={thread.id} />
          <ModelSelect value={model} onChange={setModel} />
        </div>
      </header>
      <ChatThread state={state} onSend={send} onCancel={cancel} />
    </>
  );
}

export function ChatView({ thread }: { thread: Thread }) {
  const history = useQuery(historyQuery(thread.id));
  if (history.isError) {
    return <p className="p-6 text-sm text-danger">历史加载失败：{readableError(history.error)}</p>;
  }
  if (!history.data) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        加载中…
      </p>
    );
  }
  return <ChatSession key={thread.id} thread={thread} history={history.data} />;
}
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/features/usage`

预期：2 个测试通过。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`cd frontend && pnpm build`

预期：`make check` 全部通过（Python 单元测试 48 个、前端 8 个文件 36 个）；打包成功（打包体积超过 500KB 的提示是 M1a 已接受的代价）。

---

### 任务 8：文档同步与端到端验证

**文件：**
- 修改：`docs/development/architecture.md`、`docs/development/testing.md`、`docs/development/coding-standards.md`、`docs/decisions/README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`

- [ ] **步骤 1：规范文档**

架构规范新增第 9 节"运行、事件与用量"：

在 `docs/development/architecture.md` 末尾追加：

````markdown

## 9. 运行、事件与用量（设计文档第 10 节、7.7）

**一次运行的链路**：

```
POST /threads/{id}/runs → RunManager.start：建运行记录，交给运行控制登记后台任务
  └→ MainAgent.run（agents）：deepagents 输出流 → 翻译器 → 我们的事件；运行跟踪器挂在回调上
       └→ RunManager._execute（backend）：加序号 → 事件总线（实时推送）
                                          → 每 200 毫秒分批写入 run_events
                                          → 用量事件写入 llm_usage
          结束（完成 / 失败 / 停止 / 服务停止）：run_events 整体替换为合并后的版本 → 更新 runs → 推送 run.finished
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/runtime/events.py` | 事件协议（pydantic）。新增事件在这里定义，前端 `src/api/types.ts` 同步（M1c 起自动生成） |
| `agents/main_agent/runtime/translator.py` | 输出流片段 → 事件。回答与思考取自 `messages` 模式，工具 / 子智能体 / 待办取自 `updates` 模式 |
| `agents/main_agent/runtime/tracker.py` | 运行跟踪器（回调）：子智能体命名空间 → task 调用 ID；每次模型调用的用量 |
| `agents/main_agent/models/cleanup.py` | 换模型清理中间件：发给模型的请求里去掉其他模型产生的思考内容 |
| `agents/main_agent/usage/` | `llm_usage` 表的数据访问与查询（每次调用明细、会话按模型汇总） |
| `backend/runs/manager.py` | 运行编排：执行、停止、服务停止时收尾、补发 |
| `backend/runs/writer.py` | 事件分批写库与结束时的整体替换 |
| `backend/runtime/` | 运行时替换点：事件总线（②）、运行控制（③） |

约定：
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即写入 `llm_usage`（写库失败只记日志、不影响对话）；`run.finished` 带本次合计并写入 `runs.usage`。费用取网关算好的 `response_cost`，未知为空。被停止的那次模型调用拿不到用量，不计入。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
4. **界面历史**：运行中写入的是原始事件（进程中途退出也不丢已推送内容）；结束时替换为合并版本（同一段回答 / 思考的逐字片段合并，带 `full_text`）。补发时若历史里没有结束事件，补一个失败的结束事件，前端才会停止重连。
````

在 `docs/development/testing.md` 中，把：

```markdown
- 先写测试、看它失败，再写实现。
- **不调用真实模型**：用 `agents/tests/fakes.py` 里的 `ScriptedChatModel`（按剧本回复，支持工具调用与逐字流式）、`FailingChatModel`、`FakeGateway`。LangChain 自带的 `GenericFakeChatModel` 在流式模式下不支持工具调用，不要用。
- **契约测试**：每个可替换接口在 `agents/tests/contracts/` 下有一套测试，用 `IMPLEMENTATIONS` 列表参数化；新实现必须加进列表并跑通。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空 backend 的表）；不要连接开发库。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`。
```

改为：

```markdown
- 先写测试、看它失败，再写实现。
- **不调用真实模型**：用 `agents/tests/fakes.py` 里的 `ScriptedChatModel`（按剧本回复，支持工具调用、思考过程、用量与逐字流式，并记下每次收到的消息）、`HangingChatModel`（第一次调用输出一个字后一直等待，用于验证停止）、`FailingChatModel`、`FakeGateway`。LangChain 自带的 `GenericFakeChatModel` 在流式模式下不支持工具调用，不要用。
- **契约测试**：每个可替换接口有一套测试，用参数化列出全部实现；新实现必须加进列表并跑通。agents 的接口在 `agents/tests/contracts/`；backend 的运行时替换点在 `backend/tests/`（如 `test_run_control.py`）。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`。
```

类型自动生成与决策记录挪到 M1c：

在 `docs/development/coding-standards.md` 中，把：

```markdown
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型集中在 `src/api/types.ts`（M1b 起改为自动生成）。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
```

改为：

```markdown
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型集中在 `src/api/types.ts`（M1c 起改为自动生成）。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
```

在 `docs/decisions/README.md` 中，把：

```markdown
|---|---|---|
| D01～D15 | 见设计文档第 3 节（M1b 逐条补成独立记录） | 已采纳 |
| D16 | [前端采用 assistant-ui 与主题系统](D16-前端采用assistant-ui与主题系统.md) | 已采纳 |
```

改为：

```markdown
|---|---|---|
| D01～D15 | 见设计文档第 3 节（M1c 逐条补成独立记录） | 已采纳 |
| D16 | [前端采用 assistant-ui 与主题系统](D16-前端采用assistant-ui与主题系统.md) | 已采纳 |
```

- [ ] **步骤 2：需求池与变更记录**（R04b 拆为 R04b 与 R04c；浏览器验证全部通过后 R04b 才是"完成"）

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R04a | 前端改版（主题系统、assistant-ui 对话层、新布局）与一键启动 | M1a | 高 | 完成 |
| R04b | 取消、深度思考与子智能体展示、用量统计、事件分批写库、本机安全防护、前端类型自动生成 | M1b | 高 | 计划 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
```

改为：

```markdown
| R04a | 前端改版（主题系统、assistant-ui 对话层、新布局）与一键启动 | M1a | 高 | 完成 |
| R04b | 运行体验：停止、深度思考与子智能体展示、待办清单、用量入库与展示、事件分批写库、换模型清理、服务停止时收尾 | M1b | 高 | 完成 |
| R04c | 本机安全防护、前端类型自动生成、决策记录 D1～D15、M1a 遗留小问题 | M1c | 高 | 计划 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
```

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R07 | MCP 接入、审批暂停与恢复、预算刹车 | M4 | 高 | 计划 |
| R08 | 用量统计页、备份命令、端到端测试、使用指南 | M5 | 中 | 计划 |
| R09 | 联网搜索与网页阅读（MCP） | 扩展阶段 1 | 中 | 待定 |
```

改为：

```markdown
| R07 | MCP 接入、审批暂停与恢复、预算刹车 | M4 | 高 | 计划 |
| R08 | 用量统计页（含 `GET /usage/summary`、调用网关时附带会话与运行 ID 便于在网关后台核对）、备份命令、端到端测试、使用指南 | M5 | 中 | 计划 |
| R09 | 联网搜索与网页阅读（MCP） | 扩展阶段 1 | 中 | 待定 |
```

在 `docs/changelog.md` 中，把：

```markdown
## 未发布

```

改为：

```markdown
## 未发布

### M1b 运行体验（完成）

- 新增：停止按钮——运行中输入框的发送按钮变为停止，停止后回答下方标记"已停止"，可直接继续对话（`POST /api/runs/{id}/cancel`，运行时替换点③"运行控制"）。
- 新增：深度思考过程（默认折叠）、子智能体卡片（展开可看它的每一步，并行派出也不会串）、待办清单（原地更新）。
- 新增：用量统计——每次模型调用写入 `llm_usage`；每轮回答下方显示输入 / 输出 token 与费用（可展开每次调用明细），顶栏显示本会话累计（`GET /api/threads/{id}/usage`、`GET /api/runs/{id}/usage`）。
- 新增：换模型清理——会话中途换模型时，旧模型的思考内容不再发给新模型（对话存档保持原样）。
- 改进：运行事件每 200 毫秒分批写库，进程中途退出也不丢已推送的内容；结束时整体替换为合并版本。
- 修复：服务停止时进行中的运行没有收尾（M0 遗留 M3；容器启动命令改为 `exec` 启动 uvicorn 并带 `--timeout-graceful-shutdown 3`）；回答片段 ID 缺失时用空串兜底（M0 遗留 M6）；只存了部分事件的运行补发时不结束、前端一直重连。
- 已知限制：被停止的那次模型调用拿不到用量，不计入统计。

```

- [ ] **步骤 3：浏览器端到端验证**（`make up` 重新构建镜像后打开 http://127.0.0.1:8000；会调用真实模型，费用约 0.3 美元）

1. 新会话，发送"农夫要带狼、羊、白菜过河，船每次只能带一样，狼和羊、羊和白菜不能单独留下。请认真推理后用三句话给出步骤。"：先出现折叠的"思考中…"，回答完成后变为"思考过程"（可展开）；运行中输入框右侧是停止按钮；回答下方一行"输入 … · 输出 … · $…"，点开有每次调用明细；顶栏出现本会话累计。
2. 发送"请先用 write_todos 列出两步计划，然后用 task 工具派 general-purpose 子智能体去列出根目录 / 下的文件，最后更新待办并用一句话汇报结果。"：待办清单出现并原地更新为全部完成（划线）；子智能体卡片展开后可见它的思考、`ls` 工具与回答，以及"交回的结果"；**不出现** `write_todos` 工具卡片；本轮用量包含子智能体的调用。
3. 发送"请写一篇约 2000 字的文章，介绍中国古代四大发明及其影响，直接写。"，几秒后点停止：回答立即停止，下方显示"已停止"，停止按钮变回发送按钮；再发送"用一句话概括四大发明。"正常回答。
4. 刷新页面、重新打开该会话：思考过程、待办、子智能体卡片、"已停止"、每轮用量与顶栏合计全部重现。
5. 顶栏模型切换为 `gemini-3.5-flash`，发送"刚才农夫过河一共几步？只回答数字。"：正常回答、无报错，顶栏悬停可见两个模型的拆分。
6. 发送一个长文请求，回答进行中运行 `podman restart open-personal-agent-backend-1`：约 5 秒内重启完成；刷新页面后该轮显示已输出的内容和红色的"服务停止，运行被中断"。

预期：以上全部符合描述。

- [ ] **步骤 4：检查点**

运行：`make check`

运行：`make test-int`

预期：全部通过（`make check` Python 单元测试 48 个、前端 36 个；`make test-int` 集成测试 31 个）。全部通过后，把 `docs/changelog.md` 的 M1b 小节保持"（完成）"、`docs/requirements/backlog.md` 的 R04b 保持"完成"；若浏览器验证有未通过项，两处改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖（第 21 节 M1 行的运行部分）：** 取消 → 任务 4、7；深度思考展示 → 任务 1、6、7；换模型清理 → 任务 2；完整事件集（含子智能体 `agent_path`、待办、用量）→ 任务 1、6、7；用量统计入库与每轮展示 → 任务 3、6、7；事件批量写入与续传完善 → 任务 5；M0 延后的 M3（停机回收）→ 任务 4，M6（片段 ID 兜底）→ 任务 1。本机安全防护、前端类型自动生成、决策记录 D1～D15、M1a 遗留小问题 → M1c。用量统计页（按天趋势、`GET /usage/summary`）属 M5。
- **与设计文档的差异：** ① 用量记录器与"子智能体命名空间 → 调用 ID"的对应关系合并为一个"运行跟踪器"，放在 `runtime/`（两者都依赖同一组回调）；`usage/` 模块只负责表的读写与查询。② 用量由 backend 收到 `usage` 事件时写入（表仍归 agents 所有、只经 `UsageRepo` 读写），这样用量与界面事件走同一条链路、写库失败不影响对话。③ 子智能体卡片的内部步骤放在工具调用片段的 `artifact` 里由本项目组件渲染（assistant-ui 的嵌套 `messages` 需要完整消息对象，接入成本高）。④ 被停止的那次模型调用拿不到用量，不计入（已写入变更记录的"已知限制"）。⑤ 设计文档 7.1"每次调用附带会话 ID 与运行 ID 作为网关元数据"本期未做：组装好的智能体按模型版本缓存，逐次附带需改为运行时绑定；已并入需求池 R08（M5 用量统计页）。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：** 事件字段在 `events.py`、`types.ts`、事件处理器、转换函数中一致（已用严格类型检查、mypy 与重放验证）；`RunManager` 的构造参数按任务 3（`usage`）→ 任务 4（`control`）→ 任务 5（`flush_interval`）逐步增加，测试同步更新。
