"""把 deepagents（LangGraph v2 输出流）的原始片段翻译成我们的事件。

- 回答与思考的逐字片段取自 `messages` 模式的 AIMessageChunk。思考的起止另推 thinking.started /
  thinking.finished（设计 2026-10-23 4.8）：第一段思考到来时开始；第一段文字、第一个工具调用到来，
  或这次调用结束（`model` 节点更新）时结束。时间戳在发布时加上。
- 工具、子智能体的开始 / 结束和待办清单取自 `updates` 模式里 `model` / `tools` 节点的完整内容
  （`messages` 模式里的工具参数是分片的，不适合直接展示）。
- deepagents 的 task 工具就是"派出子智能体"，翻译成 subagent.* 事件；子智能体内部的事件
  通过运行跟踪器把命名空间换算成 agent_path。
- 工具真正开始执行（审批之后）取自 `custom` 模式里 ToolRunningMiddleware 写的片段，
  翻译成 tool.running。
- 审批暂停（`__interrupt__`）不立即输出：收集成请求放在 approvals 里，流结束后由主智能体
  合成一个 approval.required。子智能体里的中断先在它的命名空间出现一次（从这里得知 agent_path），
  再在顶层出现一次（以顶层这次为准，生成请求）。
"""

import re
from collections.abc import Iterator, Mapping
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Interrupt, StreamPart

from agents.main_agent.runtime.content import text_of
from agents.main_agent.runtime.events import (
    MAIN,
    ApprovalAction,
    ApprovalRequest,
    Event,
    MemorySaved,
    MessageDelta,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    ThinkingFinished,
    ThinkingStarted,
    TodoItem,
    TodosUpdated,
    ToolFinished,
    ToolRunning,
    ToolStarted,
    UserInterjected,
)
from agents.main_agent.runtime.interjection import USER_INTERJECTED
from agents.main_agent.runtime.knowledge import REMEMBER_TOOL
from agents.main_agent.runtime.tool_running import TOOL_RUNNING
from agents.main_agent.runtime.tracker import RunTracker, is_compaction

TOOL_OUTPUT_LIMIT = 2000
SUBAGENT_TOOL = "task"
TODO_TOOL = "write_todos"  # 只以 todos.updated（完整清单）显示，不再另显示工具卡片
# 审批中间件：被拒绝的调用由它直接写入结果（不经过 tools 节点）
APPROVAL_NODE = "HumanInTheLoopMiddleware.after_model"


