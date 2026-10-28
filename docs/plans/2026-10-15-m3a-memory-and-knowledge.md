# M3a 记忆与知识库 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** M3 的前一半——跨会话记得你。

- 对话中说"记住……"（或智能体判断值得记）时记下来，回答里提示"已记住：xxx"；需要以前说过的信息时能查到。
- 每次对话自动带上常驻信息（个人画像，如"回答简洁点"）和与这句话相关的记忆。
- 每次对话顺利结束后，后台自动整理值得记住的信息（新增 / 更新 / 删除 / 忽略）；新会话第一次结束后自动起标题。
- 知识库页：查看、搜索、手动添加、修改、删除记忆，设或取消常驻；常驻信息太多时提示精简。

M3 拆成两份（2026-10-15 与用户确认"先记忆后文档"）：**M3a 是本计划**；M3b（文档上传、解析切块、检索带出处、读取原文、会话附件加入知识库）以后再写。

**架构：**

- **向量化**：新的可替换接口 `Embedder`，实现 `LiteLLMProxyEmbedder` 经模型网关调用本机 Ollama 里的 qwen3-embedding 0.6B，统一 1024 维。
- **知识存储**：可替换接口 `KnowledgeStore`，实现 `PgKnowledgeStore` 用新表 `knowledge_items`：
  - 向量存进 pgvector 字段（按意思检索）；jieba 分词后存进全文检索字段（按人名、型号、报错码等精确词检索）；
  - 混合检索 = 两路各取 4 倍候选，按"倒数排名融合"合并；
  - 相关记忆召回只看记忆，按向量相似度取前 5 条、不低于 0.3；查询加 Qwen 的任务说明前缀，条目本身不加。
- **智能体**：两个工具 `remember`、`search_knowledge`。
  - `remember` 的工具结果附带记下的条目，翻译器据此推送新事件 `memory.saved`，前端显示"已记住"；
  - 每次运行开始时查好常驻条目与相关记忆，放进运行上下文，由知识上下文中间件拼到系统提示词末尾。
- **后台任务**：`jobs` 表 + 本进程一个后台循环（运行时替换点⑤），失败按次数延后重试、最多 3 次，重启后接着做。
- **运行结束后的后续任务**（`RunFollowups`）：会话第一次顺利结束时生成标题；开启自动提取时提取记忆。两者都用会话所选的模型，用量记在这次运行名下（调用方 `title`、`memory_extraction`）。
- **前端**：回答里的"已记住"提示；标题生成期间自动刷新会话列表；侧栏"知识库"入口与知识库页。

**技术栈：**

- 新增 Python 依赖只有 `jieba==0.42.1`（中文分词）。
- 数据库镜像已带 pgvector 0.8.7；向量以文字形式 `'[…]'::vector` 传给数据库，不需要 pgvector 的 Python 包。
- 用到的现有能力：
  - LangChain 的 `@tool(response_format="content_and_artifact")` 与 `ToolRuntime`（工具里拿到运行上下文）；
  - deepagents 的 `create_deep_agent(tools=…)` 与中间件；
  - PostgreSQL 全文检索（`simple` 配置）；
  - TanStack Query。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）：

- 第 8 节（统一知识库，8.1～8.5）；
- 10.9 节运行时替换点⑤（后台任务）；
- 第 11 节表结构 `knowledge_items`、接口表"知识库"一行（本期只做条目部分）；
- 13 节知识库页；
- 第 21 节 M3 行；
- 决策记录 D10、D11、D15。

> 本计划的全部代码在写计划时已于临时目录实际运行验证：每个任务结束时 `make check`、`make test-int` 全部通过（数量见各任务检查点），向量化的真实调用（任务 1 的冒烟测试）通过。计划中的每段代码由脚本从验证过的文件直接嵌入，并已从改动前的项目出发按本计划逐任务重放、逐字核对（重放时容器虚拟机卡住，要用测试数据库的 19 个步骤没有在重放中运行，其余命令的结果与预期一致）。
>
> 写计划时**没有**验证的：任务 9 新加的真实模型冒烟测试（提取记忆与起标题，写计划时容器虚拟机卡住、网关不可用）与浏览器端到端验证，都在任务 9 里做。提取记忆的提示词与解析方式在先行探测里用三个真实模型验证过（见下表）。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。
- deepagents 只能出现在 `agents/main_agent/runtime/`；例外：`agents/main_agent/workspace/` 可以引用 `deepagents.backends`。
- 新增依赖只有 `jieba==0.42.1`，版本写死。
- 第三方服务与镜像一律由 `deploy/docker-compose.yml` 管理；只操作本项目的容器。
- 密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 由命令生成的文件不手改：`frontend/src/api/generated/`（`make types`）、`uv.lock`（`uv lock`）。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 直接运行 Python 测试时要有环境变量 `LITELLM_LOCAL_MODEL_COST_MAP=True`、`LANGGRAPH_STRICT_MSGPACK=true`（Makefile 与根目录 `conftest.py` 已设置）。集成测试先 `make test-up`（测试数据库与测试沙箱）。
- 记忆提取与标题生成**跟随会话所选的模型**（用户 2026-10-15 决定），不另配便宜模型。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **向量模型（Ollama）没启动或出错** → 对话照常进行，只是这次不带相关记忆（常驻信息照常带上）；`remember` 失败时工具结果说明原因、运行不中断；知识库页添加、搜索返回 503 并说明原因，不带搜索词的列表照常可用。测试：
   - 任务 4 `test_recall_failure_does_not_stop_the_run`、`test_failed_remember_is_reported_to_the_model_without_stopping`；
   - 任务 7 `test_unavailable_embedding_service_is_reported`；任务 9 浏览器验证第 8 步。
2. **模型回的提取结果不规范**：JSON 前后带说明或代码块、编号不存在、内容为空、根本不是 JSON → 能用的照用，其余跳过并记日志，不重试（重试多半一样，白花钱）。测试：任务 5 `test_applies_the_changes_the_model_decides`（带代码块）、`test_invalid_changes_are_skipped_and_the_rest_applied`、`test_unreadable_reply_changes_nothing`。
3. **后台任务执行前用户动过东西**：改了会话名、删了会话、在知识库页删了要被更新的那条记忆 → 不覆盖用户起的名字；任务直接结束、不重试；删掉的记忆跳过、其余照常写入。测试：任务 6 `test_title_job_keeps_a_title_the_user_set`；任务 5 `test_extraction_job_for_a_deleted_run_does_nothing`、`test_memory_deleted_meanwhile_is_skipped`。
4. **常驻信息越积越多** → 每次对话都会带上（费用和干扰都随之增加）；超过建议的 2000 token 时知识库页提示精简，不自动截断；自动提取不改常驻条目。测试：任务 7 `test_pinned_summary_counts_tokens_against_the_limit`；任务 8 `pinnedNotice`；任务 5 `test_model_sees_related_memories_numbered_and_pinned_ones_read_only`。
5. **用中文输入法在知识库页搜索**：拼音选词时按回车只是确认选词，不提前开始搜索；标签用中文逗号、顿号分隔也能识别。测试：任务 8 `parseTags`；选词回车沿用已有的 `isImeComposing`（`ime.test.ts`），任务 9 浏览器验证第 5 步检查。

## 先行探测结论（2026-10-15 写计划时实测）

| 问题 | 结论 |
|---|---|
| 向量模型经网关 | 能：`POST {网关}/embeddings`，模型名 `embed-qwen3-0.6b`，返回 1024 维；网关不可用、维度不对时要给出看得懂的原因 |
| 相关记忆的相似度阈值 | 6 条记忆、7 个问题实测：真正相关的记忆与问题的相似度只有 0.34～0.64，无关的最高也有 0.39～0.46；设计文档的 0.75 什么都召回不到。改为取最相近的 5 条、下限 0.3，并在提示词里写明"不一定相关，自行判断" |
| 中文关键词检索 | PostgreSQL 的 `simple` 配置不会切中文词；先用 jieba（搜索引擎模式）切词再存进全文检索字段，"后端""订单""ERR_CONN_RESET""iphone 15"都能查到；查询时各词用 OR 连接 |
| pgvector | 数据库镜像自带 0.8.7：`CREATE EXTENSION vector`、HNSW 索引（余弦）、距离运算 `<=>` 都可用；向量以文字 `'[…]'::vector` 传入即可 |
| 提取记忆用结构化输出还是只回 JSON | 结构化输出（`with_structured_output`）：claude-opus-4-6 返回空结果，gpt-5.5-pro 拒绝该格式。只回一段 JSON、由我们解析：gemini-3.5-flash、claude-opus-4-6、gpt-5.5-pro 都正确给出"换工作 → 更新、不喝咖啡 → 更新、新事实 → 新增"，闲聊时都返回空列表；gpt-5.5-pro 一次约 0.04 美元 |
| 工具里拿到会话与运行 ID | `@tool` 函数加一个 `runtime: ToolRuntime[AgentContext]` 参数即可（不出现在给模型看的参数里）；`response_format="content_and_artifact"` 的附加数据在 `updates` 输出流的 `ToolMessage.artifact` 里，翻译器据此推送"已记住" |
| jieba | 只有源码包（约 19MB），第一次 `uv lock` 要几分钟；加载时有 Python 3.12 不认的转义写法警告（测试配置里忽略）；没有类型信息（mypy 配置里忽略） |
| 方法名 `list` | 类里定义名为 `list` 的方法后，同一个类里的类型注解 `list[...]` 会指向这个方法而报错，知识存储的列表方法叫 `list_items` |

## 文件结构（本计划涉及）

```
agents/main_agent/
├── models/embedding.py            # 新：向量化接口与经网关的实现
├── knowledge/                     # 新：知识条目、存储接口、PostgreSQL 实现、分词、会后提取记忆
├── runtime/knowledge.py           # 新：remember / search_knowledge 工具、知识上下文中间件
├── runtime/titles.py              # 新：会话标题生成
├── runtime/agent.py               # 改：运行前查常驻与相关记忆；extract_memories、generate_title
├── runtime/events.py、translator.py # 改：memory.saved 事件
├── context.py                     # 改：运行上下文带上知识
├── bootstrap.py                   # 改：装配向量化与知识存储
└── prompts/system.md              # 改：何时记住、何时检索
backend/
├── runtime/jobs.py                # 新：后台任务队列
├── runs/followups.py              # 新：运行结束后的后续任务（标题、记忆提取）
├── runs/manager.py、repo.py        # 改：顺利结束时登记后续任务；会话的完成次数与首条消息
├── threads/repo.py                # 改：自动标题、带条件换标题
├── api/knowledge.py               # 新：知识库接口
├── api/deps.py、main.py            # 改：装配任务队列与后续任务，启动时开始处理
└── migrations/versions/           # 新：0006 knowledge_items、0007 jobs
config/settings.py、config/app.yaml  # 改：knowledge 配置段、两个新的替换点
pyproject.toml、uv.lock             # 改：jieba
frontend/src/
├── api/                           # 改：知识库接口、类型别名、查询
├── features/knowledge/            # 新：知识库页
├── features/threads/titleRefresh.ts # 新：等后台标题时刷新会话列表
├── features/chat/                 # 改："已记住"项、运行结束后等标题
├── components/chat/               # 改："已记住"提示
└── layout/AppShell.tsx            # 改：侧栏"知识库"入口
docs/                              # 改：D11 补充、架构规范、README、需求池、变更记录
```

---

### 任务 1：向量化接口

**文件：**
- 新建：`agents/main_agent/models/embedding.py`、`agents/tests/test_embedding.py`、`agents/tests/contracts/test_embedder_contract.py`
- 修改：`agents/main_agent/models/__init__.py`、`agents/tests/fakes.py`、`agents/tests/live/test_smoke.py`

**接口：**
- 产出（`agents.main_agent.models` 公开）：
  - `EMBEDDING_DIMENSIONS = 1024`；
  - `Embedder`（接口）：属性 `model -> str`；`async embed(texts: Sequence[str]) -> list[list[float]]`，一段文字一个向量、顺序不变，空输入返回空列表；
  - `LiteLLMProxyEmbedder(base_url, api_key, model, *, batch_size=32, transport=None)`：每批最多 32 段；网关不可用抛 `UpstreamError("向量化服务不可用：…")`，维度不对抛 `UpstreamError("向量维度应为 1024，实际为 …：请检查向量模型配置")`。
- 产出（测试替身，`agents/tests/fakes.py`）：`FakeEmbedder(vocabulary=())`——词表里的每个词占一个维度，含有相同词的文字向量相近。

- [ ] **步骤 1：写失败的测试**

新建 `agents/tests/test_embedding.py`：

```python
"""LiteLLM 网关向量化实现：分批请求、带密钥、出错时给出看得懂的原因。"""

import json

import httpx
import pytest

from agents.main_agent.models import EMBEDDING_DIMENSIONS, LiteLLMProxyEmbedder
from common.errors import UpstreamError


async def test_sends_model_and_key_in_batches() -> None:
    requests: list[httpx.Request] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        vector = [0.5] * EMBEDDING_DIMENSIONS
        return httpx.Response(
            200, json={"data": [{"index": i, "embedding": vector} for i in range(len(texts))]}
        )

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000",
        "sk-test",
        "embed-qwen3-0.6b",
        batch_size=2,
        transport=httpx.MockTransport(gateway),
    )
    vectors = await embedder.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert [json.loads(r.content) for r in requests] == [
        {"model": "embed-qwen3-0.6b", "input": ["a", "b"]},
        {"model": "embed-qwen3-0.6b", "input": ["c"]},
    ]
    assert requests[0].url == "http://gateway:4000/embeddings"
    assert requests[0].headers["authorization"] == "Bearer sk-test"


async def test_unavailable_gateway_or_wrong_size_is_explained() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000", "k", "m", transport=httpx.MockTransport(refuse)
    )
    with pytest.raises(UpstreamError, match="向量化服务不可用"):
        await embedder.embed(["a"])

    def small(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 768}]})

    embedder = LiteLLMProxyEmbedder(
        "http://gateway:4000", "k", "m", transport=httpx.MockTransport(small)
    )
    with pytest.raises(UpstreamError, match="向量维度应为 1024，实际为 768"):
        await embedder.embed(["a"])
```

契约测试（经网关的实现走模拟传输层，与测试替身用同一组测试）：

新建 `agents/tests/contracts/test_embedder_contract.py`：

```python
"""向量化契约测试（设计文档 4.1、8.5）：所有 Embedder 实现都必须通过同一套测试。

固定输出 1024 维；按输入顺序一一对应；空输入不发请求。
"""

import json
from collections.abc import Callable

import httpx
import pytest

from agents.main_agent.models import EMBEDDING_DIMENSIONS, Embedder, LiteLLMProxyEmbedder
from agents.tests.fakes import FakeEmbedder


def _gateway(request: httpx.Request) -> httpx.Response:
    """模拟网关的 /embeddings：每段文字的向量第一个分量是它的长度，便于核对顺序。"""
    texts = json.loads(request.content)["input"]
    data = [
        {"index": i, "embedding": [float(len(t))] + [0.0] * (EMBEDDING_DIMENSIONS - 1)}
        for i, t in enumerate(texts)
    ]
    return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 1}})


@pytest.fixture(
    params=[
        lambda: LiteLLMProxyEmbedder(
            "http://gateway:4000", "sk-test", "embed-x", transport=httpx.MockTransport(_gateway)
        ),
        lambda: FakeEmbedder(),
    ]
)
def make(request: pytest.FixtureRequest) -> Callable[[], Embedder]:
    factory: Callable[[], Embedder] = request.param
    return factory


async def test_one_vector_per_text_in_order(make: Callable[[], Embedder]) -> None:
    vectors = await make().embed(["一", "一二三", "一二"])
    assert len(vectors) == 3
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    assert len({tuple(v) for v in vectors}) == 3


async def test_empty_input_gives_no_vectors(make: Callable[[], Embedder]) -> None:
    assert await make().embed([]) == []


def test_reports_the_model_it_uses(make: Callable[[], Embedder]) -> None:
    assert make().model  # 每个知识条目记录所用的向量模型（换模型后据此重建）
```

在 `agents/tests/fakes.py` 中，把：

```python

from agents.main_agent.models import ModelInfo
from agents.main_agent.workspace import CommandResult
```

改为：

```python

from agents.main_agent.models import EMBEDDING_DIMENSIONS, ModelInfo
from agents.main_agent.workspace import CommandResult
```

在 `agents/tests/fakes.py` 末尾追加：

```python


class FakeEmbedder:
    """假向量模型：词表里的每个词占一个维度，文字含有这个词则该维为 1。

    含有相同词的文字向量相近、没有共同词的几乎正交，便于验证"按意思检索""相关记忆召回"。
    最后一维固定一个小值，任何文字都不会是零向量。
    """

    model = "fake-embedding"

    def __init__(self, vocabulary: Sequence[str] = ()) -> None:
        self._vocabulary = list(vocabulary)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            for index, word in enumerate(self._vocabulary):
                if word in text:
                    vector[index] = 1.0
            vector[-1] = 0.1 + 0.001 * len(text)  # 没有词表词的不同文字也略有区别
            vectors.append(vector)
        return vectors
```

真实调用（`make smoke` 时运行）：

在 `agents/tests/live/test_smoke.py` 中，把：

```python

from agents.main_agent.models import LiteLLMProxyGateway
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
```

改为：

```python

from agents.main_agent.models import EMBEDDING_DIMENSIONS, LiteLLMProxyEmbedder, LiteLLMProxyGateway
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
```

在 `agents/tests/live/test_smoke.py` 末尾追加：

```python


async def test_embedder_through_gateway() -> None:
    """M3a：知识库用的向量化接口经网关调用本机向量模型，维度为 1024。"""
    settings = get_settings()
    embedder = LiteLLMProxyEmbedder(
        settings.litellm_base_url, settings.litellm_master_key.get_secret_value(), EMBED
    )
    vectors = await embedder.embed(["用户喜欢喝茶", "今天天气不错"])
    assert [len(v) for v in vectors] == [EMBEDDING_DIMENSIONS, EMBEDDING_DIMENSIONS]
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_embedding.py agents/tests/contracts/test_embedder_contract.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'EMBEDDING_DIMENSIONS'`（或 `'LiteLLMProxyEmbedder'`）。

- [ ] **步骤 3：实现**

新建 `agents/main_agent/models/embedding.py`：

```python
"""向量化（设计文档 4.1、8.5）：把文字变成 1024 维向量，意思相近的文字向量也相近。

可替换接口 Embedder；v1 经 LiteLLM 网关调用本机 Ollama 里的 Qwen3 向量模型。
查询要加的任务说明前缀属于检索策略，写在知识模块里，这里只管转换。
"""

from collections.abc import Sequence
from typing import Protocol

import httpx

from common.errors import UpstreamError

EMBEDDING_DIMENSIONS = 1024  # 统一维度：pgvector 索引上限 2000 维，主流向量模型都能输出 1024 维


class Embedder(Protocol):
    @property
    def model(self) -> str:
        """所用的向量模型（记录到每个知识条目，换模型后据此重建向量）。"""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """按输入顺序返回每段文字的向量。"""
        ...


class LiteLLMProxyEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        batch_size: int = 32,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._batch_size = batch_size
        self._transport = transport  # 仅测试时注入

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            transport=self._transport,
            timeout=120,  # 本机向量模型只用 CPU，一批几十段要十几秒
        ) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                vectors.extend(await self._embed_batch(client, batch))
        return vectors

    async def _embed_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        try:
            response = await client.post("/embeddings", json={"model": self._model, "input": batch})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"向量化服务不可用：{exc}") from exc
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [list(item["embedding"]) for item in data]
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise UpstreamError(
                    f"向量维度应为 {EMBEDDING_DIMENSIONS}，实际为 {len(vector)}：请检查向量模型配置"
                )
        return vectors
```

在 `agents/main_agent/models/__init__.py` 中，把：

```python
"""模型能力模块：对外公开模型网关接口、模型信息、网关实现、换模型清理与 token 估算。"""

from agents.main_agent.models.base import ModelGateway, ModelInfo, version_name
from agents.main_agent.models.cleanup import ModelSwitchCleanupMiddleware
from agents.main_agent.models.estimate import estimate_input_tokens, estimate_text_tokens
```

改为：

```python
"""模型能力模块：对外公开模型网关与向量化接口、模型信息、网关实现、换模型清理与 token 估算。"""

from agents.main_agent.models.base import ModelGateway, ModelInfo, version_name
from agents.main_agent.models.cleanup import ModelSwitchCleanupMiddleware
from agents.main_agent.models.embedding import (
    EMBEDDING_DIMENSIONS,
    Embedder,
    LiteLLMProxyEmbedder,
)
from agents.main_agent.models.estimate import estimate_input_tokens, estimate_text_tokens
```

在 `agents/main_agent/models/__init__.py` 中，把：

```python
__all__ = [
    "LiteLLMProxyGateway",
```

改为：

```python
__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Embedder",
    "LiteLLMProxyEmbedder",
    "LiteLLMProxyGateway",
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_embedding.py agents/tests/contracts/test_embedder_contract.py -q`

预期：8 个测试通过。

可选（会调用本机向量模型，不产生费用；需先 `make infra-up`）：`uv run pytest -m live -s agents/tests/live/test_smoke.py -k embedder`，预期通过。

- [ ] **步骤 5：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 180 个、前端 82 个）。

---

### 任务 2：知识条目与混合检索

**文件：**
- 新建：`agents/main_agent/knowledge/__init__.py`、`models.py`、`base.py`、`tokens.py`、`pgvector.py`、`backend/migrations/versions/0006_agents_knowledge_items.py`、`agents/tests/contracts/test_knowledge_contract.py`
- 修改：`pyproject.toml`、`uv.lock`（命令生成）、`conftest.py`、`backend/tests/test_migrations.py`

**接口：**
- 消费：任务 1 的 `Embedder`；已有的 `estimate_text_tokens`（`agents.main_agent.models`）。
- 产出（`agents.main_agent.knowledge` 公开）：
  - `KnowledgeKind = "memory" | "document_chunk"`；`KnowledgeSource = "conversation" | "document" | "manual"`；
  - `NewKnowledge(kind="memory", content, tags=[], pinned=False, source, source_thread_id=None, source_run_id=None)`：内容去掉首尾空白后 1～20000 字；标签去空白、去重；
  - `KnowledgeItem`（id、kind、tags、pinned、content、source、source_thread_id、source_run_id、document_id、token_count、embedding_model、created_at、updated_at）；`KnowledgeHit(item, score)`；
  - `KnowledgeStore`（接口）：`add`、`get`、`update(item_id, *, content=None, tags=None, pinned=None)`（改内容时重新向量化）、`delete`（`get` / `update` / `delete` 不存在时抛 `NotFoundError`）、`list_items(*, kind=None, tags=(), pinned=None, limit=100, offset=0)`（新的在前；tags 表示必须带有这些标签）、`pinned()`（按创建先后）、`search(query, *, kinds=None, tags=(), top_k=5)`（混合检索）、`recall(query, *, top_k, min_similarity)`（只看记忆，相似度 = 1 − 余弦距离）；
  - `PgKnowledgeStore(pool, embedder)`。
- 产出（表）：`knowledge_items`（迁移 0006，同时 `CREATE EXTENSION vector`）：向量 HNSW 索引、全文检索 GIN 索引、`(kind, pinned)` 与标签索引；`document_id`、`seq`、`section_path`、`page` 留给 M3b；来源会话、来源运行不设外键（删除会话不删它记住的事）。

