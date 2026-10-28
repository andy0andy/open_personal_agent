import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from agents.main_agent.models import current_call
from agents.main_agent.runtime import (
    ApprovalAnswer,
    MainAgent,
    RunFinished,
    RunStarted,
    ToolDecision,
    UsageReported,
    UsageTotals,
)
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace, WorkspaceFileRepo, workspace_file_id
from agents.tests.fakes import (
    BreakingChatModel,
    FailingAtChatModel,
    FakeGateway,
    FakeMcpClient,
    FakeSandbox,
    HangingChatModel,
    ScriptedChatModel,
    call,
    mcp_tool,
)
from agents.tests.waiting import until
from backend.runs import (
    ResumeRequest,
    RunCreate,
    RunFollowups,
    RunManager,
    RunRecord,
    RunRepo,
)
from backend.runtime import EventEnvelope, InMemoryEventBus, InProcessRunControl
from backend.threads import Thread, ThreadRepo
from common.db import Pool
from common.errors import ConflictError, NotFoundError

pytestmark = pytest.mark.integration


class _BrokenRunRepo(RunRepo):
    """模拟运行过程中与结束时数据库写入都失败。"""

    async def add_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        raise RuntimeError("数据库暂时不可用")

    async def replace_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        raise RuntimeError("数据库暂时不可用")


class _SlowUsageRepo(UsageRepo):
    """写用量时停住（模拟数据库慢），便于在"一次模型调用刚结束、正在写用量"的瞬间点停止。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.writing = asyncio.Event()

    async def add(
        self, *, thread_id: UUID | None, run_id: UUID | None, usage: UsageReported
    ) -> None:
        self.writing.set()
        await asyncio.sleep(0.2)  # 允许等待：替身模拟写用量慢
        await super().add(thread_id=thread_id, run_id=run_id, usage=usage)


class _SlowFirstUsageRepo(UsageRepo):
    """第一条用量写得慢：后台写入若不按顺序，第二条会先落库。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.first = True

    async def add(
        self, *, thread_id: UUID | None, run_id: UUID | None, usage: UsageReported
    ) -> None:
        if self.first:
            self.first = False
            await asyncio.sleep(0.2)  # 允许等待：替身模拟第一条写得慢
        await super().add(thread_id=thread_id, run_id=run_id, usage=usage)


class _StaleRunRepo(RunRepo):
    """停止请求读到的是"运行中"，而后台任务恰好在这一刻收尾结束（之后再读就是真实状态）。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.stale = False

    async def get(self, run_id: UUID) -> RunRecord:
        run = await super().get(run_id)
        if self.stale:
            self.stale = False
            return run.model_copy(update={"status": "running"})
        return run


def _manager(
    db: Pool,
    runs: RunRepo,
    model: ScriptedChatModel | None = None,
    usage: UsageRepo | None = None,
    bus: InMemoryEventBus | None = None,
    threads: ThreadRepo | None = None,
    workspace: LocalWorkspace | None = None,
    files: WorkspaceFileRepo | None = None,
    mcp: FakeMcpClient | None = None,
) -> RunManager:
    """flush_interval 调小，测试里不必等 200 毫秒。"""
    model = model or ScriptedChatModel(responses=[AIMessage(content="好")])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        mcp=mcp,
    )
    return RunManager(
        runs=runs,
        threads=threads or ThreadRepo(db),
        usage=usage or UsageRepo(db),
        files=files or WorkspaceFileRepo(db),
        agent=agent,
        bus=bus or InMemoryEventBus(),
        control=InProcessRunControl(),
        flush_interval=0.01,
    )


async def _drain(manager: RunManager, run_id: UUID) -> list[EventEnvelope]:
    return [event async for event in manager.stream(run_id)]


async def _drain_approving(manager: RunManager, run_id: UUID) -> list[EventEnvelope]:
    """执行命令固定先问（D21）：遇到审批就同意，接着收完这次运行的事件。"""
    events = await _drain(manager, run_id)
    while events[-1].type == "approval.required":
        await manager.resume(run_id, _approve(events[-1]))
        events += [e async for e in manager.stream(run_id, after_seq=events[-1].seq)]
    return events


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


async def _status_is(runs: RunRepo, run_id: UUID, status: str) -> bool:
    return (await runs.get(run_id)).status == status


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
    ending = [event async for event in rest][-1].data
    assert (ending["status"], ending["error_kind"]) == ("failed", "interrupted")


async def test_events_reach_history_while_running_then_get_compacted(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)
    # 运行还在进行：已推送的内容会分批写进界面历史（进程此时退出也不会丢）。
    # 轮询等待而不是固定等一会儿：刚启动的测试库第一次写入可能较慢
    # 每次主智能体调用模型前先有一条上下文占用（设计 2026-10-23 4.7）
    begun = ["run.started", "context.usage", "message.delta"]

    async def saved() -> bool:
        return len(await runs.events(run.id)) == len(begun)

    await until(saved, what="已推送的事件写进界面历史")
    assert [e.type for e in await runs.events(run.id)] == begun

    await manager.cancel(run.id)
    _ = [event async for event in rest]
    stored = await runs.events(run.id)
    assert [e.type for e in stored] == [*begun, "run.finished"]
    assert stored[2].data["full_text"] is True  # 结束时整体替换为合并后的版本


class _SlowFinalizeRunRepo(RunRepo):
    """收尾写库变慢，留出"收尾途中又被取消"的时间窗口；开始收尾时发信号。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.finalizing = asyncio.Event()

    async def replace_events(self, run_id: UUID, events: list[EventEnvelope]) -> None:
        self.finalizing.set()
        await asyncio.sleep(0.3)  # 允许等待：替身模拟收尾写库慢
        await super().replace_events(run_id, events)


