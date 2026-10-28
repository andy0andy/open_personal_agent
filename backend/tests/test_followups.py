"""运行顺利结束后的后台小事：生成会话标题、自动提取记忆（设计文档 8.2）。"""

import asyncio
import json
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.conversations import NewConversationTurn
from agents.main_agent.models import CallContext
from agents.main_agent.runtime import MainAgent, MessageDelta
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace, WorkspaceFileRepo
from agents.tests.fakes import (
    FailingChatModel,
    FakeConversationIndex,
    FakeGateway,
    FakeKnowledgeStore,
    FakeSandbox,
    ScriptedChatModel,
)
from backend.runs import RunCreate, RunFollowups, RunManager, RunRepo
from backend.runtime import EventEnvelope, InMemoryEventBus, InProcessRunControl, JobHandler
from backend.threads import ThreadRepo
from common.db import Pool

pytestmark = pytest.mark.integration


class _RecordingJobs:
    """只记下登记了哪些后台任务，不执行（执行由测试直接调用处理程序）。"""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        self.enqueued.append((kind, payload))
        return uuid.uuid4()

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        pass

    async def stop(self) -> None:
        pass


class _Setup:
    def __init__(
        self,
        db: Pool,
        model: BaseChatModel,
        *,
        auto_extract: bool = True,
        conversations: FakeConversationIndex | None = None,
    ) -> None:
        self.store = FakeKnowledgeStore()
        self.conversations = conversations
        self.jobs = _RecordingJobs()
        self.runs = RunRepo(db)
        self.usage = UsageRepo(db)
        self.threads = ThreadRepo(db)
        agent = MainAgent(
            gateway=FakeGateway(model),
            checkpointer=InMemorySaver(),
            system_prompt="测试助手",
            workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
            knowledge=self.store,
            conversations=conversations,
        )
        self.followups = RunFollowups(
            runs=self.runs,
            threads=self.threads,
            usage=self.usage,
            agent=agent,
            jobs=self.jobs,
            auto_extract=auto_extract,
        )
        self.manager = RunManager(
            runs=self.runs,
            threads=self.threads,
            usage=self.usage,
            files=WorkspaceFileRepo(db),
            agent=agent,
            bus=InMemoryEventBus(),
            control=InProcessRunControl(),
            flush_interval=0.01,
            followups=self.followups,
        )

    async def run(self, message: str, thread_id: UUID | None = None) -> UUID:
        """发起一次运行并等它结束（收到结束事件时，后续任务已经登记）。不给会话时新建一个。"""
        if thread_id is None:
            thread_id = (await self.threads.create(model="m")).id
        run = await self.manager.start(thread_id, RunCreate(message=message))
        async for _ in self.manager.stream(run.id):
            pass
        return run.id


def _extraction(changes: list[dict[str, Any]]) -> AIMessage:
    return AIMessage(
        json.dumps({"changes": changes}, ensure_ascii=False),
        usage_metadata={"input_tokens": 300, "output_tokens": 20, "total_tokens": 320},
    )


async def test_first_completed_run_queues_title_then_memory_extraction(db: Pool) -> None:
    """标题排在前面：任务逐个处理，标题先出来。"""
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]))
    run_id = await setup.run("你好")
    assert setup.jobs.enqueued == [
        ("title", {"run_id": str(run_id)}),
        ("memory_extraction", {"run_id": str(run_id)}),
    ]


async def test_later_runs_queue_no_title(db: Pool) -> None:
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好"), AIMessage("好")]))
    first = await setup.run("你好")
    thread_id = (await setup.runs.get(first)).thread_id
    second = await setup.run("再说一句", thread_id)
    assert [kind for kind, payload in setup.jobs.enqueued if payload["run_id"] == str(second)] == [
        "memory_extraction"
    ]


async def test_failed_run_queues_nothing(db: Pool) -> None:
    setup = _Setup(db, FailingChatModel(responses=[]))
    await setup.run("你好")
    assert setup.jobs.enqueued == []


