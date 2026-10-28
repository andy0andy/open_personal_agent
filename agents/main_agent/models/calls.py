"""调用归属：接下来的模型调用属于哪个会话、哪次运行（设计文档 7.1：花费按会话归类）。

与网关无关：智能体的每段运行、标题生成、记忆提取都在 call_context 里进行，网关实现
（如 LiteLLM）据此给请求打上会话与运行的标签，在网关后台就能按会话核对每一次调用。
用上下文变量传递：LangGraph 在运行里新建的任务会复制它，子智能体、上下文压缩的调用也带得上。
"""

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass


@dataclass(frozen=True)
class CallContext:
    thread_id: str
    run_id: str | None  # 不属于某次运行时为空（如文档入库时的向量化）


_CURRENT: ContextVar[CallContext | None] = ContextVar("current_call", default=None)


@contextmanager
def call_context(thread_id: str, run_id: str | None) -> Iterator[None]:
    """在其中发起的模型调用都属于这个会话与运行。"""
    token = _CURRENT.set(CallContext(thread_id, run_id))
    try:
        yield
    finally:
        # 用在异步生成器里时，生成器可能在别的上下文里被关闭（如被垃圾回收），
        # 此时无法复原；那个上下文随之丢弃，不影响别处
        with suppress(ValueError):
            _CURRENT.reset(token)


def current_call() -> CallContext | None:
    return _CURRENT.get()


def detached_context() -> Context:
    """当前上下文的副本，只去掉调用归属：在运行里另开的后台写库任务用它，它们只写库、
    不调模型，不该算在这次运行的调用里（积压小问题 G2）。"""
    context = copy_context()
    context.run(_CURRENT.set, None)
    return context
