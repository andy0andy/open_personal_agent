# 向量化改为进程内 ONNX（EmbeddingGemma），去掉 Ollama Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 向量化改在后端进程里用 ONNX Runtime 跑 EmbeddingGemma 300M（768 维），去掉 compose 里的 Ollama；已有的知识条目自动重建向量。

**Architecture:** 新增 `Embedder` 的实现 `OnnxEmbedder`（第一次用到时加载模型，计算放到线程里），`adapters.embedder` 默认改为 `onnx`。模型文件放 `.workdata/models/`，后端启动后在后台检查、缺了就下载并校验。表里的向量列改成 768 维、可空；启动后在后台给没有向量的条目补算。经网关的 `LiteLLMProxyEmbedder` 保留作为另一种实现（端到端测试继续用它）。

**Tech Stack:** onnxruntime 1.20.1、tokenizers 0.23.3（都已在锁文件里，只是登记为直接依赖）、httpx、pgvector、alembic、pytest。

**Spec:** `docs/decisions/D28-向量化改为进程内ONNX与EmbeddingGemma.md`（用户 2026-11-18 决定用 gemma）。需求 R50。

> **执行记录（2026-11-18）**：迁移 0019 提前到 Task 1 做（否则集成测试会红）；Task 7 排在 Task 5、6 之前做；启动时的下载与补算放在单独的后台任务 `_prepare_embeddings`；没有做下载用的命令行入口。台账见 `.superpowers/sdd/2026-11-18-onnx-embedder/progress.md`。

## Global Constraints

- 不安装新的包：`uv add onnxruntime==1.20.1 tokenizers==0.23.3` 后锁文件里这两个包的版本不变；变了就停下来说明。
- 模型固定为 `onnx-community/embeddinggemma-300m-ONNX`，提交 `5090578d9565bb06545b4552f76e6bc2c93e4a66`，项目里的名字 `embeddinggemma-300m-q4`，三个文件（本地文件名 ← 仓库内路径，SHA-256，字节数）：
  - `model_q4.onnx` ← `onnx/model_q4.onnx`，`ad1dfee81a70f7944b9b9d1cc6e48075b832881cf33fab2f2b248be78f3f0043`，519322
  - `model_q4.onnx_data` ← `onnx/model_q4.onnx_data`，`599962c3143b040de2dd05e5975be3e9091dd067cacc6a8f7186e3203bab9e02`，196725760
  - `tokenizer.json` ← `tokenizer.json`，`4dda02faaf32bc91031dc8c88457ac272b00c1016cc679757d1c441b248b9c47`，20323312
- 向量 768 维，输出取模型的 `sentence_embedding`，再做一次长度归一化；最多 2048 个 token，超出截断。
- 前缀：查询 `task: search result | query: `，文档 `title: none | text: `（一个字符都不能差）。
- `knowledge.recall_min_similarity` 默认值 0.3 不改。
- `onnxruntime`、`tokenizers` 只在 `agents/main_agent/models/onnx_embedder.py` 里导入。
- 模型文件不进仓库、不进镜像；不读、不打印 `.env`。
- 中文注释，只写"为什么"；所有读写异步，CPU 计算放线程；可预期的错误用 `common.errors`（向量化不可用一律 `UpstreamError`，原因只给一句中文）。
- 只有用户明确要求时才提交，不推送。
- 每个任务先写失败的测试、看它失败，再写实现；任务结束跑 `make check`，涉及数据库的再跑 `make test-int`。

## Review Focus

1. **模型文件缺失、下到一半、哈希不对**：对话照常；自动召回静默降级；知识库页与工具卡片给一句中文原因；下载完成后不重启就能用（每次调用都重新检查文件，加载成功后才不再检查）。
2. **升级路径**：旧库 1024 维 → 迁移 → 向量为空 → 后台补算。补到一半重启能接着做；补算期间按关键词照常能搜到，按意思检索不报错（空向量不参与）。
3. **不挡事件循环**：入库时 CPU 用满（约 0.5 秒一段），对话的流式输出、停止按钮仍然及时；两处同时向量化不死锁、模型只加载一次。
4. **前缀只加一次**：查询与文档各用各的前缀；补算时文档片段用的文字与入库时完全一致（带《文档名》与章节）。
5. **已有安装的清理**：只删网关里上游是 `ollama/` 的模型，不误删用户自己加的；端到端测试（假网关上的向量模型）不受影响。