- [ ] **步骤 1：新增依赖**

除了 `jieba`，还要让类型检查忽略它（没有类型信息）、测试配置忽略它加载时的语法警告，并把 `PgKnowledgeStore` 的实现模块加进"backend 不得直接引用"的清单：

在 `pyproject.toml` 中，把：

```toml
    "openpyxl==3.1.5",
]
```

改为：

```toml
    "openpyxl==3.1.5",
    "jieba==0.42.1",
]
```

在 `pyproject.toml` 中，把：

```toml

[tool.pytest.ini_options]
```

改为：

```toml

[[tool.mypy.overrides]]
module = ["jieba"]  # 中文分词库没有类型标注
ignore_missing_imports = true

[tool.pytest.ini_options]
```

在 `pyproject.toml` 中，把：

```toml
addopts = "-m 'not integration and not live'"

```

改为：

```toml
addopts = "-m 'not integration and not live'"
# jieba 0.42.1 的旧代码里有 Python 3.12 不认的转义写法，加载时报语法警告，与本项目无关
filterwarnings = ["ignore:invalid escape sequence:SyntaxWarning"]

```

在 `pyproject.toml` 中，把：

```toml
    "agents.main_agent.workspace.files",
    "agents.main_agent.workspace.local",
```

改为：

```toml
    "agents.main_agent.workspace.files",
    "agents.main_agent.knowledge.pgvector",
    "agents.main_agent.workspace.local",
```

运行：`uv lock`

预期：`uv.lock` 新增 `jieba 0.42.1`。jieba 只有源码包，第一次要几分钟。

- [ ] **步骤 2：写失败的测试**

知识存储的契约测试（集成测试，连测试数据库；向量化用 `FakeEmbedder`）：

新建 `agents/tests/contracts/test_knowledge_contract.py`：

```python
"""知识存储契约测试（设计文档 8.1、8.3、11.1）：所有 KnowledgeStore 实现都必须通过同一套测试。

用假向量模型：含有相同词表词的文字向量相近，没有共同词的几乎无关。
"""

import uuid
from collections.abc import Callable

import pytest

from agents.main_agent.knowledge import KnowledgeStore, NewKnowledge, PgKnowledgeStore
from agents.tests.fakes import FakeEmbedder
from common.db import Pool
from common.errors import NotFoundError

pytestmark = pytest.mark.integration

VOCABULARY = ["咖啡", "茶", "狗", "工作", "后端"]
type Factory = Callable[[], KnowledgeStore]


@pytest.fixture(params=["pgvector"])
def make(request: pytest.FixtureRequest, db: Pool) -> Factory:
    return lambda: PgKnowledgeStore(db, FakeEmbedder(VOCABULARY))


def _memory(content: str, **fields: object) -> NewKnowledge:
    return NewKnowledge.model_validate(
        {"kind": "memory", "content": content, "source": "manual", **fields}
    )


async def test_adds_and_reads_back_an_item(make: Factory) -> None:
    store = make()
    thread, run = uuid.uuid4(), uuid.uuid4()
    item = await store.add(
        _memory(
            "用户每天早上喝美式咖啡",
            tags=["偏好"],
            pinned=True,
            source="conversation",
            source_thread_id=thread,
            source_run_id=run,
        )
    )
    assert await store.get(item.id) == item
    assert (item.kind, item.tags, item.pinned, item.source) == (
        "memory",
        ["偏好"],
        True,
        "conversation",
    )
    assert (item.source_thread_id, item.source_run_id) == (thread, run)
    assert item.token_count > 0
    assert item.embedding_model == "fake-embedding"


async def test_updating_content_updates_what_search_finds(make: Factory) -> None:
    store = make()
    item = await store.add(_memory("用户喜欢喝咖啡"))
    updated = await store.update(item.id, content="用户改喝茶了", tags=["偏好"], pinned=True)
    assert (updated.content, updated.tags, updated.pinned) == ("用户改喝茶了", ["偏好"], True)
    assert updated.updated_at > item.updated_at
    hits = await store.search("喝什么茶", top_k=1)
    assert [hit.item.id for hit in hits] == [item.id]
    assert await store.update(item.id, pinned=False) == updated.model_copy(
        update={"pinned": False, "updated_at": (await store.get(item.id)).updated_at}
    )


async def test_deleting_and_missing_items(make: Factory) -> None:
    store = make()
    item = await store.add(_memory("用户养了一只狗"))
    await store.delete(item.id)
    with pytest.raises(NotFoundError):
        await store.get(item.id)
    with pytest.raises(NotFoundError):
        await store.delete(item.id)
    with pytest.raises(NotFoundError):
        await store.update(uuid.uuid4(), pinned=True)


async def test_lists_with_filters_newest_first(make: Factory) -> None:
    store = make()
    a = await store.add(_memory("用户在做后端工作", tags=["工作"]))
    b = await store.add(_memory("用户喜欢茶", tags=["偏好"], pinned=True))
    c = await store.add(_memory("用户养了一只狗", tags=["生活", "宠物"]))
    assert [i.id for i in await store.list_items()] == [c.id, b.id, a.id]
    assert [i.id for i in await store.list_items(tags=["宠物"])] == [c.id]
    assert [i.id for i in await store.list_items(pinned=True)] == [b.id]
    assert await store.list_items(kind="document_chunk") == []
    assert [i.id for i in await store.list_items(limit=1, offset=1)] == [b.id]
    assert [i.id for i in await store.pinned()] == [b.id]


async def test_hybrid_search_finds_by_meaning_and_by_exact_words(make: Factory) -> None:
    """按意思（向量）与按精确词（分词后的关键词）两路结果合并：报错码这类词向量未必相近，关键词能找到。"""
    store = make()
    coffee = await store.add(_memory("用户每天喝咖啡", tags=["偏好"]))
    error = await store.add(_memory("线上偶发 ERR_CONN_RESET 报错", tags=["工作"]))
    await store.add(_memory("用户养了一只狗"))
    assert [h.item.id for h in await store.search("推荐点咖啡豆", top_k=1)] == [coffee.id]
    assert [h.item.id for h in await store.search("ERR_CONN_RESET 怎么排查", top_k=1)] == [error.id]
    filtered = await store.search("咖啡", tags=["工作"], top_k=5)
    assert coffee.id not in [h.item.id for h in filtered]
    assert await store.search("咖啡", kinds=["document_chunk"]) == []


async def test_recall_keeps_only_similar_memories(make: Factory) -> None:
    store = make()
    dog = await store.add(_memory("用户养了一只狗叫豆豆"))
    await store.add(_memory("用户在做后端工作"))
    hits = await store.recall("我家狗叫什么", top_k=5, min_similarity=0.5)
    assert [h.item.id for h in hits] == [dog.id]
    assert 0.5 <= hits[0].score <= 1.0
```

在 `backend/tests/test_migrations.py` 中，把：

```python
    assert row == {"files": "workspace_files"}

```

改为：

```python
    assert row == {"files": "workspace_files"}


async def test_knowledge_items_table_and_vector_extension_exist(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute(
            "SELECT to_regclass('public.knowledge_items')::text AS items, "
            "(SELECT extname FROM pg_extension WHERE extname = 'vector') AS vector"
        )
        row = await cur.fetchone()
    assert row == {"items": "knowledge_items", "vector": "vector"}

```

每个集成测试前清空的表加上 `knowledge_items`：

在 `conftest.py` 中，把：

```python
    async with pg_pool.connection() as conn:
        await conn.execute("TRUNCATE threads, runs, run_events, llm_usage, workspace_files CASCADE")
    return pg_pool
```

改为：

```python
    async with pg_pool.connection() as conn:
        await conn.execute(
            "TRUNCATE threads, runs, run_events, llm_usage, workspace_files, knowledge_items "
            "CASCADE"
        )
    return pg_pool
```

- [ ] **步骤 3：运行测试，确认失败**

运行：`make test-up`

运行：`uv run pytest -m integration agents/tests/contracts/test_knowledge_contract.py backend/tests/test_migrations.py -q`（预期失败）

预期：契约测试收集阶段报错 `ModuleNotFoundError: No module named 'agents.main_agent.knowledge'`；迁移测试报 `knowledge_items` 不存在。

- [ ] **步骤 4：实现**

新建 `agents/main_agent/knowledge/models.py`：

```python
"""知识条目（设计文档 8.1、11.1）：记忆、文档片段等都是带标记的知识条目。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

type KnowledgeKind = Literal["memory", "document_chunk"]
type KnowledgeSource = Literal["conversation", "document", "manual"]

KnowledgeText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]


def clean_tags(tags: list[str]) -> list[str]:
    """去掉首尾空白与空标签，去重并保持顺序。"""
    seen: dict[str, None] = {}
    for tag in tags:
        if tag.strip():
            seen[tag.strip()] = None
    return list(seen)


class NewKnowledge(BaseModel):
    kind: KnowledgeKind = "memory"
    content: KnowledgeText
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False  # 常驻：每次都拼进系统提示词（个人画像）
    source: KnowledgeSource
    source_thread_id: UUID | None = None
    source_run_id: UUID | None = None

    @field_validator("tags")
    @classmethod
    def _clean(cls, tags: list[str]) -> list[str]:
        return clean_tags(tags)


class KnowledgeItem(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: UUID
    kind: KnowledgeKind
    tags: list[str]
    pinned: bool
    content: str
    source: KnowledgeSource
    source_thread_id: UUID | None
    source_run_id: UUID | None
    document_id: UUID | None  # 文档片段所属文档（M3b）
    token_count: int
    embedding_model: str
    created_at: datetime
    updated_at: datetime


class KnowledgeHit(BaseModel):
    """检索结果：条目与得分（混合检索为融合得分，召回为相似度）。"""

    item: KnowledgeItem
    score: float
```

新建 `agents/main_agent/knowledge/base.py`：

```python
"""知识存储接口（设计文档 4.1"知识检索"）：知识条目的增删改查与检索。

v1 实现是 PostgreSQL（pgvector 存向量 + jieba 分词做中文关键词检索）；以后可换 Qdrant 等。
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from agents.main_agent.knowledge.models import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    NewKnowledge,
)


class KnowledgeStore(Protocol):
    async def add(self, new: NewKnowledge) -> KnowledgeItem: ...

    async def get(self, item_id: UUID) -> KnowledgeItem:
        """不存在时抛 NotFoundError。"""
        ...

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> KnowledgeItem:
        """只改给出的字段；改内容时重新向量化。不存在时抛 NotFoundError。"""
        ...

    async def delete(self, item_id: UUID) -> None:
        """不存在时抛 NotFoundError。"""
        ...

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        """按创建时间从新到旧；tags 表示必须带有这些标签。"""
        ...

    async def pinned(self) -> list[KnowledgeItem]:
        """全部常驻条目（按创建时间先后）。"""
        ...

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
    ) -> list[KnowledgeHit]:
        """混合检索：按意思（向量）与按精确词（关键词）两路结果合并排序。"""
        ...

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        """相关记忆召回：只看记忆，按意思相似度从高到低，低于 min_similarity 的不要。"""
        ...
```

jieba 分词（写入与查询用同一套切法）：

新建 `agents/main_agent/knowledge/tokens.py`：

```python
"""中文分词（jieba）：PostgreSQL 自带的全文检索不会给中文分词，先在 Python 里分好再存。"""

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)  # 第一次分词时加载词典，默认会打印几行调试信息

_WORD = re.compile(r"\w")


def search_tokens(text: str) -> list[str]:
    """搜索引擎模式分词（长词再切出短词，便于部分匹配），统一小写，去掉标点与空白。"""
    return [word.lower() for word in jieba.cut_for_search(text) if _WORD.search(word)]
```

新建 `agents/main_agent/knowledge/pgvector.py`：

```python
"""知识存储的 PostgreSQL 实现。

pgvector 存向量（按意思检索）；jieba 分词后存进全文检索字段（按精确词检索）。
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from agents.main_agent.knowledge.models import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    NewKnowledge,
    clean_tags,
)
from agents.main_agent.knowledge.tokens import search_tokens
from agents.main_agent.models import Embedder, estimate_text_tokens
from common.db import Pool
from common.errors import NotFoundError
from common.ids import new_id

_COLUMNS = (
    "id, kind, tags, pinned, content, source, source_thread_id, source_run_id, document_id, "
    "token_count, embedding_model, created_at, updated_at"
)
# Qwen3 向量模型对"查询"加一句任务说明效果更好（设计文档 8.5）；存进去的条目本身不加
QUERY_PREFIX = "Instruct: 根据问题找出相关的知识与记忆\nQuery: "
_RRF_K = 60  # 倒数排名融合的常数：排名靠前的差距被拉开，又不至于一家独大
_CANDIDATES = 4  # 每路先各取 top_k 的几倍再融合


def _vector(values: list[float]) -> str:
    return "[" + ",".join(map(str, values)) + "]"


def _search_text(text: str) -> str:
    return " ".join(search_tokens(text))


def _filters(
    *, kinds: Sequence[str] | None, tags: Sequence[str], pinned: bool | None = None
) -> tuple[str, list[Any]]:
    clauses: list[str] = ["TRUE"]
    params: list[Any] = []
    if kinds is not None:
        clauses.append("kind = ANY(%s)")
        params.append(list(kinds))
    if tags:
        clauses.append("tags @> %s")
        params.append(list(tags))
    if pinned is not None:
        clauses.append("pinned = %s")
        params.append(pinned)
    return " AND ".join(clauses), params


class PgKnowledgeStore:
    def __init__(self, pool: Pool, embedder: Embedder) -> None:
        self._pool = pool
        self._embedder = embedder

    async def add(self, new: NewKnowledge) -> KnowledgeItem:
        [vector] = await self._embedder.embed([new.content])
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO knowledge_items (id, kind, tags, pinned, content, source, "
                "source_thread_id, source_run_id, token_count, embedding, embedding_model, search) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, "
                f"to_tsvector('simple', %s)) RETURNING {_COLUMNS}",
                (
                    new_id(),
                    new.kind,
                    new.tags,
                    new.pinned,
                    new.content,
                    new.source,
                    new.source_thread_id,
                    new.source_run_id,
                    estimate_text_tokens(new.content),
                    _vector(vector),
                    self._embedder.model,
                    _search_text(new.content),
                ),
            )
            row = await cur.fetchone()
        return KnowledgeItem.model_validate(row)

    async def get(self, item_id: UUID) -> KnowledgeItem:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_items WHERE id = %s", (item_id,)
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"知识条目不存在：{item_id}")
        return KnowledgeItem.model_validate(row)

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> KnowledgeItem:
        sets: list[str] = ["updated_at = now()"]
        params: list[Any] = []
        if content is not None:
            [vector] = await self._embedder.embed([content])
            sets += [
                "content = %s",
                "token_count = %s",
                "embedding = %s::vector",
                "embedding_model = %s",
                "search = to_tsvector('simple', %s)",
            ]
            params += [
                content,
                estimate_text_tokens(content),
                _vector(vector),
                self._embedder.model,
                _search_text(content),
            ]
        if tags is not None:
            sets.append("tags = %s")
            params.append(clean_tags(tags))
        if pinned is not None:
            sets.append("pinned = %s")
            params.append(pinned)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"UPDATE knowledge_items SET {', '.join(sets)} WHERE id = %s RETURNING {_COLUMNS}",
                (*params, item_id),
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"知识条目不存在：{item_id}")
        return KnowledgeItem.model_validate(row)

    async def delete(self, item_id: UUID) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM knowledge_items WHERE id = %s RETURNING id", (item_id,)
            )
            if await cur.fetchone() is None:
                raise NotFoundError(f"知识条目不存在：{item_id}")

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        where, params = _filters(kinds=None if kind is None else [kind], tags=tags, pinned=pinned)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_items WHERE {where} "
                "ORDER BY created_at DESC, id LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def pinned(self) -> list[KnowledgeItem]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_items WHERE pinned ORDER BY created_at, id"
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
    ) -> list[KnowledgeHit]:
        [vector] = await self._embedder.embed([QUERY_PREFIX + query])
        where, params = _filters(kinds=kinds, tags=tags)
        candidates = top_k * _CANDIDATES
        words = " OR ".join(search_tokens(query))
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT id FROM knowledge_items WHERE {where} "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (*params, _vector(vector), candidates),
            )
            by_meaning = [row["id"] for row in await cur.fetchall()]
            by_words: list[UUID] = []
            if words:
                cur = await conn.execute(
                    "SELECT id FROM knowledge_items, websearch_to_tsquery('simple', %s) AS q "
                    f"WHERE search @@ q AND {where} ORDER BY ts_rank(search, q) DESC LIMIT %s",
                    (words, *params, candidates),
                )
                by_words = [row["id"] for row in await cur.fetchall()]
        # 倒数排名融合：每路排第 n 名得 1 / (60 + n) 分，两路都靠前的条目排最前
        scores: dict[UUID, float] = {}
        for ranking in (by_meaning, by_words):
            for rank, item_id in enumerate(ranking, start=1):
                scores[item_id] = scores.get(item_id, 0.0) + 1 / (_RRF_K + rank)
        best = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)[:top_k]
        items = {item.id: item for item in await self._items(best)}
        return [KnowledgeHit(item=items[item_id], score=scores[item_id]) for item_id in best]

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        [vector] = await self._embedder.embed([QUERY_PREFIX + query])
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) AS similarity "
                "FROM knowledge_items WHERE kind = 'memory' "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (_vector(vector), _vector(vector), top_k),
            )
            rows = await cur.fetchall()
        return [
            KnowledgeHit(item=KnowledgeItem.model_validate(row), score=row["similarity"])
            for row in rows
            if row["similarity"] >= min_similarity
        ]

    async def _items(self, ids: list[UUID]) -> list[KnowledgeItem]:
        if not ids:
            return []
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM knowledge_items WHERE id = ANY(%s)", (ids,)
            )
            rows = await cur.fetchall()
        return [KnowledgeItem.model_validate(row) for row in rows]
```

新建 `agents/main_agent/knowledge/__init__.py`：

```python
"""统一知识库（设计文档第 8 节）：知识条目（记忆、文档片段……）的存储、检索与召回。"""

from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.knowledge.models import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    KnowledgeSource,
    NewKnowledge,
)
from agents.main_agent.knowledge.pgvector import PgKnowledgeStore

__all__ = [
    "KnowledgeHit",
    "KnowledgeItem",
    "KnowledgeKind",
    "KnowledgeSource",
    "KnowledgeStore",
    "NewKnowledge",
    "PgKnowledgeStore",
]
```

新建 `backend/migrations/versions/0006_agents_knowledge_items.py`：

```python
"""agents 知识条目表：记忆、文档片段等统一存放（设计文档 8.1、11.1）。

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # document_id 指向文档表（M3b 新建）；来源会话、运行不设外键：删除会话不删它记住的事
    op.execute(
        """
        CREATE TABLE knowledge_items (
            id               uuid PRIMARY KEY,
            user_id          text NOT NULL DEFAULT 'me',
            kind             text NOT NULL CHECK (kind IN ('memory', 'document_chunk')),
            tags             text[] NOT NULL DEFAULT '{}',
            pinned           boolean NOT NULL DEFAULT false,
            content          text NOT NULL,
            document_id      uuid,
            seq              integer,
            section_path     text,
            page             integer,
            source           text NOT NULL CHECK (source IN ('conversation', 'document', 'manual')),
            source_thread_id uuid,
            source_run_id    uuid,
            token_count      integer NOT NULL,
            embedding        vector(1024) NOT NULL,
            embedding_model  text NOT NULL,
            search           tsvector NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX knowledge_items_embedding ON knowledge_items "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX knowledge_items_search ON knowledge_items USING gin (search)")
    op.execute("CREATE INDEX knowledge_items_kind_pinned ON knowledge_items (kind, pinned)")
    op.execute("CREATE INDEX knowledge_items_tags ON knowledge_items USING gin (tags)")


def downgrade() -> None:
    op.execute("DROP TABLE knowledge_items")
```

- [ ] **步骤 5：运行测试，确认通过**

运行：`uv run pytest -m integration agents/tests/contracts/test_knowledge_contract.py backend/tests/test_migrations.py -q`

预期：全部通过。

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 180 个、前端 82 个）；`make test-int` 全部通过（集成测试 76 个）。

---

### 任务 3：后台任务队列

**文件：**
- 新建：`backend/runtime/jobs.py`、`backend/migrations/versions/0007_backend_jobs.py`、`backend/tests/test_job_queue.py`
- 修改：`backend/runtime/__init__.py`、`conftest.py`、`backend/tests/test_migrations.py`

**接口：**
- 产出（`backend.runtime` 公开）：
  - `JobHandler = Callable[[dict[str, Any]], Awaitable[None]]`；
  - `JobQueue`（接口）：`async enqueue(kind, payload) -> UUID`（立即返回）、`async start(handlers: Mapping[str, JobHandler])`（先把上次退出时"处理中"的任务放回队列）、`async stop()`；
  - `TableJobQueue(pool, *, poll_interval=5.0, max_attempts=3, retry_delay=30.0)`：一个后台循环逐个处理；处理函数抛异常时第 n 次失败后等 n × 30 秒再试，第 3 次失败记为 `failed` 并留下原因；没有处理函数的种类直接记为失败（"没有处理这类任务的程序：…"）。
- 产出（表）：`jobs`（迁移 0007）：kind、payload（JSON）、status（queued / running / done / failed）、attempts、last_error、run_at、locked_at；待处理任务的部分索引。

- [ ] **步骤 1：写失败的测试**

新建 `backend/tests/test_job_queue.py`：

```python
"""后台任务队列（运行时替换点⑤，设计文档 10.9）：任务存进 jobs 表，进程内的后台循环逐个处理。

契约：按类型交给处理函数；失败按间隔重试，到上限记为失败；进程中途退出时正在处理的任务下次启动后重做。
"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from backend.runtime import JobQueue, TableJobQueue
from common.db import Pool

pytestmark = pytest.mark.integration

type Factory = Callable[..., JobQueue]


@pytest.fixture(params=["table"])
def make(request: pytest.FixtureRequest, db: Pool) -> Factory:
    def factory(**options: Any) -> JobQueue:
        return TableJobQueue(db, **{"poll_interval": 10.0, "retry_delay": 0.0, **options})

    return factory


async def _status(db: Pool, job_id: object) -> dict[str, Any]:
    async with db.connection() as conn:
        cur = await conn.execute(
            "SELECT status, attempts, last_error FROM jobs WHERE id = %s", (job_id,)
        )
        row = await cur.fetchone()
    assert row is not None
    return dict(row)


async def _until(condition: Callable[[], Any]) -> None:
    for _ in range(150):  # 最多等 3 秒
        if await condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("3 秒内没有等到预期的状态")


async def test_handles_jobs_by_kind_right_after_enqueue(make: Factory, db: Pool) -> None:
    """新任务立即唤醒后台循环，不用等下一次轮询（轮询间隔设成了 10 秒）。"""
    seen: list[dict[str, Any]] = []

    async def note(payload: dict[str, Any]) -> None:
        seen.append(payload)

    queue = make()
    await queue.start({"note": note})
    try:
        job = await queue.enqueue("note", {"run_id": "r1"})
        await _until(lambda: _done(db, job))
    finally:
        await queue.stop()
    assert seen == [{"run_id": "r1"}]


async def _done(db: Pool, job_id: object) -> bool:
    return str((await _status(db, job_id))["status"]) == "done"


async def test_failures_are_retried_then_recorded(make: Factory, db: Pool) -> None:
    calls = 0

    async def flaky(payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(f"第 {calls} 次失败")

    queue = make(max_attempts=3)
    await queue.start({"flaky": flaky})
    try:
        job = await queue.enqueue("flaky", {})

        async def failed() -> bool:
            return str((await _status(db, job))["status"]) == "failed"

        await _until(failed)
    finally:
        await queue.stop()
    assert await _status(db, job) == {
        "status": "failed",
        "attempts": 3,
        "last_error": "第 3 次失败",
    }


async def test_unknown_kind_fails_with_a_reason(make: Factory, db: Pool) -> None:
    queue = make()
    await queue.start({})
    try:
        job = await queue.enqueue("mystery", {})

        async def failed() -> bool:
            return str((await _status(db, job))["status"]) == "failed"

        await _until(failed)
    finally:
        await queue.stop()
    assert (await _status(db, job))["last_error"] == "没有处理这类任务的程序：mystery"


async def test_interrupted_jobs_run_again_after_restart(make: Factory, db: Pool) -> None:
    """服务停止时正在处理的任务不算失败：下次启动重新处理（如服务重启时正在提取记忆）。"""
    started = asyncio.Event()
    finished: list[str] = []

    async def slow(payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(30)

    async def quick(payload: dict[str, Any]) -> None:
        finished.append("ok")

    first = make()
    await first.start({"work": slow})
    job = await first.enqueue("work", {})
    await asyncio.wait_for(started.wait(), 3)
    await first.stop()
    assert (await _status(db, job))["status"] == "running"

    second = make()
    await second.start({"work": quick})
    try:
        await _until(lambda: _done(db, job))
    finally:
        await second.stop()
    assert finished == ["ok"]
```