async def test_second_cancel_during_finalization_still_records_cancelled(db: Pool) -> None:
    runs = _SlowFinalizeRunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await manager.cancel(run.id)
    await asyncio.wait_for(runs.finalizing.wait(), timeout=5)  # 第一次停止正在收尾（写库）
    await manager.cancel(run.id)  # 连点第二次
    events = [event async for event in rest]

    assert events[-1].data["status"] == "cancelled"
    assert (await runs.get(run.id)).status == "cancelled"
    await runs.create(thread_id=thread.id, model="m", message="下一条")  # 会话没有被卡住


async def test_cancel_during_completion_finalization_keeps_completed(db: Pool) -> None:
    runs = _SlowFinalizeRunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await asyncio.wait_for(runs.finalizing.wait(), timeout=5)  # 回答已经结束，正在收尾
    await manager.cancel(run.id)
    events = [event async for event in rest]

    assert events[-1].data["status"] == "completed"
    assert (await runs.get(run.id)).status == "completed"
    await runs.create(thread_id=thread.id, model="m", message="下一条")


async def test_shutdown_waits_for_runs_being_finalized(db: Pool) -> None:
    runs = _SlowFinalizeRunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await manager.cancel(run.id)
    await asyncio.wait_for(runs.finalizing.wait(), timeout=5)
    await manager.shutdown()  # 停机时再次取消：仍要等收尾写完，再关闭连接池

    assert (await runs.get(run.id)).status == "cancelled"


async def test_cancel_reports_interrupted_estimate_without_counting_it(db: Pool) -> None:
    runs = RunRepo(db)
    usage = UsageRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="写长文"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    await manager.cancel(run.id)
    tail = [event async for event in rest][-1]

    # 被中断那次调用的估算随结束事件推送（刷新后从界面历史重现），但不写用量表、不计入合计
    assert tail.data["interrupted_usage"]["output_tokens"] > 0
    assert tail.data["usage"]["calls"] == 0
    assert await usage.for_run(run.id) == []
    stored = (await runs.events(run.id))[-1]
    assert stored.data["interrupted_usage"] == tail.data["interrupted_usage"]


async def test_delete_thread_clears_archive_but_keeps_usage(db: Pool) -> None:
    runs, usage = RunRepo(db), UsageRepo(db)
    answer = AIMessage(
        content="好", usage_metadata={"input_tokens": 9, "output_tokens": 1, "total_tokens": 10}
    )
    manager = _manager(db, runs, ScriptedChatModel(responses=[answer]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    _ = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    await manager.delete_thread(thread.id)

    with pytest.raises(NotFoundError):
        await ThreadRepo(db).get(thread.id)
    graph = manager._agent._graph_for("m", "ask")
    assert (await graph.aget_state({"configurable": {"thread_id": str(thread.id)}})).values == {}
    assert [r.input_tokens for r in await usage.for_run(run.id)] == [9]  # 用量记录保留


async def test_delete_running_thread_is_refused(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)

    with pytest.raises(ConflictError, match="请先停止"):
        await manager.delete_thread(thread.id)

    await manager.cancel(run.id)
    _ = [event async for event in rest]
    await manager.delete_thread(thread.id)  # 停止后可以删除
    with pytest.raises(NotFoundError):
        await ThreadRepo(db).get(thread.id)


async def test_cancel_while_recording_usage_keeps_the_answer(db: Pool) -> None:
    """一次模型调用刚结束、正在写用量时点停止：已输出的回答仍要留在对话存档里，
    否则界面上看得到完整回答，模型下一轮却看不到，用户说"继续"时会从头重做。"""
    runs, usage = RunRepo(db), _SlowUsageRepo(db)
    meta = {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13}
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="完整的回答", usage_metadata=meta),
            AIMessage(content="二", usage_metadata=meta),
        ]
    )
    manager = _manager(db, runs, model, usage=usage)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="写一段话"))
    events = manager.stream(run.id)
    await asyncio.wait_for(usage.writing.wait(), timeout=5)

    await manager.cancel(run.id)
    _ = [event async for event in events]
    second = await manager.start(thread.id, RunCreate(message="继续"))
    _ = await asyncio.wait_for(_drain(manager, second.id), timeout=5)

    seen = [m.content for m in model.received[-1] if m.type == "ai"]
    assert any("完整的回答" in str(content) for content in seen)
    assert len(await usage.for_run(run.id)) == 1  # 已结束的那次调用的用量照常写入


async def _set_status(db: Pool, run_id: UUID, status: str) -> None:
    async with db.connection() as conn:
        await conn.execute("UPDATE runs SET status = %s WHERE id = %s", (status, run_id))


async def test_cancel_run_that_is_not_executing_ends_its_stream(db: Pool) -> None:
    """等待审批（interrupted，M4）的运行没有后台任务，被停止时也要存下并推送结束事件，
    否则正在看它的页面一直停在"运行中"，刷新后又显示成"运行未正常结束"。"""
    runs, bus = RunRepo(db), InMemoryEventBus()
    manager = _manager(db, runs, bus=bus)
    thread = await ThreadRepo(db).create(model="m")
    run = await runs.create(
        thread_id=thread.id, model="m", message="hi"
    )  # 不经 start：没有后台任务
    await _set_status(db, run.id, "interrupted")
    bus.open(str(run.id))
    watching = asyncio.create_task(_drain(manager, run.id))
    await asyncio.sleep(0)

    await manager.cancel(run.id)

    live = await asyncio.wait_for(watching, timeout=5)
    assert [(e.type, e.data["status"]) for e in live] == [("run.finished", "cancelled")]
    assert (await runs.get(run.id)).status == "cancelled"
    replayed = await _drain(_manager(db, runs), run.id)  # 新进程：从界面历史补发
    assert [(e.type, e.data["status"]) for e in replayed] == [("run.finished", "cancelled")]