class Translator:
    """一次运行一个翻译器。"""

    def __init__(self, tracker: RunTracker, mcp_servers: Mapping[str, str] | None = None) -> None:
        self._tracker = tracker
        self._mcp_servers = mcp_servers or {}  # MCP 工具名 → 服务名
        self._subagents: dict[str, str] = {}  # task 调用 ID → 子智能体名
        # 已开始、还没结束的调用：(agent_path, 名字, 参数, 调用 ID)，审批请求据此找到调用 ID
        self._running: list[tuple[list[str], str, dict[str, Any], str]] = []
        self._interrupt_paths: dict[str, list[str]] = {}  # 中断 ID → 所在智能体
        # 正在思考、已经想完的（智能体，消息）：同一段只推一次开始与结束
        self._thinking: dict[tuple[str, ...], set[str]] = {}
        self._thought: set[tuple[tuple[str, ...], str]] = set()
        self.approvals: list[ApprovalRequest] = []

    def translate(self, part: StreamPart[Any, Any]) -> Iterator[Event]:
        path = self._tracker.agent_path(part["ns"])
        if part["type"] == "messages":
            chunk, metadata = part["data"]
            if isinstance(chunk, AIMessageChunk) and not is_compaction(metadata):
                # 片段 ID 一般总有；缺失时用本次模型调用的命名空间，同一次调用内保持不变
                message_id = chunk.id or metadata.get("langgraph_checkpoint_ns", "")
                if thinking := _thinking_of(chunk):
                    yield from self._start_thinking(path, message_id)
                    yield ThinkingDelta(agent_path=path, message_id=message_id, text=thinking)
                text = text_of(chunk.content)
                if text or chunk.tool_call_chunks:
                    yield from self._finish_thinking(path, message_id)
                if text:
                    yield MessageDelta(agent_path=path, message_id=message_id, text=text)
        elif part["type"] == "custom":
            data = part["data"]
            if isinstance(data, dict) and data.get("type") == TOOL_RUNNING:
                skill = data.get("skill")
                yield ToolRunning(
                    agent_path=path,
                    call_id=str(data["call_id"]),
                    name=str(data.get("name", "")),
                    skill=str(skill) if skill else None,
                )
            elif isinstance(data, dict) and data.get("type") == USER_INTERJECTED:
                yield UserInterjected(agent_path=path, id=str(data["id"]), text=str(data["text"]))
        elif part["type"] == "updates":
            if "__interrupt__" in part["data"]:
                self._collect_interrupts(part["data"]["__interrupt__"], path, top=not part["ns"])
                return
            yield from self._translate_updates(part["data"], path)

    def _start_thinking(self, path: list[str], message_id: str) -> Iterator[Event]:
        key = tuple(path)
        if (key, message_id) in self._thought or message_id in self._thinking.get(key, set()):
            return
        self._thinking.setdefault(key, set()).add(message_id)
        yield ThinkingStarted(agent_path=path, message_id=message_id)

    def _finish_thinking(self, path: list[str], message_id: str | None = None) -> Iterator[Event]:
        """结束这一层正在进行的思考：指定消息的，或（这次调用结束时）这一层全部的。"""
        key = tuple(path)
        open_ids = self._thinking.get(key, set())
        for ended in sorted(open_ids) if message_id is None else [message_id]:
            if ended in open_ids:
                open_ids.discard(ended)
                self._thought.add((key, ended))
                yield ThinkingFinished(agent_path=path, message_id=ended)

    def _collect_interrupts(self, interrupts: Any, path: list[str], *, top: bool) -> None:
        for item in interrupts:
            if not isinstance(item, Interrupt) or item.id is None:
                continue
            if not top:
                self._interrupt_paths[item.id] = path
            elif all(request.interrupt_id != item.id for request in self.approvals):
                self.approvals.append(self._request(item))

    def _request(self, item: Interrupt) -> ApprovalRequest:
        assert item.id is not None  # 调用方已检查
        path = self._interrupt_paths.get(item.id, [MAIN])
        value = item.value if isinstance(item.value, dict) else {}
        allowed = {
            config["action_name"]: config["allowed_decisions"]
            for config in value.get("review_configs", [])
        }
        claimed: set[str] = set()
        actions = []
        for action in value.get("action_requests", []):
            name, args = action["name"], action["args"]
            call_id = next(
                (
                    call_id
                    for call_path, call_name, call_args, call_id in self._running
                    if call_path == path
                    and call_name == name
                    and call_args == args
                    and call_id not in claimed
                ),
                "",
            )
            claimed.add(call_id)
            actions.append(
                ApprovalAction(
                    call_id=call_id,
                    name=name,
                    args=args,
                    server=self._mcp_servers.get(name),
                    description=str(action.get("description", "")),
                    allowed=allowed.get(name, ["approve", "reject"]),
                )
            )
        return ApprovalRequest(interrupt_id=item.id, agent_path=path, actions=actions)

    def _translate_updates(self, data: dict[str, Any], path: list[str]) -> Iterator[Event]:
        for node, update in data.items():
            if not isinstance(update, dict):
                continue
            if node == APPROVAL_NODE:
                for message in update.get("messages", []):
                    if isinstance(message, ToolMessage) and message.name != TODO_TOOL:
                        yield self._finished(message, path)
                continue
            if node not in ("model", "tools"):
                continue
            if node == "model":
                yield from self._finish_thinking(path)  # 这次调用结束
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
                    if saved := _memory_saved(message, path):
                        yield saved

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
        self._running.append((path, name, args, call_id))
        return ToolStarted(agent_path=path, call_id=call_id, name=name, args=args)

    def _finished(self, message: ToolMessage, path: list[str]) -> Event:
        call_id = message.tool_call_id
        self._running = [call for call in self._running if call[3] != call_id]
        status = "error" if message.status == "error" else "success"
        output = _clip(text_of(message.content))
        if message.name == SUBAGENT_TOOL:
            name = self._subagents.get(call_id, "")
            return SubagentFinished(
                agent_path=path, call_id=call_id, name=name, status=status, output=output
            )
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        exit_code = artifact.get("exit_code")
        return ToolFinished(
            agent_path=path,
            call_id=call_id,
            name=message.name or "",
            status=status,
            output=output,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            stderr=str(artifact.get("stderr") or "")[-TOOL_OUTPUT_LIMIT:],  # 报错多在最后
        )


# deepagents 在执行命令的输出末尾追加的状态行（可能还跟着一行截断说明）
_STATUS_TAIL = re.compile(
    r"\n\[Command (?:succeeded|failed) with exit code -?\d+\](?:\n\[[^\]\n]*\])?\s*$"
)


def _clip(text: str) -> str:
    """超长的工具结果截到 TOOL_OUTPUT_LIMIT。执行命令末尾的退出码那一行留下：
    界面靠它显示命令成没成功（设计 2026-10-22 3.5），长输出最容易是装包、跑测试这类会失败的命令。"""
    if len(text) <= TOOL_OUTPUT_LIMIT:
        return text
    tail = _STATUS_TAIL.search(text)
    if tail is None:
        return text[:TOOL_OUTPUT_LIMIT]
    kept = tail.group(0)
    return text[: TOOL_OUTPUT_LIMIT - len(kept) - 2] + "\n…" + kept


def _memory_saved(message: ToolMessage, path: list[str]) -> MemorySaved | None:
    """remember 成功时工具结果附带记下的条目（工具的 artifact），据此推送"已记住"。"""
    item = message.artifact
    if message.name != REMEMBER_TOOL or message.status == "error" or not isinstance(item, dict):
        return None
    return MemorySaved(
        agent_path=path,
        item_id=str(item["id"]),
        content=str(item["content"]),
        tags=[str(tag) for tag in item["tags"]],
        pinned=bool(item["pinned"]),
        suspicious=None if item.get("trusted") else item.get("suspicious"),
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