在 `backend/tests/test_migrations.py` 中，把：

```python
    assert row == {"items": "knowledge_items", "vector": "vector"}

```

改为：

```python
    assert row == {"items": "knowledge_items", "vector": "vector"}


async def test_jobs_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.jobs')::text AS jobs")
        row = await cur.fetchone()
    assert row == {"jobs": "jobs"}

```

在 `conftest.py` 中，把：

```python
        await conn.execute(
            "TRUNCATE threads, runs, run_events, llm_usage, workspace_files, knowledge_items "
            "CASCADE"
        )
```

改为：

```python
        await conn.execute(
            "TRUNCATE threads, runs, run_events, llm_usage, workspace_files, knowledge_items, "
            "jobs CASCADE"
        )
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration backend/tests/test_job_queue.py backend/tests/test_migrations.py -q`（预期失败）

预期：`ImportError: cannot import name 'JobQueue' from 'backend.runtime'`；迁移测试报 `jobs` 不存在。

- [ ] **步骤 3：实现**

新建 `backend/migrations/versions/0007_backend_jobs.py`：

```python
"""backend 后台任务表：记忆提取、标题生成等（设计文档 10.9、11.2）。

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
            id          uuid PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'me',
            kind        text NOT NULL,
            payload     jsonb NOT NULL DEFAULT '{}',
            status      text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'done', 'failed')),
            attempts    integer NOT NULL DEFAULT 0,
            last_error  text,
            run_at      timestamptz NOT NULL DEFAULT now(),
            locked_at   timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX jobs_due ON jobs (run_at) WHERE status = 'queued'")


def downgrade() -> None:
    op.execute("DROP TABLE jobs")
```

新建 `backend/runtime/jobs.py`：

```python
"""后台任务队列（运行时替换点⑤，设计文档 10.9）：记忆提取、标题生成等运行结束后才做的事。

v1：任务存进 jobs 表，本进程里一个后台循环逐个处理（同一时间只处理一个）；
以后多进程时换成独立工作进程从表里抢任务，接口不变。
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb

from common.db import Pool
from common.ids import new_id

logger = logging.getLogger(__name__)

type JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class JobQueue(Protocol):
    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        """登记一个任务（立即返回），由后台按 kind 交给对应的处理函数。"""
        ...

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        """开始在后台处理任务；先把上次进程退出时正在处理的任务放回队列。"""
        ...

    async def stop(self) -> None:
        """停止处理。正在处理的任务被中断，保持"处理中"，下次启动时重做。"""
        ...


class TableJobQueue:
    def __init__(
        self,
        pool: Pool,
        *,
        poll_interval: float = 5.0,
        max_attempts: int = 3,
        retry_delay: float = 30.0,
    ) -> None:
        self._pool = pool
        self._poll_interval = poll_interval  # 没有新任务通知时，隔多久看一次到期的重试
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay  # 第 n 次失败后等 n 倍这么久再试
        self._handlers: Mapping[str, JobHandler] = {}
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None

    async def enqueue(self, kind: str, payload: dict[str, Any]) -> UUID:
        job_id = new_id()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO jobs (id, kind, payload) VALUES (%s, %s, %s)",
                (job_id, kind, Jsonb(payload)),
            )
        self._wake.set()
        return job_id

    async def start(self, handlers: Mapping[str, JobHandler]) -> None:
        self._handlers = handlers
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'queued', locked_at = NULL, updated_at = now() "
                "WHERE status = 'running'"
            )
        self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                job = await self._claim()
            except Exception:  # 数据库暂时不可用：稍后再试，不让后台循环退出
                logger.exception("读取后台任务失败")
                job = None
            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._poll_interval)
                continue
            await self._run(job)

    async def _claim(self) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1, "
                "updated_at = now() WHERE id = (SELECT id FROM jobs WHERE status = 'queued' "
                "AND run_at <= now() ORDER BY run_at FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING id, kind, payload, attempts"
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def _run(self, job: dict[str, Any]) -> None:
        handler = self._handlers.get(job["kind"])
        try:
            if handler is None:
                await self._finish(job["id"], "failed", f"没有处理这类任务的程序：{job['kind']}")
                return
            await handler(job["payload"])
        except Exception as exc:  # 后台任务边界：一个任务出错不影响后面的任务
            logger.exception("后台任务 %s（%s）失败", job["id"], job["kind"])
            if job["attempts"] >= self._max_attempts:
                await self._finish(job["id"], "failed", str(exc))
            else:
                await self._retry(job["id"], str(exc), delay=self._retry_delay * job["attempts"])
            return
        await self._finish(job["id"], "done", None)

    async def _finish(self, job_id: UUID, status: str, error: str | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = %s, last_error = %s, locked_at = NULL, "
                "updated_at = now() WHERE id = %s",
                (status, error, job_id),
            )

    async def _retry(self, job_id: UUID, error: str, *, delay: float) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'queued', last_error = %s, locked_at = NULL, "
                "run_at = now() + make_interval(secs => %s), updated_at = now() WHERE id = %s",
                (error, delay, job_id),
            )
        self._wake.set()
```

在 `backend/runtime/__init__.py` 中，把：

```python
"""运行时替换点（见设计文档 10.9）：v1 为单进程内存实现。"""

from backend.runtime.envelope import EventEnvelope
from backend.runtime.event_bus import EventBus, InMemoryEventBus
from backend.runtime.run_control import InProcessRunControl, RunControl

__all__ = ["EventBus", "EventEnvelope", "InMemoryEventBus", "InProcessRunControl", "RunControl"]
```

改为：

```python
"""运行时替换点（见设计文档 10.9）：v1 为单进程实现（内存 + 数据库表）。"""

from backend.runtime.envelope import EventEnvelope
from backend.runtime.event_bus import EventBus, InMemoryEventBus
from backend.runtime.jobs import JobHandler, JobQueue, TableJobQueue
from backend.runtime.run_control import InProcessRunControl, RunControl

__all__ = [
    "EventBus",
    "EventEnvelope",
    "InMemoryEventBus",
    "InProcessRunControl",
    "JobHandler",
    "JobQueue",
    "RunControl",
    "TableJobQueue",
]
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest -m integration backend/tests/test_job_queue.py backend/tests/test_migrations.py -q`

预期：全部通过。任务队列此时还没有接进服务启动流程（任务 5 接入）。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 180 个、前端 82 个）；`make test-int` 全部通过（集成测试 81 个）。

---

### 任务 4：智能体用上知识库

**文件：**
- 新建：`agents/main_agent/runtime/knowledge.py`、`agents/tests/test_knowledge_runtime.py`
- 修改：
  - agents：`context.py`、`runtime/events.py`、`runtime/translator.py`、`runtime/agent.py`、`runtime/__init__.py`、`bootstrap.py`、`prompts/system.md`、测试 `fakes.py`、`test_bootstrap.py`、`test_subagents.py`；
  - config：`settings.py`、`app.yaml`、`tests/test_settings.py`；
  - backend：`tests/test_openapi.py`；
  - frontend：`src/features/chat/reducer.ts`（及测试）、`src/components/chat/adapter.ts`（及测试）、`parts.tsx`、`src/api/generated/*`（命令生成）。

**接口：**
- 消费：任务 1 的 `LiteLLMProxyEmbedder`；任务 2 的 `KnowledgeStore`、`PgKnowledgeStore`、`NewKnowledge`、`KnowledgeHit`。
- 产出（配置）：`KnowledgeConfig(embedding_model="embed-qwen3-0.6b", recall_top_k=5, recall_min_similarity=0.3, pinned_token_limit=2000, auto_extract=True)`，即 `Settings.knowledge`；`AdaptersConfig.embedder = "litellm_proxy"`、`knowledge_index = "pgvector"`。
- 产出（agents）：
  - `AgentContext.knowledge: str = ""`（运行开始时查好的常驻条目与相关记忆）；
  - 事件 `MemorySaved(type="memory.saved", item_id, content, tags, pinned)`，紧跟在 `remember` 的 `tool.finished` 之后；
  - `MainAgent(..., knowledge: KnowledgeStore | None = None, knowledge_options: KnowledgeConfig | None = None)`，属性 `MainAgent.knowledge`；
  - 工具 `remember(content, tags=None, pinned=False)`（来源记为 `conversation`，带会话、运行 ID）与 `search_knowledge(query, kinds=None, tags=None, top_k=5)`；出错时工具结果标为出错并说明原因。
- 产出（测试替身）：`FakeKnowledgeStore(*, broken_recall=False)`，条目在 `.items`（ID → 条目）；内容与查询有相同的两个连续字就算相关。
- 产出（前端）：对话项 `{kind: "memory", id: "memory-<条目 ID>", content, pinned}`；助手消息的数据片段 `data-memory`（`MemoryNoteData {content, pinned}`）。

- [ ] **步骤 1：写失败的测试**

测试替身：内存里的知识存储：

在 `agents/tests/fakes.py` 中，把：

```python
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

```

改为：

```python
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

```

在 `agents/tests/fakes.py` 中，把：

```python

from agents.main_agent.models import EMBEDDING_DIMENSIONS, ModelInfo
from agents.main_agent.workspace import CommandResult
from common.errors import UpstreamError

```

改为：

```python

from agents.main_agent.knowledge import KnowledgeHit, KnowledgeItem, KnowledgeKind, NewKnowledge
from agents.main_agent.models import EMBEDDING_DIMENSIONS, ModelInfo
from agents.main_agent.workspace import CommandResult
from common.errors import NotFoundError, UpstreamError

```

在 `agents/tests/fakes.py` 末尾追加：

```python


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


class FakeKnowledgeStore:
    """内存里的知识存储（单元测试用，不需要数据库与向量模型）。

    检索与召回：内容与查询有相同的两个连续字（如"狗叫"）就算相关，得分为相同的个数。
    broken_recall=True 时召回抛出 UpstreamError，模拟向量化服务不可用。
    """

    def __init__(self, *, broken_recall: bool = False) -> None:
        self.items: dict[UUID, KnowledgeItem] = {}
        self._broken_recall = broken_recall

    async def add(self, new: NewKnowledge) -> KnowledgeItem:
        now = datetime.now(UTC)
        item = KnowledgeItem(
            id=uuid4(),
            kind=new.kind,
            tags=new.tags,
            pinned=new.pinned,
            content=new.content,
            source=new.source,
            source_thread_id=new.source_thread_id,
            source_run_id=new.source_run_id,
            document_id=None,
            token_count=len(new.content),
            embedding_model="fake-embedding",
            created_at=now,
            updated_at=now,
        )
        self.items[item.id] = item
        return item

    async def get(self, item_id: UUID) -> KnowledgeItem:
        if item_id not in self.items:
            raise NotFoundError(f"知识条目不存在：{item_id}")
        return self.items[item_id]

    async def update(
        self,
        item_id: UUID,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> KnowledgeItem:
        item = await self.get(item_id)
        changes: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if content is not None:
            changes["content"] = content
        if tags is not None:
            changes["tags"] = tags
        if pinned is not None:
            changes["pinned"] = pinned
        self.items[item_id] = item.model_copy(update=changes)
        return self.items[item_id]

    async def delete(self, item_id: UUID) -> None:
        await self.get(item_id)
        del self.items[item_id]

    async def list_items(
        self,
        *,
        kind: KnowledgeKind | None = None,
        tags: Sequence[str] = (),
        pinned: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        found = [
            item
            for item in reversed(self.items.values())
            if (kind is None or item.kind == kind)
            and set(tags) <= set(item.tags)
            and (pinned is None or item.pinned == pinned)
        ]
        return found[offset : offset + limit]

    async def pinned(self) -> list[KnowledgeItem]:
        return [item for item in self.items.values() if item.pinned]

    async def search(
        self,
        query: str,
        *,
        kinds: Sequence[KnowledgeKind] | None = None,
        tags: Sequence[str] = (),
        top_k: int = 5,
    ) -> list[KnowledgeHit]:
        hits = [
            KnowledgeHit(item=item, score=float(len(_bigrams(query) & _bigrams(item.content))))
            for item in self.items.values()
            if (kinds is None or item.kind in kinds) and set(tags) <= set(item.tags)
        ]
        hits = [hit for hit in hits if hit.score > 0]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    async def recall(self, query: str, *, top_k: int, min_similarity: float) -> list[KnowledgeHit]:
        if self._broken_recall:
            raise UpstreamError("向量化服务不可用：connection refused")
        return await self.search(query, kinds=["memory"], top_k=top_k)
```

新建 `agents/tests/test_knowledge_runtime.py`：

```python
"""智能体用上知识库（设计文档 8.2、8.3）：记住、检索；常驻条目与相关记忆拼进系统提示词。"""

import uuid

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.knowledge import NewKnowledge
from agents.main_agent.runtime import MainAgent, MemorySaved, RunFinished, ToolFinished
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    FakeGateway,
    FakeKnowledgeStore,
    FakeSandbox,
    ScriptedChatModel,
    call,
)
from config.settings import KnowledgeConfig

SHORT = "c_000000c1"


def _agent(model: ScriptedChatModel, store: FakeKnowledgeStore, tmp_path: object) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),  # type: ignore[arg-type]
        knowledge=store,
        knowledge_options=KnowledgeConfig(recall_top_k=5, recall_min_similarity=1.0),
    )


async def _run(agent: MainAgent, message: str, run_id: str | None = None) -> list[object]:
    thread_id, run = str(uuid.UUID(int=1)), run_id or str(uuid.uuid4())
    return [
        e
        async for e in agent.run(
            thread_id=thread_id, thread_short_id=SHORT, run_id=run, message=message, model="m"
        )
    ]


async def test_remember_saves_a_memory_and_announces_it(tmp_path: object) -> None:
    store = FakeKnowledgeStore()
    model = ScriptedChatModel(
        responses=[
            call("remember", {"content": "用户对花生过敏", "tags": ["健康"], "pinned": True}),
            AIMessage("记住了"),
        ]
    )
    run_id = str(uuid.uuid4())
    events = await _run(_agent(model, store, tmp_path), "记住我对花生过敏", run_id)
    [item] = store.items.values()
    assert (item.content, item.tags, item.pinned, item.source) == (
        "用户对花生过敏",
        ["健康"],
        True,
        "conversation",
    )
    assert (item.source_thread_id, str(item.source_run_id)) == (uuid.UUID(int=1), run_id)
    kinds = [type(e) for e in events]
    assert kinds.index(MemorySaved) == kinds.index(ToolFinished) + 1  # 工具结束后紧跟"已记住"
    saved = next(e for e in events if isinstance(e, MemorySaved))
    assert (saved.item_id, saved.content, saved.pinned) == (str(item.id), "用户对花生过敏", True)


async def test_pinned_items_and_related_memories_reach_the_model(tmp_path: object) -> None:
    store = FakeKnowledgeStore()
    await store.add(NewKnowledge(content="用户希望回答简洁", pinned=True, source="manual"))
    await store.add(NewKnowledge(content="用户养了一只狗叫豆豆", source="manual"))
    await store.add(NewKnowledge(content="用户在做后端开发", source="manual"))
    model = ScriptedChatModel(responses=[AIMessage("豆豆")])
    await _run(_agent(model, store, tmp_path), "我家狗叫什么")
    system = model.received[0][0]
    assert isinstance(system, SystemMessage)
    text = str(system.content)
    assert "用户希望回答简洁" in text
    assert "用户养了一只狗叫豆豆" in text
    assert "用户在做后端开发" not in text  # 与这句话无关的记忆不带


async def test_search_knowledge_tool_lists_what_it_found(tmp_path: object) -> None:
    store = FakeKnowledgeStore()
    await store.add(
        NewKnowledge(content="线上偶发 ERR_CONN_RESET 报错", tags=["工作"], source="manual")
    )
    model = ScriptedChatModel(
        responses=[call("search_knowledge", {"query": "ERR_CONN_RESET 怎么排查"}), AIMessage("好")]
    )
    events = await _run(_agent(model, store, tmp_path), "查一下那个报错")
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert "线上偶发 ERR_CONN_RESET 报错" in finished.output
    assert "工作" in finished.output


async def test_recall_failure_does_not_stop_the_run(tmp_path: object) -> None:
    """向量化服务不可用时照常回答（常驻条目仍然带上），只是这次没有相关记忆。"""
    store = FakeKnowledgeStore(broken_recall=True)
    await store.add(NewKnowledge(content="用户希望回答简洁", pinned=True, source="manual"))
    model = ScriptedChatModel(responses=[AIMessage("好")])
    events = await _run(_agent(model, store, tmp_path), "你好")
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"
    assert "用户希望回答简洁" in str(model.received[0][0].content)


async def test_failed_remember_is_reported_to_the_model_without_stopping(tmp_path: object) -> None:
    """记不下来（如内容为空、向量化服务不可用）时：工具结果标为出错并说明原因，不推送"已记住"。"""
    store = FakeKnowledgeStore()
    model = ScriptedChatModel(responses=[call("remember", {"content": "  "}), AIMessage("好")])
    events = await _run(_agent(model, store, tmp_path), "记住这个")
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert finished.status == "error"
    assert "没有记住" in finished.output
    assert not any(isinstance(e, MemorySaved) for e in events)
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"
    assert store.items == {}
```

系统提示词要讲到两个新工具；组装根装配知识存储；项目配置；事件清单多了 `memory.saved`：

在 `agents/tests/test_subagents.py` 中，把：

```python
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in ("execute", "uploads/", "outputs/", "data_analyst", "/skills/"):
        assert phrase in prompt, phrase
```

改为：

```python
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in (
        "execute",
        "uploads/",
        "outputs/",
        "data_analyst",
        "/skills/",
        "remember",
        "search_knowledge",
    ):
        assert phrase in prompt, phrase
```

在 `agents/tests/test_bootstrap.py` 中，把：

```python
from agents.main_agent.bootstrap import build_agent
from agents.main_agent.models import LiteLLMProxyGateway
```

改为：

```python
from agents.main_agent.bootstrap import build_agent
from agents.main_agent.knowledge import PgKnowledgeStore
from agents.main_agent.models import LiteLLMProxyGateway
```

在 `agents/tests/test_bootstrap.py` 中，把：

```python
    assert isinstance(agent.workspace, LocalWorkspace)  # 配置 adapters.workspace: docker_local
    async with pg_pool.connection() as conn:
```

改为：

```python
    assert isinstance(agent.workspace, LocalWorkspace)  # 配置 adapters.workspace: docker_local
    assert isinstance(agent.knowledge, PgKnowledgeStore)  # 配置 adapters.knowledge_index: pgvector
    async with pg_pool.connection() as conn:
```

在 `config/tests/test_settings.py` 末尾追加：

```python


def test_project_config_for_the_knowledge_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """项目的 app.yaml：向量模型经网关调用；相关记忆取前 5 条、相似度下限 0.3
    （探测后定的，见 M3a 计划）。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    settings = _settings_from(Path(__file__).resolve().parents[1] / "app.yaml")
    assert (settings.adapters.embedder, settings.adapters.knowledge_index) == (
        "litellm_proxy",
        "pgvector",
    )
    knowledge = settings.knowledge
    assert knowledge.embedding_model == "embed-qwen3-0.6b"
    assert (knowledge.recall_top_k, knowledge.recall_min_similarity) == (5, 0.3)
    assert (knowledge.pinned_token_limit, knowledge.auto_extract) == (2000, True)
```

在 `backend/tests/test_openapi.py` 中，把：

```python
        "file.created",
        "run.finished",
```

改为：

```python
        "file.created",
        "memory.saved",
        "run.finished",
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_knowledge_runtime.py agents/tests/test_subagents.py config/tests/test_settings.py backend/tests/test_openapi.py -q`（预期失败）

预期：
- `test_knowledge_runtime.py` 收集阶段报错 `ImportError: cannot import name 'MemorySaved'`；
- 系统提示词里没有 `remember`；`Settings` 没有 `knowledge`；事件清单里没有 `memory.saved`。

- [ ] **步骤 3：实现 agents 与配置**

新建 `agents/main_agent/runtime/knowledge.py`：

