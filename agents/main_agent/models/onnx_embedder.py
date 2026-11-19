"""进程内的向量化实现（D28）：在后端进程里用 ONNX Runtime 跑向量模型，不经网关、不出本机。

模型文件在 `.workdata/models/<模型名>/`，由 onnx_download.py 下载并校验；这里只管加载和计算。
第一次用到时才加载（启动快，加载后常驻内存）；计算是纯 CPU 的同步调用，放到线程里做，
同一时刻只算一批（并行抢 CPU 没有好处）。onnxruntime、tokenizers 只在这个文件里导入。
"""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agents.main_agent.models.embedding import EMBEDDING_DIMENSIONS, EmbeddingUsage, EmbedKind
from common.errors import UpstreamError

logger = logging.getLogger(__name__)

TOKENIZER_FILE = "tokenizer.json"
_PAD = "<pad>"


@dataclass(frozen=True)
class OnnxModelFile:
    path: str  # 仓库内路径
    sha256: str
    size: int  # 字节数：判断"下好了没有"只看它（算哈希要读完整个文件，留给下载时做）


@dataclass(frozen=True)
class OnnxModelSpec:
    """一个向量模型的固定信息：从哪下、哪几个文件、怎么用。"""

    name: str
    repo: str
    revision: str
    files: Mapping[str, OnnxModelFile]  # 键：本地文件名
    model_file: str  # files 里哪个是模型入口
    dimensions: int
    max_tokens: int
    query_prefix: str
    document_prefix: str
    output: str  # 取模型的哪个输出


# 仓库、提交、哈希都固定（D28）：换了任何一项都要重新验证检索效果
ONNX_MODELS: dict[str, OnnxModelSpec] = {
    "embeddinggemma-300m-q4": OnnxModelSpec(
        name="embeddinggemma-300m-q4",
        repo="onnx-community/embeddinggemma-300m-ONNX",
        revision="5090578d9565bb06545b4552f76e6bc2c93e4a66",
        files={
            "model_q4.onnx": OnnxModelFile(
                "onnx/model_q4.onnx",
                "ad1dfee81a70f7944b9b9d1cc6e48075b832881cf33fab2f2b248be78f3f0043",
                519322,
            ),
            "model_q4.onnx_data": OnnxModelFile(
                "onnx/model_q4.onnx_data",
                "599962c3143b040de2dd05e5975be3e9091dd067cacc6a8f7186e3203bab9e02",
                196725760,
            ),
            TOKENIZER_FILE: OnnxModelFile(
                "tokenizer.json",
                "4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47",
                20323312,
            ),
        },
        model_file="model_q4.onnx",
        dimensions=EMBEDDING_DIMENSIONS,
        max_tokens=2048,
        # 模型训练时查询和文档各带各的前缀，照着加检索效果才对
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        output="sentence_embedding",
    ),
}


class OnnxRuntime(Protocol):
    """加载好的模型。"""

    def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
        """返回每段文字的向量（未归一化）和这批一共多少 token。"""
        ...


type Loader = Callable[[Path, OnnxModelSpec], OnnxRuntime]


def files_ready(model_dir: Path, spec: OnnxModelSpec) -> bool:
    """每个文件都在、字节数也对（下载是先写临时文件再改名，不会出现半个文件）。"""
    for name, file in spec.files.items():
        try:
            if (model_dir / name).stat().st_size != file.size:
                return False
        except OSError:
            return False
    return True


class _Session:
    """真实的运行时：分词 + ONNX Runtime（只用 CPU）。"""

    def __init__(self, model_dir: Path, spec: OnnxModelSpec) -> None:
        # 用到时才导入：不用知识库时后端不必加载这两个库
        import numpy
        import onnxruntime
        from tokenizers import Tokenizer

        self._numpy = numpy
        self._tokenizer = Tokenizer.from_file(str(model_dir / TOKENIZER_FILE))
        self._tokenizer.enable_truncation(max_length=spec.max_tokens)
        self._tokenizer.enable_padding(pad_id=self._tokenizer.token_to_id(_PAD), pad_token=_PAD)
        self._session = onnxruntime.InferenceSession(
            str(model_dir / spec.model_file), providers=["CPUExecutionProvider"]
        )
        self._inputs = {item.name for item in self._session.get_inputs()}
        self._output = spec.output

    def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
        encoded = self._tokenizer.encode_batch(list(texts))
        ids = self._numpy.array([item.ids for item in encoded], dtype=self._numpy.int64)
        mask = self._numpy.array([item.attention_mask for item in encoded], dtype=self._numpy.int64)
        feed = {
            name: value
            for name, value in (("input_ids", ids), ("attention_mask", mask))
            if name in self._inputs
        }
        [vectors] = self._session.run([self._output], feed)
        return vectors.tolist(), int(mask.sum())