async def test_usage_is_recorded_in_call_order(db: Pool) -> None:
    """用量在后台写入，也要按调用顺序落库：每轮的调用明细按写入时间排列。"""
    runs, usage = RunRepo(db), _SlowFirstUsageRepo(db)
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "c1"}],
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            ),
            AIMessage(
                content="好",
                usage_metadata={"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
            ),
        ]
    )
    manager = _manager(db, runs, model, usage=usage)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    _ = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    assert [r.input_tokens for r in await usage.for_run(run.id)] == [1, 2]


class _CallRecordingUsageRepo(UsageRepo):
    """记下后台写用量、工具用量时的调用归属。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.seen: list[object] = []

    async def add(
        self, *, thread_id: UUID | None, run_id: UUID | None, usage: UsageReported
    ) -> None:
        self.seen.append(current_call())
        await super().add(thread_id=thread_id, run_id=run_id, usage=usage)

    async def add_tool_use(
        self, *, thread_id: UUID, run_id: UUID, tool: str, skill: str | None
    ) -> None:
        self.seen.append(current_call())
        await super().add_tool_use(thread_id=thread_id, run_id=run_id, tool=tool, skill=skill)


async def test_background_writes_do_not_carry_the_call_context(db: Pool) -> None:
    """后台写库任务不带这次运行的调用归属（积压小问题 G2）：它们只写库，不该算在哪次调用里。"""
    usage = _CallRecordingUsageRepo(db)
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "c1"}],
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            ),
            AIMessage(
                content="好",
                usage_metadata={"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
            ),
        ]
    )
    manager = _manager(db, RunRepo(db), model, usage=usage)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    assert len(usage.seen) == 3  # 两次模型调用、一次工具
    assert usage.seen == [None, None, None]


async def test_cancel_racing_with_finish_leaves_finished_run_alone(db: Pool) -> None:
    """回答刚结束时点停止：读到"运行中"，但后台任务已经收尾结束——
    不能给完整的回答追加"已停止"、把运行改成已取消，按"已结束"拒绝即可。"""
    runs = _StaleRunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    _ = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    runs.stale = True

    with pytest.raises(ConflictError, match="已结束"):
        await manager.cancel(run.id)

    assert (await runs.get(run.id)).status == "completed"
    events = await runs.events(run.id)
    assert [e.data["status"] for e in events if e.type == "run.finished"] == ["completed"]


class _SlowTouchThreadRepo(ThreadRepo):
    """记录"会话有新运行"时停住，模拟发起运行的请求还在途中。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.touching = asyncio.Event()

    async def touch(self, thread_id: UUID, *, first_message: str) -> None:
        self.touching.set()
        await asyncio.sleep(0.2)  # 允许等待：替身模拟更新会话慢
        await super().touch(thread_id, first_message=first_message)


async def test_cancel_while_run_is_starting_stops_it(db: Pool) -> None:
    """运行刚建好、发起请求还没返回时停止：要真的停下。若此时还没登记后台任务，
    运行会被记为已取消、随后却照常执行完，数据库最后写成"已完成"。"""
    runs, threads = RunRepo(db), _SlowTouchThreadRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]), threads=threads)
    thread = await ThreadRepo(db).create(model="m")
    starting = asyncio.create_task(manager.start(thread.id, RunCreate(message="hi")))
    await asyncio.wait_for(threads.touching.wait(), timeout=5)
    run_id = (await runs.history(thread.id))[-1].id

    await manager.cancel(run_id)
    run = await starting
    events = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    assert events[-1].type == "run.finished"
    assert events[-1].data["status"] == "cancelled"
    assert (await runs.get(run.id)).status == "cancelled"


async def test_cancel_stuck_run_without_task_ends_it(db: Pool) -> None:
    """数据库里"运行中"、进程里却没有它的后台任务（收尾写库失败卡住了）：停止就把它结束，
    会话不必等到重启服务才能继续。"""
    runs = RunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await runs.create(thread_id=thread.id, model="m", message="hi")  # 没有后台任务

    await manager.cancel(run.id)

    assert (await runs.get(run.id)).status == "cancelled"
    assert [e.data["status"] for e in await runs.events(run.id)] == ["cancelled"]


async def test_commands_run_in_the_threads_work_directory(db: Pool, tmp_path: Path) -> None:
    sandbox = FakeSandbox()
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    manager = _manager(db, RunRepo(db), model, workspace=LocalWorkspace(tmp_path, sandbox))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="看看有什么文件"))
    _ = await asyncio.wait_for(_drain_approving(manager, run.id), timeout=5)
    assert sandbox.calls == [(thread.short_id, "ls", None)]


async def test_delete_thread_also_removes_its_workspace(db: Pool, tmp_path: Path) -> None:
    """删除会话 = 删除它的全部内容，包括上传与产物所在的工作目录（设计文档 9.3）。"""
    manager = _manager(db, RunRepo(db), workspace=LocalWorkspace(tmp_path, FakeSandbox()))
    thread = await ThreadRepo(db).create(model="m")
    outputs = tmp_path / "workspace" / thread.short_id / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "chart.png").write_bytes(b"png")

    files = WorkspaceFileRepo(db)
    await files.record(thread.id, "outputs/chart.png", source="output", size=3, media_type="x")

    await manager.delete_thread(thread.id)

    assert not (tmp_path / "workspace" / thread.short_id).exists()
    assert await files.for_thread(thread.id) == []


