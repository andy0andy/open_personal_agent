"""插话队列（设计 2026-10-23 6.3）：运行中用户说的话先排在这里，主智能体下一次调用模型前送达。

后端每个运行一个：建运行时建，审批暂停后恢复时沿用，运行结束时关上并取回没送达的。
只在一个事件循环里用，操作都是同步的，不会交错。
"""


class Interjections:
    def __init__(self) -> None:
        self._pending: list[str] = []
        self._closed = False

    @property
    def pending(self) -> int:
        return len(self._pending)

    def put(self, text: str) -> bool:
        """排上一句；已关上（运行结束了）时返回 False。"""
        if self._closed:
            return False
        self._pending.append(text)
        return True

    def take(self) -> list[str]:
        """取走目前排着的全部。"""
        taken, self._pending = self._pending, []
        return taken

    def close(self) -> list[str]:
        """关上并取回没送达的（运行结束时）。"""
        self._closed = True
        return self.take()