```python
"""智能体用上知识库（设计文档 8.2、8.3）。

- 两个工具：记住（remember）、检索知识（search_knowledge）。
- 每次运行开始时查好常驻条目（个人画像）与和这句话相关的记忆，由中间件拼进系统提示词。
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools import ToolRuntime
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import ValidationError

from agents.main_agent.context import AgentContext
from agents.main_agent.knowledge import (
    KnowledgeHit,
    KnowledgeItem,
    KnowledgeKind,
    KnowledgeStore,
    NewKnowledge,
)
from common.errors import UpstreamError

REMEMBER_TOOL = "remember"
SEARCH_TOOL = "search_knowledge"
_MAX_TOP_K = 20


def knowledge_tools(store: KnowledgeStore) -> list[BaseTool]:
    @tool(REMEMBER_TOOL, response_format="content_and_artifact")
    async def remember(
        content: str,
        runtime: ToolRuntime[AgentContext],
        tags: list[str] | None = None,
        pinned: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """记住一条关于用户的长期信息（偏好、习惯、个人情况、约定等），以后的对话里会自动想起。

        content：一句完整的话，脱离这次对话也能看懂，如"用户对花生过敏"。
        tags：可选的标签，如 ["健康"]。
        pinned：设为常驻（每次对话都带上）。只用于很重要、长期有效的信息，如身份、回答风格要求。
        """
        context = runtime.context
        try:
            item = await store.add(
                NewKnowledge(
                    content=content,
                    tags=tags or [],
                    pinned=pinned,
                    source="conversation",
                    source_thread_id=_uuid(context.thread_id),
                    source_run_id=_uuid(context.run_id),
                )
            )
        except (ValidationError, UpstreamError) as exc:
            raise ToolException(f"没有记住：{exc}") from exc
        return f"已记住：{item.content}", item.model_dump(mode="json")

    @tool(SEARCH_TOOL)
    async def search_knowledge(
        query: str,
        kinds: list[KnowledgeKind] | None = None,
        tags: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """在用户的知识库里查找与问题相关的内容（记住的事情、知识）。

        query：要找什么，自然语言或关键词都可以（人名、型号、报错码等精确词也能找到）。
        kinds：只找某几种，memory 为记忆，document_chunk 为文档片段；不填时都找。
        tags：只在带这些标签的条目里找。
        top_k：最多返回几条（1～20）。
        """
        try:
            hits = await store.search(
                query, kinds=kinds, tags=tags or [], top_k=max(1, min(top_k, _MAX_TOP_K))
            )
        except UpstreamError as exc:
            raise ToolException(str(exc)) from exc
        if not hits:
            return "没有找到相关的知识。"
        return "\n".join(_describe(hit.item) for hit in hits)

    tools: list[BaseTool] = [remember, search_knowledge]
    for item in tools:
        item.handle_tool_error = True  # 出错时把原因交给模型（工具结果标为出错），运行不中断
    return tools


def knowledge_prompt(pinned: Sequence[KnowledgeItem], recalled: Sequence[KnowledgeHit]) -> str:
    """拼进系统提示词的一段：常驻条目（个人画像）与相关记忆。两者都没有时为空。"""
    pinned_ids = {item.id for item in pinned}
    related = [hit.item for hit in recalled if hit.item.id not in pinned_ids]
    sections: list[str] = []
    if pinned:
        lines = "\n".join(f"- {item.content}" for item in pinned)
        sections.append(f"关于用户（常驻信息，始终有效）：\n{lines}")
    if related:
        lines = "\n".join(
            f"- {item.content}（记于 {item.created_at:%Y-%m-%d}）" for item in related
        )
        sections.append(f"可能与这次对话相关的记忆（不一定相关，自行判断）：\n{lines}")
    return "\n\n".join(sections)


class KnowledgeContextMiddleware(AgentMiddleware):
    """每次调用模型前，把本次运行查好的常驻条目与相关记忆拼到系统提示词末尾。"""

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._with_knowledge(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._with_knowledge(request))

    @staticmethod
    def _with_knowledge(request: ModelRequest) -> ModelRequest:
        knowledge = cast(AgentContext, request.runtime.context).knowledge
        if not knowledge:
            return request
        base = request.system_prompt or ""
        return request.override(system_message=SystemMessage(content=f"{base}\n\n{knowledge}"))


def _describe(item: KnowledgeItem) -> str:
    tags = f"；标签：{'、'.join(item.tags)}" if item.tags else ""
    return f"- {item.content}（{_KIND_NAMES[item.kind]}，记于 {item.created_at:%Y-%m-%d}{tags}）"


_KIND_NAMES: dict[KnowledgeKind, str] = {"memory": "记忆", "document_chunk": "文档片段"}


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
```

在 `agents/main_agent/context.py` 末尾追加：

```python
    # 常驻条目与相关记忆（运行开始时查好，由 KnowledgeContextMiddleware 拼进系统提示词）
    knowledge: str = ""
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python

class RunFinished(_BaseEvent):
```

改为：

```python

class MemorySaved(_BaseEvent):
    """智能体用 remember 工具记下了一条记忆（设计文档 8.2），前端提示"已记住：xxx"。"""

    type: Literal["memory.saved"] = "memory.saved"
    item_id: str
    content: str
    tags: list[str]
    pinned: bool


class RunFinished(_BaseEvent):
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python
    | FileCreated
    | RunFinished,
```

改为：

```python
    | FileCreated
    | MemorySaved
    | RunFinished,
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    InterruptedUsage,
    MessageDelta,
```

改为：

```python
    InterruptedUsage,
    MemorySaved,
    MessageDelta,
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    "MainAgent",
    "MessageDelta",
```

改为：

```python
    "MainAgent",
    "MemorySaved",
    "MessageDelta",
```

`remember` 成功时，在它的 `tool.finished` 之后推送 `memory.saved`：

在 `agents/main_agent/runtime/translator.py` 中，把：

```python
    Event,
    MessageDelta,
```

改为：

```python
    Event,
    MemorySaved,
    MessageDelta,
```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python
)
from agents.main_agent.runtime.tracker import RunTracker, is_compaction
```

改为：

```python
)
from agents.main_agent.runtime.knowledge import REMEMBER_TOOL
from agents.main_agent.runtime.tracker import RunTracker, is_compaction
```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python
                    yield self._finished(message, path)

```

改为：

```python
                    yield self._finished(message, path)
                    if saved := _memory_saved(message, path):
                        yield saved

```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python

def _thinking_of(chunk: AIMessageChunk) -> str:
```

改为：

```python

def _memory_saved(message: ToolMessage, path: list[str]) -> MemorySaved | None:
    """remember 成功时工具结果附带记下的条目（工具的 artifact），据此推送"已记住"。"""
    item = message.artifact
    if message.name != REMEMBER_TOOL or message.status == "error" or not isinstance(item, dict):
        return None
    return MemorySaved(
        agent_path=path,
        item_id=str(item["id"]),
        content=str(item["content"]),
        tags=[str(tag) for tag in item["tags"]],
        pinned=bool(item["pinned"]),
    )


def _thinking_of(chunk: AIMessageChunk) -> str:
```

运行开始时查常驻条目与相关记忆（召回失败只记日志）；工具与中间件装进智能体：

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

改为：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.knowledge import KnowledgeHit, KnowledgeStore
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
)
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
```

改为：

```python
)
from agents.main_agent.runtime.knowledge import (
    KnowledgeContextMiddleware,
    knowledge_prompt,
    knowledge_tools,
)
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.workspace import Workspace, media_type

```

改为：

```python
from agents.main_agent.workspace import Workspace, media_type
from common.errors import UpstreamError
from config.settings import KnowledgeConfig

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
        subagents_dir: Path | None = None,
    ) -> None:
        self.models = gateway
        self.workspace = workspace
        self._checkpointer = checkpointer
```

改为：

```python
        subagents_dir: Path | None = None,
        knowledge: KnowledgeStore | None = None,
        knowledge_options: KnowledgeConfig | None = None,
    ) -> None:
        self.models = gateway
        self.workspace = workspace
        self.knowledge = knowledge
        self._knowledge_options = knowledge_options or KnowledgeConfig()
        self._checkpointer = checkpointer
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
            graph = self._graph_for(model)
            content = await user_content(
```

改为：

```python
            graph = self._graph_for(model)
            knowledge = await self._knowledge_for(message)
            content = await user_content(
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                version="v2",
                context=AgentContext(thread_id, thread_short_id, run_id),
            ):
```

改为：

```python
                version="v2",
                context=AgentContext(thread_id, thread_short_id, run_id, knowledge),
            ):
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

    def _graph_for(self, model: str) -> CompiledStateGraph[Any, Any, Any, Any]:
```

改为：

```python

    async def _knowledge_for(self, message: str) -> str:
        """常驻条目与和这句话相关的记忆（设计文档 8.3）。

        向量化服务不可用时只是这次没有相关记忆，照常回答；常驻条目不需要向量化，总会带上。
        """
        if self.knowledge is None:
            return ""
        pinned = await self.knowledge.pinned()
        recalled: list[KnowledgeHit] = []
        try:
            recalled = await self.knowledge.recall(
                message,
                top_k=self._knowledge_options.recall_top_k,
                min_similarity=self._knowledge_options.recall_min_similarity,
            )
        except UpstreamError:
            logger.warning("相关记忆召回失败（向量化服务不可用），本次运行不带相关记忆")
        return knowledge_prompt(pinned, recalled)

    def _graph_for(self, model: str) -> CompiledStateGraph[Any, Any, Any, Any]:
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                WorkDirectoryMiddleware(),
            ]
```

改为：

```python
                WorkDirectoryMiddleware(),
                KnowledgeContextMiddleware(),  # 常驻条目 + 相关记忆（设计文档 8.3）
            ]
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                system_prompt=self._system_prompt,
                middleware=middleware,
```

改为：

```python
                system_prompt=self._system_prompt,
                tools=knowledge_tools(self.knowledge) if self.knowledge else None,
                middleware=middleware,
```

在 `config/settings.py` 中，把：

```python
    workspace: str = "docker_local"

```

改为：

```python
    workspace: str = "docker_local"
    embedder: str = "litellm_proxy"
    knowledge_index: str = "pgvector"

```

在 `config/settings.py` 中，把：

```python
    max_upload_mb: int = 100  # 单个上传文件的上限

```

改为：

```python
    max_upload_mb: int = 100  # 单个上传文件的上限


class KnowledgeConfig(BaseModel):
    """统一知识库与记忆（设计文档 8）。"""

    embedding_model: str = "embed-qwen3-0.6b"  # 网关里的向量模型名（config/models.yaml）
    recall_top_k: int = 5  # 每次带上的相关记忆最多几条
    # 相关记忆的相似度下限：qwen3 0.6B 上真正相关的记忆只有 0.34～0.64，
    # 设计文档的 0.75 会什么都召回不到（M3a 计划的先行探测）
    recall_min_similarity: float = 0.3
    pinned_token_limit: int = 2000  # 常驻条目总量的建议上限，超出时知识库页提示精简
    auto_extract: bool = True  # 每次运行结束后自动从对话里提取记忆

```

在 `config/settings.py` 中，把：

```python
    workspace: WorkspaceConfig = WorkspaceConfig()
    security: SecurityConfig = SecurityConfig()
```

改为：

```python
    workspace: WorkspaceConfig = WorkspaceConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    security: SecurityConfig = SecurityConfig()
```

在 `config/app.yaml` 中，把：

```yaml
  workspace: docker_local # 本地数据卷 + Docker 沙箱（设计文档 9）

```

改为：

```yaml
  workspace: docker_local # 本地数据卷 + Docker 沙箱（设计文档 9）
  embedder: litellm_proxy # 向量化经模型网关（向量模型由 ollama 在本机运行）
  knowledge_index: pgvector # 知识条目存 PostgreSQL：向量检索 + 关键词检索（设计文档 8）

```

在 `config/app.yaml` 中，把：

```yaml
  default_model: claude-opus-4-6

```

改为：

```yaml
  default_model: claude-opus-4-6

# 统一知识库与记忆（设计文档 8）
knowledge:
  embedding_model: embed-qwen3-0.6b # config/models.yaml 里的向量模型名
  recall_top_k: 5 # 每次带上的相关记忆最多几条
  recall_min_similarity: 0.3 # 相关记忆的相似度下限（0～1）
  pinned_token_limit: 2000 # 常驻条目总量的建议上限（token），超出时知识库页提示精简
  auto_extract: true # 每次运行结束后自动从对话里提取记忆（false 为关闭）

```

在 `agents/main_agent/bootstrap.py` 中，把：

```python

from agents.main_agent.models import LiteLLMProxyGateway, ModelGateway
from agents.main_agent.runtime import MainAgent
```

改为：

```python

from agents.main_agent.knowledge import KnowledgeStore, PgKnowledgeStore
from agents.main_agent.models import (
    Embedder,
    LiteLLMProxyEmbedder,
    LiteLLMProxyGateway,
    ModelGateway,
)
from agents.main_agent.runtime import MainAgent
```

在 `agents/main_agent/bootstrap.py` 中，把：

```python

async def build_agent(settings: Settings, pool: Pool) -> MainAgent:
```

改为：

```python

_EMBEDDERS: dict[str, Callable[[Settings], Embedder]] = {
    "litellm_proxy": lambda s: LiteLLMProxyEmbedder(
        s.litellm_base_url, s.litellm_master_key.get_secret_value(), s.knowledge.embedding_model
    ),
}

_KNOWLEDGE_STORES: dict[str, Callable[[Pool, Embedder], KnowledgeStore]] = {
    "pgvector": PgKnowledgeStore,
}


async def build_agent(settings: Settings, pool: Pool) -> MainAgent:
```

在 `agents/main_agent/bootstrap.py` 中，把：

```python
        subagents_dir=settings.agent.subagents_dir,
    )
```

改为：

```python
        subagents_dir=settings.agent.subagents_dir,
        knowledge=_KNOWLEDGE_STORES[settings.adapters.knowledge_index](
            pool, _EMBEDDERS[settings.adapters.embedder](settings)
        ),
        knowledge_options=settings.knowledge,
    )
```

在 `agents/prompts/system.md` 末尾追加：

```markdown

记忆与知识：
- 用户让你记住什么，或者透露了以后用得上的长期信息（偏好、习惯、身份、家人、在做的事等），用 remember 工具记下来：一条只写一件事，写成脱离这次对话也能看懂的完整句子。一次性的问题、临时的内容不要记。只有身份、回答风格要求这类始终有效又很重要的信息才设为常驻（pinned）。
- 本提示末尾会列出关于用户的常驻信息和可能相关的记忆，回答时自然地用上，不要逐条复述。
- 需要用户以前告诉过你的信息、而末尾没有列出时，用 search_knowledge 在知识库里查。
```

事件定义改了，重新生成前端类型（`test_openapi.py` 会核对生成结果是否最新）：

运行：`make types`

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_knowledge_runtime.py agents/tests/test_subagents.py config/tests/test_settings.py backend/tests/test_openapi.py agents/tests/test_main_agent.py -q`

运行：`uv run pytest -m integration agents/tests/test_bootstrap.py -q`

预期：全部通过。

- [ ] **步骤 5：前端"已记住"**

在 `frontend/src/features/chat/reducer.test.ts` 末尾追加：

```ts

describe("已记住", () => {
  it("智能体记下一条记忆：在回答里显示一条已记住项", () => {
    const saved: EventEnvelope = {
      ...base,
      seq: 3,
      type: "memory.saved",
      data: { item_id: "k1", content: "用户对花生过敏", tags: ["健康"], pinned: true },
    };
    const state = [events[3], saved].reduce(applyEvent, emptyChat);
    expect(state.items).toEqual([
      { kind: "assistant", id: "msg-m1", text: "你" },
      { kind: "memory", id: "memory-k1", content: "用户对花生过敏", pinned: true },
    ]);
  });
});
```

在 `frontend/src/components/chat/adapter.test.ts` 末尾追加：

```ts

describe("已记住", () => {
  it("已记住项映射为记忆数据片段", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "记住我对花生过敏" },
        { kind: "memory", id: "memory-k1", content: "用户对花生过敏", pinned: false },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      { type: "data-memory", data: { content: "用户对花生过敏", pinned: false } },
    ]);
  });
});
```

运行：`cd frontend && pnpm exec vitest run src/features/chat/reducer.test.ts src/components/chat/adapter.test.ts`（预期失败）

预期：两个新测试失败（没有"已记住"项、没有 `data-memory` 片段）。

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  | { kind: "file"; id: string; fileId: string; path: string; size: number; mediaType: string }
  // 一轮运行的开始 / 结束时间（取自开始、结束事件），用于显示耗时
```

改为：

```ts
  | { kind: "file"; id: string; fileId: string; path: string; size: number; mediaType: string }
  // 智能体用 remember 记下的一条记忆（显示"已记住：xxx"）
  | { kind: "memory"; id: string; content: string; pinned: boolean }
  // 一轮运行的开始 / 结束时间（取自开始、结束事件），用于显示耗时
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
    }
  }
```

改为：

```ts
    }
    case "memory.saved": {
      const { item_id: itemId, content, pinned } = event.data;
      return [...items, { kind: "memory", id: `memory-${itemId}`, content, pinned }];
    }
  }
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
  downloadUrl: string;
}
```

改为：

```ts
  downloadUrl: string;
}

/** "已记住"提示的数据（数据片段 data-memory）。 */
export interface MemoryNoteData {
  content: string;
  pinned: boolean;
}
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
    }
    default:
```

改为：

```ts
    }
    case "memory": {
      const data: MemoryNoteData = { content: item.content, pinned: item.pinned };
      return [{ type: "data-memory", data }];
    }
    default:
```

回答里的"已记住"提示（绿色书签图标 + 一行小字，常驻的注明"常驻"）：

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
import {
  Bot,
```

改为：

```tsx
import {
  BookmarkCheck,
  Bot,
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  type FileCardData,
  type StepState,
```

改为：

```tsx
  type FileCardData,
  type MemoryNoteData,
  type StepState,
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

/** 运行中的已用时间，每秒刷新。 */
```

改为：

```tsx

/** 智能体记下了一条记忆（设计文档 8.2）：可在知识库页查看、修改或删除。 */
export const MemoryPart: DataMessagePartComponent = ({ data }) => {
  const memory = data as MemoryNoteData;
  return (
    <p className="my-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
      <BookmarkCheck className="mt-px size-3.5 shrink-0 text-success" />
      <span>
        已记住{memory.pinned ? "（常驻）" : ""}：{memory.content}
      </span>
    </p>
  );
};

/** 运行中的已用时间，每秒刷新。 */
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
        tools: { by_name: { [SUBAGENT_TOOL]: SubagentCard }, Fallback: ToolCard },
        data: { by_name: { todos: TodosPart, file: FilePart } },
      }}
```

改为：

```tsx
        tools: { by_name: { [SUBAGENT_TOOL]: SubagentCard }, Fallback: ToolCard },
        data: { by_name: { todos: TodosPart, file: FilePart, memory: MemoryPart } },
      }}
```

运行：`cd frontend && pnpm exec vitest run src/features/chat/reducer.test.ts src/components/chat/adapter.test.ts`

预期：全部通过。

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 186 个、前端 84 个）；`make test-int` 全部通过（集成测试 81 个）。

---

### 任务 5：会后自动提取记忆

**文件：**
- 新建：`agents/main_agent/knowledge/extraction.py`、`agents/tests/test_memory_extraction.py`、`backend/runs/followups.py`、`backend/tests/test_followups.py`
- 修改：`agents/main_agent/knowledge/__init__.py`、`agents/main_agent/runtime/agent.py`、`backend/runs/__init__.py`、`backend/runs/manager.py`、`backend/api/deps.py`、`backend/main.py`

**接口：**
- 消费：任务 2 的 `KnowledgeStore`；任务 3 的 `JobQueue`、`TableJobQueue`、`JobHandler`；已有的 `RunTracker`、`UsageRepo.add`、`RunRepo.get` / `events`。
- 产出（agents）：
  - `extract_memories(model, store, *, message, answer, thread_id: UUID, run_id: UUID, config=None) -> None`（`agents.main_agent.knowledge` 公开）：常驻条目只读（列出、不编号）；相近的已有记忆（最多 10 条，不含常驻）编号给模型；消息与回答各取前 4000 字；
  - `MainAgent.extract_memories(*, thread_id: str, run_id: str, model: str, message: str, answer: str) -> AsyncIterator[UsageReported]`：用会话所选的模型，输出这次的用量（调用方 `memory_extraction`）；失败时先输出已产生的用量再抛出异常。
- 产出（backend）：
  - `RunFollowups(*, runs, usage, agent, jobs, auto_extract)`（任务 6 加 `threads`）：`handlers() -> dict[str, JobHandler]`、`after_completed(run)`、`extract_memories(payload)`；任务种类 `memory_extraction`，内容 `{"run_id": "<运行 ID>"}`；
  - `RunManager(..., followups: RunFollowups | None = None)`：运行顺利结束、结果写库成功后、推送结束事件之前调用 `after_completed`（失败只记日志）；
  - `build_services(..., jobs: JobQueue | None = None)`；`Services.jobs`、`Services.followups`；启动时开始处理任务，停止时先收尾运行、再停任务队列。

- [ ] **步骤 1：写失败的测试（提取）**

新建 `agents/tests/test_memory_extraction.py`：

````python
"""会话后自动提取记忆（设计文档 8.2）：对照相近的已有记忆，按模型的决定新增 / 更新 / 删除。"""

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.knowledge import KnowledgeHit, NewKnowledge, extract_memories
from agents.main_agent.runtime import MainAgent
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeKnowledgeStore, FakeSandbox, ScriptedChatModel

THREAD, RUN = uuid.UUID(int=1), uuid.UUID(int=2)
MESSAGE = "我上个月换工作了，现在在字节做数据平台。另外我不喝咖啡了，改喝茶。"
ANSWER = "好的，恭喜换工作！"


def _reply(changes: list[dict[str, Any]], *, fenced: bool = False) -> AIMessage:
    text = json.dumps({"changes": changes}, ensure_ascii=False)
    return AIMessage(f"下面是结果：\n```json\n{text}\n```" if fenced else text)


async def _store() -> tuple[FakeKnowledgeStore, dict[str, uuid.UUID]]:
    store = FakeKnowledgeStore()
    ids = {}
    for content, pinned in [
        ("用户每天早上喝美式咖啡", False),
        ("用户的猫叫咪咪", False),
        ("用户希望回答简洁", True),
    ]:
        item = await store.add(NewKnowledge(content=content, pinned=pinned, source="manual"))
        ids[content] = item.id
    return store, ids


async def _extract(store: FakeKnowledgeStore, model: ScriptedChatModel) -> None:
    await extract_memories(
        model, store, message=MESSAGE, answer=ANSWER, thread_id=THREAD, run_id=RUN
    )


async def test_applies_the_changes_the_model_decides() -> None:
    store, ids = await _store()
    model = ScriptedChatModel(
        responses=[
            _reply(
                [
                    {"action": "update", "target": 1, "content": "用户不喝咖啡了，改喝茶"},
                    {"action": "add", "content": "用户在字节做数据平台", "tags": ["工作"]},
                ],
                fenced=True,  # 模型可能在 JSON 前后加说明或代码块标记
            )
        ]
    )
    await _extract(store, model)

    assert store.items[ids["用户每天早上喝美式咖啡"]].content == "用户不喝咖啡了，改喝茶"
    assert store.items[ids["用户的猫叫咪咪"]].content == "用户的猫叫咪咪"
    [added] = [item for item in store.items.values() if item.id not in ids.values()]
    assert (added.content, added.tags, added.pinned) == ("用户在字节做数据平台", ["工作"], False)
    assert (added.source, added.source_thread_id, added.source_run_id) == (
        "conversation",
        THREAD,
        RUN,
    )


async def test_model_sees_related_memories_numbered_and_pinned_ones_read_only() -> None:
    store, _ = await _store()
    model = ScriptedChatModel(responses=[_reply([])])
    await _extract(store, model)

    prompt = "\n".join(str(message.content) for message in model.received[0])
    assert "[1] 用户每天早上喝美式咖啡" in prompt
    assert "用户的猫叫咪咪" not in prompt  # 与这轮对话无关的记忆不给模型看
    assert "- 用户希望回答简洁" in prompt  # 常驻条目只读：列出来避免重复，但不编号、不能改
    assert "[2]" not in prompt
    assert MESSAGE in prompt
    assert ANSWER in prompt


async def test_delete_removes_an_outdated_memory() -> None:
    store, ids = await _store()
    model = ScriptedChatModel(responses=[_reply([{"action": "delete", "target": 1}])])
    await _extract(store, model)
    assert ids["用户每天早上喝美式咖啡"] not in store.items
    assert len(store.items) == 2


async def test_invalid_changes_are_skipped_and_the_rest_applied() -> None:
    """编号不存在、内容为空的改动跳过；常驻条目即使相关也改不到（不给编号）。"""
    store, ids = await _store()
    model = ScriptedChatModel(
        responses=[
            _reply(
                [
                    {"action": "update", "target": 9, "content": "不存在的编号"},
                    {"action": "delete", "target": None},
                    {"action": "add", "content": "  "},
                    {"action": "add", "content": "用户在字节做数据平台"},
                ]
            )
        ]
    )
    await _extract(store, model)
    contents = sorted(item.content for item in store.items.values())
    assert contents == sorted(
        ["用户每天早上喝美式咖啡", "用户的猫叫咪咪", "用户希望回答简洁", "用户在字节做数据平台"]
    )
    assert store.items[ids["用户希望回答简洁"]].pinned


async def test_memory_deleted_meanwhile_is_skipped() -> None:
    """提取期间用户在知识库页删掉了要更新的那条记忆：跳过它，其余改动照常写入。"""
    store, ids = await _store()
    search = store.search

    async def search_then_user_deletes(query: str, **options: Any) -> list[KnowledgeHit]:
        hits = await search(query, **options)
        await store.delete(ids["用户每天早上喝美式咖啡"])
        return hits

    store.search = search_then_user_deletes  # type: ignore[method-assign]
    model = ScriptedChatModel(
        responses=[
            _reply(
                [
                    {"action": "update", "target": 1, "content": "用户不喝咖啡了，改喝茶"},
                    {"action": "add", "content": "用户在字节做数据平台"},
                ]
            )
        ]
    )
    await _extract(store, model)
    assert sorted(item.content for item in store.items.values()) == sorted(
        ["用户的猫叫咪咪", "用户希望回答简洁", "用户在字节做数据平台"]
    )


async def test_unreadable_reply_changes_nothing() -> None:
    store, _ = await _store()
    before = dict(store.items)
    model = ScriptedChatModel(responses=[AIMessage("这轮对话没有需要记住的内容。")])
    await _extract(store, model)
    assert store.items == before


async def test_main_agent_reports_usage_as_memory_extraction(tmp_path: object) -> None:
    store, _ = await _store()
    reply = _reply([])
    reply.usage_metadata = {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}
    agent = MainAgent(
        gateway=FakeGateway(ScriptedChatModel(responses=[reply])),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),  # type: ignore[arg-type]
        knowledge=store,
    )
    usage = [
        u
        async for u in agent.extract_memories(
            thread_id=str(THREAD), run_id=str(RUN), model="m", message=MESSAGE, answer=ANSWER
        )
    ]
    assert [(u.caller, u.input_tokens, u.output_tokens) for u in usage] == [
        ("memory_extraction", 300, 20)
    ]
````

运行：`uv run pytest agents/tests/test_memory_extraction.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'extract_memories'`。

- [ ] **步骤 2：实现提取**

模型只回一段 JSON，由我们解析（见"先行探测结论"）：

新建 `agents/main_agent/knowledge/extraction.py`：

```python
"""会话后自动提取记忆（设计文档 8.2）。

读刚结束的一轮对话，对照与它相近的已有记忆，由模型决定"新增 / 更新已有 / 删除过时 / 忽略"，
避免重复和矛盾。常驻条目（个人画像）只读：列给模型看以免重复，但不给编号，改不到。

模型只回一段 JSON，由我们自己解析：先行探测里，结构化输出（with_structured_output）在部分模型上
不可靠（claude 返回空结果、gpt-5.5-pro 拒绝该格式），只回 JSON 在三个模型上都稳定。
"""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, ValidationError