async def test_created_files_get_an_id_and_are_recorded(db: Pool, tmp_path: Path) -> None:
    """产物事件推送时已带文件 ID（前端据此下载）；登记在后台完成，结束事件推送前已写好。"""
    thread = await ThreadRepo(db).create(model="m")

    def make_chart(session: str, command: str) -> None:
        outputs = tmp_path / "workspace" / session / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "chart.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python plot.py"}), AIMessage("好")]
    )
    workspace = LocalWorkspace(tmp_path, FakeSandbox(effect=make_chart))
    manager = _manager(db, RunRepo(db), model, workspace=workspace)
    run = await manager.start(thread.id, RunCreate(message="画图"))
    events = await asyncio.wait_for(_drain_approving(manager, run.id), timeout=5)

    created = [e for e in events if e.type == "file.created"]
    assert [e.data["file_id"] for e in created] == [
        str(workspace_file_id(thread.id, "outputs/chart.png"))
    ]
    record = await WorkspaceFileRepo(db).get(UUID(created[0].data["file_id"]))
    assert (record.path, record.size, record.source, record.media_type) == (
        "outputs/chart.png",
        4,
        "output",
        "image/png",
    )


async def test_stopped_run_registers_its_outputs(db: Pool, tmp_path: Path) -> None:
    """命令写好产物后卡住、被停止（积压小问题 D1）：那个文件照样登记，
    结束事件之前推一条 file.created（原来卡片、文件面板都看不到，文件却在磁盘上）。"""
    chart = tmp_path / "workspace" / "{session}" / "outputs" / "x.png"

    def make_chart(session: str, command: str) -> None:
        target = Path(str(chart).replace("{session}", session))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"png!")

    sandbox = FakeSandbox(hang=True, effect=make_chart)
    workspace = LocalWorkspace(tmp_path, sandbox)  # 会话目录在 tmp_path/workspace/<会话>/
    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python plot.py"}), AIMessage(content="好")]
    )
    runs, files = RunRepo(db), WorkspaceFileRepo(db)
    manager = _manager(db, runs, model, workspace=workspace, files=files)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="画图"))
    paused = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    await manager.resume(run.id, _approve(paused[-1]))  # 执行命令固定先问（D21）
    await until(lambda: bool(sandbox.calls), what="命令开始执行")
    await manager.cancel(run.id)
    await until(lambda: _status_is(runs, run.id, "cancelled"), what="运行记为已停止")

    stored = await runs.events(run.id)
    assert [e.type for e in stored[-2:]] == ["file.created", "run.finished"]
    assert stored[-2].data["path"] == "outputs/x.png"
    assert stored[-1].seq == stored[-2].seq + 1
    assert [f.path for f in await files.for_thread(thread.id)] == ["outputs/x.png"]


async def test_attachments_are_recorded_and_given_to_the_agent(db: Pool, tmp_path: Path) -> None:
    thread = await ThreadRepo(db).create(model="m")
    uploads = tmp_path / "workspace" / thread.short_id / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.csv").write_text("x,y")
    record = await WorkspaceFileRepo(db).record(
        thread.id, "uploads/a.csv", source="upload", size=3, media_type="text/csv"
    )
    model = ScriptedChatModel(responses=[AIMessage("好")])
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    manager = _manager(db, RunRepo(db), model, workspace=workspace)
    run = await manager.start(thread.id, RunCreate(message="看看", attachments=[record.id]))
    assert [(a.id, a.path, a.media_type, a.size) for a in run.attachments] == [
        (record.id, "uploads/a.csv", "text/csv", 3)
    ]
    await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    assert (await RunRepo(db).history(thread.id))[0].attachments == run.attachments
    assert f"/workspace/{thread.short_id}/uploads/a.csv" in str(model.received[0][-1].content)


async def test_attachments_from_other_threads_are_refused(db: Pool) -> None:
    threads = ThreadRepo(db)
    thread, other = await threads.create(model="m"), await threads.create(model="m")
    foreign = await WorkspaceFileRepo(db).record(
        other.id, "uploads/a.csv", source="upload", size=3, media_type="text/csv"
    )
    runs = RunRepo(db)
    manager = _manager(db, runs)
    with pytest.raises(NotFoundError):
        await manager.start(thread.id, RunCreate(message="看看", attachments=[foreign.id]))
    assert await runs.history(thread.id) == []


# ---- 审批暂停与恢复（设计文档 10.5）----


class _Notes:
    """先问你的 MCP 工具 demo_add_note，记下它收到的参数。"""

    def __init__(self) -> None:
        self.received: list[str] = []

        @tool
        def demo_add_note(text: str) -> str:
            """记一条笔记"""
            self.received.append(text)
            return f"added {text}"

        self.tool = demo_add_note


class _Followups(RunFollowups):
    """只记下哪些运行登记了后续任务。"""

    def __init__(self) -> None:
        self.completed: list[UUID] = []

    async def after_completed(self, run: RunRecord) -> None:
        self.completed.append(run.id)


def _with_usage(message: AIMessage) -> AIMessage:
    message.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    return message


def _note_script() -> ScriptedChatModel:
    return ScriptedChatModel(
        responses=[
            _with_usage(call("demo_add_note", {"text": "买牛奶"}, "c1")),
            _with_usage(AIMessage(content="记好了")),
        ]
    )


