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
        task.add_done_callback(lambda done: self._forget(run_id, done))

    def _forget(self, run_id: str, task: asyncio.Task[None]) -> None:
        # 审批后恢复时同一运行会登记新任务：暂停那一段的任务晚一点结束，不能注销新任务
        if self._tasks.get(run_id) is task:
            del self._tasks[run_id]

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        _cancel_once(task)
        return True

    async def cancel_all(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            _cancel_once(task)
        await asyncio.gather(*tasks, return_exceptions=True)


def _cancel_once(task: asyncio.Task[None]) -> None:
    """已在取消中（连点停止、停止后紧接着服务停止）就不再打断：第二次取消会打断它的收尾，
    例如把已输出的回答写进对话存档。"""
    if not task.cancelling():
        task.cancel()
