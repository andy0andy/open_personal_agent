"""运行管理：在后台执行运行，把事件推给事件总线，结束后写入界面历史。"""

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID
from weakref import WeakValueDictionary

from agents.main_agent.models import detached_context
from agents.main_agent.runtime import (
    ApprovalAnswer,
    ApprovalRequired,
    Attachment,
    Event,
    FileCreated,
    Interjections,
    MainAgent,
    RunFinished,
    SubagentStarted,
    ToolRunning,
    UsageReported,
    UsageTotals,
)
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import WorkspaceFileRepo, media_type, workspace_file_id
from backend.runs.followups import RunFollowups
from backend.runs.repo import RunRepo
from backend.runs.schemas import ResumeRequest, RunAttachment, RunCreate, RunRecord
from backend.runs.writer import EventWriter
from backend.runtime import EventBus, EventEnvelope, RunControl
from backend.threads import ThreadRepo
from common.errors import ConflictError, NotFoundError

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
        files: WorkspaceFileRepo,
        agent: MainAgent,
        bus: EventBus,
        control: RunControl,
        flush_interval: float = 0.2,
        followups: RunFollowups | None = None,
    ) -> None:
        self._runs = runs
        self._threads = threads
        self._usage = usage
        self._files = files
        self._agent = agent
        self._bus = bus
        self._control = control
        self._flush_interval = flush_interval
        self._followups = followups
        self._stopping = False
        # 收尾途中点了停止的运行（积压小问题 B9）：这时停不下写库，只是不再用插话接着发起下一轮
        self._stop_requested: set[UUID] = set()
        self._finalizing: set[asyncio.Task[None]] = set()
        # 同一运行的"恢复"与"停止"排队进行：两者都要先读状态再改，交错时会出现
        # "显示已停止、恢复的那段却照常跑完"（没人持有时锁自动释放，不会越积越多）
        self._transitions: WeakValueDictionary[UUID, asyncio.Lock] = WeakValueDictionary()
        # 每个运行一个插话队列（设计 2026-10-23 6.3）：建运行时建，审批暂停后恢复时沿用，结束时关上
        self._interjections: dict[UUID, Interjections] = {}

    async def start(self, thread_id: UUID, body: RunCreate) -> RunRecord:
        """发起一次运行并立即返回；运行在后台进行。"""
        thread = await self._threads.get(thread_id)
        attachments = [await self._attachment(thread.id, file_id) for file_id in body.attachments]
        # 模型与审批权限都取会话上的：会话设置只在会话上改（D23）
        run = await self._runs.create(
            thread_id=thread.id,
            model=thread.model,
            message=body.message,
            attachments=attachments,
            permission=thread.permission_mode,
        )
        self._launch(run, thread.short_id)
        try:
            await self._threads.touch(thread.id, first_message=body.message)
        except Exception:  # 运行已经发起：记账失败不能让调用方以为没发起（审查 Minor 8）
            logger.exception("会话 %s 的更新时间没能刷新", thread.id)
        return run

    async def retry(self, run_id: UUID) -> RunRecord:
        """ "重试这一轮"（D26，设计 2026-10-23 4.5）：用同样的原文与附件、会话当前的模型与权限，
        从这次运行之前的对话存档分叉重跑。

        只能用在会话里最近一次、失败或停止的运行上；这一轮做过有副作用的操作（运行命令、写文件、
        记记忆等）时不能重试——重跑多半会再做一遍，只能说"继续"。连点、两个标签页同时点只生效一次。
        能否重试以收尾时记下的为准（报错卡片照它给按钮），不在这时重新判断。
        """
        async with self._transition(run_id):
            run = await self._runs.get(run_id)
            if run.status not in ("failed", "cancelled"):
                raise ConflictError("只能重试失败或停止的运行")
            latest = await self._runs.latest(run.thread_id)
            if latest is None or latest.id != run.id:
                raise ConflictError("只能重试会话里最近的一轮")
            stored = await self._runs.events(run.id)
            if not stored or stored[-1].type != "run.finished":
                raise ConflictError(
                    "这一轮没有正常结束（服务中途退出），不知道做到了哪一步，不能重试；"
                    "可以说“继续”接着做"
                )
            if not stored[-1].data.get("retryable"):
                raise ConflictError(
                    "这一轮已经执行过会改动东西的操作（运行命令、写文件、记记忆等），不能重试；"
                    "可以说“继续”接着做"
                )
            thread = await self._threads.get(run.thread_id)
            retried = await self._runs.create(
                thread_id=thread.id,
                model=thread.model,
                message=run.message,
                attachments=run.attachments,
                permission=thread.permission_mode,
                retry_of=run.id,
            )
            self._launch(retried, thread.short_id)
        await self._threads.touch(thread.id, first_message=run.message)
        return retried

    def _launch(self, run: RunRecord, thread_short_id: str) -> None:
        """建好运行就立即登记后台任务（中间没有等待）：停止请求不会碰上"运行中却没有任务"的空档。"""
        self._interjections[run.id] = Interjections()
        self._bus.open(str(run.id))
        self._control.track(str(run.id), asyncio.create_task(self._execute(run, thread_short_id)))

    async def resume(self, run_id: UUID, body: ResumeRequest) -> RunRecord:
        """按用户的审批决定让等待审批的运行接着跑（设计文档 10.5）；结果随推送到达。

        事件序号接着暂停前的往下编。重复提交（连点、两个标签页）只有一次生效，其余得到 409。
        """
        async with self._transition(run_id):
            # 之前那一段收尾时的停止请求已经处理过了，不管到新的这一段（审查 Minor 4）
            self._stop_requested.discard(run_id)
            run = await self._runs.get(run_id)
            stored = await self._runs.events(run_id)
            if run.status != "interrupted" or not stored or stored[-1].type != "approval.required":
                raise ConflictError("这次运行没有在等待审批")
            await self._agent.check_answers(
                thread_id=str(run.thread_id),
                model=run.model,
                answers=body.answers,
                tools_version=str(stored[-1].data.get("tools_version", "")),
                permission=run.permission,
            )
            thread = await self._threads.get(run.thread_id)
            totals = await self._runs.usage_totals(run_id)
            if not await self._runs.mark_resumed(run_id):
                raise ConflictError("这次审批已经提交过了")
            key = str(run_id)
            # 改回运行中之后立即重新打开推送、登记后台任务（中间没有等待），同 start；
            # 插话队列沿用暂停前的（进程重启过就新建一个）
            self._interjections.setdefault(run_id, Interjections())
            self._bus.open(key)
            task = self._execute(
                run,
                thread.short_id,
                answers=body.answers,
                prior=stored,
                totals=totals,
            )
            self._control.track(key, asyncio.create_task(task))
        return await self._runs.get(run_id)

    async def interject(self, run_id: UUID, message: str) -> None:
        """运行中插话（设计 2026-10-23 6.3）：放进这次运行的队列，主智能体下一次调用模型前送达。

        等审批时不行（先处理卡片）；运行已经结束（队列已关上）时也不行。
        """
        run = await self._runs.get(run_id)
        if run.status == "interrupted":
            raise ConflictError("正在等你审批：先处理上面的审批卡片，再插话")
        queue = self._interjections.get(run_id)
        if run.status not in ("queued", "running") or queue is None or not queue.put(message):
            raise ConflictError("这一轮已经结束，插话没送达：请重新发送")

    @asynccontextmanager
    async def _transition(self, run_id: UUID) -> AsyncIterator[None]:
        lock = self._transitions.get(run_id)
        if lock is None:
            lock = self._transitions[run_id] = asyncio.Lock()
        async with lock:
            yield

    async def cancel(self, run_id: UUID) -> RunRecord:
        """请求停止一次运行；结果（run.finished: cancelled）随推送到达。"""
        async with self._transition(run_id):
            return await self._cancel(run_id)

    async def _cancel(self, run_id: UUID) -> RunRecord:
        run = await self._runs.get(run_id)
        if run.status not in _ACTIVE:
            raise ConflictError("运行已结束，无需停止")
        if self._control.cancel(str(run_id)):
            self._stop_requested.add(run_id)
            return run
        # 没有后台任务。先再读一次：停止请求可能恰好碰上收尾——读到"运行中"时任务已写完结果
        run = await self._runs.get(run_id)
        if run.status not in _ACTIVE:
            raise ConflictError("运行已结束，无需停止")
        # 等待审批的运行，或收尾写库失败而卡住的运行：直接记为已取消
        await self._finish_idle(run)
        return run

    async def delete_thread(self, thread_id: UUID) -> None:
        """删除会话及其全部内容：对话存档、工作区目录与文件登记、运行、界面历史；
        用量记录保留（用量统计不受影响）。

        有进行中的运行时拒绝，需先停止。先删对话存档再删会话：中途失败时会话仍在列表里，可以重试。
        """
        thread = await self._threads.get(thread_id)
        if await self._runs.has_active(thread_id):
            raise ConflictError("会话正在运行，请先停止")
        await self._agent.delete_thread(str(thread_id), thread.short_id)
        await self._files.delete_for_thread(thread_id)
        await self._threads.delete(thread_id)
        # 写索引的后台任务可能恰好在上面删过索引之后写进一行（审查 Minor 4）：会话删掉后再删一次
        if self._agent.conversations is not None:
            await self._agent.conversations.delete_thread(thread_id)

    async def shutdown(self) -> None:
        """服务停止时调用：中断进行中的运行，并等它们把结果写入数据库。"""
        self._stopping = True
        await self._control.cancel_all()
        await asyncio.gather(*self._finalizing, return_exceptions=True)

    async def stream(self, run_id: UUID, *, after_seq: int = 0) -> AsyncIterator[EventEnvelope]:
        """推送某次运行在 after_seq 之后的事件：运行还在内存中则实时推送，否则从界面历史补发。"""
        key = str(run_id)
        if self._bus.has(key):
            # 恢复审批后总线从恢复的这一段重来（open 清空了暂停前的），暂停前那段在库里：库里只补发
            # 这一段开始之前的，这一段的全部从总线取（积压小问题 E9）。拼接点不能取库里的最后一个：
            # 结束事件推给页面的那份才带下一轮的编号、退回的插话（第三批审查 Important 1）。
            # 没暂停过的运行这一段从 1 开始，等于只看总线
            start = self._bus.first_seq(key)
            sent = after_seq
            for event in await self._runs.events(run_id, after_seq=after_seq):
                if start is not None and event.seq >= start:
                    break
                yield event
                sent = event.seq
            async for event in self._bus.subscribe(key, sent):
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
                # 进程中途退出（重启）：算"被打断"；不知道中断前做过什么，只给"继续"（D26）
                ending = RunFinished(
                    status="failed",
                    error=run.error or "运行未正常结束",
                    error_kind="interrupted",
                )
                seq = max(after_seq, stored[-1].seq if stored else 0) + 1
                # 时间取最后一个已存事件（没有则取运行创建时间），耗时只算到中断前
                ts = stored[-1].ts if stored else run.created_at
                yield EventEnvelope.wrap(ending, seq=seq, run_id=key, ts=ts)

    async def _execute(
        self,
        run: RunRecord,
        thread_short_id: str,
        *,
        answers: Sequence[ApprovalAnswer] | None = None,
        prior: Sequence[EventEnvelope] = (),
        totals: UsageTotals | None = None,
    ) -> None:
        """执行一段运行：新的一轮，或带着审批决定（answers）从暂停处恢复。

        恢复时 prior 是已存的事件（新事件的序号接着最后一个往下编：合并过的事件序号不连续，
        不能按条数算），totals 是已记下的用量合计。
        """
        run_id = str(run.id)
        base_seq = prior[-1].seq if prior else 0
        published: list[EventEnvelope] = []
        background = _Background()
        totals = totals or UsageTotals()
        finished = RunFinished(status="failed", error="运行意外中止")
        paused = False
        writer = EventWriter(self._runs, run.id, interval=self._flush_interval, prior=prior)
        writer.start()
        try:
            async for event in self._agent_events(run, thread_short_id, answers):
                if isinstance(event, ApprovalRequired):
                    paused = True  # 智能体随后结束这一段，不发 run.finished
                if isinstance(event, RunFinished):
                    finished = event  # 先落库、后推送，保证前端收到时数据库已是最终状态
                    continue
                if isinstance(event, UsageReported):
                    totals = totals.add(event)
                pushed = self._record_later(run, event, background)
                envelope = await self._publish(run_id, pushed, seq=base_seq + len(published) + 1)
                published.append(envelope)
                writer.add(envelope)
        except asyncio.CancelledError:
            paused = False  # 停止（或停机）总以结束事件收尾
            finished = self._stopped(run_id)
            raise
        finally:
            writes = background.all()
            if paused:
                finalizing = _spawn(self._finalize_pause(run, writer, writes, published, totals))
            else:
                finished, continue_with = self._wrap_up(run, finished, [*prior, *published], totals)
                tail = EventEnvelope.wrap(
                    finished, seq=base_seq + len(published) + 1, run_id=run_id
                )
                # 收尾单独成任务并挡住取消：连点停止、回答刚结束时点停止、停机时再次取消，
                # 都不能打断写库，否则运行会一直停在"运行中"，会话被卡住（409）
                finalizing = _spawn(
                    self._finalize(
                        run,
                        writer,
                        writes,
                        [*published, tail],
                        finished,
                        totals,
                        continue_with,
                        short_id=thread_short_id,
                    )
                )
            self._finalizing.add(finalizing)
            finalizing.add_done_callback(self._finalizing.discard)
            try:
                await asyncio.shield(finalizing)
            except asyncio.CancelledError:
                if paused:
                    # 停止请求落在暂停收尾期间（approval.required 已推送、还没记为等待审批）：
                    # 收尾完成后按"等待审批时停止"结束，否则这次停止就被吞掉了
                    await asyncio.shield(self._stop_after_pause(run, finalizing))
                raise

    def _agent_events(
        self,
        run: RunRecord,
        thread_short_id: str,
        answers: Sequence[ApprovalAnswer] | None,
    ) -> AsyncIterator[Event]:
        """新的一轮交给智能体运行；带着审批决定时从暂停处恢复。"""
        interjections = self._interjections.get(run.id)
        if answers is None:
            return self._agent.run(
                thread_id=str(run.thread_id),
                thread_short_id=thread_short_id,
                run_id=str(run.id),
                message=run.message,
                model=run.model,
                attachments=[Attachment(a.path, a.media_type, a.size) for a in run.attachments],
                permission=run.permission,
                retry_of=str(run.retry_of) if run.retry_of else None,
                interjections=interjections,
            )
        return self._agent.resume(
            thread_id=str(run.thread_id),
            thread_short_id=thread_short_id,
            run_id=str(run.id),
            model=run.model,
            message=run.message,
            answers=answers,
            permission=run.permission,
            interjections=interjections,
        )

    def _record_later(self, run: RunRecord, event: Event, background: "_Background") -> Event:
        """用量、工具用量、产物登记都在后台写，返回要推送的事件（产物带上文件 ID）。

        处理事件的循环里不能有真正的等待：停止才总是落在智能体内部，由它把已输出的回答存进
        对话存档（落在这里则存档会丢掉刚完成的那次回答）。收尾前等这些都写完。
        """
        if isinstance(event, UsageReported):
            previous = background.usage[-1] if background.usage else None
            background.usage.append(_spawn(self._record_usage(run, event, after=previous)))
        if isinstance(event, ToolRunning) and event.name:
            # 工具与技能用量（设计 2026-10-23 6.8）
            background.other.append(_spawn(self._record_tool(run, event.name, event.skill)))
        if isinstance(event, SubagentStarted):
            # 派出子智能体记一次 task（积压小问题 B12）：这个事件来自主智能体的模型输出，
            # 每次派出只有一次；task 本身恢复审批时会再执行，不按它记
            background.other.append(_spawn(self._record_tool(run, "task", None)))
        if isinstance(event, FileCreated):
            # 文件 ID 由会话与路径算出，不必等登记：推送立即带上 ID
            file_id = workspace_file_id(run.thread_id, event.path)
            event = event.model_copy(update={"file_id": str(file_id)})
            background.other.append(_spawn(self._record_file(run, event)))
        return event

    def _stopped(self, run_id: str) -> RunFinished:
        """停止或停机时的结束事件；被中断那次模型调用的估算用量随它显示，不写用量表、不计入合计。"""
        estimate = self._agent.take_interrupted_usage(run_id)
        if self._stopping:
            return RunFinished(
                status="failed",
                error=STOPPED_BY_SHUTDOWN,
                error_kind="interrupted",
                interrupted_usage=estimate,
            )
        return RunFinished(status="cancelled", interrupted_usage=estimate)

    def _wrap_up(
        self,
        run: RunRecord,
        finished: RunFinished,
        events: Sequence[EventEnvelope],
        totals: UsageTotals,
    ) -> tuple[RunFinished, list[str]]:
        """定下结束事件，并给出要接着发起下一轮的插话。

        关上插话队列（之后到的插话一律 409）：没送达的，顺利结束时接着发起下一轮，失败、被停时
        退回给界面放回输入框（设计 2026-10-23 6.3）。能否"重试这一轮"（D26）：审批暂停之前那段
        里开始的调用也算（events 含 prior）。
        """
        queue = self._interjections.pop(run.id, None)
        leftover = queue.close() if queue is not None else []
        continue_with: list[str] = []
        if leftover and finished.status == "completed" and not self._stopping:
            continue_with = leftover
        elif leftover:
            finished = finished.model_copy(update={"undelivered": leftover})
        retryable = finished.status != "completed" and self._retryable(events)
        return finished.model_copy(update={"usage": totals, "retryable": retryable}), continue_with

    def _retryable(self, events: Sequence[EventEnvelope]) -> bool:
        """这次运行能否"重试这一轮"：没有开始过有副作用的调用。判断出错时按不能重试处理——
        这里在收尾之前，抛出去会让运行一直停在"运行中"、会话被卡住。"""
        if any(event.type == "user.interjected" for event in events):
            return False  # 送达过插话：重跑会丢掉插话（设计 2026-10-23 6.3），只给"继续"
        try:
            return not self._agent.has_side_effects(_started_tools(events))
        except Exception:  # 收尾边界：判断不了就只给"继续"
            logger.exception("判断运行有没有副作用时出错，按不能重试处理")
            return False

    async def _finalize(
        self,
        run: RunRecord,
        writer: EventWriter,
        writes: list[asyncio.Task[None]],
        events: list[EventEnvelope],
        finished: RunFinished,
        totals: UsageTotals,
        continue_with: Sequence[str] = (),
        *,
        short_id: str,
    ) -> None:
        run_id = str(run.id)
        try:
            # 前端收到结束事件后会查用量、下载产物，此时须已写完
            await asyncio.gather(*writes)
            if finished.status != "completed":
                await self._register_outputs(run, short_id, events)
            await writer.finish(events)
            await self._runs.finish(
                run.id, status=finished.status, error=finished.error, usage=totals
            )
        except Exception:  # 后台任务边界：落库失败也必须结束推送，并留下日志
            logger.exception("运行 %s 的结果写入数据库失败", run_id)
            if continue_with:  # 发不起下一轮（这一轮没记成结束）：插话退回界面（审查 Minor 7）
                data = {**events[-1].data, "undelivered": list(continue_with)}
                events[-1] = events[-1].model_copy(update={"data": data})
        else:
            if self._followups is not None:
                try:
                    # 在推送结束事件之前登记：前端收到结束事件时，后续任务已经在队列里
                    if finished.status == "completed":
                        await self._followups.after_completed(run)
                    await self._followups.after_finished(run)
                except Exception:  # 后台任务边界：登记失败只是少了后续任务，不影响这次运行
                    logger.exception("运行 %s 的后续任务登记失败", run_id)
            if continue_with:
                events[-1] = await self._continue(run, events[-1], continue_with)
        finally:
            self._stop_requested.discard(run.id)
            await self._bus.publish(run_id, events[-1])
            await self._bus.close(run_id)

    async def _register_outputs(
        self, run: RunRecord, short_id: str, events: list[EventEnvelope]
    ) -> None:
        """停止、失败的运行：outputs/ 里还没登记的文件照常登记，结束事件之前补推 file.created
        （命令写好文件后卡住被停时，智能体来不及发现它们，积压小问题 D1）。
        结束事件的序号往后顺延。"""
        try:
            outputs = await self._agent.workspace.list_outputs(short_id)
            known = {record.path for record in await self._files.for_thread(run.thread_id)}
        except Exception:  # 收尾边界：只是少登记几个产物，不能挡住收尾
            logger.exception("运行 %s 收尾时列不出产物", run.id)
            return
        tail = events[-1]
        seq = tail.seq
        added: list[EventEnvelope] = []
        for output in outputs:
            if output.path in known:
                continue
            created = FileCreated(
                path=output.path,
                size=output.size,
                media_type=media_type(output.path),
                file_id=str(workspace_file_id(run.thread_id, output.path)),
            )
            await self._record_file(run, created)
            envelope = EventEnvelope.wrap(created, seq=seq, run_id=str(run.id))
            await self._bus.publish(str(run.id), envelope)
            added.append(envelope)
            seq += 1
        if added:
            events[-1:] = [*added, tail.model_copy(update={"seq": seq})]

    async def _continue(
        self, run: RunRecord, tail: EventEnvelope, texts: Sequence[str]
    ) -> EventEnvelope:
        """顺利结束时还有没送达的插话：用它们接着发起下一轮（这一轮已记为结束，才发得起来），
        推送的结束事件带上下一轮的编号；发不起来就退回给界面。存下的结束事件不带这些：
        下一轮在历史里自己就是一轮。"""
        if self._stopping or run.id in self._stop_requested:
            return await self._give_back(run, tail, texts)
        try:
            following = await self.start(run.thread_id, RunCreate(message="\n".join(texts)))
        except Exception:  # 收尾边界：发不起来只是插话退回输入框
            logger.exception("运行 %s 结束后没能用插话接着发起下一轮", run.id)
            return tail.model_copy(update={"data": {**tail.data, "undelivered": list(texts)}})
        return tail.model_copy(update={"data": {**tail.data, "next_run_id": str(following.id)}})

    async def _give_back(
        self, run: RunRecord, tail: EventEnvelope, texts: Sequence[str]
    ) -> EventEnvelope:
        """收尾途中停机或点了停止（积压小问题 B9）：不再接着发起下一轮，插话退回。也存进历史：
        停机时页面多半已断开，重新打开时显示"没送达"。"""
        returned = tail.model_copy(update={"data": {**tail.data, "undelivered": list(texts)}})
        try:
            await self._runs.update_event(run.id, returned)
        except Exception:  # 收尾边界：存不进去只是重开页面看不到，推送仍带着
            logger.exception("运行 %s 没送达的插话没能存进历史", run.id)
        return returned

    async def _finalize_pause(
        self,
        run: RunRecord,
        writer: EventWriter,
        writes: list[asyncio.Task[None]],
        events: list[EventEnvelope],
        totals: UsageTotals,
    ) -> None:
        """一段运行停在审批处：事件、用量写完后把运行记为等待审批，关闭推送（不登记后续任务）。"""
        try:
            await asyncio.gather(*writes)
            await writer.finish(events)
            await self._runs.pause(run.id, usage=totals)
        except Exception:  # 后台任务边界：落库失败也必须结束推送，并留下日志
            logger.exception("运行 %s 暂停时写入数据库失败", run.id)
        finally:
            await self._bus.close(str(run.id))

    async def _stop_after_pause(self, run: RunRecord, finalizing: asyncio.Task[None]) -> None:
        await asyncio.gather(finalizing, return_exceptions=True)
        async with self._transition(run.id):
            current = await self._runs.get(run.id)
            if current.status == "interrupted":  # 期间没有被恢复（恢复也要先拿到这把锁）
                await self._finish_idle(current)

    async def _finish_idle(self, run: RunRecord) -> None:
        """结束一个没有后台任务的运行：结束事件存进界面历史并推送，关闭推送。

        等待审批时停止的运行，暂停前记下的用量保留。
        """
        run_id = str(run.id)
        self._stop_requested.discard(run.id)  # 这次运行到此结束（审查 Minor 4）
        stored = await self._runs.events(run.id)
        totals = await self._runs.usage_totals(run.id)
        queue = self._interjections.pop(run.id, None)
        leftover = queue.close() if queue is not None else []
        finished = RunFinished(status="cancelled", usage=totals, undelivered=leftover)
        tail = EventEnvelope.wrap(
            finished, seq=(stored[-1].seq if stored else 0) + 1, run_id=run_id
        )
        await self._runs.add_events(run.id, [tail])
        await self._runs.finish(run.id, status="cancelled", error=None, usage=totals)
        if self._followups is not None:
            try:
                await self._followups.after_finished(run)
            except Exception:  # 后台任务边界：只是少了会话索引
                logger.exception("运行 %s 的后续任务登记失败", run_id)
        if self._bus.has(run_id):
            await self._bus.publish(run_id, tail)
            await self._bus.close(run_id)

    async def _record_usage(
        self, run: RunRecord, usage: UsageReported, *, after: asyncio.Task[None] | None
    ) -> None:
        """等上一条写完再写（明细按写入时间排列，须与调用顺序一致）。写库失败不影响运行，只留日志。"""
        if after is not None:
            await asyncio.wait({after})
        try:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)
        except Exception:  # 后台任务边界：用量记录失败不能中断对话
            logger.exception("运行 %s 的用量写入数据库失败", run.id)

    async def _record_tool(self, run: RunRecord, tool: str, skill: str | None) -> None:
        """记一次工具用量。写库失败不影响运行，只留日志。"""
        try:
            await self._usage.add_tool_use(
                thread_id=run.thread_id, run_id=run.id, tool=tool, skill=skill
            )
        except Exception:  # 后台任务边界：用量记录失败不能中断对话
            logger.exception("运行 %s 的工具用量写入数据库失败", run.id)

    async def _attachment(self, thread_id: UUID, file_id: UUID) -> RunAttachment:
        """消息附带的文件必须是本会话登记过的文件。"""
        record = await self._files.get(file_id)
        if record.thread_id != thread_id:
            raise NotFoundError(f"附件不存在：{file_id}")
        return RunAttachment(
            id=record.id, path=record.path, media_type=record.media_type, size=record.size
        )

    async def _record_file(self, run: RunRecord, event: FileCreated) -> None:
        """登记一个产物文件。写库失败不影响运行，只留日志（该文件暂时无法下载）。"""
        try:
            await self._files.record(
                run.thread_id,
                event.path,
                source="output",
                size=event.size,
                media_type=event.media_type,
            )
        except Exception:  # 后台任务边界：登记失败不能中断对话
            logger.exception("运行 %s 的产物 %s 登记失败", run.id, event.path)

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
        envelope = EventEnvelope.wrap(event, seq=seq, run_id=run_id)
        await self._bus.publish(run_id, envelope)
        return envelope


def _spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """收尾与后台写库的任务：不带这次运行的调用归属（积压小问题 G2，它们只写库、不调模型）。"""
    return asyncio.create_task(coro, context=detached_context())


def _started_tools(events: Sequence[EventEnvelope]) -> list[str]:
    """一次运行里开始过的工具调用（含子智能体内部的）。"""
    return [str(event.data.get("name", "")) for event in events if event.type == "tool.started"]


@dataclass
class _Background:
    """一段运行里放到后台写库的任务：用量要按调用顺序写（单独一串），其余的随便。"""

    usage: list[asyncio.Task[None]] = field(default_factory=list)
    other: list[asyncio.Task[None]] = field(default_factory=list)

    def all(self) -> list[asyncio.Task[None]]:
        return [*self.usage, *self.other]