async def test_switched_off_extraction_is_not_queued(db: Pool) -> None:
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), auto_extract=False)
    await setup.run("你好")
    assert [kind for kind, _ in setup.jobs.enqueued] == ["title"]


async def test_extraction_job_reads_the_conversation_and_records_usage(db: Pool) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage("恭喜你换了新工作！"),
            _extraction([{"action": "add", "content": "用户在字节做数据平台", "tags": ["工作"]}]),
        ]
    )
    setup = _Setup(db, model)
    run_id = await setup.run("我换工作了，现在在字节做数据平台")

    payload = dict(setup.jobs.enqueued)["memory_extraction"]
    await setup.followups.handlers()["memory_extraction"](payload)

    prompt = str(model.received[-1][-1].content)
    assert "用户：我换工作了，现在在字节做数据平台" in prompt
    assert "助手：恭喜你换了新工作！" in prompt  # 逐字片段已拼成完整回答
    [memory] = setup.store.items.values()
    assert (memory.content, memory.source_run_id) == ("用户在字节做数据平台", run_id)
    usage = await setup.usage.for_run(run_id)
    assert [(u.caller, u.input_tokens) for u in usage] == [("memory_extraction", 300)]


async def test_extraction_job_for_a_deleted_run_does_nothing(db: Pool) -> None:
    """会话（连同运行）在任务执行前被删掉了：没什么可提取的，任务直接结束，不重试。"""
    setup = _Setup(db, ScriptedChatModel(responses=[]))
    await setup.followups.handlers()["memory_extraction"]({"run_id": str(uuid.uuid4())})
    assert setup.store.items == {}


async def test_title_job_replaces_the_automatic_title_and_records_usage(db: Pool) -> None:
    title = AIMessage(
        "《周报模板》",
        usage_metadata={"input_tokens": 120, "output_tokens": 6, "total_tokens": 126},
    )
    model = ScriptedChatModel(responses=[AIMessage("好的，下面是周报模板……"), title])
    setup = _Setup(db, model, auto_extract=False)
    message = "帮我写一个每周给团队发的周报模板，要包含本周进展、风险和下周计划"
    run_id = await setup.run(message)
    run = await setup.runs.get(run_id)
    assert (await setup.threads.get(run.thread_id)).title == message[
        :30
    ]  # 先用首条消息的前 30 个字

    await setup.followups.handlers()["title"]({"run_id": str(run_id)})

    assert (await setup.threads.get(run.thread_id)).title == "周报模板"
    usage = await setup.usage.for_run(run_id)
    assert [(u.caller, u.input_tokens) for u in usage] == [("title", 120)]
    # 生成标题那次调用属于这次运行的会话与运行（网关后台能按会话找到它）
    assert model.calls_in[-1] == CallContext(str(run.thread_id), str(run_id))


async def test_title_job_keeps_a_title_the_user_set(db: Pool) -> None:
    model = ScriptedChatModel(responses=[AIMessage("好"), AIMessage("不该用上的标题")])
    setup = _Setup(db, model, auto_extract=False)
    run_id = await setup.run("你好")
    thread_id = (await setup.runs.get(run_id)).thread_id
    await setup.threads.update(thread_id, title="我自己起的名字")

    await setup.followups.handlers()["title"]({"run_id": str(run_id)})

    assert (await setup.threads.get(thread_id)).title == "我自己起的名字"
    assert model.cursor == 1  # 没有为标题调用模型


# 会话索引（设计 2026-10-23 6.1）
async def _run_jobs(setup: _Setup, kind: str) -> None:
    for job_kind, payload in setup.jobs.enqueued:
        if job_kind == kind:
            await setup.followups.handlers()[kind](payload)


