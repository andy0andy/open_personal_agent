"""主智能体总入口：按模型版本组装 deepagents，运行并输出我们自己的事件流。"""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from deepagents import FilesystemMiddleware, SubAgent, create_deep_agent
from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.agents.middleware import AgentMiddleware, InterruptOnConfig, TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from agents.main_agent.context import AgentContext
from agents.main_agent.conversations import ConversationIndex
from agents.main_agent.integrations import (
    ApprovalPolicy,
    McpClient,
    McpProbeResult,
    McpServerStatus,
    McpTool,
    PermissionMode,
    ToolApproval,
)
from agents.main_agent.interjections import Interjections
from agents.main_agent.knowledge import (
    DocumentLibrary,
    KnowledgeHit,
    KnowledgeStore,
    extract_memories,
)
from agents.main_agent.models import (
    ModelGateway,
    ModelStalledError,
    ModelSwitchCleanupMiddleware,
    call_context,
    classify_failure,
)
from agents.main_agent.runtime.approvals import (
    BUILTIN_TOOLS,
    KNOWLEDGE_TOOLS,
    SIDE_EFFECT_TOOLS,
    ApprovalMiddleware,
    EditNoticeMiddleware,
    check_answers,
    interrupt_on,
    resume_command,
)
from agents.main_agent.runtime.attachments import Attachment, user_content
from agents.main_agent.runtime.compaction import compaction_middleware
from agents.main_agent.runtime.conversations import SEARCH_CONVERSATIONS, conversation_tools
from agents.main_agent.runtime.events import (
    MAIN,
    ApprovalAnswer,
    ApprovalRequired,
    ApprovalResolved,
    Event,
    FileCreated,
    InterruptedUsage,
    MessageDelta,
    RunFinished,
    RunStarted,
    ToolFinished,
    UsageReported,
)
from agents.main_agent.runtime.execute import ExecuteResultMiddleware
from agents.main_agent.runtime.files import (
    SKILLS_ROOT,
    WRITE_FILE_DESCRIPTION,
    WorkDirectoryMiddleware,
    build_file_tree,
)
from agents.main_agent.runtime.interjection import InterjectionMiddleware
from agents.main_agent.runtime.interruption import (
    QUOTA,
    QUOTA_EXHAUSTED,
    STALLED,
    STOPPED,
    InterruptionMarkerMiddleware,
    failed_reason,
    interrupted_note,
)
from agents.main_agent.runtime.knowledge import (
    MEMORY_WRITE_TOOLS,
    KnowledgeContextMiddleware,
    knowledge_tools,
    neutralize_markers,
    profile_prompt,
    related_prefix,
    with_related,
)
from agents.main_agent.runtime.mcp_calls import McpBreaker, McpCallMiddleware
from agents.main_agent.runtime.skills import SkillCatalog, SkillInfo
from agents.main_agent.runtime.subagent_reports import SubagentReportMiddleware
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
from agents.main_agent.runtime.titles import generate_title
from agents.main_agent.runtime.tool_running import ToolRunningMiddleware
from agents.main_agent.runtime.tracker import Calibration, RunTracker
from agents.main_agent.runtime.translator import Translator
from agents.main_agent.workspace import Workspace, media_type
from common.errors import ConflictError, UpstreamError
from common.redact import redact
from config import ApprovalRulesConfig, McpServerConfig
from config.settings import KnowledgeConfig

logger = logging.getLogger(__name__)

# 运行之外的模型调用在用量表里的调用方
MEMORY_EXTRACTION = "memory_extraction"  # 会后提取记忆
TITLE = "title"  # 生成会话标题
# 召回只拿消息开头这么多字去向量化：贴了长文时本机向量模型（只用 CPU）会很慢
_RECALL_QUERY_LIMIT = 2000

# 恢复审批前最多等外部集成（MCP 服务）连接多久：重启后首次连接 npx 服务较慢
_SETTLE_TIMEOUT = 75.0
# 新发起的运行最多等 MCP 服务（重）连多久（积压小问题 E15，用户 2026-10-26 定 20 秒）：
# npx 首次下载可能要几十秒，等不到就照常跑
_NEW_RUN_SETTLE_TIMEOUT = 20.0

# 审批方案的版本（算进工具指纹）：2 = 加了硬底线、中文的拒绝说法（设计 2026-10-23 5.2、5.3）
_APPROVAL_SCHEME = "2"

# 可能在 outputs/ 里新增或改动文件的工具：它们结束后检查一次产物
_FILE_TOOLS = frozenset({"write_file", "edit_file", "execute"})


