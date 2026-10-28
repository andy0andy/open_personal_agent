"""运行结束后的后台小事：生成会话标题、自动提取记忆（M3，设计文档 8.2）、写会话索引
（设计 2026-10-23 6.1）。

运行结束时只登记后台任务（jobs 表），由任务队列在后台执行：不拖慢回答，进程重启后也会接着做。
"""

import logging
from typing import Any
from uuid import UUID

from agents.main_agent.conversations import NewConversationTurn
from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from backend.runs.answers import answer_text, user_text
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunRecord
from backend.runtime import JobHandler, JobQueue
from backend.threads import ThreadRepo, auto_title
from common.errors import NotFoundError

logger = logging.getLogger(__name__)

TITLE = "title"
MEMORY_EXTRACTION = "memory_extraction"
CONVERSATION_INDEX = "conversation_index"


class RunFollowups:
    def __init__(
        self,
        *,
        runs: RunRepo,
        threads: ThreadRepo,
        usage: UsageRepo,
        agent: MainAgent,
        jobs: JobQueue,
        auto_extract: bool,
    ) -> None:
        self._runs = runs
        self._threads = threads
        self._usage = usage
        self._agent = agent
        self._jobs = jobs
        self._auto_extract = auto_extract

    def handlers(self) -> dict[str, JobHandler]:
        """交给任务队列的处理程序：任务种类 → 处理函数。"""
        return {
            TITLE: self.generate_title,
            MEMORY_EXTRACTION: self.extract_memories,
            CONVERSATION_INDEX: self.index_conversation,
        }

    async def after_completed(self, run: RunRecord) -> None:
        """一次运行顺利结束（停止、失败的不算）：登记它的后续任务。

        会话第一次顺利结束时生成标题，排在前面（任务逐个处理，标题先出来）。
        """
        if await self._runs.completed_count(run.thread_id) == 1:
            await self._jobs.enqueue(TITLE, {"run_id": str(run.id)})
        if self._auto_extract and self._agent.knowledge is not None:
            await self._jobs.enqueue(MEMORY_EXTRACTION, {"run_id": str(run.id)})

    async def after_finished(self, run: RunRecord) -> None:
        """一次运行结束（顺利、失败、被停都算）：登记写会话索引（排在标题、记忆之后，
        标题先换好）。"""
        await self.index_later(run.id)

    async def index_later(self, run_id: UUID) -> None:
        """登记写会话索引的后台任务；没有会话索引时不登记。服务中途退出的运行在下次启动时
        也走这里（积压小问题 B7）。"""
        if self._agent.conversations is not None:
            await self._jobs.enqueue(CONVERSATION_INDEX, {"run_id": str(run_id)})

    async def index_conversation(self, payload: dict[str, Any]) -> None:
        """把这一轮写进会话索引：用户原文 + 主智能体的回答全文；"重试这一轮"替换掉原来那一轮。"""
        conversations = self._agent.conversations
        if conversations is None:
            return
        try:
            run = await self._runs.get(UUID(payload["run_id"]))
            thread = await self._threads.get(run.thread_id)
        except NotFoundError:
            return  # 会话已被删除
        if await self._runs.retried(run.id):
            # 已被"重试这一轮"替换（这个任务失败重试、补建重跑时晚于替换才做）：不再写回（B6）
            return
        events = await self._runs.events(run.id)
        turn = NewConversationTurn(
            thread_id=run.thread_id,
            run_id=run.id,
            title=thread.title,
            started_at=run.created_at,
            user_text=user_text(run.message, events),
            answer_text=answer_text(events),
        )
        await conversations.index(turn, replaces=run.retry_of)
        # 写的时候会话可能刚被删掉（审查 Minor 4）：写完再看一眼，不在了就删掉这一行
        try:
            await self._threads.get(run.thread_id)
        except NotFoundError:
            await conversations.delete_thread(run.thread_id)

    async def generate_title(self, payload: dict[str, Any]) -> None:
        """按这次的对话给会话起标题；标题已不是自动标题（用户改过名）时不动。"""
        try:
            run = await self._runs.get(UUID(payload["run_id"]))
            thread = await self._threads.get(run.thread_id)
        except NotFoundError:
            return  # 会话已被删除
        automatic = auto_title(await self._runs.first_message(thread.id))
        if thread.title != automatic:
            return
        events = await self._runs.events(run.id)
        title, usage = await self._agent.generate_title(
            thread_id=str(run.thread_id),
            run_id=str(run.id),
            model=run.model,
            message=user_text(run.message, events),
            answer=answer_text(events),
        )
        for item in usage:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=item)
        if not title:
            return
        # 带上原标题作条件：生成期间用户改了名，就保留用户起的
        replaced = await self._threads.replace_title(thread.id, old=automatic, new=title)
        if replaced and self._agent.conversations is not None:
            await self._agent.conversations.retitle(thread.id, title)

    async def extract_memories(self, payload: dict[str, Any]) -> None:
        """从这次运行的对话里提取记忆，用量记在这次运行名下（调用方 memory_extraction）。"""
        try:
            run = await self._runs.get(UUID(payload["run_id"]))
        except NotFoundError:
            return  # 会话已被删除：没什么可提取的
        events = await self._runs.events(run.id)
        async for usage in self._agent.extract_memories(
            thread_id=str(run.thread_id),
            run_id=str(run.id),
            model=run.model,
            message=user_text(run.message, events),  # 插话也算这一轮说的话（设计 6.3）
            answer=answer_text(events),
        ):
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)