from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.knowledge.models import KnowledgeItem, NewKnowledge
from common.errors import NotFoundError

logger = logging.getLogger(__name__)

_TEXT_LIMIT = 4000  # 用户消息、回答各取前这么多字（贴了长文时不必全给模型）
_QUERY_LIMIT = 2000  # 找相近记忆时用的文字长度
_CANDIDATES = 10  # 最多给模型看几条相近的已有记忆

EXTRACTION_PROMPT = "\n".join(
    [
        "你负责维护用户的长期记忆。读下面这一轮对话，找出值得长期记住的关于用户的信息"
        "（偏好、习惯、个人情况、身边的人、在做的事等），对照“已有记忆”决定：",
        '- 新信息：{"action": "add", "content": "一句完整的话，第三人称，如：用户对花生过敏", '
        '"tags": ["标签"]}',
        '- 与某条已有记忆矛盾，或是对它的更新：{"action": "update", "target": 编号, '
        '"content": "更新后的完整内容", "tags": ["标签"]}',
        '- 某条已有记忆明显过时、不再成立：{"action": "delete", "target": 编号}',
        "已经记过的不要重复记；“常驻信息”只读，不要重复记，也不能修改。"
        "临时的问题、闲聊、一次性任务的内容不要记；只记关于用户本人的信息，不记一般知识。",
        '只回复一个 JSON 对象，不要任何其他文字：{"changes": [...]}；'
        '没有要改的就回复 {"changes": []}。',
    ]
)


class MemoryChange(BaseModel):
    action: Literal["add", "update", "delete"]
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    target: int | None = None  # 更新、删除时：已有记忆的编号（从 1 开始）


class Extraction(BaseModel):
    changes: list[MemoryChange] = Field(default_factory=list)


async def extract_memories(
    model: BaseChatModel,
    store: KnowledgeStore,
    *,
    message: str,
    answer: str,
    thread_id: UUID,
    run_id: UUID,
    config: RunnableConfig | None = None,
) -> None:
    """从一轮对话里提取记忆并写入知识库。

    向量化服务、模型网关不可用时抛出 UpstreamError（由后台任务稍后重试）；
    模型的回复读不懂、个别改动无效时跳过并记日志，不重试（重试多半还是一样，白花钱）。
    """
    query = f"{message}\n{answer}"[:_QUERY_LIMIT]
    pinned = await store.pinned()
    hits = await store.search(query, kinds=["memory"], top_k=_CANDIDATES)
    existing = [hit.item for hit in hits if not hit.item.pinned]
    prompt = _prompt(message, answer, existing, pinned)
    reply = await model.ainvoke(
        [SystemMessage(EXTRACTION_PROMPT), HumanMessage(prompt)], config=config
    )
    extraction = _parse(_text_of(reply.content))
    if extraction is None:
        logger.warning("记忆提取：模型的回复无法解析，本次不改动记忆")
        return
    for change in extraction.changes:
        await _apply(store, change, existing, thread_id=thread_id, run_id=run_id)


def _prompt(
    message: str,
    answer: str,
    existing: Sequence[KnowledgeItem],
    pinned: Sequence[KnowledgeItem],
) -> str:
    pinned_lines = "\n".join(f"- {item.content}" for item in pinned) or "（无）"
    existing_lines = (
        "\n".join(f"[{number}] {item.content}" for number, item in enumerate(existing, 1))
        or "（无）"
    )
    return (
        f"常驻信息（只读）：\n{pinned_lines}\n\n"
        f"已有记忆：\n{existing_lines}\n\n"
        f"本轮对话：\n用户：{_clip(message)}\n助手：{_clip(answer)}"
    )


def _clip(text: str) -> str:
    return text if len(text) <= _TEXT_LIMIT else f"{text[:_TEXT_LIMIT]}……（后略）"


def _parse(text: str) -> Extraction | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        return Extraction.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError):
        return None


async def _apply(
    store: KnowledgeStore,
    change: MemoryChange,
    existing: Sequence[KnowledgeItem],
    *,
    thread_id: UUID,
    run_id: UUID,
) -> None:
    content = change.content.strip()
    if change.action == "add":
        if not content:
            logger.warning("记忆提取：跳过内容为空的新增")
            return
        await store.add(
            NewKnowledge(
                content=content[:20_000],
                tags=change.tags,
                source="conversation",
                source_thread_id=thread_id,
                source_run_id=run_id,
            )
        )
        return
    if change.target is None or not 1 <= change.target <= len(existing):
        logger.warning("记忆提取：跳过编号无效的改动 %s", change.target)
        return
    target = existing[change.target - 1]
    try:
        if change.action == "delete":
            await store.delete(target.id)
        elif content:
            await store.update(target.id, content=content[:20_000], tags=change.tags or None)
        else:
            logger.warning("记忆提取：跳过内容为空的更新")
    except NotFoundError:
        pass  # 这期间被用户在知识库页删掉了，不必再改


def _text_of(content: str | list[Any]) -> str:
    """回复的纯文本；内容块形式（如带思考过程的 Anthropic 回复）只取 text 块。"""
    if isinstance(content, str):
        return content
    return "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
```

在 `agents/main_agent/knowledge/__init__.py` 中，把：

```python
from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.knowledge.models import (
```

改为：

```python
from agents.main_agent.knowledge.base import KnowledgeStore
from agents.main_agent.knowledge.extraction import extract_memories
from agents.main_agent.knowledge.models import (
```

在 `agents/main_agent/knowledge/__init__.py` 中，把：

```python
    "PgKnowledgeStore",
]
```

改为：

```python
    "PgKnowledgeStore",
    "extract_memories",
]
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from typing import Any

```

改为：

```python
from typing import Any
from uuid import UUID

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.knowledge import KnowledgeHit, KnowledgeStore
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

改为：

```python
from agents.main_agent.context import AgentContext
from agents.main_agent.knowledge import KnowledgeHit, KnowledgeStore, extract_memories
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    ToolFinished,
)
```

改为：

```python
    ToolFinished,
    UsageReported,
)
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
logger = logging.getLogger(__name__)

```

改为：

```python
logger = logging.getLogger(__name__)

MEMORY_EXTRACTION = "memory_extraction"  # 会后提取记忆的模型调用在用量表里的调用方

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

    async def _keep_partial_answer(
```

改为：

```python

    async def extract_memories(
        self, *, thread_id: str, run_id: str, model: str, message: str, answer: str
    ) -> AsyncIterator[UsageReported]:
        """从刚结束的一轮对话里提取记忆（设计文档 8.2，由后台任务调用），输出这次的模型用量。

        用会话所选的模型（M3 决定，不另配便宜模型）。失败时先输出已产生的用量，再把异常抛给调用方。
        """
        if self.knowledge is None:
            return
        tracker = RunTracker(calibration=self._calibration, model_info=self.models.model_info)
        try:
            await extract_memories(
                self.models.chat_model(model),
                self.knowledge,
                message=message,
                answer=answer,
                thread_id=UUID(thread_id),
                run_id=UUID(run_id),
                config={"callbacks": [tracker], "metadata": {"lc_agent_name": MEMORY_EXTRACTION}},
            )
        except Exception:
            for usage in tracker.drain_usage():
                yield usage
            raise
        for usage in tracker.drain_usage():
            yield usage

    async def _keep_partial_answer(
```

运行：`uv run pytest agents/tests/test_memory_extraction.py -q`

预期：7 个测试通过。

- [ ] **步骤 3：写失败的测试（后台任务）**

新建 `backend/tests/test_followups.py`：

```python
"""运行顺利结束后的后台小事：自动提取记忆（设计文档 8.2）。"""

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

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace, WorkspaceFileRepo
from agents.tests.fakes import (
    FailingChatModel,
    FakeGateway,
    FakeKnowledgeStore,
    FakeSandbox,
    ScriptedChatModel,
)
from backend.runs import RunCreate, RunFollowups, RunManager, RunRepo
from backend.runtime import InMemoryEventBus, InProcessRunControl, JobHandler
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
    def __init__(self, db: Pool, model: BaseChatModel, *, auto_extract: bool = True) -> None:
        self.store = FakeKnowledgeStore()
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
        )
        self.followups = RunFollowups(
            runs=self.runs, usage=self.usage, agent=agent, jobs=self.jobs, auto_extract=auto_extract
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

    async def run(self, message: str) -> UUID:
        """发起一次运行并等它结束（收到结束事件时，后续任务已经登记）。"""
        thread = await self.threads.create(model="m")
        run = await self.manager.start(thread.id, RunCreate(message=message))
        async for _ in self.manager.stream(run.id):
            pass
        return run.id


def _extraction(changes: list[dict[str, Any]]) -> AIMessage:
    return AIMessage(
        json.dumps({"changes": changes}, ensure_ascii=False),
        usage_metadata={"input_tokens": 300, "output_tokens": 20, "total_tokens": 320},
    )


async def test_completed_run_queues_memory_extraction(db: Pool) -> None:
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]))
    run_id = await setup.run("你好")
    assert setup.jobs.enqueued == [("memory_extraction", {"run_id": str(run_id)})]


async def test_failed_run_or_switched_off_extraction_queues_nothing(db: Pool) -> None:
    failed = _Setup(db, FailingChatModel(responses=[]))
    await failed.run("你好")
    assert failed.jobs.enqueued == []

    off = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), auto_extract=False)
    await off.run("你好")
    assert off.jobs.enqueued == []


async def test_extraction_job_reads_the_conversation_and_records_usage(db: Pool) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage("恭喜你换了新工作！"),
            _extraction([{"action": "add", "content": "用户在字节做数据平台", "tags": ["工作"]}]),
        ]
    )
    setup = _Setup(db, model)
    run_id = await setup.run("我换工作了，现在在字节做数据平台")

    [(kind, payload)] = setup.jobs.enqueued
    await setup.followups.handlers()[kind](payload)

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
```

运行：`uv run pytest -m integration backend/tests/test_followups.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'RunFollowups' from 'backend.runs'`。

- [ ] **步骤 4：实现后续任务并接进服务**

新建 `backend/runs/followups.py`：

```python
"""运行顺利结束后的后台小事（M3）：自动提取记忆（设计文档 8.2）。

运行结束时只登记后台任务（jobs 表），由任务队列在后台执行：不拖慢回答，进程重启后也会接着做。
"""

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
from backend.runs.repo import RunRepo
from backend.runs.schemas import RunRecord
from backend.runtime import EventEnvelope, JobHandler, JobQueue
from common.errors import NotFoundError

logger = logging.getLogger(__name__)

MEMORY_EXTRACTION = "memory_extraction"


class RunFollowups:
    def __init__(
        self,
        *,
        runs: RunRepo,
        usage: UsageRepo,
        agent: MainAgent,
        jobs: JobQueue,
        auto_extract: bool,
    ) -> None:
        self._runs = runs
        self._usage = usage
        self._agent = agent
        self._jobs = jobs
        self._auto_extract = auto_extract

    def handlers(self) -> dict[str, JobHandler]:
        """交给任务队列的处理程序：任务种类 → 处理函数。"""
        return {MEMORY_EXTRACTION: self.extract_memories}

    async def after_completed(self, run: RunRecord) -> None:
        """一次运行顺利结束（停止、失败的不算）：登记它的后续任务。"""
        if self._auto_extract and self._agent.knowledge is not None:
            await self._jobs.enqueue(MEMORY_EXTRACTION, {"run_id": str(run.id)})

    async def extract_memories(self, payload: dict[str, Any]) -> None:
        """从这次运行的对话里提取记忆，用量记在这次运行名下（调用方 memory_extraction）。"""
        try:
            run = await self._runs.get(UUID(payload["run_id"]))
        except NotFoundError:
            return  # 会话已被删除：没什么可提取的
        answer = _answer(await self._runs.events(run.id))
        async for usage in self._agent.extract_memories(
            thread_id=str(run.thread_id),
            run_id=str(run.id),
            model=run.model,
            message=run.message,
            answer=answer,
        ):
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=usage)


def _answer(events: Sequence[EventEnvelope]) -> str:
    """主智能体这次的回答全文：界面历史里的回答片段按出现顺序拼接（子智能体内部的不算）。"""
    texts: dict[str, str] = {}
    for event in events:
        if event.type != "message.delta" or len(event.agent_path) != 1:
            continue
        key, text = event.data["message_id"], event.data["text"]
        # 合并过的片段（full_text）带着这段回答到此为止的全文
        texts[key] = text if event.data.get("full_text") else texts.get(key, "") + text
    return "\n\n".join(texts.values())
```

在 `backend/runs/__init__.py` 中，把：

```python

from backend.runs.manager import RunManager
```

改为：

```python

from backend.runs.followups import RunFollowups
from backend.runs.manager import RunManager
```

在 `backend/runs/__init__.py` 中，把：

```python

__all__ = ["RunAttachment", "RunCreate", "RunHistory", "RunManager", "RunRecord", "RunRepo"]
```

改为：

```python

__all__ = [
    "RunAttachment",
    "RunCreate",
    "RunFollowups",
    "RunHistory",
    "RunManager",
    "RunRecord",
    "RunRepo",
]
```

在 `backend/runs/manager.py` 中，把：

```python
from agents.main_agent.workspace import WorkspaceFileRepo, workspace_file_id
from backend.runs.repo import RunRepo
```

改为：

```python
from agents.main_agent.workspace import WorkspaceFileRepo, workspace_file_id
from backend.runs.followups import RunFollowups
from backend.runs.repo import RunRepo
```

在 `backend/runs/manager.py` 中，把：

```python
        flush_interval: float = 0.2,
    ) -> None:
```

改为：

```python
        flush_interval: float = 0.2,
        followups: RunFollowups | None = None,
    ) -> None:
```

在 `backend/runs/manager.py` 中，把：

```python
        self._flush_interval = flush_interval
        self._stopping = False
```

改为：

```python
        self._flush_interval = flush_interval
        self._followups = followups
        self._stopping = False
```

在 `backend/runs/manager.py` 中，把：

```python
            logger.exception("运行 %s 的结果写入数据库失败", run_id)
        finally:
```

改为：

```python
            logger.exception("运行 %s 的结果写入数据库失败", run_id)
        else:
            if finished.status == "completed" and self._followups is not None:
                try:
                    # 在推送结束事件之前登记：前端收到结束事件时，后续任务已经在队列里
                    await self._followups.after_completed(run)
                except Exception:  # 后台任务边界：登记失败只是少了后续任务，不影响这次运行
                    logger.exception("运行 %s 的后续任务登记失败", run_id)
        finally:
```

在 `backend/api/deps.py` 中，把：

```python
from agents.main_agent.workspace import WorkspaceFileRepo
from backend.runs import RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus, InProcessRunControl
from backend.threads import ThreadRepo
```

改为：

```python
from agents.main_agent.workspace import WorkspaceFileRepo
from backend.runs import RunFollowups, RunManager, RunRepo
from backend.runtime import EventBus, InMemoryEventBus, InProcessRunControl, JobQueue, TableJobQueue
from backend.threads import ThreadRepo
```

在 `backend/api/deps.py` 中，把：

```python
    manager: RunManager


def build_services(
    settings: Settings, pool: Pool, agent: MainAgent, *, bus: EventBus | None = None
) -> Services:
```

改为：

```python
    manager: RunManager
    jobs: JobQueue
    followups: RunFollowups


def build_services(
    settings: Settings,
    pool: Pool,
    agent: MainAgent,
    *,
    bus: EventBus | None = None,
    jobs: JobQueue | None = None,
) -> Services:
```

在 `backend/api/deps.py` 中，把：

```python
    files = WorkspaceFileRepo(pool)
    manager = RunManager(
```

改为：

```python
    files = WorkspaceFileRepo(pool)
    jobs = jobs or TableJobQueue(pool)
    followups = RunFollowups(
        runs=runs,
        usage=usage,
        agent=agent,
        jobs=jobs,
        auto_extract=settings.knowledge.auto_extract,
    )
    manager = RunManager(
```

在 `backend/api/deps.py` 中，把：

```python
        control=InProcessRunControl(),
    )
```

改为：

```python
        control=InProcessRunControl(),
        followups=followups,
    )
```

在 `backend/api/deps.py` 中，把：

```python
        manager=manager,
    )
```

改为：

```python
        manager=manager,
        jobs=jobs,
        followups=followups,
    )
```

在 `backend/main.py` 中，把：

```python
        await services.runs.fail_unfinished()
        app.state.services = services
```

改为：

```python
        await services.runs.fail_unfinished()
        await services.jobs.start(services.followups.handlers())
        app.state.services = services
```

在 `backend/main.py` 中，把：

```python
            await services.manager.shutdown()  # 关闭连接池之前，让进行中的运行写完结果
    finally:
```

改为：

```python
            await services.manager.shutdown()  # 关闭连接池之前，让进行中的运行写完结果
            await services.jobs.stop()  # 正在做的后台任务下次启动时重做
    finally:
```

运行：`uv run pytest -m integration backend/tests/test_followups.py backend/tests/test_manager.py -q`

预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 193 个、前端 84 个）；`make test-int` 全部通过（集成测试 85 个）。

---

### 任务 6：会话标题

**文件：**
- 新建：`agents/main_agent/runtime/titles.py`、`agents/tests/test_titles.py`、`frontend/src/features/threads/titleRefresh.ts`（及测试）
- 修改：
  - agents：`runtime/translator.py`、`runtime/agent.py`、`runtime/__init__.py`；
  - backend：`runs/followups.py`、`runs/repo.py`、`threads/repo.py`、`threads/__init__.py`、`api/deps.py`、`tests/test_followups.py`；
  - frontend：`src/features/chat/ChatView.tsx`。

**接口：**
- 消费：任务 5 的 `RunFollowups`、`_answer`（回答全文）；已有的 `ThreadRepo.touch`（标题为空时填首条消息的前 30 个字）、`threadsQuery`。
- 产出（agents）：
  - `clean_title(text) -> str`（`agents.main_agent.runtime` 公开）：取第一行，去掉"标题："前缀、外面的引号书名号与结尾标点，最长 30 个字；
  - `MainAgent.generate_title(*, model, message, answer) -> tuple[str, list[UsageReported]]`（调用方 `title`；模型什么都没给时标题为空字符串）；
  - 翻译器的 `_text_of` 改名为 `text_of`（标题生成也要用）。
- 产出（backend）：
  - `auto_title(first_message) -> str`（`backend.threads` 公开）：首条消息的前 30 个字；
  - `ThreadRepo.replace_title(thread_id, *, old, new) -> bool`：标题仍是 `old` 时才换；
  - `RunRepo.completed_count(thread_id) -> int`、`RunRepo.first_message(thread_id) -> str`；
  - `RunFollowups(*, runs, threads, usage, agent, jobs, auto_extract)`；会话第一次顺利结束时先登记 `title` 再登记 `memory_extraction`。
- 产出（前端）：`isAutoTitle(title, firstMessage)`、`scheduleRefreshes(refresh, delays = [2000, 5000, 10000, 20000]) -> 取消函数`。

- [ ] **步骤 1：写失败的测试（生成标题）**

新建 `agents/tests/test_titles.py`：

```python
"""会话标题生成：第一次顺利结束后，用会话所选的模型起一个简短的标题。"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import MainAgent, clean_title
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, ScriptedChatModel


@pytest.mark.parametrize(
    ("reply", "title"),
    [
        ("周报模板", "周报模板"),
        ("《周报模板》", "周报模板"),
        ('"写周报模板"。\n', "写周报模板"),
        ("标题：Python 数据清洗\n（概括了用户的需求）", "Python 数据清洗"),
        ("**整理会议纪要**", "整理会议纪要"),
        ("一" * 40, "一" * 30),  # 太长时截断
        ("\n\n", ""),
    ],
)
def test_clean_title(reply: str, title: str) -> None:
    assert clean_title(reply) == title


async def test_main_agent_generates_a_title_and_reports_usage(tmp_path: object) -> None:
    reply = AIMessage(
        "《周报模板》",
        usage_metadata={"input_tokens": 120, "output_tokens": 6, "total_tokens": 126},
    )
    model = ScriptedChatModel(responses=[reply])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),  # type: ignore[arg-type]
    )
    title, usage = await agent.generate_title(
        model="m", message="帮我写个周报模板", answer="好的，下面是周报模板……"
    )
    assert title == "周报模板"
    assert [(u.caller, u.input_tokens) for u in usage] == [("title", 120)]
    prompt = "\n".join(str(message.content) for message in model.received[0])
    assert "帮我写个周报模板" in prompt
    assert "好的，下面是周报模板" in prompt
```