async def test_finished_run_is_indexed(db: Pool) -> None:
    """运行结束后登记索引任务（排在标题、记忆之后），处理时写进"原文 + 回答全文"。"""
    index = FakeConversationIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("晴，25 度")]), conversations=index)
    run_id = await setup.run("明天天气怎么样")
    assert [kind for kind, _ in setup.jobs.enqueued] == [
        "title",
        "memory_extraction",
        "conversation_index",
    ]
    await _run_jobs(setup, "conversation_index")
    [row] = index.rows.values()
    assert (row.run_id, row.user_text, row.answer_text) == (run_id, "明天天气怎么样", "晴，25 度")


async def test_failed_run_is_indexed_too(db: Pool) -> None:
    index = FakeConversationIndex()
    setup = _Setup(db, FailingChatModel(responses=[]), conversations=index)
    run_id = await setup.run("你好")
    assert setup.jobs.enqueued == [("conversation_index", {"run_id": str(run_id)})]
    await _run_jobs(setup, "conversation_index")
    assert list(index.rows) == [run_id]


async def test_retry_replaces_index_row(db: Pool) -> None:
    """ "重试这一轮"后，失败的那一轮从索引里拿掉（界面上它收成一行）。"""
    index = FakeConversationIndex()
    model = FailingChatModel(responses=[])
    setup = _Setup(db, model, conversations=index)
    failed = await setup.run("整理发票")
    await _run_jobs(setup, "conversation_index")
    setup.manager._agent.models = FakeGateway(ScriptedChatModel(responses=[AIMessage("整理好了")]))
    retried = await setup.manager.retry(failed)
    async for _ in setup.manager.stream(retried.id):
        pass
    setup.jobs.enqueued = [j for j in setup.jobs.enqueued if j[1]["run_id"] == str(retried.id)]
    await _run_jobs(setup, "conversation_index")
    assert list(index.rows) == [retried.id]


async def test_turn_replaced_by_retry_is_not_written_back(db: Pool) -> None:
    """原来那一轮的写索引任务晚于"重试这一轮"才做（任务失败重试、补建重跑）：不再写回（B6）。"""
    index = FakeConversationIndex()
    setup = _Setup(db, FailingChatModel(responses=[]), conversations=index)
    failed = await setup.run("整理发票")
    setup.manager._agent.models = FakeGateway(ScriptedChatModel(responses=[AIMessage("整理好了")]))
    retried = await setup.manager.retry(failed)
    async for _ in setup.manager.stream(retried.id):
        pass

    await setup.followups.index_conversation({"run_id": str(retried.id)})
    await setup.followups.index_conversation({"run_id": str(failed)})

    assert list(index.rows) == [retried.id]


async def test_crashed_run_is_indexed_with_its_partial_answer(db: Pool) -> None:
    """服务中途退出的那一轮：启动时记成失败，并登记写索引，已写下的部分回答也搜得到（B7）。"""
    index = FakeConversationIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[]), conversations=index)
    thread = await setup.threads.create(model="m")
    run = await setup.runs.create(thread_id=thread.id, model="m", message="写一份周报")
    partial = EventEnvelope.wrap(
        MessageDelta(message_id="m1", text="本周完成了"), seq=1, run_id=str(run.id)
    )
    await setup.runs.add_events(run.id, [partial])

    for run_id in await setup.runs.fail_unfinished():
        await setup.followups.index_later(run_id)
    assert setup.jobs.enqueued == [("conversation_index", {"run_id": str(run.id)})]
    await _run_jobs(setup, "conversation_index")

    [row] = index.rows.values()
    assert (row.user_text, row.answer_text) == ("写一份周报", "本周完成了")


async def test_title_job_retitles_the_index(db: Pool) -> None:
    index = FakeConversationIndex()
    model = ScriptedChatModel(
        responses=[AIMessage("好的，下面是周报模板……"), AIMessage("周报模板")]
    )
    setup = _Setup(db, model, auto_extract=False, conversations=index)
    await setup.run("帮我写个周报模板")
    await _run_jobs(setup, "conversation_index")
    await _run_jobs(setup, "title")
    [row] = index.rows.values()
    assert row.title == "周报模板"


