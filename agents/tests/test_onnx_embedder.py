"""进程内的向量化实现（D28）：按用途加前缀、归一化、懒加载、分批、出错时给出看得懂的原因。

这里都用注入的假运行时，不加载真模型（真模型的测试在 live/test_onnx_embedding.py）。
"""

import asyncio
import gc
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from agents.main_agent.models import (
    EMBEDDING_DIMENSIONS,
    ONNX_MODELS,
    EmbeddingUsage,
    OnnxEmbedder,
    OnnxModelSpec,
    OnnxRuntime,
    files_ready,
)
from common.errors import UpstreamError

SPEC = ONNX_MODELS["embeddinggemma-300m-q4"]


class _Runtime:
    """假的"加载好的模型"：每段文字给同一个向量，记下收到的文字。"""

    def __init__(self, vector: Sequence[float] | None = None, *, delay: float = 0) -> None:
        self.vector = list(vector or [3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2))
        self.delay = delay
        self.batches: list[list[str]] = []

    def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
        if self.delay:
            time.sleep(self.delay)  # 允许等待：替身模拟模型算得慢
        self.batches.append(list(texts))
        return [list(self.vector) for _ in texts], 7 * len(texts)


def _model_dir(tmp_path: Path, spec: OnnxModelSpec = SPEC) -> Path:
    """按规格里的字节数造出占位文件（只看在不在、大小对不对，内容不读）。"""
    for name, file in spec.files.items():
        with (tmp_path / name).open("wb") as handle:
            handle.truncate(file.size)
    return tmp_path


def _embedder(
    tmp_path: Path, runtime: OnnxRuntime, **options: object
) -> tuple[OnnxEmbedder, list[Path]]:
    loads: list[Path] = []

    def load(model_dir: Path, spec: OnnxModelSpec) -> OnnxRuntime:
        loads.append(model_dir)
        return runtime

    embedder = OnnxEmbedder(_model_dir(tmp_path), SPEC, load=load, **options)  # type: ignore[arg-type]
    return embedder, loads


async def test_prefixes_by_kind_and_normalizes(tmp_path: Path) -> None:
    runtime = _Runtime()
    embedder, _ = _embedder(tmp_path, runtime)
    [query] = await embedder.embed(["我住在哪"], kind="query")
    await embedder.embed(["用户常住上海"])
    assert runtime.batches == [
        ["task: search result | query: 我住在哪"],
        ["title: none | text: 用户常住上海"],
    ]
    assert query[:2] == pytest.approx([0.6, 0.8])  # 长度归一化：相似度才能直接比
    assert len(query) == EMBEDDING_DIMENSIONS
    assert embedder.model == "embeddinggemma-300m-q4"


async def test_loads_lazily_and_only_once(tmp_path: Path) -> None:
    embedder, loads = _embedder(tmp_path, _Runtime())
    assert loads == []  # 构造时不加载：启动快，没人用知识库就不占内存
    await asyncio.gather(embedder.embed(["a"]), embedder.embed(["b"]))
    await embedder.embed(["c"])
    assert len(loads) == 1


async def test_batches_in_order(tmp_path: Path) -> None:
    runtime = _Runtime()
    embedder, _ = _embedder(tmp_path, runtime, batch_size=2)
    vectors = await embedder.embed(["1", "2", "3", "4", "5"])
    assert [len(batch) for batch in runtime.batches] == [2, 2, 1]
    assert [batch[0][-1] for batch in runtime.batches] == ["1", "3", "5"]
    assert len(vectors) == 5


async def test_empty_input_does_not_load(tmp_path: Path) -> None:
    embedder, loads = _embedder(tmp_path, _Runtime())
    assert await embedder.embed([]) == []
    assert loads == []


async def test_missing_files_raise_upstream_error(tmp_path: Path) -> None:
    """模型还在下载（或没联网）：给一句看得懂的原因；文件到位后同一个对象直接能用，不用重启。"""
    runtime = _Runtime()
    embedder = OnnxEmbedder(tmp_path, SPEC, load=lambda _dir, _spec: runtime)
    assert not files_ready(tmp_path, SPEC)
    with pytest.raises(UpstreamError, match="向量模型还没下载好"):
        await embedder.embed(["a"])
    _model_dir(tmp_path)
    assert files_ready(tmp_path, SPEC)
    assert len(await embedder.embed(["a"])) == 1


def test_files_with_wrong_size_are_not_ready(tmp_path: Path) -> None:
    _model_dir(tmp_path)
    (tmp_path / "tokenizer.json").write_bytes(b"{}")  # 下到一半或被改过
    assert not files_ready(tmp_path, SPEC)


async def test_runtime_error_becomes_upstream_error(tmp_path: Path) -> None:
    class Broken(_Runtime):
        def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
            raise RuntimeError("onnxruntime: bad input")

    embedder, _ = _embedder(tmp_path, Broken())
    with pytest.raises(UpstreamError, match="向量化服务不可用：向量模型运行出错"):
        await embedder.embed(["a"])


async def test_load_error_becomes_upstream_error(tmp_path: Path) -> None:
    def load(model_dir: Path, spec: OnnxModelSpec) -> _Runtime:
        raise RuntimeError("invalid protobuf")

    embedder = OnnxEmbedder(_model_dir(tmp_path), SPEC, load=load)
    with pytest.raises(UpstreamError, match="向量化服务不可用：向量模型加载不了"):
        await embedder.embed(["a"])


