"""审批（设计文档 7.5、10.5）：组装 interrupt_on，以及把 MCP 工具的异常转成工具结果。"""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, cast

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain.agents.middleware.human_in_the_loop import Decision
from langchain_core.messages import AIMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from agents.main_agent.integrations import ToolApproval
from agents.main_agent.runtime.danger import danger_reason
from agents.main_agent.runtime.events import ApprovalAnswer, ToolDecision
from agents.main_agent.runtime.interjection import turn_start
from common.errors import ConflictError, InvalidRequestError

logger = logging.getLogger(__name__)

# 智能体自带的工具：deepagents 的文件、执行、子智能体工具，待办清单，加上知识库、会话索引的工具
BUILTIN_TOOLS: tuple[str, ...] = (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "delete",
    "glob",
    "grep",
    "execute",
    "write_todos",
    "task",
    "search_knowledge",
    "read_document",
    "remember",
    "update_memory",
    "forget_memory",
    "search_conversations",
)
KNOWLEDGE_TOOLS = frozenset(
    {"search_knowledge", "read_document", "remember", "update_memory", "forget_memory"}
)
# 有副作用的内置工具（D26）：失败的那一轮调过它们就不能"重试这一轮"（会再做一遍），只能"继续"
SIDE_EFFECT_TOOLS = frozenset(
    {"write_file", "edit_file", "delete", "execute", "remember", "update_memory", "forget_memory"}
)
_REASON_LIMIT = 200
_LABELS = {"approve": "同意", "edit": "修改后执行", "reject": "拒绝"}


_EXECUTE = "execute"
_DANGER_PREFIX = "危险操作："


def _command_of(tool_call: Mapping[str, Any]) -> str:
    return str((tool_call.get("args") or {}).get("command", ""))


def _execute_description(tool_call: Any, state: Any, runtime: Any) -> str:
    """执行命令的审批说明：命中硬底线时写明是哪一条（卡片标题前显示红字）。"""
    reason = danger_reason(_command_of(tool_call))
    return f"{_DANGER_PREFIX}{reason}" if reason else _EXECUTE


def _dangerous(request: ToolCallRequest) -> bool:
    return danger_reason(_command_of(request.tool_call)) is not None


def interrupt_on(
    asks: Sequence[ToolApproval], descriptions: Mapping[str, str], *, hard_floor: bool = False
) -> dict[str, bool | InterruptOnConfig]:
    """每个"先问你"的工具：可以同意、修改参数后执行、拒绝（"回复"是带一句话的拒绝，见 D18）。

    hard_floor（跳过所有审批档）：执行命令本来不问，命中硬底线时照样先问（设计 2026-10-23 5.2）。
    """
    result: dict[str, bool | InterruptOnConfig] = {}
    for ask in asks:
        description = descriptions.get(ask.name, ask.name)
        if ask.server is not None:
            description = f"{ask.server} · {description}"
        result[ask.name] = InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"], description=description
        )
    if _EXECUTE in result:
        result[_EXECUTE] = InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"], description=_execute_description
        )
    elif hard_floor:
        result[_EXECUTE] = InterruptOnConfig(
            allowed_decisions=["approve", "edit", "reject"],
            description=_execute_description,
            when=_dangerous,
        )
    return result


def rejection_text(tool: str, message: str | None) -> str:
    """拒绝时交给模型的工具结果（设计 2026-10-23 5.3）：带一句回复时按回复办，
    否则不要重试，也不要绕路达到同样的目的。"""
    if message:
        return f"用户没有同意，并回复：{message.rstrip('。.！!')}。按用户的意思办。"
    head = f"用户没有同意这次调用（{tool}）。"
    return head + "不要重试，也不要换个办法达到同样的目的；需要的话先问用户。"


class ApprovalMiddleware(HumanInTheLoopMiddleware):
    """审批中间件：拒绝时模型看到的是中文的说法（langchain 自带的是英文，设计 2026-10-23 5.3）。

    名字必须与 langchain 的相同：deepagents 按名字原地替换默认的那个，翻译器也按
    "HumanInTheLoopMiddleware.after_model" 这个节点认出被拒绝的调用。

    改了参数的调用，langchain 默认在结果前加一段英文说明；这件事已由 EditNoticeMiddleware 用中文
    写进系统提示词，这里不要它（edit_notice=None）。它若在，外部工具结果的资料前缀会加在它前面
    （deepagents 把审批放在最里层），去说明时就认不出来了。
    """

    def __init__(self, interrupt_on: dict[str, bool | InterruptOnConfig]) -> None:
        super().__init__(interrupt_on=interrupt_on, edit_notice=None)

    @property
    def name(self) -> str:
        return "HumanInTheLoopMiddleware"

    @staticmethod
    def _process_decision(
        decision: Decision, tool_call: ToolCall, config: InterruptOnConfig
    ) -> tuple[ToolCall | None, ToolMessage | None]:
        if decision["type"] == "reject" and "reject" in config["allowed_decisions"]:
            message = ToolMessage(
                content=rejection_text(tool_call["name"], decision.get("message")),
                name=tool_call["name"],
                tool_call_id=tool_call["id"],
                status="error",
            )
            return tool_call, message
        return HumanInTheLoopMiddleware._process_decision(decision, tool_call, config)