运行：`uv run pytest agents/tests/test_titles.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'clean_title'`。

- [ ] **步骤 2：实现生成标题**

新建 `agents/main_agent/runtime/titles.py`：

```python
"""会话标题生成：第一次顺利结束后，用会话所选的模型按对话内容起一个简短的标题。

在此之前会话标题是首条消息的前 30 个字（backend 在发起运行时填上）。
"""

import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agents.main_agent.runtime.translator import text_of

TITLE_LENGTH = 30
_MESSAGE_LIMIT = 2000
_ANSWER_LIMIT = 1000

TITLE_PROMPT = (
    "根据下面这轮对话，给这个会话起一个简短的标题：不超过 15 个字，概括用户想做的事，"
    "用对话所用的语言；不加引号、标点和“标题：”这类前缀。只回复标题本身。"
)

# 模型常在标题外面加的引号、书名号、加粗记号与结尾标点
_WRAPPING = " \t\"'“”‘’《》「」『』*`#。.!！?？,，;；:："
_PREFIX = re.compile(r"^(标题|title)\s*[:：]\s*", re.IGNORECASE)


async def generate_title(
    model: BaseChatModel, *, message: str, answer: str, config: RunnableConfig | None = None
) -> str:
    """起一个标题；模型什么都没给时返回空字符串（由调用方保留原标题）。"""
    reply = await model.ainvoke(
        [
            SystemMessage(TITLE_PROMPT),
            HumanMessage(f"用户：{message[:_MESSAGE_LIMIT]}\n助手：{answer[:_ANSWER_LIMIT]}"),
        ],
        config=config,
    )
    return clean_title(text_of(reply.content))


def clean_title(text: str) -> str:
    """取第一行，去掉"标题："前缀、外面的引号与结尾标点，最长 30 个字。"""
    line = next((line for line in text.splitlines() if line.strip(_WRAPPING)), "")
    line = _PREFIX.sub("", line.strip(_WRAPPING)).strip(_WRAPPING)
    return line[:TITLE_LENGTH]
```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python
                    yield ThinkingDelta(agent_path=path, message_id=message_id, text=thinking)
                if text := _text_of(chunk.content):
                    yield MessageDelta(agent_path=path, message_id=message_id, text=text)
```

改为：

```python
                    yield ThinkingDelta(agent_path=path, message_id=message_id, text=thinking)
                if text := text_of(chunk.content):
                    yield MessageDelta(agent_path=path, message_id=message_id, text=text)
```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python
        status = "error" if message.status == "error" else "success"
        output = _text_of(message.content)[:TOOL_OUTPUT_LIMIT]
        if message.name == SUBAGENT_TOOL:
```

改为：

```python
        status = "error" if message.status == "error" else "success"
        output = text_of(message.content)[:TOOL_OUTPUT_LIMIT]
        if message.name == SUBAGENT_TOOL:
```

在 `agents/main_agent/runtime/translator.py` 中，把：

```python

def _text_of(content: str | list[Any]) -> str:
    """取出消息内容中的纯文本；内容块形式（如 Anthropic）只拼接 text 块。"""
```

改为：

```python

def text_of(content: str | list[Any]) -> str:
    """取出消息内容中的纯文本；内容块形式（如 Anthropic）只拼接 text 块。"""
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
)

```

改为：

```python
)
from agents.main_agent.runtime.titles import clean_title

```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    "UsageTotals",
    "user_content",
```

改为：

```python
    "UsageTotals",
    "clean_title",
    "user_content",
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
from agents.main_agent.runtime.tracker import Calibration, RunTracker
```

改为：

```python
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
from agents.main_agent.runtime.titles import generate_title
from agents.main_agent.runtime.tracker import Calibration, RunTracker
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

MEMORY_EXTRACTION = "memory_extraction"  # 会后提取记忆的模型调用在用量表里的调用方

```

改为：

```python

# 运行之外的模型调用在用量表里的调用方
MEMORY_EXTRACTION = "memory_extraction"  # 会后提取记忆
TITLE = "title"  # 生成会话标题

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

    async def _keep_partial_answer(
```

改为：

```python

    async def generate_title(
        self, *, model: str, message: str, answer: str
    ) -> tuple[str, list[UsageReported]]:
        """按第一轮对话起一个会话标题（由后台任务调用），连同这次的模型用量一起返回。

        用会话所选的模型。模型什么都没给时标题为空字符串。
        """
        tracker = RunTracker(calibration=self._calibration, model_info=self.models.model_info)
        title = await generate_title(
            self.models.chat_model(model),
            message=message,
            answer=answer,
            config={"callbacks": [tracker], "metadata": {"lc_agent_name": TITLE}},
        )
        return title, tracker.drain_usage()

    async def _keep_partial_answer(
```

运行：`uv run pytest agents/tests/test_titles.py agents/tests/test_main_agent.py -q`

预期：全部通过。

- [ ] **步骤 3：写失败的测试（标题任务）**

第一次顺利结束先登记标题；之后的运行不再登记；用户改过名的不动：

在 `backend/tests/test_followups.py` 中，把：

```python
"""运行顺利结束后的后台小事：自动提取记忆（设计文档 8.2）。"""

```

改为：

```python
"""运行顺利结束后的后台小事：生成会话标题、自动提取记忆（设计文档 8.2）。"""

```

在 `backend/tests/test_followups.py` 中，把：

```python
        self.followups = RunFollowups(
            runs=self.runs, usage=self.usage, agent=agent, jobs=self.jobs, auto_extract=auto_extract
        )
```

改为：

```python
        self.followups = RunFollowups(
            runs=self.runs,
            threads=self.threads,
            usage=self.usage,
            agent=agent,
            jobs=self.jobs,
            auto_extract=auto_extract,
        )
```

在 `backend/tests/test_followups.py` 中，把：

```python

    async def run(self, message: str) -> UUID:
        """发起一次运行并等它结束（收到结束事件时，后续任务已经登记）。"""
        thread = await self.threads.create(model="m")
        run = await self.manager.start(thread.id, RunCreate(message=message))
        async for _ in self.manager.stream(run.id):
```

改为：

```python

    async def run(self, message: str, thread_id: UUID | None = None) -> UUID:
        """发起一次运行并等它结束（收到结束事件时，后续任务已经登记）。不给会话时新建一个。"""
        if thread_id is None:
            thread_id = (await self.threads.create(model="m")).id
        run = await self.manager.start(thread_id, RunCreate(message=message))
        async for _ in self.manager.stream(run.id):
```

在 `backend/tests/test_followups.py` 中，把：

```python

async def test_completed_run_queues_memory_extraction(db: Pool) -> None:
    setup = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]))
    run_id = await setup.run("你好")
    assert setup.jobs.enqueued == [("memory_extraction", {"run_id": str(run_id)})]


async def test_failed_run_or_switched_off_extraction_queues_nothing(db: Pool) -> None:
    failed = _Setup(db, FailingChatModel(responses=[]))
    await failed.run("你好")
    assert failed.jobs.enqueued == []

    off = _Setup(db, ScriptedChatModel(responses=[AIMessage("好")]), auto_extract=False)
    await off.run("你好")
    assert off.jobs.enqueued == []

```

改为：

```python

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

```

在 `backend/tests/test_followups.py` 中，把：

```python

    [(kind, payload)] = setup.jobs.enqueued
    await setup.followups.handlers()[kind](payload)

```

改为：

```python

    payload = dict(setup.jobs.enqueued)["memory_extraction"]
    await setup.followups.handlers()["memory_extraction"](payload)

```

在 `backend/tests/test_followups.py` 末尾追加：

```python


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


async def test_title_job_keeps_a_title_the_user_set(db: Pool) -> None:
    model = ScriptedChatModel(responses=[AIMessage("好"), AIMessage("不该用上的标题")])
    setup = _Setup(db, model, auto_extract=False)
    run_id = await setup.run("你好")
    thread_id = (await setup.runs.get(run_id)).thread_id
    await setup.threads.rename(thread_id, "我自己起的名字")

    await setup.followups.handlers()["title"]({"run_id": str(run_id)})

    assert (await setup.threads.get(thread_id)).title == "我自己起的名字"
    assert model.cursor == 1  # 没有为标题调用模型
```

运行：`uv run pytest -m integration backend/tests/test_followups.py -q`（预期失败）

预期：`TypeError: RunFollowups.__init__() got an unexpected keyword argument 'threads'`。

- [ ] **步骤 4：实现标题任务**

在 `backend/runs/repo.py` 中，把：

```python

    async def finish(
```

改为：

```python

    async def completed_count(self, thread_id: UUID) -> int:
        """该会话里顺利结束的运行次数。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM runs WHERE thread_id = %s AND status = 'completed'",
                (thread_id,),
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def first_message(self, thread_id: UUID) -> str:
        """该会话第一次运行的消息（会话的自动标题由它而来）；没有运行时为空字符串。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT input->>'message' AS message FROM runs WHERE thread_id = %s "
                "ORDER BY created_at LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()
        return str(row["message"]) if row else ""

    async def finish(
```

在 `backend/threads/repo.py` 中，把：

```python
_COLUMNS = "id, short_id, title, model, created_at, updated_at"

```

改为：

```python
_COLUMNS = "id, short_id, title, model, created_at, updated_at"


def auto_title(first_message: str) -> str:
    """会话的自动标题：首条消息的前 30 个字（之后由后台按对话内容生成正式标题）。"""
    return first_message[:30]

```

在 `backend/threads/repo.py` 中，把：

```python
    async def touch(self, thread_id: UUID, *, first_message: str) -> None:
        """记录一次新运行：刷新更新时间；标题为空时用首条消息的前 30 个字作标题。"""
        async with self._pool.connection() as conn:
```

改为：

```python
    async def touch(self, thread_id: UUID, *, first_message: str) -> None:
        """记录一次新运行：刷新更新时间；标题为空时用自动标题（首条消息的前 30 个字）。"""
        async with self._pool.connection() as conn:
```

在 `backend/threads/repo.py` 中，把：

```python
                "title = CASE WHEN title = '' THEN %s ELSE title END WHERE id = %s",
                (first_message[:30], thread_id),
            )
```

改为：

```python
                "title = CASE WHEN title = '' THEN %s ELSE title END WHERE id = %s",
                (auto_title(first_message), thread_id),
            )

    async def replace_title(self, thread_id: UUID, *, old: str, new: str) -> bool:
        """标题仍是 old 时才换成 new（期间用户改过名就不动），返回是否换了。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE threads SET title = %s WHERE id = %s AND title = %s",
                (new, thread_id, old),
            )
            return cur.rowcount > 0
```

在 `backend/threads/__init__.py` 中，把：

```python

from backend.threads.repo import ThreadRepo
from backend.threads.schemas import Thread, ThreadCreate, ThreadOrder, ThreadUpdate

__all__ = ["Thread", "ThreadCreate", "ThreadOrder", "ThreadRepo", "ThreadUpdate"]
```

改为：

```python

from backend.threads.repo import ThreadRepo, auto_title
from backend.threads.schemas import Thread, ThreadCreate, ThreadOrder, ThreadUpdate

__all__ = ["Thread", "ThreadCreate", "ThreadOrder", "ThreadRepo", "ThreadUpdate", "auto_title"]
```

在 `backend/runs/followups.py` 中，把：

```python
"""运行顺利结束后的后台小事（M3）：自动提取记忆（设计文档 8.2）。

```

改为：

```python
"""运行顺利结束后的后台小事（M3）：生成会话标题、自动提取记忆（设计文档 8.2）。

```

在 `backend/runs/followups.py` 中，把：

```python
from backend.runtime import EventEnvelope, JobHandler, JobQueue
from common.errors import NotFoundError
```

改为：

```python
from backend.runtime import EventEnvelope, JobHandler, JobQueue
from backend.threads import ThreadRepo, auto_title
from common.errors import NotFoundError
```

在 `backend/runs/followups.py` 中，把：

```python

MEMORY_EXTRACTION = "memory_extraction"
```

改为：

```python

TITLE = "title"
MEMORY_EXTRACTION = "memory_extraction"
```

在 `backend/runs/followups.py` 中，把：

```python
        runs: RunRepo,
        usage: UsageRepo,
```

改为：

```python
        runs: RunRepo,
        threads: ThreadRepo,
        usage: UsageRepo,
```

在 `backend/runs/followups.py` 中，把：

```python
        self._runs = runs
        self._usage = usage
```

改为：

```python
        self._runs = runs
        self._threads = threads
        self._usage = usage
```

在 `backend/runs/followups.py` 中，把：

```python
        """交给任务队列的处理程序：任务种类 → 处理函数。"""
        return {MEMORY_EXTRACTION: self.extract_memories}

    async def after_completed(self, run: RunRecord) -> None:
        """一次运行顺利结束（停止、失败的不算）：登记它的后续任务。"""
        if self._auto_extract and self._agent.knowledge is not None:
            await self._jobs.enqueue(MEMORY_EXTRACTION, {"run_id": str(run.id)})

```

改为：

```python
        """交给任务队列的处理程序：任务种类 → 处理函数。"""
        return {TITLE: self.generate_title, MEMORY_EXTRACTION: self.extract_memories}

    async def after_completed(self, run: RunRecord) -> None:
        """一次运行顺利结束（停止、失败的不算）：登记它的后续任务。

        会话第一次顺利结束时生成标题，排在前面（任务逐个处理，标题先出来）。
        """
        if await self._runs.completed_count(run.thread_id) == 1:
            await self._jobs.enqueue(TITLE, {"run_id": str(run.id)})
        if self._auto_extract and self._agent.knowledge is not None:
            await self._jobs.enqueue(MEMORY_EXTRACTION, {"run_id": str(run.id)})

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
        title, usage = await self._agent.generate_title(
            model=run.model,
            message=run.message,
            answer=_answer(await self._runs.events(run.id)),
        )
        for item in usage:
            await self._usage.add(thread_id=run.thread_id, run_id=run.id, usage=item)
        if title:
            # 带上原标题作条件：生成期间用户改了名，就保留用户起的
            await self._threads.replace_title(thread.id, old=automatic, new=title)

```

在 `backend/api/deps.py` 中，把：

```python
    followups = RunFollowups(
        runs=runs,
        usage=usage,
        agent=agent,
```

改为：

```python
    followups = RunFollowups(
        runs=runs,
        threads=threads,
        usage=usage,
        agent=agent,
```

运行：`uv run pytest -m integration backend/tests/test_followups.py backend/tests/test_repos.py -q`

预期：全部通过。

- [ ] **步骤 5：前端等标题**

新建 `frontend/src/features/threads/titleRefresh.test.ts`：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { isAutoTitle, scheduleRefreshes } from "./titleRefresh";

describe("isAutoTitle", () => {
  it("标题还是首条消息的前 30 个字（按字符算，表情也算一个字）", () => {
    const message = "帮我写一个每周给团队发的周报模板😀，要包含本周进展、风险和下周计划";
    expect(isAutoTitle(Array.from(message).slice(0, 30).join(""), message)).toBe(true);
    expect(isAutoTitle("周报模板", message)).toBe(false);
    expect(isAutoTitle("", "")).toBe(false); // 还没有消息
  });
});