---

### Task 1: `Embedder` 接口区分查询与文档，维度改 768

**Files:**
- Modify: `agents/main_agent/models/embedding.py`、`agents/main_agent/models/__init__.py`
- Modify: `agents/main_agent/knowledge/pgvector.py`（删掉 `QUERY_PREFIX`，调用处传 `kind`）
- Modify: `agents/tests/fakes.py`（`FakeEmbedder.embed` 加同样的参数，忽略它）
- Test: `agents/tests/contracts/test_embedder_contract.py`、`agents/tests/test_embedding.py`、`agents/tests/test_pgvector_store.py`

**Interfaces:**
- Produces:
  - `type EmbedKind = Literal["query", "document"]`（从 `agents.main_agent.models` 导出）
  - `Embedder.embed(self, texts: Sequence[str], *, kind: EmbedKind = "document") -> list[list[float]]`
  - `EMBEDDING_DIMENSIONS = 768`
  - `LiteLLMProxyEmbedder(..., query_prefix: str = "", document_prefix: str = "")`：发给网关前按 `kind` 加前缀

- [x] **Step 1: 写失败的测试**
  - 契约 `test_accepts_query_and_document_kinds`：两种 `kind` 都返回 `EMBEDDING_DIMENSIONS` 维、数量与输入一致。
  - `test_embedding.py::test_prefix_follows_kind`：`query_prefix="Q:"`、`document_prefix="D:"` 时，网关收到的 `input` 分别是 `["Q:一"]`、`["D:一"]`；不传前缀时原样。
  - `test_embedding.py` 里维度不对的那条改为断言 `"向量维度应为 768，实际为 1024"`。
  - `test_pgvector_store.py::test_embeds_queries_and_documents_by_kind`：用一个记录调用的假向量模型，`add`、`add_chunks`、`update`（改内容）记到的是 `("document", 原文)`；`search`、`recall` 记到的是 `("query", 问句原文)`，文字里不带任何前缀。
- [x] **Step 2: 运行** `uv run pytest agents/tests/contracts/test_embedder_contract.py agents/tests/test_embedding.py -q`，Expected: 新增的几条 FAIL（`embed() got an unexpected keyword argument 'kind'`、维度断言不符）。
- [x] **Step 3: 实现**上面 Produces 的四项；`pgvector.py` 里四处 `embed` 调用补上 `kind`。
- [x] **Step 4: 运行** `make check` 与 `make test-int`，Expected: 全部通过。

### Task 2: `OnnxEmbedder`

**Files:**
- Create: `agents/main_agent/models/onnx_embedder.py`
- Modify: `agents/main_agent/models/__init__.py`、`pyproject.toml`（两个直接依赖；mypy 对 `onnxruntime`、`tokenizers` 缺类型标注时加 `ignore_missing_imports`）、`uv.lock`
- Test: `agents/tests/test_onnx_embedder.py`、`agents/tests/contracts/test_embedder_contract.py`（参数里加一个配假运行时的 `OnnxEmbedder`）

**Interfaces:**
- Consumes: Task 1 的 `Embedder`、`EmbedKind`、`EMBEDDING_DIMENSIONS`、`EmbeddingUsage`。
- Produces:
  ```python
  @dataclass(frozen=True)
  class OnnxModelFile:
      path: str      # 仓库内路径
      sha256: str
      size: int

  @dataclass(frozen=True)
  class OnnxModelSpec:
      name: str
      repo: str
      revision: str
      files: Mapping[str, OnnxModelFile]  # 键：本地文件名
      model_file: str                     # files 里哪个是模型入口
      dimensions: int
      max_tokens: int
      query_prefix: str
      document_prefix: str
      output: str                         # 取模型的哪个输出

  ONNX_MODELS: dict[str, OnnxModelSpec]   # 现在只有 "embeddinggemma-300m-q4"

  class OnnxRuntime(Protocol):            # 加载好的模型
      def encode(self, texts: Sequence[str]) -> tuple[list[list[float]], int]:
          """返回每段文字的向量（未归一化）和这批一共多少 token。"""

  def files_ready(model_dir: Path, spec: OnnxModelSpec) -> bool   # 每个文件都在且字节数相符

  class OnnxEmbedder:
      def __init__(
          self, model_dir: Path, spec: OnnxModelSpec, *, batch_size: int = 2,
          on_usage: Callable[[EmbeddingUsage], Awaitable[None]] | None = None,
          load: Callable[[Path, OnnxModelSpec], OnnxRuntime] | None = None,  # 仅测试时注入
      ) -> None
      model: str                          # = spec.name
      async def embed(self, texts, *, kind: EmbedKind = "document") -> list[list[float]]
  ```