def _ask_manager(
    db: Pool,
    model: ScriptedChatModel,
    notes: _Notes,
    *,
    checkpointer: InMemorySaver | None = None,
    followups: RunFollowups | None = None,
) -> RunManager:
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=checkpointer or InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        mcp=FakeMcpClient([mcp_tool(notes.tool)]),
    )
    return RunManager(
        runs=RunRepo(db),
        threads=ThreadRepo(db),
        usage=UsageRepo(db),
        files=WorkspaceFileRepo(db),
        agent=agent,
        bus=InMemoryEventBus(),
        control=InProcessRunControl(),
        flush_interval=0.01,
        followups=followups,
    )


async def _pause(manager: RunManager, db: Pool) -> tuple[RunRecord, list[EventEnvelope]]:
    thread = await ThreadRepo(db).create(model="fake-model")
    run = await manager.start(thread.id, RunCreate(message="记一下"))
    return run, await _drain(manager, run.id)


def _approve(paused: EventEnvelope) -> ResumeRequest:
    [request] = paused.data["requests"]
    return ResumeRequest(
        answers=[
            ApprovalAnswer(
                interrupt_id=request["interrupt_id"], decisions=[ToolDecision(type="approve")]
            )
        ]
    )


async def test_run_pauses_for_approval(db: Pool) -> None:
    notes, followups = _Notes(), _Followups()
    manager = _ask_manager(db, _note_script(), notes, followups=followups)
    run, events = await _pause(manager, db)
    assert events[-1].type == "approval.required"
    assert "run.finished" not in [e.type for e in events]
    runs = RunRepo(db)
    assert (await runs.get(run.id)).status == "interrupted"
    assert (await runs.usage_totals(run.id)).calls == 1
    with pytest.raises(ConflictError):
        await manager.start(run.thread_id, RunCreate(message="再来"))
    assert followups.completed == []
    assert notes.received == []


async def test_resume_continues_with_following_seq(db: Pool) -> None:
    notes, followups = _Notes(), _Followups()
    manager = _ask_manager(db, _note_script(), notes, followups=followups)
    run, events = await _pause(manager, db)
    last = events[-1].seq
    resumed = await manager.resume(run.id, _approve(events[-1]))
    assert resumed.status == "running"
    tail = [e async for e in manager.stream(run.id, after_seq=last)]
    assert (tail[0].type, tail[0].seq) == ("approval.resolved", last + 1)
    assert tail[-1].type == "run.finished"
    assert tail[-1].data["status"] == "completed"
    runs = RunRepo(db)
    stored = await runs.events(run.id)
    seqs = [e.seq for e in stored]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert {"approval.required", "approval.resolved", "run.finished"} <= {e.type for e in stored}
    assert (await runs.get(run.id)).status == "completed"
    assert (await runs.usage_totals(run.id)).calls == 2
    assert notes.received == ["买牛奶"]
    assert followups.completed == [run.id]


async def test_second_resume_is_conflict(db: Pool) -> None:
    notes = _Notes()
    manager = _ask_manager(db, _note_script(), notes)
    run, events = await _pause(manager, db)
    request = _approve(events[-1])
    results = await asyncio.gather(
        manager.resume(run.id, request), manager.resume(run.id, request), return_exceptions=True
    )
    assert sorted(type(r).__name__ for r in results) == ["ConflictError", "RunRecord"]
    await _drain(manager, run.id)
    assert notes.received == ["买牛奶"]  # 工具只执行了一次（积压小问题 I4）


async def test_stream_from_before_the_pause_after_resume_misses_nothing(db: Pool) -> None:
    """恢复审批后从头订阅（积压小问题 E9）：暂停前那一段（在库里）与恢复后的（在总线里）
    拼起来不缺不重。"""
    manager = _ask_manager(db, _note_script(), _Notes())
    run, events = await _pause(manager, db)
    await manager.resume(run.id, _approve(events[-1]))
    replay = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    seqs = [event.seq for event in replay]
    assert seqs == sorted(set(seqs))
    types = [event.type for event in replay]
    assert {"approval.required", "approval.resolved"} <= set(types)  # 接缝两侧都在
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"


async def test_resume_rejects_stale_answers(db: Pool) -> None:
    manager = _ask_manager(db, _note_script(), _Notes())
    run, _ = await _pause(manager, db)
    stale = ResumeRequest(
        answers=[ApprovalAnswer(interrupt_id="stale", decisions=[ToolDecision(type="approve")])]
    )
    with pytest.raises(ConflictError):
        await manager.resume(run.id, stale)
    assert (await RunRepo(db).get(run.id)).status == "interrupted"


async def test_cancel_while_waiting_keeps_usage(db: Pool) -> None:
    notes = _Notes()
    manager = _ask_manager(db, _note_script(), notes)
    run, events = await _pause(manager, db)
    await manager.cancel(run.id)
    tail = [e async for e in manager.stream(run.id, after_seq=events[-1].seq)]
    assert tail[-1].type == "run.finished"
    assert tail[-1].data["status"] == "cancelled"
    assert tail[-1].data["usage"]["calls"] == 1
    runs = RunRepo(db)
    assert (await runs.get(run.id)).status == "cancelled"
    assert (await runs.usage_totals(run.id)).calls == 1
    assert notes.received == []


async def test_resume_after_restart(db: Pool) -> None:
    """服务重启后再审批：新的 RunManager 与智能体（同一数据库、同一对话存档）接着跑完。"""
    notes, checkpointer = _Notes(), InMemorySaver()
    model = _note_script()
    run, events = await _pause(_ask_manager(db, model, notes, checkpointer=checkpointer), db)
    restarted = _ask_manager(db, model, notes, checkpointer=checkpointer)
    await restarted.resume(run.id, _approve(events[-1]))
    tail = [e async for e in restarted.stream(run.id, after_seq=events[-1].seq)]
    assert tail[-1].data["status"] == "completed"
    assert notes.received == ["买牛奶"]