describe("scheduleRefreshes", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("按给定的间隔依次刷新，取消后不再刷新", () => {
    vi.useFakeTimers();
    const refresh = vi.fn();
    const cancel = scheduleRefreshes(refresh, [1000, 3000, 6000]);
    vi.advanceTimersByTime(1000);
    expect(refresh).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2000);
    expect(refresh).toHaveBeenCalledTimes(2);
    cancel();
    vi.advanceTimersByTime(10000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
```

运行：`cd frontend && pnpm exec vitest run src/features/threads/titleRefresh.test.ts`（预期失败）

预期：找不到 `./titleRefresh`。

新建 `frontend/src/features/threads/titleRefresh.ts`：

```ts
/**
 * 会话第一次顺利结束后，后台按对话内容生成标题（通常几秒内完成）：
 * 期间隔一阵刷新几次会话列表，标题出来后侧栏与顶部自动更新。
 */
export const TITLE_REFRESH_DELAYS = [2000, 5000, 10000, 20000];

/** 标题还是自动标题：首条消息的前 30 个字（与后端一致，按字符而不是 UTF-16 单元算）。 */
export function isAutoTitle(title: string, firstMessage: string): boolean {
  return firstMessage !== "" && title === Array.from(firstMessage).slice(0, 30).join("");
}

/** 按给定的间隔（从现在算起）依次调用 refresh；返回取消函数。 */
export function scheduleRefreshes(
  refresh: () => void,
  delays: number[] = TITLE_REFRESH_DELAYS,
): () => void {
  const timers = delays.map((delay) => setTimeout(refresh, delay));
  return () => timers.forEach(clearTimeout);
}
```

运行顺利结束后，标题仍是自动标题时刷新几次会话列表；标题一变（或用户改了名）就不再刷新：

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
import { subscribeRun } from "../../api/events";
import { filesQuery, historyQuery, recheckAccess, threadUsageQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
```

改为：

```tsx
import { subscribeRun } from "../../api/events";
import {
  filesQuery,
  historyQuery,
  recheckAccess,
  threadUsageQuery,
  threadsQuery,
} from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
import { ModelSelect } from "../models/ModelSelect";
import { ThreadUsageBadge } from "../usage/ThreadUsageBadge";
```

改为：

```tsx
import { ModelSelect } from "../models/ModelSelect";
import { isAutoTitle, scheduleRefreshes } from "../threads/titleRefresh";
import { ThreadUsageBadge } from "../usage/ThreadUsageBadge";
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  });
  const openFile = useCallback((fileId: string) => setPanel({ open: true, fileId }), []);
```

改为：

```tsx
  });
  // 顺利结束的运行次数：每次加一，触发下面检查标题是否还在等后台生成
  const [completedRuns, setCompletedRuns] = useState(0);
  const firstMessage = state.items.find((item) => item.kind === "user")?.text ?? "";
  const openFile = useCallback((fileId: string) => setPanel({ open: true, fileId }), []);
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
      }
    });
  }, [active, queryClient, thread.id]);

```

改为：

```tsx
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
        if (event.data.status === "completed") setCompletedRuns((count) => count + 1);
      }
    });
  }, [active, queryClient, thread.id]);

  // 标题还是自动标题时，刷新几次会话列表等后台生成的标题；标题一变（或用户改了名）就不再刷新
  useEffect(() => {
    if (completedRuns === 0 || !isAutoTitle(thread.title, firstMessage)) return;
    return scheduleRefreshes(
      () => void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey }),
    );
  }, [completedRuns, firstMessage, queryClient, thread.title]);

```

运行：`cd frontend && pnpm exec vitest run src/features/threads/titleRefresh.test.ts`

预期：全部通过。

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 201 个、前端 86 个）；`make test-int` 全部通过（集成测试 89 个）。

---

### 任务 7：知识库接口

**文件：**
- 新建：`backend/api/knowledge.py`、`backend/tests/test_knowledge_api.py`
- 修改：`agents/main_agent/knowledge/__init__.py`、`backend/api/router.py`、`backend/tests/conftest.py`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 消费：任务 2 的 `KnowledgeStore`；任务 4 的 `MainAgent.knowledge`、`Settings.knowledge.pinned_token_limit`。
- 产出（`agents.main_agent.knowledge` 公开）：`KnowledgeText`（请求体里的内容字段沿用同一校验）。
- 产出（接口，前缀 `/api/knowledge`）：
  - `GET /items?kind=&tags=&pinned=&q=&limit=100&offset=0` → `KnowledgeItem[]`：不带 `q` 时新的在前；带 `q` 时按相关程度检索（忽略 `offset`）；
  - `POST /items`（`{content, tags?, pinned?}`）→ 201，种类为记忆、来源为手动添加；
  - `PATCH /items/{id}`（`{content?, tags?, pinned?}`，只改给出的字段）；`DELETE /items/{id}` → 204；
  - `GET /pinned` → `PinnedSummary {items, total_tokens, token_limit}`；
  - 不存在 404；内容为空 422；向量化不可用 503（说明原因）。
- 产出（测试夹具）：`make_client(..., knowledge=None)`。

- [ ] **步骤 1：写失败的测试**

接口测试用真实的 `PgKnowledgeStore` 加 `FakeEmbedder`（检索、筛选都走真实的 SQL）：

新建 `backend/tests/test_knowledge_api.py`：

```python
"""知识库接口（设计文档 8.4、11.2）：筛选与检索、手动添加、修改、删除、常驻条目汇总。"""

from collections.abc import Sequence
from typing import Any

import pytest
from httpx import AsyncClient

from agents.main_agent.knowledge import PgKnowledgeStore
from agents.tests.fakes import FakeEmbedder, ScriptedChatModel
from backend.tests.conftest import ClientFactory
from common.db import Pool
from common.errors import UpstreamError

pytestmark = pytest.mark.integration

VOCABULARY = ["咖啡", "茶", "狗", "工作", "后端"]


class _BrokenEmbedder:
    model = "broken"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise UpstreamError("向量化服务不可用：connection refused")


def _client(make_client: ClientFactory, db: Pool, embedder: Any = None) -> Any:
    store = PgKnowledgeStore(db, embedder or FakeEmbedder(VOCABULARY))
    return make_client(ScriptedChatModel(responses=[]), knowledge=store)


async def _add(client: AsyncClient, content: str, **extra: Any) -> dict[str, Any]:
    response = await client.post("/api/knowledge/items", json={"content": content, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_add_and_list_memories(make_client: ClientFactory, db: Pool) -> None:
    async with _client(make_client, db) as client:
        item = await _add(client, "  用户每天早上喝美式咖啡 ", tags=["饮食", " 饮食 ", ""])
        assert (item["content"], item["tags"], item["pinned"]) == (
            "用户每天早上喝美式咖啡",
            ["饮食"],
            False,
        )
        assert (item["kind"], item["source"]) == ("memory", "manual")  # 手动添加的都是记忆
        await _add(client, "用户在 某公司 做后端工作", tags=["工作"], pinned=True)

        listed = (await client.get("/api/knowledge/items")).json()
        assert [i["content"] for i in listed] == [
            "用户在 某公司 做后端工作",
            "用户每天早上喝美式咖啡",
        ]  # 新的在前
        pinned = (await client.get("/api/knowledge/items", params={"pinned": "true"})).json()
        assert [i["content"] for i in pinned] == ["用户在 某公司 做后端工作"]
        tagged = (await client.get("/api/knowledge/items", params={"tags": ["饮食"]})).json()
        assert [i["content"] for i in tagged] == ["用户每天早上喝美式咖啡"]
        documents = await client.get("/api/knowledge/items", params={"kind": "document_chunk"})
        assert documents.json() == []


async def test_search_finds_by_meaning_and_exact_words(
    make_client: ClientFactory, db: Pool
) -> None:
    async with _client(make_client, db) as client:
        await _add(client, "用户每天早上喝美式咖啡")
        await _add(client, "线上偶发 ERR_CONN_RESET 报错")
        await _add(client, "用户养了一只狗")
        by_meaning = await client.get("/api/knowledge/items", params={"q": "咖啡还是茶"})
        assert by_meaning.json()[0]["content"] == "用户每天早上喝美式咖啡"
        exact = await client.get("/api/knowledge/items", params={"q": "ERR_CONN_RESET"})
        assert exact.json()[0]["content"] == "线上偶发 ERR_CONN_RESET 报错"


async def test_update_and_delete(make_client: ClientFactory, db: Pool) -> None:
    async with _client(make_client, db) as client:
        item = await _add(client, "用户每天早上喝美式咖啡")
        url = f"/api/knowledge/items/{item['id']}"
        changed = await client.patch(url, json={"content": "用户改喝茶了", "pinned": True})
        assert changed.status_code == 200
        assert (changed.json()["content"], changed.json()["pinned"]) == ("用户改喝茶了", True)
        assert changed.json()["tags"] == []  # 没给的字段不变
        found = await client.get("/api/knowledge/items", params={"q": "茶"})
        assert found.json()[0]["content"] == "用户改喝茶了"  # 改了内容会重新向量化

        assert (await client.delete(url)).status_code == 204
        assert (await client.patch(url, json={"pinned": False})).status_code == 404
        assert (await client.delete(url)).status_code == 404


async def test_pinned_summary_counts_tokens_against_the_limit(
    make_client: ClientFactory, db: Pool
) -> None:
    async with _client(make_client, db) as client:
        first = await _add(client, "用户希望回答简洁", pinned=True)
        second = await _add(client, "用户在 某公司 做后端工作", pinned=True)
        await _add(client, "用户养了一只狗")
        summary = (await client.get("/api/knowledge/pinned")).json()
        assert [i["content"] for i in summary["items"]] == [
            "用户希望回答简洁",
            "用户在 某公司 做后端工作",
        ]
        assert summary["total_tokens"] == first["token_count"] + second["token_count"]
        assert summary["token_limit"] == 2000  # config/app.yaml 的 knowledge.pinned_token_limit


async def test_invalid_input_is_rejected(make_client: ClientFactory, db: Pool) -> None:
    async with _client(make_client, db) as client:
        assert (
            await client.post("/api/knowledge/items", json={"content": "  "})
        ).status_code == 422
        item = await _add(client, "用户养了一只狗")
        url = f"/api/knowledge/items/{item['id']}"
        assert (await client.patch(url, json={"content": ""})).status_code == 422


async def test_unavailable_embedding_service_is_reported(
    make_client: ClientFactory, db: Pool
) -> None:
    """向量模型（ollama）没启动：添加、检索返回 503 并说明原因；不用向量的列表照常可用。"""
    async with _client(make_client, db, _BrokenEmbedder()) as client:
        added = await client.post("/api/knowledge/items", json={"content": "用户养了一只狗"})
        assert added.status_code == 503
        assert "向量化服务不可用" in added.json()["detail"]
        searched = await client.get("/api/knowledge/items", params={"q": "狗"})
        assert searched.status_code == 503
        assert (await client.get("/api/knowledge/items")).status_code == 200
```

在 `backend/tests/conftest.py` 中，把：

```python

from agents.main_agent.models import ModelGateway
```

改为：

```python

from agents.main_agent.knowledge import KnowledgeStore
from agents.main_agent.models import ModelGateway
```

在 `backend/tests/conftest.py` 中，把：

```python
        upload_limit_mb: int = 100,
    ) -> AsyncIterator[AsyncClient]:
```

改为：

```python
        upload_limit_mb: int = 100,
        knowledge: KnowledgeStore | None = None,
    ) -> AsyncIterator[AsyncClient]:
```

在 `backend/tests/conftest.py` 中，把：

```python
            workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        )
```

改为：

```python
            workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
            knowledge=knowledge,
        )
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration backend/tests/test_knowledge_api.py -q`（预期失败）

预期：6 个测试都失败，接口返回 404。

- [ ] **步骤 3：实现**

在 `agents/main_agent/knowledge/__init__.py` 中，把：

```python
    KnowledgeSource,
    NewKnowledge,
```

改为：

```python
    KnowledgeSource,
    KnowledgeText,
    NewKnowledge,
```

在 `agents/main_agent/knowledge/__init__.py` 中，把：

```python
    "KnowledgeStore",
    "NewKnowledge",
```

改为：

```python
    "KnowledgeStore",
    "KnowledgeText",
    "NewKnowledge",
```

新建 `backend/api/knowledge.py`：

```python
"""知识库接口（设计文档 8.4、11.2）：筛选与检索、手动添加、修改、删除；常驻条目（个人画像）汇总。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict

from agents.main_agent.knowledge import (
    KnowledgeItem,
    KnowledgeKind,
    KnowledgeStore,
    KnowledgeText,
    NewKnowledge,
)
from backend.api.deps import Services, ServicesDep
from common.errors import UpstreamError

knowledge_router = APIRouter(prefix="/knowledge")


class KnowledgeCreate(BaseModel):
    """手动添加一条记忆。"""

    content: KnowledgeText
    tags: list[str] = []
    pinned: bool = False


class KnowledgeUpdate(BaseModel):
    """修改条目：只改给出的字段。"""

    content: KnowledgeText | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


class PinnedSummary(BaseModel):
    """常驻条目（个人画像）：每次对话都会带上，总量超过建议上限时前端提示精简。"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[KnowledgeItem]
    total_tokens: int
    token_limit: int


def _store(services: Services) -> KnowledgeStore:
    if services.agent.knowledge is None:
        raise UpstreamError("知识库未启用：请检查 config/app.yaml 的 adapters.knowledge_index")
    return services.agent.knowledge


@knowledge_router.get("/items")
async def list_items(
    services: ServicesDep,
    kind: KnowledgeKind | None = None,
    tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI 的查询参数默认值，不会被修改
    pinned: bool | None = None,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeItem]:
    """不带 q 时按时间倒序列出；带 q 时按相关程度检索（向量 + 关键词，忽略 offset）。"""
    store = _store(services)
    if not q.strip():
        return await store.list_items(
            kind=kind, tags=tags, pinned=pinned, limit=limit, offset=offset
        )
    hits = await store.search(q, kinds=[kind] if kind else None, tags=tags, top_k=limit)
    return [hit.item for hit in hits if pinned is None or hit.item.pinned == pinned]


@knowledge_router.post("/items", status_code=status.HTTP_201_CREATED)
async def add_item(body: KnowledgeCreate, services: ServicesDep) -> KnowledgeItem:
    new = NewKnowledge(content=body.content, tags=body.tags, pinned=body.pinned, source="manual")
    return await _store(services).add(new)


@knowledge_router.patch("/items/{item_id}")
async def update_item(item_id: UUID, body: KnowledgeUpdate, services: ServicesDep) -> KnowledgeItem:
    return await _store(services).update(
        item_id, content=body.content, tags=body.tags, pinned=body.pinned
    )


@knowledge_router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: UUID, services: ServicesDep) -> None:
    await _store(services).delete(item_id)


@knowledge_router.get("/pinned")
async def pinned_summary(services: ServicesDep) -> PinnedSummary:
    items = await _store(services).pinned()
    return PinnedSummary(
        items=items,
        total_tokens=sum(item.token_count for item in items),
        token_limit=services.settings.knowledge.pinned_token_limit,
    )
```

在 `backend/api/router.py` 中，把：

```python
"""接口路由：会话、运行（含推送）、文件、用量、模型、健康检查。"""

```

改为：

```python
"""接口路由：会话、运行（含推送）、文件、用量、模型、知识库、健康检查。"""

```

在 `backend/api/router.py` 中，把：

```python
from backend.api.deps import Services, ServicesDep
from backend.files import MAX_PREVIEW_BYTES, PreviewError, TablePreview, table_preview
```

改为：

```python
from backend.api.deps import Services, ServicesDep
from backend.api.knowledge import knowledge_router
from backend.files import MAX_PREVIEW_BYTES, PreviewError, TablePreview, table_preview
```

在 `backend/api/router.py` 中，把：

```python
api_router = APIRouter()

```

改为：

```python
api_router = APIRouter()
api_router.include_router(knowledge_router)

```

运行：`uv run pytest -m integration backend/tests/test_knowledge_api.py -q`

预期：6 个测试通过。

- [ ] **步骤 4：检查点**

接口改了，重新生成前端类型：

运行：`make types`

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 201 个、前端 86 个）；`make test-int` 全部通过（集成测试 95 个）。

---

### 任务 8：知识库页

**文件：**
- 新建：`frontend/src/features/knowledge/filters.ts`（及测试）、`KnowledgePage.tsx`、`KnowledgeItemCard.tsx`
- 修改：`frontend/src/api/types.ts`、`client.ts`、`queries.ts`、`frontend/src/layout/AppShell.tsx`

**接口：**
- 消费：任务 7 的接口与生成的类型。
- 产出：
  - 类型别名 `KnowledgeItem`、`KnowledgeCreate`、`KnowledgeUpdate`、`PinnedSummary`；
  - `api.listKnowledge(params)`、`addKnowledge(body)`、`updateKnowledge(id, body)`、`deleteKnowledge(id)`、`pinnedKnowledge()`；
  - 查询 `knowledgeQuery(params)`、`pinnedKnowledgeQuery`：查询键都以 `"knowledge"` 开头，增删改后一起刷新；
  - `knowledgeSearchParams(filter)`、`parseTags(text)`、`pinnedNotice(summary)`、`sourceLabel(source)`。
- 界面：
  - 侧栏会话列表下方的"知识库"入口；点会话或新建会话回到对话；
  - 页面从上到下：说明、常驻信息汇总（超量提示）、添加表单、视图切换（全部 / 记忆 / 常驻）与搜索框（回车开始，清空即回到列表）、条目列表；
  - 每条可设或取消常驻、修改内容与标签、删除（要再点一次确认），点标签只看带这个标签的。

- [ ] **步骤 1：写失败的测试**

新建 `frontend/src/features/knowledge/filters.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { knowledgeSearchParams, parseTags, pinnedNotice, sourceLabel } from "./filters";

describe("knowledgeSearchParams", () => {
  it("按视图、标签、搜索词生成查询参数", () => {
    expect(knowledgeSearchParams({ view: "all", tag: null, query: "" })).toBe("");
    expect(knowledgeSearchParams({ view: "memory", tag: null, query: "" })).toBe("kind=memory");
    expect(knowledgeSearchParams({ view: "pinned", tag: null, query: "" })).toBe("pinned=true");
    expect(
      new URLSearchParams(knowledgeSearchParams({ view: "all", tag: "工作", query: "  咖啡 " })),
    ).toEqual(new URLSearchParams({ tags: "工作", q: "咖啡" }));
  });
});

describe("parseTags", () => {
  it("中英文逗号、顿号都能分隔，去空白、去重", () => {
    expect(parseTags("工作, 健康，饮食、 工作 ,,")).toEqual(["工作", "健康", "饮食"]);
    expect(parseTags("  ")).toEqual([]);
  });
});

describe("pinnedNotice", () => {
  it("常驻信息超过建议上限时提示精简", () => {
    expect(pinnedNotice({ total_tokens: 1999, token_limit: 2000 })).toBeNull();
    expect(pinnedNotice({ total_tokens: 2300, token_limit: 2000 })).toBe(
      "常驻信息约 2300 token，超过建议的 2000：每次对话都会带上，建议精简或取消部分常驻",
    );
  });
});

describe("sourceLabel", () => {
  it("说明条目从哪里来", () => {
    expect(sourceLabel("conversation")).toBe("对话中记下");
    expect(sourceLabel("manual")).toBe("手动添加");
    expect(sourceLabel("document")).toBe("来自文档");
  });
});
```

运行：`cd frontend && pnpm exec vitest run src/features/knowledge`（预期失败）

预期：找不到 `./filters`。

- [ ] **步骤 2：实现纯逻辑**

在 `frontend/src/api/types.ts` 中，把：

```ts
export type TablePreview = Schemas["TablePreview"];

```

改为：

```ts
export type TablePreview = Schemas["TablePreview"];
export type KnowledgeItem = Schemas["KnowledgeItem"];
export type KnowledgeCreate = Schemas["KnowledgeCreate"];
export type KnowledgeUpdate = Schemas["KnowledgeUpdate"];
export type PinnedSummary = Schemas["PinnedSummary"];

```

新建 `frontend/src/features/knowledge/filters.ts`：

```ts
import type { KnowledgeItem, PinnedSummary } from "../../api/types";

/** 知识库页的视图：全部 / 记忆 / 常驻（个人画像）。文档在 M3b 加入。 */
export type KnowledgeView = "all" | "memory" | "pinned";

export interface KnowledgeFilter {
  view: KnowledgeView;
  tag: string | null; // 点了某个标签：只看带这个标签的
  query: string; // 搜索词：非空时按相关程度检索
}

export const defaultFilter: KnowledgeFilter = { view: "all", tag: null, query: "" };

/** 筛选条件 → 列表接口的查询参数。 */
export function knowledgeSearchParams(filter: KnowledgeFilter): string {
  const params = new URLSearchParams();
  if (filter.view === "memory") params.set("kind", "memory");
  if (filter.view === "pinned") params.set("pinned", "true");
  if (filter.tag) params.set("tags", filter.tag);
  if (filter.query.trim()) params.set("q", filter.query.trim());
  return params.toString();
}

/** 输入框里的标签：中英文逗号、顿号分隔，去空白、去重。 */
export function parseTags(text: string): string[] {
  const tags = text
    .split(/[,，、]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  return [...new Set(tags)];
}

/** 常驻信息超过建议上限时的提示（每次对话都会带上，太多既费钱也干扰回答）。 */
export function pinnedNotice(
  summary: Pick<PinnedSummary, "total_tokens" | "token_limit">,
): string | null {
  if (summary.total_tokens <= summary.token_limit) return null;
  return `常驻信息约 ${summary.total_tokens} token，超过建议的 ${summary.token_limit}：每次对话都会带上，建议精简或取消部分常驻`;
}

const SOURCE_LABELS: Record<KnowledgeItem["source"], string> = {
  conversation: "对话中记下",
  manual: "手动添加",
  document: "来自文档",
};

export function sourceLabel(source: KnowledgeItem["source"]): string {
  return SOURCE_LABELS[source];
}
```

运行：`cd frontend && pnpm exec vitest run src/features/knowledge`

预期：4 个测试通过。

- [ ] **步骤 3：接口调用与页面**

在 `frontend/src/api/client.ts` 中，把：

```ts
import type {
  ModelInfo,
  RunHistory,
```

改为：

```ts
import type {
  KnowledgeCreate,
  KnowledgeItem,
  KnowledgeUpdate,
  ModelInfo,
  PinnedSummary,
  RunHistory,
```

在 `frontend/src/api/client.ts` 中，把：

```ts
    (await send(`/threads/${threadId}/files/${fileId}/content`)).text(),
  // 令牌正确时服务器写入 Cookie，之后的请求（含推送）由浏览器自动带上
```

改为：

```ts
    (await send(`/threads/${threadId}/files/${fileId}/content`)).text(),
  /** 知识库条目；params 为筛选与检索的查询参数（见 knowledge/filters.ts）。 */
  listKnowledge: (params: string) =>
    request<KnowledgeItem[]>(`/knowledge/items${params ? `?${params}` : ""}`),
  addKnowledge: (body: KnowledgeCreate) =>
    request<KnowledgeItem>("/knowledge/items", { method: "POST", body: JSON.stringify(body) }),
  updateKnowledge: (itemId: string, body: KnowledgeUpdate) =>
    request<KnowledgeItem>(`/knowledge/items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteKnowledge: (itemId: string) =>
    request<undefined>(`/knowledge/items/${itemId}`, { method: "DELETE" }),
  pinnedKnowledge: () => request<PinnedSummary>("/knowledge/pinned"),
  // 令牌正确时服务器写入 Cookie，之后的请求（含推送）由浏览器自动带上
```

在 `frontend/src/api/queries.ts` 中，把：

```ts

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
```

改为：

```ts

/** 知识库条目（筛选与检索）。知识库的查询键都以 "knowledge" 开头，增删改后一起刷新。 */
export function knowledgeQuery(params: string) {
  return { queryKey: ["knowledge", "items", params], queryFn: () => api.listKnowledge(params) };
}

/** 常驻条目（个人画像）与总 token 占用。 */
export const pinnedKnowledgeQuery = {
  queryKey: ["knowledge", "pinned"],
  queryFn: api.pinnedKnowledge,
};

/** 会话累计用量；每次运行结束后由对话区主动刷新。 */
```

新建 `frontend/src/features/knowledge/KnowledgeItemCard.tsx`：

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Pin, PinOff, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, readableError } from "../../api/client";
import type { KnowledgeItem, KnowledgeUpdate } from "../../api/types";
import { parseTags, sourceLabel } from "./filters";

const ICON_BUTTON = "rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground";

/** 一条知识：查看、改内容与标签、设或取消常驻、删除（删除要再点一次确认）。 */
export function KnowledgeItemCard({
  item,
  onTag,
}: {
  item: KnowledgeItem;
  onTag: (tag: string) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["knowledge"] });
  const update = useMutation({
    mutationFn: (body: KnowledgeUpdate) => api.updateKnowledge(item.id, body),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteKnowledge(item.id),
    onSuccess: refresh,
  });
  const error = update.error ?? remove.error;

  if (editing) {
    return (
      <li className="rounded-lg border border-ring bg-card p-3">
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            update.mutate({
              content: String(form.get("content")),
              tags: parseTags(String(form.get("tags"))),
            });
          }}
        >
          <textarea
            name="content"
            aria-label="内容"
            autoFocus
            required
            rows={3}
            defaultValue={item.content}
            className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-ring"
          />
          <input
            name="tags"
            aria-label="标签"
            placeholder="标签（用逗号分隔）"
            defaultValue={item.tags.join("，")}
            className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:border-ring"
          />
          {error && <p className="text-xs text-danger">保存失败：{readableError(error)}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-border px-3 py-1 text-sm hover:bg-muted"
              onClick={() => {
                setEditing(false);
                update.reset();
              }}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={update.isPending}
              className="rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className="group rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 text-sm whitespace-pre-wrap">{item.content}</p>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            className={item.pinned ? `${ICON_BUTTON} text-warning` : ICON_BUTTON}
            title={item.pinned ? "取消常驻" : "设为常驻（每次对话都带上）"}
            aria-label={item.pinned ? "取消常驻" : "设为常驻"}
            disabled={update.isPending}
            onClick={() => update.mutate({ pinned: !item.pinned })}
          >
            {item.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
          </button>
          <button
            className={ICON_BUTTON}
            title="修改"
            aria-label="修改"
            onClick={() => setEditing(true)}
          >
            <Pencil className="size-3.5" />
          </button>
          <button
            className={ICON_BUTTON}
            title="删除"
            aria-label="删除"
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {item.pinned && (
          <span className="flex items-center gap-1 text-warning">
            <Pin className="size-3" />
            常驻
          </span>
        )}
        {item.tags.map((tag) => (
          <button
            key={tag}
            className="rounded bg-muted px-1.5 py-0.5 hover:text-foreground"
            title={`只看标签「${tag}」`}
            onClick={() => onTag(tag)}
          >
            #{tag}
          </button>
        ))}
        <span>{sourceLabel(item.source)}</span>
        <span>{new Date(item.created_at).toLocaleDateString("zh-CN")}</span>
      </div>
      {confirmingDelete && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <span className="text-danger">删除这条？删除后无法恢复。</span>
          <button
            className="rounded-md bg-danger px-2.5 py-0.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            删除
          </button>
          <button
            className="rounded-md border border-border px-2.5 py-0.5 text-sm hover:bg-muted"
            onClick={() => {
              setConfirmingDelete(false);
              remove.reset();
            }}
          >
            取消
          </button>
        </div>
      )}
      {error && !editing && (
        <p className="mt-1.5 text-xs text-danger">操作失败：{readableError(error)}</p>
      )}
    </li>
  );
}
```

新建 `frontend/src/features/knowledge/KnowledgePage.tsx`：

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, LoaderCircle, Plus, Search, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { api, readableError } from "../../api/client";
import { knowledgeQuery, pinnedKnowledgeQuery } from "../../api/queries";
import { isImeComposing } from "../threads/ime";
import {
  defaultFilter,
  knowledgeSearchParams,
  parseTags,
  pinnedNotice,
  type KnowledgeFilter,
  type KnowledgeView,
} from "./filters";
import { KnowledgeItemCard } from "./KnowledgeItemCard";

const VIEWS: { value: KnowledgeView; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "memory", label: "记忆" },
  { value: "pinned", label: "常驻" },
];

/** 知识库页（设计文档 8.4）：查看、搜索、手动添加、修改、删除记忆，设或取消常驻。 */
export function KnowledgePage() {
  const [filter, setFilter] = useState<KnowledgeFilter>(defaultFilter);
  const [searchText, setSearchText] = useState("");
  const items = useQuery(knowledgeQuery(knowledgeSearchParams(filter)));
  const pinned = useQuery(pinnedKnowledgeQuery);
  const notice = pinned.data ? pinnedNotice(pinned.data) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-border px-6 py-3">
        <h1 className="flex items-center gap-2 font-medium">
          <BookMarked className="size-4 text-warning" />
          知识库
        </h1>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 px-6 py-5">
          <p className="text-sm text-muted-foreground">
            智能体记住的关于你的信息：常驻信息（个人画像）每次对话都会带上，其余的在相关时自动想起。
            对话中说"记住……"，或每次对话结束后自动整理，都会记到这里。
          </p>
          <section className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
            <p>
              常驻信息
              {pinned.data && (
                <span className="ml-2 text-muted-foreground">
                  {pinned.data.items.length} 条，约 {pinned.data.total_tokens} /{" "}
                  {pinned.data.token_limit} token
                </span>
              )}
            </p>
            {notice && (
              <p className="mt-1.5 flex items-start gap-1.5 text-warning">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                {notice}
              </p>
            )}
          </section>
          <AddForm />
          <div className="flex flex-wrap items-center gap-3">
            <div
              role="radiogroup"
              aria-label="视图"
              className="flex rounded-lg border border-border bg-card p-0.5"
            >
              {VIEWS.map(({ value, label }) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={filter.view === value}
                  onClick={() => setFilter((current) => ({ ...current, view: value }))}
                  className={`rounded-md px-3 py-1 text-sm transition-colors ${
                    filter.view === value
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="flex min-w-48 flex-1 items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm focus-within:border-ring">
              <Search className="size-3.5 text-muted-foreground" />
              <input
                aria-label="搜索"
                placeholder="搜索（按意思或关键词），回车开始"
                value={searchText}
                onChange={(event) => {
                  setSearchText(event.target.value);
                  // 清空输入框即回到全部列表
                  if (!event.target.value.trim())
                    setFilter((current) => ({ ...current, query: "" }));
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !isImeComposing(event.nativeEvent)) {
                    setFilter((current) => ({ ...current, query: searchText }));
                  }
                }}
                className="min-w-0 flex-1 bg-transparent outline-none"
              />
            </label>
            {filter.tag && (
              <button
                className="flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs hover:text-foreground"
                title="不再按标签筛选"
                onClick={() => setFilter((current) => ({ ...current, tag: null }))}
              >
                #{filter.tag}
                <X className="size-3" />
              </button>
            )}
          </div>
          {filter.query.trim() && (
            <p className="text-xs text-muted-foreground">
              按与「{filter.query.trim()}」的相关程度排列
            </p>
          )}
          {items.isPending && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              加载中…
            </p>
          )}
          {items.isError && (
            <p className="text-sm text-danger">加载失败：{readableError(items.error)}</p>
          )}
          {items.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {filter.query.trim() || filter.tag || filter.view !== "all"
                ? "没有符合条件的条目"
                : "还没有记住任何信息"}
            </p>
          )}
          <ul className="space-y-2">
            {items.data?.map((item) => (
              <KnowledgeItemCard
                key={item.id}
                item={item}
                onTag={(tag) => setFilter((current) => ({ ...current, tag }))}
              />
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/** 手动添加一条记忆。 */
function AddForm() {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [pinned, setPinned] = useState(false);
  const add = useMutation({
    mutationFn: api.addKnowledge,
    onSuccess: async () => {
      setContent("");
      setTags("");
      setPinned(false);
      await queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });
  return (
    <form
      className="space-y-2 rounded-lg border border-border bg-card p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (content.trim()) add.mutate({ content, tags: parseTags(tags), pinned });
      }}
    >
      <textarea
        aria-label="要记住的信息"
        placeholder="写一条要记住的信息，如：我对花生过敏"
        rows={2}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-ring"
      />
      <div className="flex flex-wrap items-center gap-3">
        <input
          aria-label="标签"
          placeholder="标签（用逗号分隔，可不填）"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          className="min-w-40 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:border-ring"
        />
        <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(event) => setPinned(event.target.checked)}
          />
          常驻（每次对话都带上）
        </label>
        <button
          type="submit"
          disabled={!content.trim() || add.isPending}
          className="flex items-center gap-1 rounded-md bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
        >
          <Plus className="size-3.5" />
          添加
        </button>
      </div>
      {add.isError && <p className="text-xs text-danger">添加失败：{readableError(add.error)}</p>}
    </form>
  );
}
```

在 `frontend/src/layout/AppShell.tsx` 中，把：

```tsx
import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useState } from "react";
```

改为：

```tsx
import { useQuery } from "@tanstack/react-query";
import { BookMarked, Bot } from "lucide-react";
import { useState } from "react";
```

在 `frontend/src/layout/AppShell.tsx` 中，把：

```tsx
import { ChatView } from "../features/chat/ChatView";
import { AppearanceToggle } from "../features/settings/AppearanceToggle";
import { ThreadList } from "../features/threads/ThreadList";

/** 整体布局（参考 Hermes 的聊天页）：左侧会话栏 + 右侧对话区。 */
export function AppShell() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const threads = useQuery(threadsQuery);
```

改为：

```tsx
import { ChatView } from "../features/chat/ChatView";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { AppearanceToggle } from "../features/settings/AppearanceToggle";
import { ThreadList } from "../features/threads/ThreadList";

/** 整体布局（参考 Hermes 的聊天页）：左侧会话栏 + 右侧对话区（或知识库页）。 */
export function AppShell() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"chat" | "knowledge">("chat");
  const threads = useQuery(threadsQuery);
```

在 `frontend/src/layout/AppShell.tsx` 中，把：

```tsx
        </div>
        <ThreadList selectedId={selectedId} onSelect={setSelectedId} />
        <AppearanceToggle />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        {thread ? (
          <ChatView thread={thread} />
```

改为：

```tsx
        </div>
        <ThreadList
          selectedId={view === "chat" ? selectedId : null}
          onSelect={(threadId) => {
            setSelectedId(threadId);
            setView("chat");
          }}
        />
        <button
          aria-current={view === "knowledge" ? "page" : undefined}
          onClick={() => setView("knowledge")}
          className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${
            view === "knowledge"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <BookMarked className="size-4" />
          知识库
        </button>
        <AppearanceToggle />
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        {view === "knowledge" ? (
          <KnowledgePage />
        ) : thread ? (
          <ChatView thread={thread} />
```

- [ ] **步骤 4：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 201 个、前端 90 个）。页面本身在任务 9 的浏览器验证里检查（项目的前端单元测试只覆盖纯逻辑）。

---

### 任务 9：文档收尾与端到端验证

**文件：**
- 修改：`docs/decisions/D11-记忆与个人画像都是知识条目.md`、`docs/development/architecture.md`、`README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`、`agents/tests/live/test_smoke.py`

- [ ] **步骤 1：决策记录、架构规范与 README**

D11 补上落地时的调整（召回下限、跟随会话模型、只回 JSON、代码位置）：

在 `docs/decisions/D11-记忆与个人画像都是知识条目.md` 末尾追加：

```markdown

## 补充：M3a 落地时的调整（2026-10-15）

- **相关记忆的相似度下限改为 0.3**：先行探测里，qwen3-embedding 0.6B 上真正相关的记忆与问题的相似度只有 0.34～0.64，无关的也有 0.39～0.46，0.75 什么都召回不到。现在取最相近的 5 条、下限 0.3（`config/app.yaml` 的 `knowledge.recall_min_similarity`），由提示词告诉模型"不一定相关，自行判断"。
- **记忆提取与标题生成跟随会话所选的模型**（用户决定），不另配便宜模型。代价：用贵的模型时每次运行后多一次较贵的调用（gpt-5.5-pro 约 0.04 美元一次）；不需要时可关闭自动提取。
- **提取结果让模型只回一段 JSON，由我们自己解析**：结构化输出（with_structured_output）在 claude 上返回空结果、在 gpt-5.5-pro 上被拒绝；只回 JSON 在三个模型上都稳定。回复读不懂时本次不改动记忆、不重试。
- 后台任务落在 `backend/runtime/jobs.py`（任务队列，运行时替换点⑤）与 `backend/runs/followups.py`（运行结束后登记、执行的后续任务），不是原计划的 `backend/jobs/`。
- 向量化本身的用量（本机模型，免费）不记入用量表。
```

架构规范新增第 12 节"知识库、记忆与后台任务"：

在 `docs/development/architecture.md` 中，把：

```markdown
| `backend/runs/writer.py` | 事件分批写库与结束时的整体替换 |
| `backend/runtime/` | 运行时替换点：事件总线（②）、运行控制（③） |

```

改为：

```markdown
| `backend/runs/writer.py` | 事件分批写库与结束时的整体替换 |
| `backend/runtime/` | 运行时替换点：事件总线（②）、运行控制（③）、后台任务队列（⑤，见第 12 节） |

```

在 `docs/development/architecture.md` 中，把：

```markdown

## 11. 本机安全防护（设计文档 12.2）
```

改为：

````markdown

## 12. 知识库、记忆与后台任务（设计文档第 8 节）

```
每次运行开始 → MainAgent 查常驻条目 + 与这句话相关的记忆（向量召回）→ 运行上下文 → 知识上下文中间件拼进系统提示词
智能体 remember → 知识存储写入（向量化 + 分词）→ 工具结果附带条目 → 翻译器推送 memory.saved → 前端"已记住"
运行顺利结束 → RunFollowups 登记后台任务（第一次顺利结束：标题；开启自动提取：记忆提取）→ jobs 表
  └→ TableJobQueue 后台循环逐个处理 → 读运行的消息与回答 → MainAgent.generate_title / extract_memories
       → 改会话标题 / 改知识库；模型用量记在这次运行名下（调用方 title / memory_extraction）
知识库页 → /api/knowledge/*（列表、检索、增删改、常驻汇总）
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/models/embedding.py` | 替换点：向量化（`Embedder`），经网关的实现；统一 1024 维；契约测试 `agents/tests/contracts/test_embedder_contract.py` |
| `agents/main_agent/knowledge/base.py` | 替换点：知识存储（`KnowledgeStore`：增删改查、常驻条目、检索、记忆召回）；契约测试 `test_knowledge_contract.py`（集成） |
| `agents/main_agent/knowledge/pgvector.py` | PostgreSQL 实现：`knowledge_items` 表；向量检索与关键词检索按倒数排名融合合并；查询加 Qwen 的任务说明前缀，条目本身不加 |
| `agents/main_agent/knowledge/tokens.py` | jieba 分词（搜索引擎模式），写入与查询用同一套切法 |
| `agents/main_agent/knowledge/extraction.py` | 会后提取记忆：对照相近的已有记忆，按模型回的 JSON 新增 / 更新 / 删除 |
| `agents/main_agent/runtime/knowledge.py` | `remember` / `search_knowledge` 工具与知识上下文中间件 |
| `agents/main_agent/runtime/titles.py` | 会话标题生成与清理 |
| `backend/runtime/jobs.py` | 后台任务队列：`jobs` 表 + 本进程一个后台循环，失败按次数延后重试，最多 3 次 |
| `backend/runs/followups.py` | 运行顺利结束后的后续任务：登记与处理程序 |
| `backend/api/knowledge.py` | 知识库接口 |
| `frontend/src/features/knowledge/` | 知识库页 |

约定：
1. **召回失败不影响回答**：向量化服务不可用时，本次运行不带相关记忆（常驻条目不需要向量化，照常带上）；`remember` / `search_knowledge` 失败时工具结果标为出错并说明原因，运行继续。知识库页的添加、搜索返回 503 并说明原因，不带搜索词的列表照常可用。
2. **常驻条目**：每次调用模型都带上，总量的建议上限是 `config/app.yaml` 的 `knowledge.pinned_token_limit`（默认 2000 token），超过时知识库页提示精简——只提示，不截断。自动提取不改常驻条目（只列给模型看，避免重复）。
3. **后台任务**：只在运行顺利结束时登记，并且在推送结束事件之前登记（前端收到结束事件时任务已在队列里）；登记失败只记日志。任务逐个处理，标题排在记忆提取前面。处理程序抛异常时按次数延后重试（30 秒、60 秒），第 3 次失败记为失败并留下原因；服务停止时正在处理的任务保持"处理中"，下次启动时重做。会话被删除后，它的任务直接结束。
4. **标题**：会话的标题先是首条消息的前 30 个字（自动标题）；第一次顺利结束后由后台生成。只有标题仍是自动标题时才替换（带条件更新，生成期间用户改了名也不覆盖）。前端在运行结束后标题仍是自动标题时，隔 2、5、10、20 秒刷新会话列表。
5. **新增后台任务种类**：在 `RunFollowups.handlers()` 登记处理函数，在 `after_completed` 里决定何时登记；处理函数要能重复执行（可能被重试或重启后重做）。

## 11. 本机安全防护（设计文档 12.2）
````

在 `README.md` 中，把：

```markdown

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

改为：

```markdown

长期记忆：对话中说"记住……"，智能体会记下来并在回答里提示"已记住"；每次对话结束后，后台还会自动整理值得记住的信息（`config/app.yaml` 的 `knowledge.auto_extract: false` 可关闭），并为新会话起标题——这两件事用的是会话所选的模型，会产生少量费用。点侧栏的"知识库"查看、搜索、修改、删除记下的内容；设为"常驻"的条目（个人画像，如"回答简洁点"）每次对话都会带上。向量化用本机 Ollama 里的向量模型（`make up` 会自动下载），不产生费用。

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

- [ ] **步骤 2：需求池与变更记录**

R06 拆成 R06a（本期）与 R06b（M3b）：

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R05b | 文件上传、右侧文件面板、预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型；M2a 延后的下载、文件类型等小问题 | M2b | 高 | 完成 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
| R07 | MCP 接入、审批暂停与恢复、预算刹车 | M4 | 高 | 计划 |
```

改为：

```markdown
| R05b | 文件上传、右侧文件面板、预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型；M2a 延后的下载、文件类型等小问题 | M2b | 高 | 完成 |
| R06a | 统一知识库的记忆部分：知识条目与混合检索（向量 + 关键词）、记住 / 检索工具、相关记忆自动召回、常驻条目（个人画像）、会后自动提取记忆、后台任务队列、会话标题生成、知识库页（记忆管理）、"已记住"提示 | M3a | 高 | 完成 |
| R06b | 统一知识库的文档部分：文档上传与解析切块、检索带出处、读取文档原文（read_document）、知识库页的文档部分、会话附件一键加入知识库 | M3b | 高 | 计划 |
| R07 | MCP 接入、审批暂停与恢复、预算刹车 | M4 | 高 | 计划 |
```

在 `docs/changelog.md` 中，把：

```markdown
## 未发布

```

改为：

```markdown
## 未发布

### M3a 记忆与知识库（完成）

- 新增：长期记忆（设计文档第 8 节）——对话中说"记住……"或智能体判断值得记时，用 `remember` 工具记下，回答里显示"已记住：xxx"（推送 `memory.saved` 事件）；需要以前说过的信息时用 `search_knowledge` 检索。每次运行开始时，常驻条目（个人画像）与和这句话相关的记忆（最多 5 条）拼进系统提示词；向量模型不可用时照常回答，只是这次不带相关记忆。
- 新增：会后自动提取记忆——每次运行顺利结束后，后台用会话所选的模型读这一轮对话，对照相近的已有记忆决定新增 / 更新 / 删除 / 忽略（常驻条目只读）；可在 `config/app.yaml` 的 `knowledge.auto_extract` 关闭。费用记入用量表，调用方为 `memory_extraction`。
- 新增：会话标题——会话第一次顺利结束后，后台用会话所选的模型按对话内容起一个简短的标题，几秒后侧栏自动更新；用户改过名的不动。调用方为 `title`。
- 新增：知识库页（侧栏"知识库"）——按全部 / 记忆 / 常驻查看，按意思或关键词搜索，点标签筛选；手动添加、修改、删除，设或取消常驻；显示常驻信息的总 token，超过建议的 2000 时提示精简。接口 `GET/POST /api/knowledge/items`、`PATCH/DELETE /api/knowledge/items/{id}`、`GET /api/knowledge/pinned`。
- 新增：知识条目表 `knowledge_items`（迁移 0006，启用 pgvector 扩展）与后台任务表 `jobs`（迁移 0007）。检索 = 向量检索（qwen3-embedding 0.6B，经网关）+ 关键词检索（jieba 分词后存入全文检索字段），按倒数排名融合合并。新增依赖 `jieba` 0.42.1。
- 调整（与设计文档不同）：相关记忆的相似度下限为 0.3（设计文档写的初始值 0.75 在实测中什么都召回不到）；记忆提取与标题生成跟随会话所选的模型（不另配便宜模型）；记忆提取让模型只回 JSON、由我们自己解析（部分模型的结构化输出不可靠）。见 D11 的补充说明。

```

- [ ] **步骤 3：真实模型冒烟测试**

提取记忆与起标题用真实模型各跑一次（claude-opus-4-6，费用约 0.05 美元）：

在 `agents/tests/live/test_smoke.py` 中，把：

```python
import time
from pathlib import Path
```

改为：

```python
import time
import uuid
from pathlib import Path
```

在 `agents/tests/live/test_smoke.py` 中，把：

```python

from agents.main_agent.models import EMBEDDING_DIMENSIONS, LiteLLMProxyEmbedder, LiteLLMProxyGateway
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeSandbox
from config import get_settings
```

改为：

```python

from agents.main_agent.knowledge import NewKnowledge
from agents.main_agent.models import EMBEDDING_DIMENSIONS, LiteLLMProxyEmbedder, LiteLLMProxyGateway
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeKnowledgeStore, FakeSandbox
from config import get_settings
```

在 `agents/tests/live/test_smoke.py` 末尾追加：

```python


async def test_memory_extraction_and_title_with_real_model(gateway: LiteLLMProxyGateway) -> None:
    """M3a：会后提取记忆、生成标题用会话所选的模型；模型只回 JSON，由我们自己解析。"""
    store = FakeKnowledgeStore()
    await store.add(NewKnowledge(content="用户每天早上喝美式咖啡", source="manual"))
    agent = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        knowledge=store,
    )
    message = "我上个月换工作了，现在在字节做数据平台。另外我不喝咖啡了，改喝茶。帮我写个周报模板。"
    answer = "好的，下面是周报模板……"
    usage = [
        u
        async for u in agent.extract_memories(
            thread_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            model=CLAUDE,
            message=message,
            answer=answer,
        )
    ]
    contents = [item.content for item in store.items.values()]
    print(f"提取后的记忆：{contents}；用量：{usage}")
    assert any("字节" in content for content in contents)
    assert not any("美式咖啡" in content for content in contents)  # 过时的记忆被更新或删除
    assert [u.caller for u in usage] == ["memory_extraction"]

    title, title_usage = await agent.generate_title(model=CLAUDE, message=message, answer=answer)
    print(f"标题：{title}；用量：{title_usage}")
    assert 0 < len(title) <= 30
    assert [u.caller for u in title_usage] == ["title"]
```

先 `make infra-up`，再运行（会产生费用，不放进自动重放）：

```bash
uv run pytest -m live -s agents/tests/live/test_smoke.py -k "embedder or memory_extraction"
```

预期：2 个测试通过；输出里"提取后的记忆"包含"字节"相关的一条、不再有"美式咖啡"，标题不超过 30 个字。若模型的判断与断言不符（如把咖啡那条留着又新增了"改喝茶"），把输出记进执行记录再判断是提示词问题还是断言过严，不要直接放宽断言。

- [ ] **步骤 4：浏览器端到端验证**

先运行 `make build`（前端界面改了、后端加了 `jieba`，要重新构建镜像；启动时自动执行迁移 0006、0007），打开 http://127.0.0.1:8000。对话模型选 `gemini-3.5-flash`（便宜），整个验证费用约 0.1 美元。

1. **记住**：新建会话，发送"记住：我对花生过敏，以后推荐吃的都要避开"。
   - 回答里出现绿色书签图标和"已记住：用户对花生过敏"（措辞可能略有不同）；
   - 刷新页面后这条提示仍在。
2. **标题**：几秒内侧栏和顶部的会话标题从首条消息的前 30 个字变成一个简短的标题（如"花生过敏提醒"）。
   - 再新建一个会话，发消息后、标题生成前，在侧栏把它重命名为"我的测试"：之后标题保持"我的测试"。
3. **召回**：新建会话，发送"推荐几样下午茶零食"：回答避开花生，或提到你对花生过敏。
4. **自动提取**：新建会话，发送"我上个月换工作了，现在在字节做数据平台。帮我列个周报的提纲"。
   - 等十几秒后打开侧栏"知识库"：出现一条与"字节、数据平台"有关的记忆，来源"对话中记下"；
   - 顶栏这个会话的累计用量比回答下方显示的多出两次调用（标题与记忆提取）。
5. **知识库页**：
   - 全部 / 记忆 / 常驻三个视图切换正常；
   - 搜索框用拼音输入"过敏"：选词时按回车只确认选词，再按一次回车才开始搜索，结果第一条是花生过敏那条；搜索"ERR"之类不存在的词显示"没有符合条件的条目"；清空搜索框回到全部列表；
   - 手动添加"回答尽量简洁，先给结论"，标签填"偏好，风格"，勾选常驻：出现在列表顶部，带两个标签和"常驻"；常驻视图里能看到，汇总显示条数与 token；点"#偏好"只看带这个标签的，点 × 取消；
   - 修改一条记忆的内容和标签，保存后列表更新；取消常驻再设回常驻；
   - 删除一条：先出现"删除这条？删除后无法恢复。"，点"删除"后消失。
6. **常驻生效**：新建会话，问"Python 的 GIL 是什么"：回答明显简短、先给结论。
7. **深浅色**：侧栏底部切到浅色、深色，知识库页与"已记住"提示都清晰可读。
8. **向量模型不可用**：终端运行 `podman compose --env-file .env -f deploy/docker-compose.yml stop ollama`（用 Docker 的把 `podman compose` 换成 `docker compose`）。
   - 新建会话问一句话：照常回答（只是不带相关记忆）；
   - 知识库页添加一条：显示"添加失败：向量化服务不可用：…"；搜索同样提示失败；不搜索的列表照常显示；
   - 运行 `podman compose --env-file .env -f deploy/docker-compose.yml start ollama` 恢复，再添加一次成功。

预期：以上全部符合描述。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 201 个、前端 90 个）；`make test-int` 全部通过（集成测试 95 个）。

收尾：
- 全部通过后，`docs/changelog.md` 的 M3a 小节保持"（完成）"、`docs/requirements/backlog.md` 的 R06a 保持"完成"；
- 若冒烟测试或浏览器验证有未通过项，两处改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖**（第 21 节 M3 行中属于 M3a 的部分）：
  - 知识条目（8.1：种类、标签、常驻、来源）、`knowledge_items` 表（11 节）→ 任务 2；
  - 混合检索（8.3：向量 + jieba 关键词，倒数排名融合）→ 任务 2；向量模型、统一 1024 维、查询加任务说明前缀（8.5）→ 任务 1、2；
  - 常驻条目每次拼进系统提示词、相关记忆自动召回（8.3）→ 任务 4；
  - 智能体工具 `remember`、`search_knowledge`（8.3）与"已记住"提示（8.2，`memory.saved`）→ 任务 4；
  - 会后自动提取记忆，"新增 / 更新 / 删除 / 忽略"，可在 `config/app.yaml` 关闭，费用计入用量表（8.2）→ 任务 5；
  - 后台任务（10.9 替换点⑤）→ 任务 3、5；标题生成 → 任务 6；
  - 知识库界面：按种类、标签、常驻筛选与搜索，修改、删除、设常驻，"常驻"视图即个人画像并显示总 token（8.4、13 节）→ 任务 7、8；常驻条目总量上限约 2000 token、超出时提示（8.1）→ 任务 7、8。
- **与设计文档的差异：**
  1. 8.3 相关记忆的阈值：设计文档的初始值 0.75 实测召回不到任何记忆，改为取最相近的 5 条、相似度不低于 0.3（可在 `config/app.yaml` 调整），提示词说明"不一定相关"。
  2. 8.2、8.5 记忆提取与标题生成"用便宜的模型"：按用户决定改为跟随会话所选的模型；`config/app.yaml` 只能开关自动提取，不能单独指定模型。
  3. 记忆提取让模型只回 JSON、由我们自己解析（不用结构化输出）；回复读不懂时本次不改动、不重试。
  4. 8.3"同一中间件在每条新用户消息到来时将其向量化"：改为主智能体在运行开始时查一次（常驻条目与相关记忆），中间件只负责拼进系统提示词——同一次运行里多次调用模型不重复向量化。
  5. 后台任务的代码在 `backend/runtime/jobs.py`（队列）与 `backend/runs/followups.py`（运行结束后的任务），不是 D11 写的 `backend/jobs/`；任务逐个处理。
  6. 只在运行顺利结束时提取记忆、生成标题；停止、失败的运行不做。
  7. 接口表"知识库"一行：本期只做条目部分，另加 `GET /knowledge/pinned`（常驻汇总）；带搜索词的列表忽略 `offset`。文档部分（`/knowledge/documents`）属于 M3b。
  8. 13 节知识库页：本期只有"全部 / 记忆 / 常驻"三个视图（文档在 M3b）；13.3 右侧侧栏的"知识"页不做，知识库是侧栏入口打开的整页。
  9. 向量化本身的用量（本机模型，免费）不记入用量表。
  10. 删除会话不删它记下的记忆（知识条目的来源会话不设外键）；要删在知识库页删。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：** 已用严格类型检查、mypy 与重放验证。
  - `KnowledgeStore` 的方法名（`list_items`、`pinned`、`search`、`recall`）在 PostgreSQL 实现、测试替身、主智能体、提取、接口里一致；
  - 任务种类 `title`、`memory_extraction` 与用量调用方同名；`RunFollowups` 的参数在服务装配、测试里一致；
  - `memory.saved` 的字段在事件、翻译器、前端事件处理器（`memory-<item_id>`）、转换函数（`data-memory`）里一致。