- [x] **Step 1: 写失败的测试**（都用注入的假运行时，不加载真模型）
  - `test_prefixes_by_kind_and_normalizes`：假运行时对任何文字返回 `[3.0, 4.0, 0, …]`；结果前两维是 `0.6, 0.8`；它收到的文字分别带查询、文档前缀。
  - `test_loads_lazily_and_only_once`：构造时不调用 `load`；`asyncio.gather` 同时两次 `embed` 后 `load` 只被调用 1 次。
  - `test_batches_in_order`：5 段、`batch_size=2` → 运行时依次收到 2、2、1 段，结果顺序与输入一致。
  - `test_empty_input_does_not_load`。
  - `test_missing_files_raise_upstream_error`：目录里缺文件 → `UpstreamError`，消息含"向量模型还没下载好"；之后把文件补齐，同一个对象再调用就成功（不用重启）。
  - `test_runtime_error_becomes_upstream_error`：`encode` 抛 `RuntimeError` → `UpstreamError("向量化服务不可用：向量模型运行出错")`。
  - `test_wrong_dimensions_rejected`：运行时给出 5 维 → `UpstreamError`，消息含"向量维度应为 768"。
  - `test_reports_usage`：`on_usage` 收到 `EmbeddingUsage(model="embeddinggemma-300m-q4", input_tokens=<运行时报的合计>, duration_ms>=0)`；`on_usage` 抛错不影响返回。
  - `test_does_not_block_the_event_loop`：`encode` 里 `time.sleep(0.3)`；同时跑一个每 10 毫秒计数的协程，期间计数 ≥ 10。
  - `test_gemma_spec_matches_the_decision`：`ONNX_MODELS["embeddinggemma-300m-q4"]` 的仓库、提交、三个文件的路径与哈希与字节数、768、2048、两个前缀、`sentence_embedding` 与 Global Constraints 逐项相同。
- [x] **Step 2: 运行** `uv run pytest agents/tests/test_onnx_embedder.py -q`，Expected: FAIL（模块不存在）。
- [x] **Step 3: 登记直接依赖** `uv add onnxruntime==1.20.1 tokenizers==0.23.3`，然后 `git diff uv.lock` 确认这两个包的版本没变。
- [x] **Step 4: 实现。** 要点：`embed` 先看 `files_ready`，再在 `asyncio.Lock` 里加载一次（`asyncio.to_thread`）；每批的 `encode` 也走 `asyncio.to_thread`，并用同一把锁串行（CPU 计算并行没有好处）。真实的加载函数：`tokenizers.Tokenizer.from_file` + 截断到 `max_tokens` + 用 `<pad>` 补齐；`onnxruntime.InferenceSession(…, providers=["CPUExecutionProvider"])`；只喂会话声明了的输入（`input_ids`、`attention_mask`）；token 数取 `attention_mask` 的和。
- [x] **Step 5: 运行** `make check`，Expected: 通过（含契约测试里新增的一项）。

### Task 3: 模型文件的下载与校验

**Files:**
- Create: `agents/main_agent/models/onnx_download.py`
- Modify: `agents/main_agent/models/__init__.py`、`config/settings.py`（新增 `embedding_download_base: str = "https://huggingface.co"`，只从环境变量读，不进设置页；新增属性 `models_dir` = `workdata_dir / "models"`）
- Test: `agents/tests/test_onnx_download.py`、`config/tests/test_settings.py`