async def test_wrong_dimensions_rejected(tmp_path: Path) -> None:
    embedder, _ = _embedder(tmp_path, _Runtime([1.0] * 5))
    with pytest.raises(UpstreamError, match="向量维度应为 768，实际为 5"):
        await embedder.embed(["a"])


async def test_reports_usage(tmp_path: Path) -> None:
    seen: list[EmbeddingUsage] = []

    async def record(usage: EmbeddingUsage) -> None:
        seen.append(usage)
        raise RuntimeError("用量表写不进去")  # 用量记录失败不能影响向量化本身

    embedder, _ = _embedder(tmp_path, _Runtime(), batch_size=2, on_usage=record)
    assert len(await embedder.embed(["1", "2", "3"])) == 3
    [usage] = seen  # 一次调用报一次，token 是各批的合计
    assert (usage.model, usage.input_tokens) == ("embeddinggemma-300m-q4", 21)
    assert usage.duration_ms >= 0


async def test_does_not_block_the_event_loop(tmp_path: Path) -> None:
    """模型计算是纯 CPU 的同步调用：要放到线程里，入库时对话的流式输出才不会卡住。"""
    embedder, _ = _embedder(tmp_path, _Runtime(delay=0.3))
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)  # 允许等待：计数用的节拍，看事件循环有没有被挡住
            ticks += 1

    ticking = asyncio.create_task(tick())
    await embedder.embed(["a"])
    ticking.cancel()
    assert ticks >= 10


class _BlockingRuntime:
    """第一批算到一半停住，等测试放行；记下同一时刻最多有几批在算。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.second_started = threading.Event()
        self.peak = 0
        self._guard = threading.Lock()
        self._active = 0
        self._calls = 0

    def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
        with self._guard:
            self._calls += 1
            first = self._calls == 1
            self._active += 1
            self.peak = max(self.peak, self._active)
        if first:
            self.started.set()
            self.release.wait(5)
        else:
            self.second_started.set()
        with self._guard:
            self._active -= 1
        return [[3.0, 4.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2) for _ in texts], 7 * len(texts)


async def test_cancelled_call_keeps_its_turn_until_the_batch_finishes(tmp_path: Path) -> None:
    # 找相关记忆有时限，超时会取消调用；可线程里那一批停不下来，还在占着 CPU。
    # 这时下一批要等它算完，不能并发（并行抢 CPU，两批都更慢）
    runtime = _BlockingRuntime()
    embedder, _ = _embedder(tmp_path, runtime)
    first = asyncio.create_task(embedder.embed(["a"]))
    assert await asyncio.to_thread(runtime.started.wait, 5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(embedder.embed(["b"]))
    assert not await asyncio.to_thread(runtime.second_started.wait, 0.2)  # 第一批没完，不该开始
    runtime.release.set()
    assert len(await second) == 1
    assert runtime.peak == 1


async def test_cancelled_call_does_not_leave_an_unretrieved_error(tmp_path: Path) -> None:
    # 调用方已经取消、没人等结果时这一批才出错：错误要被取走，不能留下"异常没人处理"的警告
    class _Failing(_BlockingRuntime):
        def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
            super().encode(texts)
            raise RuntimeError("boom")

    runtime = _Failing()
    embedder, _ = _embedder(tmp_path, runtime)
    unhandled: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _, context: unhandled.append(context))
    try:
        first = asyncio.create_task(embedder.embed(["a"]))
        assert await asyncio.to_thread(runtime.started.wait, 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        runtime.release.set()
        with pytest.raises(UpstreamError):  # 下一次调用照常：先等上一批收尾，再算自己的
            await embedder.embed(["b"])
        gc.collect()  # 没人取走的异常要等任务被回收时才报
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(None)
    assert unhandled == []


def test_gemma_spec_matches_the_decision() -> None:
    """固定的仓库、提交、文件哈希（D28）：下载后按它校验，换了任何一项都要重新验证效果。"""
    assert SPEC.name == "embeddinggemma-300m-q4"
    assert SPEC.repo == "onnx-community/embeddinggemma-300m-ONNX"
    assert SPEC.revision == "5090578d9565bb06545b4552f76e6bc2c93e4a66"
    assert {name: (f.path, f.sha256, f.size) for name, f in SPEC.files.items()} == {
        "model_q4.onnx": (
            "onnx/model_q4.onnx",
            "ad1dfee81a70f7944b9b9d1cc6e48075b832881cf33fab2f2b248be78f3f0043",
            519322,
        ),
        "model_q4.onnx_data": (
            "onnx/model_q4.onnx_data",
            "599962c3143b040de2dd05e5975be3e9091dd067cacc6a8f7186e3203bab9e02",
            196725760,
        ),
        "tokenizer.json": (
            "tokenizer.json",
            "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47",
            20323312,
        ),
    }
    assert SPEC.model_file == "model_q4.onnx"
    assert (SPEC.dimensions, SPEC.max_tokens) == (EMBEDDING_DIMENSIONS, 2048)
    assert SPEC.query_prefix == "task: search result | query: "
    assert SPEC.document_prefix == "title: none | text: "
    assert SPEC.output == "sentence_embedding"