def _load(model_dir: Path, spec: OnnxModelSpec) -> OnnxRuntime:
    return _Session(model_dir, spec)


class OnnxEmbedder:
    def __init__(
        self,
        model_dir: Path,
        spec: OnnxModelSpec,
        *,
        batch_size: int = 2,
        on_usage: Callable[[EmbeddingUsage], Awaitable[None]] | None = None,
        load: Loader | None = None,
    ) -> None:
        self._model_dir = model_dir
        self._spec = spec
        self._batch_size = batch_size
        self._on_usage = on_usage
        self._load = load or _load  # 仅测试时注入
        self._prefixes: dict[EmbedKind, str] = {
            "query": spec.query_prefix,
            "document": spec.document_prefix,
        }
        self._runtime: OnnxRuntime | None = None
        self._loading: asyncio.Task[OnnxRuntime] | None = None
        self._computing = asyncio.Lock()

    @property
    def model(self) -> str:
        return self._spec.name

    async def embed(
        self, texts: Sequence[str], *, kind: EmbedKind = "document"
    ) -> list[list[float]]:
        if not texts:
            return []
        started = time.monotonic()
        runtime = await self._ready()
        prefixed = [self._prefixes[kind] + text for text in texts]
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(prefixed), self._batch_size):
            batch = prefixed[start : start + self._batch_size]
            computing = asyncio.create_task(self._encode(runtime, batch))
            # 调用方中途被取消（找相关记忆有时限）时没人等这个任务：取走它的异常，不留警告
            computing.add_done_callback(lambda task: task.cancelled() or task.exception())
            # 线程里的计算停不下来：调用方被取消也让这一批占着锁算完，下一批排在它后面
            raw, used = await asyncio.shield(computing)
            vectors.extend(self._normalized(vector) for vector in raw)
            tokens += used
        await self._report(tokens, round((time.monotonic() - started) * 1000))
        return vectors

    async def _encode(
        self, runtime: OnnxRuntime, batch: Sequence[str]
    ) -> tuple[list[list[float]], int]:
        async with self._computing:
            try:
                return await asyncio.to_thread(runtime.encode, batch)
            except Exception as exc:  # 运行库抛什么都有：原始报错记日志，只给一句中文
                logger.exception("向量模型运行出错")
                raise UpstreamError("向量化服务不可用：向量模型运行出错") from exc

    async def _ready(self) -> OnnxRuntime:
        if self._runtime is not None:
            return self._runtime
        if self._loading is None:
            # 每次都重新看文件在不在：模型后台下好以后不用重启就能用
            if not files_ready(self._model_dir, self._spec):
                raise UpstreamError(
                    "向量化服务不可用：向量模型还没下载好"
                    "（后端会自动下载，失败了隔几分钟再试；make doctor 可查看）"
                )
            self._loading = asyncio.create_task(self._load_once())
            # 调用方中途被取消（找相关记忆有时限）时没人等这个任务：取走它的异常，不留警告
            self._loading.add_done_callback(lambda task: task.cancelled() or task.exception())
        # 加载要一两秒：调用方超时被取消也让它加载完，下一次调用直接用
        return await asyncio.shield(self._loading)

    async def _load_once(self) -> OnnxRuntime:
        try:
            runtime = await asyncio.to_thread(self._load, self._model_dir, self._spec)
        except Exception as exc:  # 文件坏了、运行库不认：原始报错记日志，下次调用再试
            logger.exception("向量模型加载不了：%s", self._model_dir)
            self._loading = None
            raise UpstreamError("向量化服务不可用：向量模型加载不了") from exc
        self._runtime = runtime
        return runtime

    def _normalized(self, vector: list[float]) -> list[float]:
        if len(vector) != self._spec.dimensions:
            raise UpstreamError(
                f"向量维度应为 {self._spec.dimensions}，实际为 {len(vector)}：请检查向量模型配置"
            )
        # 长度统一成 1：余弦相似度才能直接当分数比
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / length for value in vector]

    async def _report(self, tokens: int, duration_ms: int) -> None:
        if self._on_usage is None:
            return
        try:
            await self._on_usage(
                EmbeddingUsage(model=self._spec.name, input_tokens=tokens, duration_ms=duration_ms)
            )
        except Exception:  # 用量记录失败不能影响向量化本身
            logger.exception("向量化的用量记录失败")