**Interfaces:**
- Consumes: Task 2 的 `OnnxModelSpec`、`ONNX_MODELS`。
- Produces:
  ```python
  async def ensure_model(
      model_dir: Path, spec: OnnxModelSpec, *, base_url: str,
      transport: httpx.AsyncBaseTransport | None = None,  # 仅测试时注入
      connections: int = 8, part_bytes: int = 4 * 1024 * 1024,
  ) -> list[str]:
      """文件齐全且哈希都对就什么都不做；否则下载缺的、坏的。返回这次下载的本地文件名。"""
  ```
  下载地址 `{base_url}/{repo}/resolve/{revision}/{path}`；失败抛 `UpstreamError`。

- [x] **Step 1: 写失败的测试**（`httpx.MockTransport` 模拟支持 `Range` 的文件服务；用几十字节的假模型规格）
  - `test_downloads_and_verifies`：三个文件都落盘、内容正确、目录里没有 `.part`；请求的地址符合上面的格式。
  - `test_does_nothing_when_files_are_valid`：一次请求都不发，返回 `[]`。
  - `test_replaces_a_corrupt_file`：内容被改过的那个文件被重新下载，其余不动。
  - `test_hash_mismatch_fails_cleanly`：服务器给的内容不对 → `UpstreamError`，消息含"校验没通过"；正式文件名不存在、`.part` 已删。
  - `test_large_file_uses_ranges`：`part_bytes=10`、文件 35 字节 → 发了 4 个带 `Range` 的请求，拼回来与原文一致。
  - `test_retries_a_failed_part`：某一段第一次 500、第二次成功 → 整体成功。
  - `test_network_error_becomes_upstream_error`：连不上 → `UpstreamError("向量模型下载失败：连不上下载地址")`。
  - `test_settings.py::test_models_dir_and_download_base`：`models_dir == workdata_dir / "models"`；`EMBEDDING_DOWNLOAD_BASE` 环境变量生效；`embedding_download_base` 不在 `SETTING_SPECS` 里。
- [x] **Step 2: 运行** `uv run pytest agents/tests/test_onnx_download.py -q`，Expected: FAIL（模块不存在）。
- [x] **Step 3: 实现。** 先写 `<文件名>.part`，SHA-256 对上再原子改名；先发一次请求拿到大小，超过 `part_bytes` 的按段并发（`asyncio.Semaphore(connections)`），每段最多试 3 次；哈希计算放线程。
- [x] **Step 4: 运行** `make check`，Expected: 通过。

### Task 4: 配置与装配

**Files:**
- Modify: `config/settings.py`（`AdaptersConfig.embedder` 默认 `"onnx"`；`KnowledgeConfig.embedding_model` 默认 `"embeddinggemma-300m-q4"`，注释改为"onnx：`ONNX_MODELS` 里的名字；litellm_proxy：网关里的模型名"；`ModelsConfig.sources` 删掉 `ollama`）
- Modify: `config/seed/models.yaml`（删掉 `embed-qwen3-0.6b`）
- Modify: `agents/main_agent/bootstrap.py`（`_EMBEDDERS` 加 `"onnx"`）
- Modify: `backend/tests/e2e_server.py`（设置里显式写 `adapters.embedder="litellm_proxy"`）
- Test: `config/tests/test_settings.py`、`agents/tests/test_bootstrap.py`、`backend/tests/test_seed.py`、`backend/tests/test_models_api.py`

**Interfaces:**
- Consumes: `OnnxEmbedder`、`ONNX_MODELS`、`Settings.models_dir`。
- Produces: `_EMBEDDERS["onnx"](settings, on_usage)` → `OnnxEmbedder(settings.models_dir / spec.name, spec, on_usage=on_usage)`，其中 `spec = ONNX_MODELS[settings.knowledge.embedding_model]`；名字不在表里时抛 `common.errors.InvalidConfigError`，消息列出可用的名字。

- [x] **Step 1: 写失败的测试**
  - `test_settings.py::test_defaults_match_the_old_app_yaml` 里向量模型与实现两处改为新默认值；新增断言 `[s.id for s in settings.models.sources] == ["upstream"]`。
  - `test_bootstrap.py::test_onnx_embedder_is_the_default`：默认设置装配出的向量化实现 `model == "embeddinggemma-300m-q4"`，构造时不加载模型、不联网。
  - `test_bootstrap.py::test_unknown_onnx_model_is_a_config_error`：抛 `InvalidConfigError`。
  - `test_seed.py`、`test_models_api.py` 里用到 `source="ollama"` 的测试：改为在测试自己的设置里加一个向量来源（如 `id="vec"`），不依赖默认来源。