async def test_stream_of_paused_run_ends_at_approval(db: Pool) -> None:
    """推送已关闭（如服务重启后）：从界面历史补发到 approval.required 就结束，不补结束事件。"""
    notes = _Notes()
    run, _ = await _pause(_ask_manager(db, _note_script(), notes), db)
    fresh = _ask_manager(db, _note_script(), notes)
    replayed = await asyncio.wait_for(_drain(fresh, run.id), timeout=2)
    assert replayed[-1].type == "approval.required"


class _SlowGetThreadRepo(ThreadRepo):
    """恢复时读会话变慢：停止请求恰好落在"已改回运行中、还没登记后台任务"的空档里。"""

    slow = False

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.getting = asyncio.Event()

    async def get(self, thread_id: UUID) -> Thread:
        if self.slow:
            self.getting.set()
            await asyncio.sleep(0.3)  # 允许等待：替身模拟读会话慢
        return await super().get(thread_id)


async def test_cancel_racing_resume_ends_cancelled_and_consistent(db: Pool) -> None:
    """同意后立刻点停止：最终是"已停止"，界面历史只有一个结束事件。

    原来恢复的那段会照常跑完，把"已停止"改回"完成"（审查 I2）。
    """
    notes, threads = _Notes(), _SlowGetThreadRepo(db)
    manager = _ask_manager(db, _note_script(), notes)
    manager._threads = threads  # 测试替身：换成会变慢的会话数据访问
    run, events = await _pause(manager, db)
    threads.slow = True
    resuming = asyncio.create_task(manager.resume(run.id, _approve(events[-1])))
    await asyncio.wait_for(threads.getting.wait(), timeout=5)
    await manager.cancel(run.id)
    await asyncio.gather(resuming, return_exceptions=True)
    await _drain(manager, run.id)
    runs = RunRepo(db)
    await until(lambda: _status_is(runs, run.id, "cancelled"), what="运行记为已停止")
    stored = await runs.events(run.id)
    finished = [e for e in stored if e.type == "run.finished"]
    assert [e.data["status"] for e in finished] == ["cancelled"]


class _SlowPauseRunRepo(RunRepo):
    """暂停收尾（把运行记为等待审批）变慢：停止请求落在收尾期间。"""

    async def pause(self, run_id: UUID, *, usage: UsageTotals) -> None:
        await asyncio.sleep(0.3)  # 允许等待：替身模拟暂停收尾慢
        await super().pause(run_id, usage=usage)


async def test_cancel_during_pause_finalization_stops_the_run(db: Pool) -> None:
    """approval.required 刚推送、暂停还没写完时点停止：停止不能被吞掉（审查 I2）。"""
    manager = _ask_manager(db, _note_script(), _Notes())
    manager._runs = _SlowPauseRunRepo(db)  # 测试替身：暂停收尾变慢
    thread = await ThreadRepo(db).create(model="fake-model")
    run = await manager.start(thread.id, RunCreate(message="记一下"))
    async for event in manager.stream(run.id):
        if event.type == "approval.required":
            break
    await manager.cancel(run.id)
    runs = RunRepo(db)
    await until(lambda: _status_is(runs, run.id, "cancelled"), what="运行记为已停止")
    assert (await runs.events(run.id))[-1].type == "run.finished"
    # 这次停止已经处理完，不再记着（审查 Minor 4：原来只在顺利收尾里清，这条路会一直留着）
    assert run.id not in manager._stop_requested


# ---- "重试这一轮"（D26，设计 2026-10-23 4.5） ----


async def test_retry_starts_a_new_run_with_the_same_input(db: Pool) -> None:
    """同样的原文与附件、会话当前的模型；模型只看到一次这句话（从失败前分叉）。"""
    runs, threads = RunRepo(db), ThreadRepo(db)
    model = BreakingChatModel(
        error=RuntimeError("boom"), partial="", responses=[AIMessage(content="重试成功")]
    )
    manager = _manager(db, runs, model)
    thread = await threads.create(model="m")
    failed = await manager.start(thread.id, RunCreate(message="写报告"))
    ending = (await _drain(manager, failed.id))[-1]
    assert (ending.data["status"], ending.data["retryable"]) == ("failed", True)
    await threads.update(thread.id, model="m2")

    retried = await manager.retry(failed.id)

    assert (retried.retry_of, retried.message, retried.model) == (failed.id, "写报告", "m2")
    assert retried.attachments == failed.attachments
    assert (await _drain(manager, retried.id))[-1].data["status"] == "completed"
    assert [m.content for m in model.received[-1] if m.type == "human"] == ["写报告"]


async def test_finished_event_marks_retryable(db: Pool) -> None:
    """只用了只读工具（如 ls）就失败：可以重试。"""
    runs = RunRepo(db)
    model = FailingAtChatModel(fail_at=1, responses=[call("ls", {"path": "/"})])
    manager = _manager(db, runs, model)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="看看"))
    ending = (await _drain(manager, run.id))[-1]
    assert (ending.data["status"], ending.data["retryable"]) == ("failed", True)


