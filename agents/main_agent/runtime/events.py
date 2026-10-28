"""智能体对外推送的事件协议（设计文档 10.3）。backend 原样转发，只在外层加序号等信封字段。

agent_path 表示事件属于哪个智能体：主智能体为 ["main"]；子智能体内部的事件为
["main", "<派出它的 task 调用 ID>"]，前端据此把它们嵌套显示在对应的子智能体卡片里。
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from agents.main_agent.models import ErrorKind

MAIN = "main"


# 导出的类型定义里，有默认值的字段也标为必有：输出的数据总带着它们，前端类型不必处理"可能没有"
_OUTPUT = ConfigDict(json_schema_serialization_defaults_required=True)


class _BaseEvent(BaseModel):
    model_config = _OUTPUT

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


class ThinkingStarted(_BaseEvent):
    """这次调用开始思考（第一段思考到来时，设计 2026-10-23 4.8）：前端用它的时间算思考用时。"""

    type: Literal["thinking.started"] = "thinking.started"
    message_id: str


class ThinkingFinished(_BaseEvent):
    """思考结束：第一段文字或第一个工具调用到来，或这次调用结束时。"""

    type: Literal["thinking.finished"] = "thinking.finished"
    message_id: str


class ToolStarted(_BaseEvent):
    type: Literal["tool.started"] = "tool.started"
    call_id: str
    name: str
    args: dict[str, Any]


class UserInterjected(_BaseEvent):
    """运行中的插话送达了（设计 2026-10-23 6.3）：界面在这一轮里显示成一条用户消息。"""

    type: Literal["user.interjected"] = "user.interjected"
    id: str
    text: str


class ToolRunning(_BaseEvent):
    """工具真正开始执行（审批之后，设计 2026-10-23 5.7）：前端从这时算用时，等过审批的也有用时。"""

    type: Literal["tool.running"] = "tool.running"
    call_id: str
    # 工具名与读到的技能（设计 2026-10-23 6.8，后端据此记工具用量）；旧历史没有
    name: str = ""
    skill: str | None = None


class ToolFinished(_BaseEvent):
    type: Literal["tool.finished"] = "tool.finished"
    call_id: str
    name: str
    status: Literal["success", "error"]
    output: str
    # 执行命令的真实退出码与错误输出（设计 2026-10-23 5.4）；别的工具、旧历史没有
    exit_code: int | None = None
    stderr: str = ""


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
    """一次模型调用的用量（设计文档 7.7）。只算 token，不算费用（设计 2026-10-19 4.11）：
    input_tokens 是实际发给模型的全部输入（含命中缓存的部分），缓存读写与思考另记明细。"""

    type: Literal["usage"] = "usage"
    caller: str
    requested_model: str
    actual_model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    duration_ms: int = 0


class ContextUsage(_BaseEvent):
    """主智能体这次调用模型时上下文各部分的大小（设计 2026-10-23 4.7），在拿到最终请求时算。

    按真实分词器估算、再用该模型最近一次的实际用量校准；工具条据此显示"上下文 N%"与分段。
    """

    type: Literal["context.usage"] = "context.usage"
    system: int  # 系统提示词（不含常驻记忆）
    profile: int  # 常驻记忆
    tools: int  # 工具定义
    related: int  # 本轮附加的相关记忆
    history: int  # 对话历史
    total: int
    max_input_tokens: int | None


class UsageTotals(BaseModel):
    """一次运行的用量合计。"""

    model_config = _OUTPUT

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage: UsageReported) -> "UsageTotals":
        return UsageTotals(
            calls=self.calls + 1,
            input_tokens=self.input_tokens + usage.input_tokens,
            output_tokens=self.output_tokens + usage.output_tokens,
        )


class InterruptedUsage(BaseModel):
    """被中断的模型调用的估算用量（中断后网关不返回用量）：只用于显示，不计入用量表与合计。"""

    model_config = _OUTPUT

    input_tokens: int
    output_tokens: int


class FileCreated(_BaseEvent):
    """outputs/ 下新增或改动了一个文件（产物，设计文档 9.3）。

    file_id 由 backend 登记后填入（下载地址用它）；智能体发出时为空。
    """

    type: Literal["file.created"] = "file.created"
    path: str  # 相对会话目录，如 outputs/chart.png
    size: int
    media_type: str
    file_id: str | None = None


class MemorySaved(_BaseEvent):
    """智能体用 remember 工具记下了一条记忆（设计文档 8.2），前端提示"已记住：xxx"。"""

    type: Literal["memory.saved"] = "memory.saved"
    item_id: str
    content: str
    tags: list[str]
    pinned: bool
    # 内容像是要求智能体做事的话时的可疑原因（设计 2026-10-23 6.6）：聊天里也标出来；旧历史没有
    suspicious: str | None = None


type DecisionType = Literal["approve", "edit", "reject"]


class ApprovalAction(BaseModel):
    """一个待审批的工具调用。call_id 与它的 tool.started 一致（前端据此标出"等待审批"）。"""

    model_config = _OUTPUT

    call_id: str
    name: str
    args: dict[str, Any]
    server: str | None  # MCP 服务名；内置工具为 None
    description: str
    allowed: list[DecisionType]


class ApprovalRequest(BaseModel):
    """一处暂停：待审批的工具调用（预算刹车已去掉，D23）。"""

    model_config = _OUTPUT

    interrupt_id: str
    agent_path: list[str]
    actions: list[ApprovalAction] = []


class ApprovalRequired(_BaseEvent):
    """运行暂停，等用户决定（设计文档 10.5）。这一段运行到此结束，不发 run.finished。

    tools_version 是暂停时的工具与审批规则的指纹：恢复时对不上（改了规则、MCP 服务没连上），
    这次审批就作废——否则用户的决定可能被无视（如"拒绝"了的调用因为不再需要审批而照样执行）。
    """

    type: Literal["approval.required"] = "approval.required"
    requests: list[ApprovalRequest]
    tools_version: str


class ToolDecision(BaseModel):
    """对一个待审批调用的决定：同意、修改参数后执行（args）、拒绝。

    拒绝时带 message 即"回复一句话"：调用不执行，这句话转给智能体（D18）。
    """

    type: DecisionType
    args: dict[str, Any] | None = None
    message: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _fields_match_type(self) -> "ToolDecision":
        if (self.type == "edit") != (self.args is not None):
            raise ValueError("修改参数后执行要带上新参数（args），其他决定不带")
        if self.message is not None and self.type != "reject":
            raise ValueError("只有拒绝可以附一句话（message）")
        return self


class ApprovalAnswer(BaseModel):
    """对一处暂停的答复：每个待审批的调用一个决定，顺序同 actions。"""

    interrupt_id: str
    decisions: list[ToolDecision] = []


class ApprovalResolved(_BaseEvent):
    """用户做出了决定，运行接着往下跑（恢复后的第一个事件）。"""

    type: Literal["approval.resolved"] = "approval.resolved"
    answers: list[ApprovalAnswer]


class RunFinished(_BaseEvent):
    type: Literal["run.finished"] = "run.finished"
    status: Literal["completed", "failed", "cancelled"]
    error: str | None = None
    # 失败的类型（设计 2026-10-23 4.5）：报错卡片按它给按钮；旧历史没有，前端按 other 处理
    error_kind: ErrorKind | None = None
    # 能否"重试这一轮"（D26）：失败或停止、且这一轮没有做过有副作用的操作；由后端收尾时填
    retryable: bool = False
    usage: UsageTotals | None = None
    interrupted_usage: InterruptedUsage | None = None  # 被中断那次调用的估算（不计入 usage）
    # 插话（设计 2026-10-23 6.3）：没送达、退回输入框的；顺利结束时接着发起的下一轮
    undelivered: list[str] = Field(default_factory=list)
    next_run_id: str | None = None


type Event = Annotated[
    RunStarted
    | MessageDelta
    | ThinkingStarted
    | ThinkingDelta
    | ThinkingFinished
    | UserInterjected
    | ToolStarted
    | ToolRunning
    | ToolFinished
    | SubagentStarted
    | SubagentFinished
    | TodosUpdated
    | UsageReported
    | ContextUsage
    | FileCreated
    | MemorySaved
    | ApprovalRequired
    | ApprovalResolved
    | RunFinished,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