- [x] **Step 2: 运行** 相关测试，Expected: FAIL（默认值还是旧的、`"onnx"` 没登记）。
- [x] **Step 3: 实现**上面的修改。
- [x] **Step 4: 运行** `make check`、`make test-int`、`make e2e`，Expected: 通过（端到端仍走假网关）。

### Task 5: 表结构改 768 维，后台补算向量

**Files:**
- Create: `backend/migrations/versions/0019_agents_knowledge_embedding_768.py`
- Modify: `agents/main_agent/knowledge/base.py`、`agents/main_agent/knowledge/pgvector.py`、`agents/tests/fakes.py`（`FakeKnowledgeStore`）
- Modify: `backend/main.py`（`_seed_models` 里加一段）
- Test: `backend/tests/test_migrations.py`、`agents/tests/test_pgvector_store.py`、`agents/tests/contracts/test_knowledge_contract.py`、`backend/tests/test_main_lifespan.py`（启动补算，与 `test_document_hashes_are_backfilled_on_every_start` 同一种写法）

**Interfaces:**
- Consumes: Task 1 的 `embed(…, kind="document")`；Task 3 的 `ensure_model`。
- Produces:
  - `KnowledgeStore.reembed_missing(self, *, limit: int = 20) -> int`：给最多 `limit` 条没有向量的条目补上向量和 `embedding_model`，返回补了几条（0 表示补完）。
  - 迁移 0019：`knowledge_items.embedding` 变为 `vector(768)`、可空，已有行置空，HNSW 索引重建；降级改回 `vector(1024)`（仍可空，向量仍为空）。
  - 启动后台任务的顺序：`adapters.embedder == "onnx"` 时先 `ensure_model`，再循环 `reembed_missing` 直到返回 0。

- [x] **Step 1: 写失败的测试**
  - `test_migrations.py::test_embedding_becomes_768_and_nullable`：升到 0018 插入一行带 1024 维向量的条目；升到 0019 后列类型是 `vector(768)`、可空，该行向量为 `NULL`、其余列不变，索引 `knowledge_items_embedding` 存在；降回 0018 后类型是 `vector(1024)`。
  - `test_pgvector_store.py::test_items_without_vectors_are_found_by_words_only`：把一条记忆的向量置空；`search` 用它里面的词能搜到，`recall` 不报错、不返回它。
  - `test_pgvector_store.py::test_reembed_missing_fills_in_batches`：一条记忆、两段文档片段的向量置空；`reembed_missing(limit=2)` 返回 2，再调返回 1，再调返回 0；三条的 `embedding_model` 都是当前模型；文档片段送去向量化的文字与 `add_chunks` 时相同（`《文档名》章节\n正文`）。
  - 契约 `test_reembed_missing_returns_zero_when_nothing_is_missing`。
  - 启动补算：`ensure_model` 抛 `UpstreamError` 时只记日志、不补算、不影响启动；正常时 `reembed_missing` 被反复调用到返回 0；`reembed_missing` 抛 `UpstreamError` 时停止并记日志。
- [x] **Step 2: 运行** `make test-int`（或指定这几条），Expected: FAIL。
- [x] **Step 3: 实现。** 迁移顺序：删索引 → 去掉 `NOT NULL` → 向量置空 → 改类型 → 建索引。`search`、`recall` 的向量那一路加 `i.embedding IS NOT NULL`。`reembed_missing` 每条 `UPDATE … WHERE id = %s AND embedding IS NULL`（并发时不重复写）。
- [x] **Step 4: 运行** `make check`、`make test-int`，Expected: 通过。

### Task 6: 已有安装里网关上的 Ollama 模型删一次

**Files:**
- Modify: `backend/settings/seed.py`、`backend/models/service.py`、`backend/main.py`
- Test: `backend/tests/test_seed.py`、`backend/tests/test_models_api.py`