async def test_retry_refuses_after_side_effects(db: Pool) -> None:
    """执行过命令再失败：不能重试（会再跑一遍），只能"继续"。执行命令的开始事件在审批暂停之前
    那一段里，恢复后的那段才失败——也要算上。"""
    runs = RunRepo(db)
    model = FailingAtChatModel(fail_at=1, responses=[call("execute", {"command": "ls"})])
    manager = _manager(db, runs, model)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="跑一下"))
    ending = (await _drain_approving(manager, run.id))[-1]
    assert (ending.data["status"], ending.data["retryable"]) == ("failed", False)
    with pytest.raises(ConflictError, match="不能重试"):
        await manager.retry(run.id)


async def test_retry_refuses_older_runs(db: Pool) -> None:
    runs = RunRepo(db)
    model = BreakingChatModel(
        error=RuntimeError("boom"), partial="", responses=[AIMessage(content="好")]
    )
    manager = _manager(db, runs, model)
    thread = await ThreadRepo(db).create(model="m")
    failed = await manager.start(thread.id, RunCreate(message="一"))
    await _drain(manager, failed.id)
    later = await manager.start(thread.id, RunCreate(message="二"))
    await _drain(manager, later.id)
    with pytest.raises(ConflictError, match="最近的一轮"):
        await manager.retry(failed.id)


async def test_retry_refuses_completed_runs(db: Pool) -> None:
    runs = RunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="一"))
    await _drain(manager, run.id)
    with pytest.raises(ConflictError, match="失败或停止"):
        await manager.retry(run.id)


async def test_retry_twice_conflicts(db: Pool) -> None:
    """连点两次、两个标签页同时点：只发起一次新运行。"""
    runs = RunRepo(db)
    model = BreakingChatModel(
        error=RuntimeError("boom"), partial="", responses=[AIMessage(content="好")]
    )
    manager = _manager(db, runs, model)
    thread = await ThreadRepo(db).create(model="m")
    failed = await manager.start(thread.id, RunCreate(message="一"))
    await _drain(manager, failed.id)
    results = await asyncio.gather(
        manager.retry(failed.id), manager.retry(failed.id), return_exceptions=True
    )
    assert sum(isinstance(item, RunRecord) for item in results) == 1
    assert sum(isinstance(item, ConflictError) for item in results) == 1


async def _ended_run(runs: RunRepo, thread: Thread, *, retryable: bool | None) -> RunRecord:
    """一次失败的运行：retryable 为 None 时界面历史里没有结束事件（进程中途退出）。"""
    run = await runs.create(thread_id=thread.id, model="m", message="一")
    events = [EventEnvelope.wrap(RunStarted(model="m"), seq=1, run_id=str(run.id))]
    if retryable is not None:
        finished = RunFinished(status="failed", error="boom", retryable=retryable)
        events.append(EventEnvelope.wrap(finished, seq=2, run_id=str(run.id)))
    await runs.add_events(run.id, events)
    await runs.finish(run.id, status="failed", error="boom")
    return run


async def test_retry_refuses_runs_that_ended_without_a_finish_event(db: Pool) -> None:
    """进程中途退出的运行（D26 第 6 条）：不知道做到了哪一步，后端拒绝重试（审查 M4）。"""
    runs = RunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await _ended_run(runs, thread, retryable=None)
    with pytest.raises(ConflictError, match="没有正常结束"):
        await manager.retry(run.id)


async def test_retry_follows_the_recorded_decision(db: Pool) -> None:
    """以收尾时记下的"能否重试"为准，不在点按钮时重新判断（那时 MCP 服务可能已断开）。"""
    runs = RunRepo(db)
    manager = _manager(db, runs)
    thread = await ThreadRepo(db).create(model="m")
    run = await _ended_run(runs, thread, retryable=False)
    with pytest.raises(ConflictError, match="不能重试"):
        await manager.retry(run.id)


async def test_side_effect_check_failure_still_finishes_the_run(db: Pool) -> None:
    """收尾时判断副作用出错：照样收尾（按不能重试处理），会话不能被卡在"运行中"（审查 M5）。"""
    runs = RunRepo(db)
    model = BreakingChatModel(error=RuntimeError("boom"), partial="", responses=[])
    manager = _manager(db, runs, model)

    def broken(_: object) -> bool:
        raise RuntimeError("MCP 工具清单读不出来")

    manager._agent.has_side_effects = broken  # type: ignore[method-assign,assignment]
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="一"))
    ending = (await asyncio.wait_for(_drain(manager, run.id), timeout=5))[-1]
    assert (ending.data["status"], ending.data["retryable"]) == ("failed", False)
    assert (await runs.get(run.id)).status == "failed"


# 插话不打断：收尾时剩下的插话（设计 2026-10-23 6.3）
@tool
def demo_tool() -> str:
    """查一下"""
    return "查到了"


class _LateInterjection(ScriptedChatModel):
    """第 at 次调用（从 0 数）开始以后用户才插话：这句来不及在这次调用前送达。"""

    at: int = 0
    late: list[str] = Field(default_factory=list)
    queue_of: Any = None
    fail_at: int | None = None

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        index = self.cursor
        if index == self.at and self.queue_of is not None:
            for text in self.late:
                self.queue_of().put(text)
        if index == self.fail_at:
            self.cursor += 1
            raise RuntimeError("模型调用失败")
        return super()._next(messages)


def _the_queue(manager: RunManager) -> Any:
    return lambda: next(iter(manager._interjections.values()))


async def test_leftover_interjection_starts_next_run(db: Pool) -> None:
    """顺利结束时还有没送达的插话：自动用它们发起下一轮，结束事件带上下一轮的编号。"""
    runs = RunRepo(db)
    model = _LateInterjection(
        responses=[AIMessage(content="好"), AIMessage(content="收到补充")], late=["再补一句"]
    )
    manager = _manager(db, runs, model)
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))
    events = [e async for e in manager.stream(run.id)]
    assert events[-1].type == "run.finished"
    next_id = events[-1].data["next_run_id"]
    assert next_id
    following = await runs.get(UUID(next_id))
    assert following.message == "再补一句"
    async for _ in manager.stream(following.id):
        pass
    assert (await runs.get(following.id)).status == "completed"


