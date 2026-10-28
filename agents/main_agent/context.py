"""一次运行的上下文（LangGraph 运行时上下文，设计文档 7.2）：工作区等据此知道当前是哪个会话。"""

from dataclasses import dataclass

from agents.main_agent.interjections import Interjections


@dataclass(frozen=True)
class AgentContext:
    thread_id: str
    thread_short_id: str  # 形如 c_8f3a2b9d：工作目录 /workspace/<会话短 ID>/
    run_id: str
    # 常驻条目（运行开始时查好，由 KnowledgeContextMiddleware 拼进系统提示词）；
    # 相关记忆不在这里，放在本轮的用户消息里（D24）
    profile: str = ""
    # 这次运行的插话队列（设计 2026-10-23 6.3），只有主智能体取
    interjections: Interjections | None = None