**Interfaces:**
- Produces:
  - `ModelAdmin.names_with_upstream_prefix(self, prefix: str) -> list[str]`
  - `async def retire_ollama_models_once(workdata: Path, models: ModelAdmin) -> list[str]`：标记名 `ollama_retired`；删掉上游以 `ollama/` 开头的模型，返回删掉的名字；网关出错不记标记，下次启动再试。
  - `_seed_models` 里只在 `settings.adapters.embedder == "onnx"` 时调用，放在 `seed_models_once` 之后。

- [x] **Step 1: 写失败的测试**
  - `test_retire_ollama_models_once_deletes_only_ollama_models`：网关里有 `embed-qwen3-0.6b`（上游 `ollama/qwen3-embedding:0.6b`）和两个对话模型 → 只删前者，写了标记。
  - `test_retire_ollama_models_runs_once`：有标记时不查网关。
  - `test_retire_ollama_models_retries_after_gateway_error`：网关出错 → 不写标记、返回 `[]`。
  - 启动时 `adapters.embedder="litellm_proxy"` 不调用它（端到端测试的假网关里 `embed-fake` 的上游正是 `ollama/embed`）。
- [x] **Step 2: 运行**，Expected: FAIL。
- [x] **Step 3: 实现。**
- [x] **Step 4: 运行** `make check`、`make test-int`、`make e2e`，Expected: 通过。

### Task 7: compose、Makefile、打包、体检

**Files:**
- Modify: `deploy/docker-compose.yml`（删 `ollama`、`ollama-init`、数据卷 `ollama-models`；backend 的 `depends_on` 去掉 `ollama-init`）
- Modify: `Makefile`（`infra-up` 只起 `postgres litellm`、不再跑下载；几处说明文字）
- Modify: `deploy/bundle-images.sh`（`pull postgres litellm`）
- Modify: `deploy/doctor.py`
- Modify: `.env.example`（加一段注释掉的 `EMBEDDING_DOWNLOAD_BASE` 说明）
- Test: `deploy/tests/test_compose.py`、`test_makefile.py`、`test_bundle.py`、`test_doctor.py`

**Interfaces:**
- Consumes: `ONNX_MODELS["embeddinggemma-300m-q4"]`（只在测试里对照）。
- Produces（`deploy/doctor.py`，仍然只用标准库）：
  - `SERVICES = ("postgres", "litellm", "backend")`
  - `EMBEDDING_DIR = "models/embeddinggemma-300m-q4"`、`EMBEDDING_FILES: dict[str, int]`（文件名 → 字节数）
  - `_embedding_model(workdata: Path) -> Result`：三个文件都在且字节数相符 → `✓ 向量模型：embeddinggemma-300m-q4 已下载`；否则 `✗`，说明缺哪个，修法"后端启动后会自动下载（约 207 MB，make logs 看进度）；网络慢时在 .env 里设 EMBEDDING_DOWNLOAD_BASE 换镜像站，再 make restart"。
  - `_models`：不再要求网关里有向量模型；文字为"对话模型 N 个"，有向量模型时再加"、向量模型 M 个"。

- [x] **Step 1: 写失败的测试**
  - `test_compose.py::test_only_three_services_and_no_ollama`：默认服务恰好是 `postgres`、`litellm`、`backend`（另有 `test` 档的 `postgres-test`）；全文没有 `ollama`；数据卷只有 `pgdata`；backend 只依赖 `postgres`、`litellm`。删掉原来两条关于 `ollama-init` 的测试。
  - `test_makefile.py`：`make -n infra-up` 的输出里没有 `ollama`。
  - `test_bundle.py`：假镜像清单去掉 Ollama 那一行；脚本文本里没有 `ollama`。
  - `test_doctor.py`：清单里"Ollama"换成"向量模型"；新增文件齐全 `✓`、缺文件 `✗`、字节数不对 `✗` 三条；网关里没有向量模型时"模型"一项仍是 `✓`；`test_doctor_knows_the_same_model_files`：`EMBEDDING_DIR`、`EMBEDDING_FILES` 与 `ONNX_MODELS` 里的名字、文件名、字节数一致（替换原来"三处是同一个"的那条）。