async def test_next_run_id_reaches_a_late_subscriber(db: Pool) -> None:
    """结束后（总线还留着这个运行时）重新订阅，结束事件照样带下一轮的编号（第三批审查
    Important 1：从库里补发时，库里那份结束事件不带它）。"""
    runs = RunRepo(db)
    model = _LateInterjection(
        responses=[AIMessage(content="好"), AIMessage(content="收到补充")], late=["再补一句"]
    )
    manager = _manager(db, runs, model)
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))
    first = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    late = await asyncio.wait_for(_drain(manager, run.id), timeout=5)  # 断线重连
    assert late[-1].data["next_run_id"] == first[-1].data["next_run_id"]
    assert late[-1].data["next_run_id"] is not None


async def test_leftover_on_stop_is_returned(db: Pool) -> None:
    """被停时还有没送达的插话：放在结束事件里退回，界面放回输入框。"""
    runs = RunRepo(db)
    manager = _manager(db, runs, HangingChatModel(responses=[]))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="写长文"))
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)  # 卡在输出里
    await manager.interject(run.id, "等等，换个题目")
    await manager.cancel(run.id)
    events = [e async for e in rest]
    finished = events[-1]
    assert (finished.data["status"], finished.data["undelivered"]) == (
        "cancelled",
        ["等等，换个题目"],
    )


async def test_run_with_interjections_is_not_retryable(db: Pool) -> None:
    """送达过插话的一轮失败了：只给"继续"——重跑会丢掉插话。"""
    runs = RunRepo(db)
    model = _LateInterjection(
        responses=[call("demo_tool", {}), AIMessage(content="")],
        at=0,
        late=["用英文"],
        fail_at=1,
    )
    manager = _manager(db, runs, model, mcp=FakeMcpClient([mcp_tool(demo_tool, read_only=True)]))
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="查一下"))
    events = [e async for e in manager.stream(run.id)]
    assert [e.data["text"] for e in events if e.type == "user.interjected"] == ["用英文"]
    assert events[-1].data["status"] == "failed"
    assert events[-1].data["retryable"] is False


async def test_leftover_is_returned_when_saving_the_run_fails(db: Pool) -> None:
    """收尾写库失败时没法接着发起下一轮：剩下的插话退回（审查 Minor 7：原来悄悄丢掉）。"""
    model = _LateInterjection(responses=[AIMessage(content="好")], late=["再补一句"])
    manager = _manager(db, _BrokenRunRepo(db), model)
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))
    events = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    assert (events[-1].data["undelivered"], events[-1].data["next_run_id"]) == (["再补一句"], None)


async def test_stop_during_wrap_up_gives_interjections_back(db: Pool) -> None:
    """回答已经结束、正在收尾时点停止（B9）：不再用插话接着发起下一轮，插话退回并存进历史。"""
    runs = _SlowFinalizeRunRepo(db)
    model = _LateInterjection(responses=[AIMessage(content="好")], late=["再补一句"])
    manager = _manager(db, runs, model)
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))
    draining = asyncio.create_task(_drain(manager, run.id))

    await asyncio.wait_for(runs.finalizing.wait(), timeout=5)  # 回答已经结束，正在收尾
    await manager.cancel(run.id)
    events = await asyncio.wait_for(draining, timeout=5)

    ending = events[-1].data
    assert (ending["status"], ending["undelivered"], ending["next_run_id"]) == (
        "completed",
        ["再补一句"],
        None,
    )
    assert (await runs.latest(thread.id)).id == run.id  # type: ignore[union-attr]
    assert (await runs.events(run.id))[-1].data["undelivered"] == ["再补一句"]


async def test_shutdown_during_wrap_up_gives_interjections_back(db: Pool) -> None:
    """收尾途中停机（B9）：不再发起下一轮（原来停机返回后它还在跑），插话存进结束事件。"""
    runs = _SlowFinalizeRunRepo(db)
    model = _LateInterjection(responses=[AIMessage(content="好")], late=["再补一句"])
    manager = _manager(db, runs, model)
    model.queue_of = _the_queue(manager)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))

    await asyncio.wait_for(runs.finalizing.wait(), timeout=5)
    await manager.shutdown()

    assert (await runs.latest(thread.id)).id == run.id  # type: ignore[union-attr]
    stored = await runs.events(run.id)
    assert (stored[-1].data["status"], stored[-1].data["undelivered"]) == (
        "completed",
        ["再补一句"],
    )


class _TouchFailingThreadRepo(ThreadRepo):
    async def touch(self, thread_id: UUID, *, first_message: str | None = None) -> None:
        raise RuntimeError("数据库暂时不可用")


async def test_started_run_is_returned_even_if_bookkeeping_fails(db: Pool) -> None:
    """运行已经发起后，更新会话时间失败只记日志（审查 Minor 8：原来报错，调用方以为没发起，
    插话接续时会退回输入框、再发一次就做两遍）。"""
    runs = RunRepo(db)
    threads = _TouchFailingThreadRepo(db)
    manager = _manager(db, runs, threads=threads)
    thread = await threads.create(model="m")
    run = await manager.start(thread.id, RunCreate(message="你好"))
    async for _ in manager.stream(run.id):
        pass
    assert (await runs.get(run.id)).status == "completed"