class MainAgent:
    """backend 只通过它与智能体交互。"""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        checkpointer: BaseCheckpointSaver[Any],
        system_prompt: str,
        workspace: Workspace,
        skills: SkillCatalog | None = None,
        skills_dir: Path | None = None,  # 不需要停用清单时的简写（测试常用）
        subagents_dir: Path | None = None,
        knowledge: KnowledgeStore | None = None,
        knowledge_options: KnowledgeConfig | None = None,
        documents: DocumentLibrary | None = None,
        mcp: McpClient | None = None,
        approval: ApprovalRulesConfig | None = None,
        conversations: ConversationIndex | None = None,
    ) -> None:
        self.models = gateway
        self.workspace = workspace
        self.conversations = conversations  # 会话索引（设计 2026-10-23 6.1），后端收尾时写入
        self.knowledge = knowledge
        self.documents = documents  # 知识库文档（上传、后台处理、删除）
        self._knowledge_options = knowledge_options or KnowledgeConfig()
        self._checkpointer = checkpointer
        self._system_prompt = system_prompt
        self._skills = skills or (SkillCatalog(skills_dir) if skills_dir is not None else None)
        self._subagents = load_subagents(subagents_dir) if subagents_dir else []
        # 按（模型，会话的审批权限）缓存：要先问的工具不同，组装出的智能体就不同（D23）
        self._graphs: dict[tuple[str, PermissionMode], CompiledStateGraph[Any, Any, Any, Any]] = {}
        self._calibration: dict[str, Calibration] = {}  # 模型版本 → 估算用量的校准值
        self._interrupted: dict[str, InterruptedUsage] = {}
        self._mcp = mcp
        self._breaker = McpBreaker()  # MCP 服务连续出错时暂停（设计 2026-10-23 5.8）
        if mcp is not None:
            # MCP 服务断线重连后工具变了：下一次运行重新组装（设计 2026-10-23 5.8）
            mcp.on_tools_changed(self._graphs.clear)
        # 正在重连 MCP 服务、换审批规则时为未设置：恢复审批要等它完成（重启后的首次连接）
        self._settled = asyncio.Event()
        self._settled.set()
        self._policy = ApprovalPolicy(approval or ApprovalRulesConfig())

    async def reload_integrations(
        self, servers: Sequence[McpServerConfig], rules: ApprovalRulesConfig
    ) -> None:
        """重连 MCP 服务、换审批规则；组装好的智能体随之失效，下一次运行重新组装。

        正在跑的运行继续用它手里那份。
        """
        self._settled.clear()
        try:
            if self._mcp is not None:
                await self._mcp.connect(servers)
            self._policy = ApprovalPolicy(rules)
            self._graphs.clear()
        finally:
            self._settled.set()

    @asynccontextmanager
    async def reconnecting(self) -> AsyncIterator[None]:
        """接下来要重连 MCP 服务（管理页面"重新加载"、改服务）：期间新发起的运行等它连完再
        组装。调用方在里面先查"有没有对话在进行"再重连，查完到重连之间发起的运行也不会用着
        正被关掉的连接（积压小问题 E10）。"""
        self._settled.clear()
        try:
            yield
        finally:
            self._settled.set()

    def update_rules(self, rules: ApprovalRulesConfig) -> None:
        """只换审批规则、不重连 MCP 服务（管理页面改某个工具"自动 / 先问"）。

        组装好的智能体随之失效；正在跑的运行继续用它手里那份。
        """
        self._policy = ApprovalPolicy(rules)
        self._graphs.clear()

    async def probe_mcp(self, server: McpServerConfig) -> McpProbeResult:
        """测试连接一个服务（不接入）；没有 MCP 客户端时报不可用。"""
        if self._mcp is None:
            return McpProbeResult(ok=False, error="没有接入 MCP 客户端")
        return await self._mcp.probe(server)

    def mcp_servers(self) -> list[McpServerStatus]:
        return self._mcp.statuses() if self._mcp is not None else []

    def tool_approvals(self, mode: PermissionMode = "ask") -> list[ToolApproval]:
        """全部工具在某个审批权限下的审批方式与原因（设置页、MCP 页按"每次先问"显示）。"""
        return self._policy.table(
            self._builtin_tools(), self._mcp.tools() if self._mcp else [], mode
        )

    @property
    def skill_catalog(self) -> SkillCatalog | None:
        return self._skills

    def skills(self) -> list[SkillInfo]:
        return self._skills.list() if self._skills is not None else []

    async def close(self) -> None:
        """关闭 MCP 连接（服务停止时调用）。"""
        if self._mcp is not None:
            await self._mcp.close()

    async def delete_thread(self, thread_id: str, thread_short_id: str) -> None:
        """删除该会话的对话存档（模型上下文）、工作区目录与会话索引。"""
        await self._checkpointer.adelete_thread(thread_id)
        await self.workspace.remove(thread_short_id)
        if self.conversations is not None:
            await self.conversations.delete_thread(UUID(thread_id))

    def take_interrupted_usage(self, run_id: str) -> InterruptedUsage | None:
        """取走（并清除）该运行被中断时那次模型调用的估算用量。"""
        return self._interrupted.pop(run_id, None)

    def has_side_effects(self, tool_names: Iterable[str]) -> bool:
        """这些调用里有没有会改动东西的（D26）：执行命令、写改删文件、记记忆、没声明只读的
        MCP 工具；认不出的名字（如 MCP 服务已经不在）也按有副作用算——宁可只给"继续"。"""
        read_only_mcp = {t.name for t in self._mcp.tools() if t.read_only} if self._mcp else set()
        read_only_builtin = set(BUILTIN_TOOLS) - SIDE_EFFECT_TOOLS
        return any(
            name not in read_only_builtin and name not in read_only_mcp for name in tool_names
        )

    async def run(
        self,
        *,
        thread_id: str,
        thread_short_id: str,
        run_id: str,
        message: str,
        model: str,
        attachments: Sequence[Attachment] = (),
        permission: PermissionMode = "ask",
        retry_of: str | None = None,
        interjections: Interjections | None = None,
    ) -> AsyncIterator[Event]:
        """执行一次运行。任何异常都转成 `run.finished(failed)`，不向调用方抛出。
        interjections：这次运行的插话队列（设计 2026-10-23 6.3），主智能体每次调用模型前取。

        retry_of：这是"重试这一轮"（D26）——从那次运行开始之前的对话存档分叉重跑，模型看不到
        失败的那一轮。run_id 必须是新的。
        遇到审批暂停时以 `approval.required` 结束，不发 `run.finished`（设计文档 10.5）。
        取消（调用方取消所在任务）时：留下被中断调用的估算用量（take_interrupted_usage），
        把已输出的部分和中断说明写进对话存档，然后让 CancelledError 照常向外传播，由调用方收尾。
        """
        yield RunStarted(model=model)

        async def inputs() -> dict[str, Any]:
            content = await user_content(
                message,
                attachments,
                short_id=thread_short_id,
                workspace=self.workspace,
                vision=self._can_see(model),
            )
            # 相关记忆只在新的一轮召回一次，放进这一轮的用户消息（D24）；审批后继续时已在存档里
            content = with_related(content, await self._related_prefix(message))
            first: dict[str, Any] = {"messages": [{"role": "user", "content": content}]}
            if self._skills is not None:
                # deepagents 每个会话只在第一次运行时读技能清单；
                # 每次都重读，新加的技能老会话也能用上
                first["skills_metadata"] = None
            return first

        async for event in self._drive(
            thread_id=thread_id,
            thread_short_id=thread_short_id,
            run_id=run_id,
            message=message,
            model=model,
            permission=permission,
            inputs=inputs,
            retry_of=retry_of,
            interjections=interjections,
        ):
            yield event

    async def check_answers(
        self,
        *,
        thread_id: str,
        model: str,
        answers: Sequence[ApprovalAnswer],
        tools_version: str | None = None,
        permission: PermissionMode = "ask",
    ) -> None:
        """恢复前校验答复与待审批的暂停是否对得上。

        tools_version 是暂停时 approval.required 带的指纹：工具或审批规则变了就不能恢复。
        permission 是这次运行开始时定下的审批权限（D23），指纹按它算。
        正在连接 MCP 服务（如刚重启）时先等连接完成。
        对不上时抛 ConflictError（暂停已不存在、配置变了）或 InvalidRequestError（决定不合要求）。
        """
        try:
            async with asyncio.timeout(_SETTLE_TIMEOUT):
                await self._settled.wait()
        except TimeoutError as exc:
            raise ConflictError("外部工具还在连接，请过一会儿再提交审批") from exc
        if tools_version is not None and tools_version != self._tools_version(permission):
            raise ConflictError(
                "外部工具或审批规则变了（如重新加载了配置、MCP 服务没连上），"
                "这次审批已失效：请点停止后重新发消息"
            )
        check_answers(answers, await self._pending(thread_id, model, permission))

    async def _wait_settled(self) -> None:
        """MCP 服务正在（重）连时，新运行等它连完再组装（积压小问题 E15）：不等的话，模型
        调到还没连上的工具会得到"不是有效的工具"。最多等 20 秒，等不到就照常跑。"""
        if self._settled.is_set():
            return
        try:
            async with asyncio.timeout(_NEW_RUN_SETTLE_TIMEOUT):
                await self._settled.wait()
        except TimeoutError:
            logger.warning("MCP 服务 %g 秒还没连好，这次运行先不等了", _NEW_RUN_SETTLE_TIMEOUT)

    def _tools_version(self, mode: PermissionMode) -> str:
        """当前工具与审批规则在某个审批权限下的指纹：哪些工具、哪些要先问你。"""
        rows = sorted((row.name, row.action) for row in self.tool_approvals(mode))
        # 带上审批方案的版本：方案变了（如加了硬底线），升级前停在审批处的运行恢复时对不上
        payload = json.dumps([_APPROVAL_SCHEME, rows], ensure_ascii=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return digest[:16]

    async def resume(
        self,
        *,
        thread_id: str,
        thread_short_id: str,
        run_id: str,
        model: str,
        message: str,
        answers: Sequence[ApprovalAnswer],
        permission: PermissionMode = "ask",
        interjections: Interjections | None = None,
    ) -> AsyncIterator[Event]:
        """按用户的决定从审批暂停处接着跑（同一次运行，设计文档 10.5）。

        调用前先用 check_answers 校验。message 是这次运行的用户消息（相关记忆已在对话存档里，
        不再召回，D24）。permission 是这次运行开始时定下的审批权限，整次运行不变。
        异常与取消的处理同 run。
        """
        yield ApprovalResolved(answers=list(answers))

        async def inputs() -> Command[Any]:
            return resume_command(answers, await self._pending(thread_id, model, permission))

        async for event in self._drive(
            thread_id=thread_id,
            thread_short_id=thread_short_id,
            run_id=run_id,
            message=message,
            model=model,
            permission=permission,
            inputs=inputs,
            interjections=interjections,
        ):
            yield event

    async def _pending(self, thread_id: str, model: str, mode: PermissionMode) -> dict[str, Any]:
        """该会话待审批的暂停：中断 ID → 中断内容。"""
        graph = self._graph_for(model, mode)
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        return {item.id: item.value for item in state.interrupts if item.id is not None}

    async def _drive(
        self,
        *,
        thread_id: str,
        thread_short_id: str,
        run_id: str,
        message: str,
        model: str,
        permission: PermissionMode,
        inputs: Callable[[], Awaitable[Any]],
        retry_of: str | None = None,
        interjections: Interjections | None = None,
    ) -> AsyncIterator[Event]:
        """驱动一段运行（新的一轮，或从审批暂停处恢复），把输出流翻译成事件。

        整段在调用归属里：其中每次模型调用（含子智能体、上下文压缩）都属于这个会话与运行。
        """
        with call_context(thread_id, run_id):
            async for event in self._drive_events(
                thread_id=thread_id,
                thread_short_id=thread_short_id,
                run_id=run_id,
                message=message,
                model=model,
                permission=permission,
                inputs=inputs,
                retry_of=retry_of,
                interjections=interjections,
            ):
                yield event

    async def _drive_events(
        self,
        *,
        thread_id: str,
        thread_short_id: str,
        run_id: str,
        message: str,
        model: str,
        permission: PermissionMode,
        inputs: Callable[[], Awaitable[Any]],
        retry_of: str | None = None,
        interjections: Interjections | None = None,
    ) -> AsyncIterator[Event]:
        if self._mcp is not None:
            await self._wait_settled()
        info = self.models.model_info(model)
        tracker = RunTracker(
            calibration=self._calibration, context_limit=info.max_input_tokens if info else None
        )
        mcp_servers = {t.name: t.server for t in self._mcp.tools()} if self._mcp else {}
        translator = Translator(tracker, mcp_servers)
        graph: CompiledStateGraph[Any, Any, Any, Any] | None = None
        partial = ""  # 主智能体正在输出、还没存进对话存档的回答
        outputs = _OutputWatcher(self.workspace, thread_short_id)
        try:
            await self.workspace.prepare(thread_short_id)
            await outputs.start()
            graph = self._graph_for(model, permission)
            profile = await self._profile_prompt()
            graph_input = await inputs()
            configurable: dict[str, Any] = {"thread_id": thread_id}
            if retry_of is not None:
                configurable = await self._fork_point(graph, thread_id, retry_of)
            async for part in graph.astream(
                graph_input,
                {
                    "configurable": configurable,
                    "metadata": {"run_id": run_id},
                    "callbacks": [tracker],
                },
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
                version="v2",
                context=AgentContext(thread_id, thread_short_id, run_id, profile, interjections),
            ):
                if not part["ns"] and part["type"] == "updates" and "model" in part["data"]:
                    partial = ""  # 模型节点完成：这条回答已存进对话存档
                # 上下文占用在这次调用开始时就记下了，排在它的回答之前（设计 2026-10-23 4.7）
                for context in tracker.drain_context():
                    yield context
                touched_files = False
                for event in translator.translate(part):
                    if isinstance(event, MessageDelta) and event.agent_path == [MAIN]:
                        partial += event.text
                    touched_files |= isinstance(event, ToolFinished) and event.name in _FILE_TOOLS
                    yield event
                if touched_files:
                    for created in await outputs.changes():
                        yield created
                for usage in tracker.drain_usage():
                    yield usage
        except asyncio.CancelledError:
            if (estimate := tracker.interrupted_usage()) is not None:
                self._interrupted[run_id] = estimate
            # 停止时没有输出就不写：下一轮的中断标记补上的通用说明就是真实原因
            if graph is not None and partial.strip():
                await self._mark_interrupted(graph, thread_id, run_id, partial, STOPPED)
            raise
        except Exception as exc:  # noqa: BLE001 - 运行边界：模型 / 工具链路的任何失败都要变成失败事件
            async for event in self._failed(exc, graph, tracker, thread_id, run_id, partial):
                yield event
            return
        for usage in tracker.drain_usage():
            yield usage
        if translator.approvals:
            yield ApprovalRequired(
                requests=translator.approvals, tools_version=self._tools_version(permission)
            )
            return
        yield RunFinished(status="completed")

    async def _failed(
        self,
        exc: Exception,
        graph: CompiledStateGraph[Any, Any, Any, Any] | None,
        tracker: RunTracker,
        thread_id: str,
        run_id: str,
        partial: str,
    ) -> AsyncIterator[Event]:
        """运行失败：同停止，已输出的部分连同原因写进存档，说"继续"能接着做（D23，设计 4.4）；
        交出已产生的用量与失败事件。"""
        if isinstance(exc, ModelStalledError):
            # 模型卡住：被放弃的那次调用给出估算
            if graph is not None:
                await self._mark_interrupted(graph, thread_id, run_id, partial, STALLED)
            for usage in tracker.drain_usage():
                yield usage
            yield RunFinished(
                status="failed",
                error=str(exc),
                error_kind="stalled",
                interrupted_usage=tracker.interrupted_usage(),
            )
            return
        kind = classify_failure(exc)
        if graph is not None:
            # 报错文字可能带着密钥（如网关把请求头写进了错误）：进存档、界面前打码（设计 5.12）
            reason = QUOTA if kind == "quota" else redact(failed_reason(exc))
            await self._mark_interrupted(graph, thread_id, run_id, partial, reason)
        for usage in tracker.drain_usage():
            yield usage
        error = QUOTA_EXHAUSTED if kind == "quota" else redact(f"{type(exc).__name__}: {exc}")
        yield RunFinished(status="failed", error=error, error_kind=kind)

    async def extract_memories(
        self, *, thread_id: str, run_id: str, model: str, message: str, answer: str
    ) -> AsyncIterator[UsageReported]:
        """从刚结束的一轮对话里提取记忆（设计文档 8.2，由后台任务调用），输出这次的模型用量。

        用会话所选的模型（M3 决定，不另配便宜模型）。失败时先输出已产生的用量，再把异常抛给调用方。
        """
        if self.knowledge is None:
            return
        tracker = RunTracker(calibration=self._calibration)
        try:
            with call_context(thread_id, run_id):
                await extract_memories(
                    self.models.chat_model(model),
                    self.knowledge,
                    message=message,
                    answer=answer,
                    thread_id=UUID(thread_id),
                    run_id=UUID(run_id),
                    config={
                        "callbacks": [tracker],
                        "metadata": {"lc_agent_name": MEMORY_EXTRACTION},
                    },
                )
        except Exception:
            for usage in tracker.drain_usage():
                yield usage
            raise
        for usage in tracker.drain_usage():
            yield usage

    async def generate_title(
        self, *, thread_id: str, run_id: str, model: str, message: str, answer: str
    ) -> tuple[str, list[UsageReported]]:
        """按第一轮对话起一个会话标题（由后台任务调用），连同这次的模型用量一起返回。

        用会话所选的模型。模型什么都没给时标题为空字符串。
        """
        tracker = RunTracker(calibration=self._calibration)
        with call_context(thread_id, run_id):
            title = await generate_title(
                self.models.chat_model(model),
                message=message,
                answer=answer,
                config={"callbacks": [tracker], "metadata": {"lc_agent_name": TITLE}},
            )
        return title, tracker.drain_usage()

    async def _fork_point(
        self, graph: CompiledStateGraph[Any, Any, Any, Any], thread_id: str, run_id: str
    ) -> dict[str, Any]:
        """ "重试这一轮"从哪里跑（D26）：那次运行最早的存档点的上一个存档点。

        那次运行一个存档点都没留下（还没进到这一轮就失败）：照常从最新的往下跑；
        它就是会话的第一轮（没有上一个存档点）：先清掉这个会话的存档，从头跑。
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        earliest = None
        async for snapshot in graph.aget_state_history(config, filter={"run_id": run_id}):
            earliest = snapshot  # 从新到旧排列，最后一个最早
        if earliest is None:
            return {"thread_id": thread_id}
        if earliest.parent_config is None:
            await self._checkpointer.adelete_thread(thread_id)
            return {"thread_id": thread_id}
        return dict(earliest.parent_config.get("configurable") or {})

    async def _mark_interrupted(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        thread_id: str,
        run_id: str,
        partial: str,
        reason: str,
    ) -> None:
        """把已输出的部分连同中断说明（写明原因）存进对话存档，由下一句话决定是否接着做。

        没有输出文字时只写说明（设计 2026-10-23 4.5：否则下一轮补上的通用说明会丢掉真实原因）；
        还没进到这一轮就失败（存档里最新的存档点不属于这次运行）时不写，免得把说明接在上一轮后面。
        写入失败只记日志，不影响取消或失败本身。
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        note = interrupted_note(reason)
        try:
            if not partial.strip():
                latest = await graph.aget_state(config)
                if (latest.metadata or {}).get("run_id") != run_id:
                    return
            content = f"{partial}\n\n{note}" if partial.strip() else note
            await graph.aupdate_state(
                config, {"messages": [AIMessage(content=content)]}, as_node="model"
            )
        except Exception:  # 收尾边界：写不进存档也要让取消继续完成
            logger.exception("会话 %s 的中断内容写入对话存档失败", thread_id)

    async def _profile_prompt(self) -> str:
        """常驻条目（个人画像，设计文档 8.3）：每段运行都重新查，刚改过的也能用上。"""
        if self.knowledge is None:
            return ""
        limit = self._knowledge_options.pinned_token_limit
        return profile_prompt(await self.knowledge.pinned(), limit)

    async def _related_prefix(self, message: str) -> str:
        """和这句话相关的记忆（设计文档 8.3），放在本轮用户消息开头（D24）。

        向量化服务不可用时只是这次没有相关记忆，照常回答。
        """
        if self.knowledge is None:
            return ""
        options = self._knowledge_options
        recalled: list[KnowledgeHit] = []
        try:
            # 召回挡在回答开始之前：向量模型卡住时最多等这么久，不让每条消息都干等
            async with asyncio.timeout(options.recall_timeout):
                recalled = await self.knowledge.recall(
                    message[:_RECALL_QUERY_LIMIT],
                    top_k=options.recall_top_k,
                    min_similarity=options.recall_min_similarity,
                )
        except (UpstreamError, TimeoutError):
            logger.warning("相关记忆召回失败或超时，本次运行不带相关记忆", exc_info=True)
            return ""
        return related_prefix(recalled, await self.knowledge.pinned()) if recalled else ""

    def _graph_for(
        self, model: str, mode: PermissionMode
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        """按（模型版本，审批权限）缓存组装好的智能体，避免每次请求重新组装。

        还没拿到模型的上下文上限时不缓存（设计 2026-10-23 4.6）：压缩阈值要按它算，
        一直用组装时的默认值会压缩得太早或太晚；下次运行重新组装。
        """
        key = (model, mode)
        if key in self._graphs:
            return self._graphs[key]
        chat_model = self.models.chat_model(model)
        backend = build_file_tree(self.workspace.agent_backend, self._skills)
        middleware: list[AgentMiddleware[Any, Any, Any]] = [
            TodoListMiddleware(),  # deepagents 0.7 默认不带待办清单，手动加回
            ModelSwitchCleanupMiddleware(model, vision=lambda: self._can_see(model)),
            InterruptionMarkerMiddleware(),  # 被打断的一轮补上"已中断"，模型不会重做
            WorkDirectoryMiddleware(),
            KnowledgeContextMiddleware(),  # 常驻条目（相关记忆在用户消息里，D24）
            InterjectionMiddleware(),  # 运行中的插话在调用模型前送达（设计 6.3，只给主智能体）
            EditNoticeMiddleware(),  # 审批时改了参数：用中文告诉模型实际执行的参数
            # 同名替换默认的压缩：附上用户原话与锚点索引（设计 2026-10-23 4.6）
            compaction_middleware(chat_model, backend),
            ExecuteResultMiddleware(),  # 执行命令的退出码、错误输出交给界面（设计 5.4）
            _filesystem(backend),  # 同名替换：write_file 说明改为先读再覆盖（设计 5.6）
            SubagentReportMiddleware(backend),  # 子智能体的长报告存进 reports/（设计 5.10）
        ]
        mcp_tools = self._mcp.tools() if self._mcp is not None else []
        mcp_servers = {t.name: t.server for t in mcp_tools}
        if mcp_servers:
            middleware.append(McpCallMiddleware(mcp_servers, self._breaker))
        # 工具真正开始执行时告诉界面（设计 5.7），后端据此记工具用量（6.8）：
        # 排在 MCP 调用中间件之后，暂停挡下的调用不算
        middleware.append(ToolRunningMiddleware())
        tools = [
            *(
                knowledge_tools(self.knowledge, self._knowledge_options.pinned_token_limit)
                if self.knowledge
                else []
            ),
            *(conversation_tools(self.conversations) if self.conversations else []),
            *(t.tool for t in mcp_tools),
        ]
        # 子智能体收权（设计 2026-10-23 5.10、6.6）：不能记、改、删记忆，其余工具照给
        sub_tools = [t for t in tools if t.name not in MEMORY_WRITE_TOOLS]
        asks = [row for row in self.tool_approvals(mode) if row.action == "ask"]
        descriptions = {t.name: t.description for t in mcp_tools}
        approval = interrupt_on(asks, descriptions, hard_floor=mode == "skip")
        if approval:  # 同名替换 deepagents 默认的审批中间件：拒绝时用中文的说法（设计 5.3）
            middleware.append(ApprovalMiddleware(interrupt_on=approval))
        statuses = self._mcp.statuses() if self._mcp is not None else []
        graph = create_deep_agent(
            model=chat_model,
            system_prompt=self._system_prompt + _services_prompt(mcp_tools, statuses),
            tools=tools or None,
            middleware=middleware,
            subagents=[
                self._general_purpose(sub_tools, mcp_servers, chat_model, backend, approval),
                *(
                    self._subagent(
                        definition, sub_tools, mcp_servers, chat_model, backend, approval
                    )
                    for definition in self._subagents
                ),
            ],
            backend=backend,
            skills=self._skill_sources(),
            context_schema=AgentContext,
            checkpointer=self._checkpointer,
            interrupt_on=approval or None,
        )
        info = self.models.model_info(model)
        if info is not None and info.max_input_tokens:
            self._graphs[key] = graph
        return graph

    def _builtin_tools(self) -> list[str]:
        """智能体自带的工具名；没有知识库时不带知识库的三个工具，没有会话索引时不带查以前的对话。"""
        return [
            name
            for name in BUILTIN_TOOLS
            if (self.knowledge is not None or name not in KNOWLEDGE_TOOLS)
            and (self.conversations is not None or name != SEARCH_CONVERSATIONS)
        ]

    def _can_see(self, model: str) -> bool:
        """模型能否看图（来自网关的模型信息；不知道时按不能处理）。"""
        info = self.models.model_info(model)
        return bool(info and info.supports_vision)

    def _subagent_middleware(
        self,
        mcp_servers: Mapping[str, str],
        model: BaseChatModel,
        backend: BackendProtocol,
        approval: dict[str, bool | InterruptOnConfig] | None = None,
    ) -> list[AgentMiddleware[Any, Any, Any]]:
        """子智能体的中间件：同样要知道工作目录、看懂审批时改过的参数；
        它们继承了 MCP 工具，出错时同样只作为工具结果（不让整次运行失败）。
        压缩同样附上原话与锚点索引（设计 2026-10-23 4.6）。"""
        middleware: list[AgentMiddleware[Any, Any, Any]] = [
            WorkDirectoryMiddleware(),
            EditNoticeMiddleware(),
            compaction_middleware(model, backend),
            ExecuteResultMiddleware(),
            _filesystem(backend),
        ]
        if mcp_servers:
            middleware.append(McpCallMiddleware(mcp_servers, self._breaker))
        middleware.append(ToolRunningMiddleware())  # 同主智能体：暂停挡下的调用不算
        if (
            approval
        ):  # 子智能体同样用中文的拒绝说法；spec 里 interrupt_on 设为空，免得再加一个同名的
            middleware.append(ApprovalMiddleware(interrupt_on=approval))
        return middleware

    def _general_purpose(
        self,
        tools: Sequence[BaseTool],
        mcp_servers: Mapping[str, str],
        model: BaseChatModel,
        backend: BackendProtocol,
        approval: dict[str, bool | InterruptOnConfig] | None = None,
    ) -> SubAgent:
        """通用子智能体：deepagents 自动加的那个不带我们的中间件，换成自己的同名定义。

        其余与自动加的相同（同样的说明与提示词、继承全部工具与审批规则、能用技能）。
        """
        spec: SubAgent = {
            **GENERAL_PURPOSE_SUBAGENT,
            "tools": list(tools),
            "middleware": self._subagent_middleware(mcp_servers, model, backend, approval),
            "interrupt_on": {},
        }
        if sources := self._skill_sources():
            spec["skills"] = sources
        return spec

    def _skill_sources(self) -> list[str] | None:
        """deepagents 的技能来源：技能目录挂在文件树的 /skills/（D22：只有一处）。"""
        if self._skills is None or self._skills.skills_dir is None:
            return None
        return [SKILLS_ROOT]

    def _subagent(
        self,
        definition: SubagentDefinition,
        tools: Sequence[BaseTool],
        mcp_servers: Mapping[str, str],
        main_model: BaseChatModel,
        backend: BackendProtocol,
        approval: dict[str, bool | InterruptOnConfig] | None = None,
    ) -> SubAgent:
        """定义文件 → deepagents 子智能体。不指定模型时跟随主对话所选的模型；
        与通用子智能体一样能用技能（如数据分析员先读 excel 技能）。"""
        model = self.models.chat_model(definition.model) if definition.model else main_model
        spec: SubAgent = {
            "name": definition.name,
            "description": definition.description,
            "system_prompt": definition.system_prompt,
            "tools": list(tools),
            "middleware": self._subagent_middleware(mcp_servers, model, backend, approval),
            "interrupt_on": {},
        }
        if sources := self._skill_sources():
            spec["skills"] = sources
        if definition.model:
            spec["model"] = model
        return spec


def _filesystem(backend: BackendProtocol) -> FilesystemMiddleware:
    """deepagents 的文件工具中间件（同名替换默认的），只换 write_file 的说明。"""
    return FilesystemMiddleware(
        backend=backend, custom_tool_descriptions={"write_file": WRITE_FILE_DESCRIPTION}
    )


def _services_prompt(tools: Sequence[McpTool], statuses: Sequence[McpServerStatus]) -> str:
    """已接入的 MCP 服务各是什么（积压小问题 E13，按服务的说明动态写）：用户提到说明里的东西
    （如"共享文件夹"）时，模型知道该用哪个服务的工具。没有服务时为空。"""
    servers = list(dict.fromkeys(tool.server for tool in tools))
    if not servers:
        return ""
    descriptions = {status.name: status.description for status in statuses}
    lines = [
        f"- {name}（工具名以 {name}_ 开头）："
        + neutralize_markers(descriptions.get(name) or "没有说明")
        for name in servers
    ]
    return (
        "\n\n已接入的外部服务（MCP）：\n"
        + "\n".join(lines)
        + "\n用户提到这些服务说明里的东西（如“共享文件夹”）时，用对应服务的工具读写，"
        "不要用会话工作目录。"
    )


class _OutputWatcher:
    """对比 outputs/ 的前后状态，找出本次运行新增或改动的产物（设计文档 9.3）。"""

    def __init__(self, workspace: Workspace, short_id: str) -> None:
        self._workspace = workspace
        self._short_id = short_id
        self._seen: dict[str, tuple[int, float]] = {}

    async def start(self) -> None:
        self._seen = await self._snapshot()

    async def changes(self) -> list[FileCreated]:
        current = await self._snapshot()
        changed = [path for path, state in current.items() if self._seen.get(path) != state]
        self._seen = current
        return [
            FileCreated(
                path=path,
                size=current[path][0],
                media_type=media_type(path),
            )
            for path in sorted(changed)
        ]

    async def _snapshot(self) -> dict[str, tuple[int, float]]:
        files = await self._workspace.list_outputs(self._short_id)
        return {f.path: (f.size, f.modified) for f in files}
