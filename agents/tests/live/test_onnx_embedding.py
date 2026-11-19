"""真实的进程内向量模型（D28）：维度、跨语言检索、无关问句的区分、速度。不花钱，但要先有模型文件
（约 207 MB，后端启动后在后台下载到 .workdata/models/）；没有时跳过。运行：make smoke。
"""

import statistics
import time

import pytest

from agents.main_agent.models import EMBEDDING_DIMENSIONS, ONNX_MODELS, OnnxEmbedder, files_ready
from config import get_settings

pytestmark = pytest.mark.live

MEMORIES = [
    "用户常住上海，在浦东新区租房。",
    "用户养了一只叫“年糕”的橘猫，今年三岁。",
    "用户每周二、周四晚上去健身房做力量训练。",
    "The user is allergic to penicillin.",
    "The user's manager is Sarah Chen, and they have a one-on-one every other Friday.",
    "The user keeps personal notes in Obsidian and syncs them with iCloud.",
]
# （问句, 正确的那条记忆在 MEMORIES 里的位置）：同语言、中文问英文记忆、英文问中文记忆
QUESTIONS = [
    ("我住在哪个城市？", 0),
    ("我对什么药物过敏？", 3),
    ("我的直属领导是谁？", 4),
    ("What is my cat's name?", 1),
]
UNRELATED = ["法国的首都是哪里？", "帮我写一个快速排序的 Python 函数"]
THRESHOLD = 0.3  # knowledge.recall_min_similarity 的默认值


@pytest.fixture(scope="module")
def embedder() -> OnnxEmbedder:
    settings = get_settings()
    spec = ONNX_MODELS[settings.knowledge.embedding_model]
    model_dir = settings.models_dir / spec.name
    if not files_ready(model_dir, spec):
        pytest.skip(f"向量模型还没下载（{model_dir}）：先 make up 启动一次后端，等它在后台下好")
    return OnnxEmbedder(model_dir, spec)


def _similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


async def test_real_model_dimensions(embedder: OnnxEmbedder) -> None:
    [vector] = await embedder.embed(["用户喜欢喝茶"])
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert _similarity(vector, vector) == pytest.approx(1.0, abs=1e-3)  # 长度已归一化


async def test_real_model_finds_memories_across_languages(embedder: OnnxEmbedder) -> None:
    memories = await embedder.embed(MEMORIES)
    for question, expected in QUESTIONS:
        [query] = await embedder.embed([question], kind="query")
        scores = [_similarity(query, memory) for memory in memories]
        print(f"{question} → {[round(score, 2) for score in scores]}")
        assert scores.index(max(scores)) == expected, question
        assert scores[expected] >= THRESHOLD, question  # 现有的召回门槛留得住它


async def test_real_model_separates_unrelated_questions(embedder: OnnxEmbedder) -> None:
    memories = await embedder.embed(MEMORIES)
    for question in UNRELATED:
        [query] = await embedder.embed([question], kind="query")
        best = max(_similarity(query, memory) for memory in memories)
        print(f"{question} → 最高 {best:.2f}")
        assert best < THRESHOLD, question  # 无关的问句不该带上任何记忆


async def test_real_model_speed(embedder: OnnxEmbedder) -> None:
    """D28 的先行验证：单条问句十几毫秒、入库每秒约 2 段（容器里 4 核）；这里只挡住数量级的退步。"""
    await embedder.embed(["预热"])
    latencies = []
    for _ in range(5):
        started = time.perf_counter()
        await embedder.embed(["今天下午三点和产品经理开会讨论需求"], kind="query")
        latencies.append(time.perf_counter() - started)
    chunk = "个人知识库中的一段文档内容，用于测试批量向量化的速度。" * 25  # 约 600 token
    started = time.perf_counter()
    await embedder.embed([chunk] * 10)
    per_second = 10 / (time.perf_counter() - started)
    print(
        f"单条问句中位 {statistics.median(latencies) * 1000:.0f} 毫秒；入库每秒 {per_second:.1f} 段"
    )
    assert statistics.median(latencies) < 0.3
    assert per_second > 0.5