async def test_index_job_for_a_deleted_run_does_nothing(db: Pool) -> None:
    index = FakeConversationIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[]), conversations=index)
    await setup.followups.handlers()["conversation_index"]({"run_id": str(uuid.uuid4())})
    assert index.rows == {}


async def test_deleting_thread_drops_its_index(db: Pool) -> None:
    index = FakeConversationIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), conversations=index)
    run_id = await setup.run("你好")
    await _run_jobs(setup, "conversation_index")
    thread_id = (await setup.runs.get(run_id)).thread_id
    await setup.manager.delete_thread(thread_id)
    assert index.rows == {}


async def test_followups_include_interjections(db: Pool) -> None:
    """插话也是这一轮用户说的话：标题、记忆提取、会话索引都带上（设计 2026-10-23 6.3）。"""
    index = FakeConversationIndex()
    model = ScriptedChatModel(
        responses=[AIMessage("好的，用英文写"), AIMessage("《英文介绍》"), _extraction([])]
    )
    setup = _Setup(db, model, conversations=index)
    run_id = await setup.run("写一段介绍")
    last = max(e.seq for e in await setup.runs.events(run_id))
    interjected = EventEnvelope(
        seq=last + 1,
        run_id=str(run_id),
        type="user.interjected",
        agent_path=["main"],
        data={"id": "i1", "text": "改成英文"},
    )
    await setup.runs.add_events(run_id, [interjected])

    await _run_jobs(setup, "title")
    assert "改成英文" in "".join(str(m.content) for m in model.received[-1])
    await _run_jobs(setup, "memory_extraction")
    assert "改成英文" in "".join(str(m.content) for m in model.received[-1])
    await _run_jobs(setup, "conversation_index")
    [row] = index.rows.values()
    assert row.user_text == "写一段介绍\n\n改成英文"


# 删会话与写索引撞在一起（审查 Minor 4）：已删会话的内容不能留在索引里被搜到
class _PausingIndex(FakeConversationIndex):
    """写入前停住：后台任务已读完这一轮、正要写的那一刻。"""

    def __init__(self) -> None:
        super().__init__()
        self.reached = asyncio.Event()
        self.go = asyncio.Event()

    async def index(self, turn: NewConversationTurn, *, replaces: UUID | None = None) -> None:
        self.reached.set()
        await self.go.wait()
        await super().index(turn, replaces=replaces)


async def test_index_written_after_the_thread_is_deleted_is_dropped(db: Pool) -> None:
    index = _PausingIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), conversations=index)
    run_id = await setup.run("我家小狗叫旺财")
    job: asyncio.Future[None] = asyncio.ensure_future(
        setup.followups.handlers()["conversation_index"]({"run_id": str(run_id)})
    )
    await asyncio.wait_for(index.reached.wait(), 5)
    await setup.manager.delete_thread((await setup.runs.get(run_id)).thread_id)
    index.go.set()
    await job
    assert index.rows == {}


class _LateWriteIndex(FakeConversationIndex):
    """删会话先删索引：就在这之后、会话本身删掉之前，写索引的任务把这一轮写了进来。"""

    def __init__(self) -> None:
        super().__init__()
        self.late: NewConversationTurn | None = None

    async def delete_thread(self, thread_id: UUID) -> None:
        await super().delete_thread(thread_id)
        if self.late is not None:
            turn, self.late = self.late, None
            await self.index(turn)


async def test_index_written_while_the_thread_is_being_deleted_is_dropped(db: Pool) -> None:
    index = _LateWriteIndex()
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), conversations=index)
    run = await setup.runs.get(await setup.run("我家小狗叫旺财"))
    index.late = NewConversationTurn(
        thread_id=run.thread_id,
        run_id=run.id,
        title="小狗",
        started_at=run.created_at,
        user_text=run.message,
        answer_text="好",
    )
    await setup.manager.delete_thread(run.thread_id)
    assert index.rows == {}