- [x] **Step 2: 运行** `uv run pytest deploy/tests -q`，Expected: 新增的 FAIL。
- [x] **Step 3: 实现。**
- [x] **Step 4: 运行** `make check`，Expected: 通过；再 `podman compose -f deploy/docker-compose.yml config --images`（不带 `.env`，在干净的拷贝里跑）确认只列出三个镜像。

### Task 8: 真实模型验证、文档、本机切换

**Files:**
- Create: `agents/tests/live/test_onnx_embedding.py`
- Modify: `agents/tests/live/test_smoke.py`（删掉经网关调本机向量模型、断言 1024 维的两条）
- Modify 文档：`docs/decisions/D15-…md`（状态改"已替代（被 D28 替代）"）、`docs/decisions/README.md`、`docs/development/architecture.md`、`docs/development/testing.md`、`README.md`、`docs/usage.md`、`CLAUDE.md`（命令表里 `infra-up`、`doctor` 两行）、`docs/requirements/backlog.md`（R50 完成）、`docs/changelog.md`

- [x] **Step 1: 写真实模型的测试**（`live` 标记；`.workdata/models/embeddinggemma-300m-q4/` 不齐全时跳过并说明）
  - `test_real_model_dimensions`：768 维、长度为 1。
  - `test_real_model_finds_memories_across_languages`：6 条记忆（中文 3 条、英文 3 条），问句"我住在哪个城市？""我对什么药物过敏？"（答案是英文记忆）"What is my cat's name?"（答案是中文记忆）各自第 1 名正确。
  - `test_real_model_separates_unrelated_questions`：上面三个问句对正确记忆的相似度都 ≥ 0.3；"法国的首都是哪里？"对所有记忆的最高相似度 < 0.3。
- [x] **Step 2: 把已经下载并校验过的模型文件放到位**（省掉 5 分钟下载）：从验证用的临时目录复制到 `.workdata/models/embeddinggemma-300m-q4/`，三个文件名按 Global Constraints；然后 `uv run pytest -m live agents/tests/live/test_onnx_embedding.py -s`，Expected: 3 条通过。
- [x] **Step 3: 写文档。** `README.md`、`docs/usage.md` 要写到：服务从 4 个变 3 个；首次启动后台下载约 207 MB 的向量模型，下载期间能对话、知识库稍后可用；网络慢时怎么换下载地址；EmbeddingGemma 的来源与 Gemma 使用条款链接，模型不随仓库和镜像分发；`make bundle` 的包里没有模型，目标机器上自动下载或手工拷贝 `.workdata/models/`；模型页的来源只剩"公司 LiteLLM 网关"；"文档处理很慢"一段改成现在的速度。`architecture.md` 改替换点表、启动流程、用量那一段。`changelog.md` 写一节，列出磁盘、内存、速度、准确度的前后对比和升级注意事项（先备份、旧向量作废、自动补算）。
- [x] **Step 4: 全量检查** `make check`、`make test-int`、`make e2e`，Expected: 全部通过；把三条命令的结果数字记进台账。
- [x] **Step 5: 本机切换**（会动正在用的数据，按顺序）
  1. `make backup`，记下备份名。
  2. `make build`（重建后端镜像并启动；迁移 0019 自动执行）。
  3. `make logs` 里应看到：模型文件校验通过（不下载）、补算向量 13 条、删掉网关里的 `embed-qwen3-0.6b`。
  4. `make doctor`，Expected: 全部 ✓，其中"向量模型"一项 ✓，容器 3 个。
  5. 浏览器里验证：问一句和已有记忆相关的话，回答用上了记忆；知识库页搜索已有文档能搜到；上传一份新文档，处理完成；用量页有"向量化"的记录。
  6. `podman stats --no-stream` 记下后端容器的内存，写进 changelog。
- [x] **Step 6: 清理旧的 Ollama**（删除前先向用户确认）：停掉并删除容器 `open-personal-agent-ollama-1`、`open-personal-agent-ollama-init-1`，删数据卷 `open-personal-agent_ollama-models`（610 MB），删镜像 `mirror.gcr.io/ollama/ollama:0.40.3`（4.23 GB）。
- [x] **Step 7: 整体审查**（一次，用最强的模型，范围是本计划的全部改动），按 Review Focus 逐条检查；需要修的走"先写失败的测试"再修。