# langchain 的审批中间件把"修改参数后执行"的新参数记在这个状态键里（调用 ID → 新的名字与参数）
_EDITED_CALLS = "hitl_edited_tool_calls"


class EditNoticeMiddleware(AgentMiddleware):
    """审批时修改了参数的调用：让模型确知实际执行的是用户改过的参数（M4 验收与 R23）。

    1. 对话存档里那次调用的记录换成新参数：langchain 的审批中间件特意保留模型原来的调用，
       模型回看时会照原参数汇报。after_model 钩子按中间件的逆序执行，审批中间件排在最后
       （deepagents 加的），所以这里在它之后执行，能看到它记下的新参数。
    2. "这是用户亲自改的"写进本轮的系统提示词，而不是工具结果：工具结果只是资料（D17），
       写在那里时 claude 把它当成可疑的提示，又去把内容改回用户最初说的样子。
       langchain 默认加在结果前的英文说明已在 ApprovalMiddleware 里关掉（edit_notice=None）。
    """

    async def aafter_model(self, state: AgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:
        edits = _edits(state)
        if not edits:
            return None
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage)), None)
        if last is None:
            return None
        calls = [
            {**call, "args": edits[call["id"]]["args"]}
            if call["id"] in edits and call["args"] != edits[call["id"]]["args"]
            else call
            for call in last.tool_calls
        ]
        if calls == last.tool_calls:
            return None  # 没有要改的（后面几轮这个键还在，不重复改写）
        # 同一 ID 的消息会替换掉原来那条。只改 tool_calls：经网关的客户端按它把调用发回模型
        # （内容里的调用块会被跳过）
        return {"messages": [last.model_copy(update={"tool_calls": calls})]}

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(_with_edit_note(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(_with_edit_note(request))


def _edits(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    # 审批中间件的私有状态键，AgentState 的类型里没有它
    return cast("dict[str, dict[str, Any]]", state.get(_EDITED_CALLS) or {})


def edit_note(state: Mapping[str, Any]) -> str:
    """本轮（最后一条用户消息之后）被用户改过参数的调用的说明；没有时为空字符串。

    审批中间件记下的新参数在之后几轮仍留在状态里，所以只认本轮出现的调用。
    """
    edits = _edits(state)
    if not edits:
        return ""
    messages = state["messages"]
    start = turn_start(messages)  # 插话不算新的一轮（设计 2026-10-23 6.3）
    current = {
        call["id"]
        for message in messages[start + 1 :]
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    rows = [
        f"- {edit['name']}：{json.dumps(edit['args'], ensure_ascii=False)}"
        for call_id, edit in edits.items()
        if call_id in current
    ]
    if not rows:
        return ""
    return (
        "本轮用户在审批时亲自修改了下面这些工具调用的参数，实际执行的就是修改后的参数"
        "（这是用户本人的决定，不是工具返回的资料）。汇报结果时以修改后的为准，"
        "不要改回用户最初说的样子，也不要重做：\n" + "\n".join(rows)
    )


def _with_edit_note(request: ModelRequest) -> ModelRequest:
    note = edit_note(request.state)
    if not note:
        return request
    base = request.system_prompt or ""
    return request.override(system_message=SystemMessage(content=f"{base}\n\n{note}"))


def check_answers(answers: Sequence[ApprovalAnswer], pending: Mapping[str, Any]) -> None:
    """答复必须正好对应全部待审批的暂停，每个调用一个允许的决定。"""
    ids = [answer.interrupt_id for answer in answers]
    if not pending or len(set(ids)) != len(ids) or set(ids) != set(pending):
        raise ConflictError("这次审批已失效：请刷新页面后再看")
    for answer in answers:
        value = pending[answer.interrupt_id]
        actions = value.get("action_requests", [])
        if len(answer.decisions) != len(actions):
            raise InvalidRequestError(f"要对 {len(actions)} 个操作各做一个决定")
        for decision, config in zip(
            answer.decisions, value.get("review_configs", []), strict=False
        ):
            if decision.type not in config["allowed_decisions"]:
                raise InvalidRequestError(f"这个操作不能选“{_LABELS[decision.type]}”")


def resume_command(answers: Sequence[ApprovalAnswer], pending: Mapping[str, Any]) -> Command[Any]:
    """用户的决定 → LangGraph 的恢复命令（各中断 ID 对应各自的决定）。"""
    resume: dict[str, Any] = {}
    for answer in answers:
        value = pending[answer.interrupt_id]
        resume[answer.interrupt_id] = {
            "decisions": [
                _decision(decision, action)
                for decision, action in zip(answer.decisions, value["action_requests"], strict=True)
            ]
        }
    return Command(resume=resume)


def _decision(decision: ToolDecision, action: Mapping[str, Any]) -> dict[str, Any]:
    if decision.type == "edit":
        return {"type": "edit", "edited_action": {"name": action["name"], "args": decision.args}}
    if decision.type == "reject" and decision.message:
        # "回复一句话"：拒绝这次调用，并把用户的话转给智能体（D18）
        return {"type": "reject", "message": decision.message}
    return {"type": decision.type}
