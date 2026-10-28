# M3b 文档与出处 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。
>
> 本计划只写定下来的决定：文件、名称与签名、取值、每个任务用哪些测试证明。函数体由执行者按签名与测试写出；只有签名和测试决定不了的算法才在计划里写明规则。

**目标：** M3 的后一半——上传文档后，智能体能检索并带出处回答。

- 知识库页可以上传文档（PDF、Word、PPT、Excel、CSV、Markdown、TXT、网页），后台解析、切块、向量化，页面上看得到处理进度。
- 智能体检索到文档片段时，回答里带可点击的出处；点开在右侧看到这段原文和前后文，PDF 能打开到对应页。
- 智能体可以读取片段前后的原文（`read_document`）。
- 会话里的文件（上传的、生成的）可以一键加入知识库。
- 顺带处理需求池 R17（知识库的小问题）。

M3 拆成两份（2026-10-15 与用户确认"先记忆后文档"）：M3a 已完成，**M3b 是本计划**。

**架构：**

- **两个新的可替换接口**（设计文档 4.2 的 `doc_parser`、`blob_storage`）：
  - `DocumentParser`：文件内容 → Markdown；实现 `MarkItDownParser`；
  - `BlobStore`：原文件的存取；实现 `LocalDiskBlobStore`，文件存在 `workdata/knowledge/`。
- **文档登记**：新表 `knowledge_documents`（标题、文件名、类型、大小、状态、进度、错误原因）。文档切出的片段仍是 `knowledge_items` 里的条目（`kind=document_chunk`），删除文档时片段随外键一起删除。
- **处理流程**（`DocumentLibrary.ingest`）：读原文件 → 解析为 Markdown（页码统一成标记）→ 按标题切块（约 600 token、重叠约 80）→ 每次向量化 2 块、写入、更新进度 → 完成或失败（带原因）。
- **后台任务分道**：文档处理单独一条任务队列。一份大文档要处理几分钟，不能让新会话的标题和记忆提取排在它后面。
- **出处**：检索结果里给出引用写法 `[《文档名》章节或页码](#kb-<条目 ID>)`，模型照抄进回答；前端把 `#kb-` 开头的链接显示成出处按钮，点开右侧"出处"面板。

**技术栈：**

- 新增 Python 依赖只有 `markitdown[pdf,docx,pptx,xlsx]==0.1.8`。它会连带装上 pdfminer、mammoth、python-pptx、pandas、文件类型识别 magika（含 onnxruntime），后端镜像约大 200MB。
- 用到的现有能力：
  - M3a 的知识存储、任务队列、`FakeEmbedder`；
  - 会话上传的"边收边写、超限删除"做法与 `X-File-Name` 请求头；
  - assistant-ui 的 `MarkdownTextPrimitive` 的 `components`（替换链接组件）；
  - 浏览器 PDF 阅读器的 `#page=N`。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）：

- 4.2 节（`doc_parser`、`blob_storage` 两个替换点）；
- 8.1～8.4 节（文档条目、上传处理流程、`search_knowledge` 带出处、`read_document`、会话附件加入知识库、知识库页的文档部分）；
- 9.3 节（会话附件与知识库文档的区别）；
- 第 11 节表结构 `knowledge_documents`、接口表"知识库"一行的文档部分；
- 13.3 节知识库页"上传文档、查看处理状态"；
- 第 21 节 M3 行；
- 决策记录 D10、D15，先行验证 V6（本机向量化慢，用户已接受）。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。`agents.main_agent.knowledge.markitdown_parser` 与 `.blobs_local` 加进"backend 不得直接引用"的清单。
- deepagents 只能出现在 `agents/main_agent/runtime/`。
- 新增依赖只有 `markitdown[pdf,docx,pptx,xlsx]==0.1.8`，版本写死；`uv.lock` 由 `uv lock` 生成。
- 第三方服务与镜像一律由 `deploy/docker-compose.yml` 管理；只操作本项目的容器。
- 密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 由命令生成的文件不手改：`frontend/src/api/generated/`（`make types`）、`uv.lock`。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 集成测试先 `make test-up`。
- 给用户看的报错一律是一句中文（M3a 审查的结论），原始异常只记进日志。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **处理大文档期间照常聊天**：对话里找相关记忆不被堵住（仍在 5 秒时限内），新会话的标题和记忆提取不排在文档后面。测试：
   - 任务 4 `test_embedding_requests_stay_small`（每次向量化请求不超过 2 段）；
   - 任务 6 `test_lanes_do_not_block_each_other`。
2. **解析不了的文件**：扫描件、损坏或加密的 PDF、老格式 `.doc` / `.ppt` / `.xls`、空文件 → 不支持的格式上传时就拒绝（415，说明怎么办）；能上传但解析不出文字的，状态"失败"并说明原因，可以删除。测试：
   - 任务 1 `test_scanned_pdf_has_no_text`、`test_old_office_formats_are_refused`；
   - 任务 4 `test_unparseable_file_fails_with_reason`；
   - 任务 7 `test_unsupported_file_is_refused`。
3. **处理途中删除文档、重复点"重新处理"、服务重启**：不报错，不留残余片段，不出现重复片段；重启后接着处理。测试：
   - 任务 4 `test_document_deleted_while_processing_stops_quietly`、`test_reprocess_replaces_chunks`；
   - 任务 6 `test_start_requeues_only_its_own_kinds`。
4. **向量模型停掉时上传**：状态"失败"，原因写明向量化服务不可用，并提示恢复后点"重新处理"；恢复后重新处理成功。测试：任务 4 `test_embedding_down_fails_with_hint_then_reprocess_works`。
5. **出处链接异常**：模型写的出处指向已删除的片段、编号格式不对；或是普通网址链接 → 已删除的显示"这段内容已不在知识库里"，格式不对的按普通文字处理；普通网址照常在新标签页打开。测试：
   - 任务 9 `citationTarget`、`documentContentUrl`；
   - 任务 7 `test_context_of_a_missing_item_is_404`。

## 先行探测结论（2026-10-16 写计划时实测）

| 问题 | 结论 |
|---|---|
| markitdown 转各类文件 | 0.1.8。PDF：纯文字、没有标题层级，页与页之间是分页符 `\f`，中文段落被硬换行切断；Word、网页：保留标题层级（`#`），网页里的脚本被去掉；PPT：每页前有 `<!-- Slide number: N -->`；Excel：每个工作表一个 `##` 标题加表格；TXT 原样。都在 0.1 秒内完成 |
| 扫描件、损坏的 PDF | 不报错，转出空文字：要按"没有提取到文字"处理，原因写"可能是扫描件、图片或文件已损坏" |
| 老格式 `.doc` | 抛 `UnsupportedFormatException`：上传时按扩展名直接拒绝，提示另存为新格式 |
| 转内存里的文件 | `MarkItDown(enable_plugins=False).convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=".pptx", filename=...))` 可用；包里自带类型信息（`py.typed`） |
| 依赖大小 | `markitdown[pdf,docx,pptx,xlsx]` 连同依赖约 247MB（含 magika、onnxruntime、pandas、numpy） |
| 向量化排队 | 本机向量模型一次只处理一个请求。后台每次向量化 8 段（约 13 秒）时，对话里的单条查询要等 12.5 秒；每次 2 段时只等 2.5 秒，速度不变（约 1.5 秒 / 段，100 页 PDF 约 7 分钟）。文档入库每次向量化 2 段 |
| 后台任务 | M3a 的任务队列逐个处理：一份大文档会让新会话的标题、记忆提取等上几分钟。文档处理要单独一条队列 |
| 出处写法 | 检索结果里给出 `[《员工手册》第一章 考勤 › 1.1 请假](#kb-<条目 ID>)`，gemini-3.5-flash、claude-opus-4-6 都照抄进了回答（gemini 外面多套一层方括号，不影响）。只带 `#` 的地址能通过 react-markdown 默认的链接过滤 |
| 带筛选的向量检索 | pgvector 0.8.7 支持 `SET LOCAL hnsw.iterative_scan = relaxed_order`（R17：筛选后结果不够时继续往下扫） |

## 文件结构（本计划涉及）

```
agents/main_agent/knowledge/
├── parsing.py           # 新：解析接口 DocumentParser、ParsedDocument、DocumentParseError、支持的扩展名、页码标记
├── markitdown_parser.py # 新：markitdown 实现（页码统一成标记）
├── chunking.py          # 新：按标题切块 chunk_markdown
├── blobs.py             # 新：原文件存储接口 BlobStore
├── blobs_local.py       # 新：本地磁盘实现
├── documents.py         # 新：knowledge_documents 表的数据访问
├── library.py           # 新：DocumentLibrary——登记、存原文件、处理流程、删除、重新处理
├── models.py、base.py、pgvector.py、tokens.py  # 改：条目带位置信息；片段的写入、删除、前后文；R17
agents/main_agent/runtime/knowledge.py  # 改：检索结果带出处；read_document 工具
agents/main_agent/runtime/agent.py、bootstrap.py、prompts/system.md
backend/
├── knowledge/           # 新：文档处理的后台任务
├── api/knowledge.py     # 改：文档接口、片段前后文
├── api/router.py        # 改：会话文件加入知识库
├── runtime/jobs.py      # 改：任务队列只领自己会处理的种类
├── api/deps.py、main.py  # 改：两条队列
└── migrations/versions/0008_agents_knowledge_documents.py
common/errors.py、backend/api/errors.py  # 改：UnsupportedError → 415
config/settings.py、app.yaml            # 改：doc_parser、blob_storage、切块与上限
frontend/src/
├── features/knowledge/  # 改：记忆 / 常驻 / 文档三个视图、文档列表与上传、加载更多、出处面板
├── components/chat/     # 改：回答里的出处链接
├── features/files/      # 改：文件"加入知识库"
└── features/chat/ChatView.tsx  # 改：右侧面板可显示出处
agents/tests/fixtures/documents/  # 新：样例文件与生成脚本
docs/                    # 改：架构规范、README、需求池、变更记录、D10 补充
```

---

### 任务 1：文档解析与切块

**文件：**
- 新建：`agents/main_agent/knowledge/parsing.py`、`markitdown_parser.py`、`chunking.py`；`agents/tests/fixtures/documents/make_fixtures.py` 及其生成的样例；`agents/tests/contracts/test_document_parser_contract.py`、`agents/tests/test_chunking.py`
- 修改：`agents/main_agent/knowledge/__init__.py`、`pyproject.toml`、`uv.lock`（命令生成）

**接口：**
- 消费：`estimate_text_tokens`（`agents.main_agent.models`）。
- 产出（`agents.main_agent.knowledge` 公开）：
  - `ParsedDocument(BaseModel)`：`title: str | None`、`markdown: str`；
  - `DocumentParser`（接口）：`async parse(data: bytes, filename: str) -> ParsedDocument`；
  - `DocumentParseError(Exception)`：消息直接给用户看；
  - `SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".md", ".markdown", ".txt", ".html", ".htm"})`；
  - 页码标记 `<!-- page: N -->`（`page_mark(n: int) -> str`）；
  - `Chunk(BaseModel)`：`seq: int`（从 0 开始）、`content: str`、`section_path: str | None`、`page: int | None`；
  - `chunk_markdown(markdown: str, *, target_tokens: int = 600, overlap_tokens: int = 80) -> list[Chunk]`。
- 产出（实现，不公开）：`MarkItDownParser`。

- [ ] **步骤 1：新增依赖与样例文件**

`pyproject.toml` 加 `"markitdown[pdf,docx,pptx,xlsx]==0.1.8"`，import-linter 的禁止清单加 `agents.main_agent.knowledge.markitdown_parser`；运行 `uv lock`。

预期：`uv.lock` 新增 markitdown 0.1.8 及其依赖。

写 `agents/tests/fixtures/documents/make_fixtures.py`：用 pymupdf 与 python-docx 生成样例。这两个不是项目依赖，运行一次即可：

```bash
uv run --no-project --with pymupdf==1.28.2 --with python-docx==1.2.0 --with python-pptx==1.0.2 --with openpyxl==3.1.5 python agents/tests/fixtures/documents/make_fixtures.py
```

生成以下样例（放在脚本所在的目录，连同脚本一起保留）：
- `design.pdf`：3 页，每页一个"第 n 章 订单系统设计"，正文含 `ERR_ORDER_n00`；字体 `china-s`；
- `handbook.docx`：标题"员工手册"，`# 第一章 考勤`、`## 1.1 请假`、`# 第二章 报销`；
- `review.pptx`：2 页；
- `sales.xlsx`：两个工作表"销售""成本"；
- `faq.html`：带 `<script>`；
- `scan.pdf`：只有一个灰色方块；
- `old.doc`：OLE 文件头加 600 个零字节。

- [ ] **步骤 2：写失败的测试**

解析契约（`test_document_parser_contract.py`，参数化实现，目前只有 markitdown）：

```python
async def test_pdf_pages_are_marked(parser):          # design.pdf
    md = (await parser.parse(read("design.pdf"), "design.pdf")).markdown
    assert [page_mark(n) in md for n in (1, 2, 3)] == [True, True, True]
    assert md.index(page_mark(2)) < md.index("ERR_ORDER_200") < md.index(page_mark(3))
async def test_word_keeps_headings(parser):            # "# 第一章 考勤"、"## 1.1 请假" 都在
async def test_slides_become_pages(parser):            # review.pptx：page_mark(1)、page_mark(2)，不再有 "Slide number"
async def test_sheets_and_web_pages(parser):           # sales.xlsx 含 "## 销售"；faq.html 含 "# 常见问题"、不含 "alert"
async def test_scanned_pdf_has_no_text(parser):        # pytest.raises(DocumentParseError, match="没有提取到文字")
async def test_old_office_formats_are_refused(parser): # old.doc → DocumentParseError，消息含 "另存为"
```

切块（`test_chunking.py`）：

```python
def test_section_paths_follow_headings():
    md = "# 第一章 考勤\n\n上班 9:30。\n\n## 1.1 请假\n\n病假要证明。\n\n# 第二章 报销\n\n30 天内提交。"
    chunks = chunk_markdown(md, target_tokens=8, overlap_tokens=0)
    assert [c.section_path for c in chunks] == ["第一章 考勤", "第一章 考勤 › 1.1 请假", "第二章 报销"]
    assert [c.seq for c in chunks] == [0, 1, 2]
def test_pages_come_from_page_marks():              # page_mark(1)…正文A…page_mark(2)…正文B → 各块 page 为 1、2；块内容里没有标记
def test_long_text_is_split_with_overlap():         # 3000 字无标题无空行：每块估算 ≤ 600×1.1 token；相邻块，后一块开头 30 字出现在前一块里
def test_empty_markdown_gives_no_chunks():          # "" 与只有标记 → []
```

- [ ] **步骤 3：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_chunking.py agents/tests/contracts/test_document_parser_contract.py -q`

预期：收集阶段报错 `ImportError: cannot import name 'chunk_markdown'`（或 `'page_mark'`）。

- [ ] **步骤 4：实现**

`MarkItDownParser.parse` 的要求：
- 在 `asyncio.to_thread` 里调用 `convert_stream`，`StreamInfo(extension=后缀, filename=filename)`；
- 后缀不在 `SUPPORTED_SUFFIXES` → `DocumentParseError("暂不支持这种文件：.doc；Word、PowerPoint、Excel 的旧格式请另存为 .docx、.pptx、.xlsx 再上传")`；
- PDF：按 `\f` 分页，每页前加 `page_mark(n)`；PPT：把 `<!-- Slide number: N -->` 换成 `page_mark(N)`；
- 去掉标记后没有文字 → `DocumentParseError("没有提取到文字：可能是扫描件、图片或文件已损坏（暂不支持识别图片里的文字）")`；
- markitdown 的其他异常 → `DocumentParseError("无法解析这个文件：请确认文件没有损坏、没有加密")`，原始异常记日志；
- `title`：markitdown 给出的标题，没有则为 `None`（由调用方用文件名）。

`chunk_markdown` 的规则（签名与测试决定不了的部分）：
1. 按空行把正文分成段落块。以 `#`～`######` 开头的行是标题：更新标题栈（同级或更高级出栈），`section_path` = 标题栈用 ` › ` 连接，没有标题时为 `None`。标题行本身也是内容。
2. `page_mark` 只更新当前页码，不进内容。
3. 一块从第一个段落开始，记下当时的 `section_path` 与 `page`；依次加段落，加上后超过 `target_tokens` 就结束这一块。
4. 遇到标题、且当前块已有至少 `target_tokens / 4` 时，先结束当前块（让一块尽量只属于一节）。
5. 新块开头带上前一块末尾的若干段落，合计不超过 `overlap_tokens`（为 0 时不带）。
6. 单个段落超过 `target_tokens` 时，先在句末（`。！？.!?` 与换行）切开，仍超过则按字数切；切出的片段按规则 3 组块，相邻片段重叠 `overlap_tokens`。

- [ ] **步骤 5：运行测试，确认通过**

运行：同步骤 3。预期：全部通过。

- [ ] **步骤 6：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 2：文档登记与原文件存储

**文件：**
- 新建：`agents/main_agent/knowledge/blobs.py`、`blobs_local.py`、`documents.py`、`backend/migrations/versions/0008_agents_knowledge_documents.py`、`agents/tests/contracts/test_blob_store_contract.py`、`agents/tests/test_document_repo.py`
- 修改：`agents/main_agent/knowledge/__init__.py`、`conftest.py`（清空的表加 `knowledge_documents`）、`backend/tests/test_migrations.py`、`pyproject.toml`（禁止清单加 `blobs_local`）

**接口：**
- 消费：`OpenedFile`（`agents.main_agent.workspace`）；`TooLargeError`、`NotFoundError`（`common.errors`）。
- 产出（公开）：
  - `BlobStore`（接口）：
    - `async save(key: str, chunks: AsyncIterator[bytes], *, max_bytes: int) -> int`：返回大小；超限抛 `TooLargeError`，不留下文件；
    - `async read(key: str) -> bytes`；
    - `async open(key: str) -> OpenedFile`：不存在抛 `NotFoundError`；
    - `async delete(key: str) -> None`：不存在也不报错。
  - `LocalDiskBlobStore(root: Path)`（实现，不公开给 backend）：键只允许 `<UUID>/<文件名>` 形式，不能写到 `root` 外。
  - `DocumentStatus = Literal["pending", "processing", "done", "failed"]`；
  - `KnowledgeDocument(BaseModel)`：`id`、`title`、`filename`、`media_type`、`size`、`status`、`error: str | None`、`chunk_total: int`、`item_count: int`、`source_thread_id: UUID | None`、`created_at`、`updated_at`（`json_schema_serialization_defaults_required`）；
  - `DocumentRepo(pool)`：
    - `create(*, document_id, title, filename, media_type, size, blob_key, source_thread_id=None) -> KnowledgeDocument`（状态 pending）；
    - `get(id) -> KnowledgeDocument`（不存在抛 `NotFoundError`）、`blob_key(id) -> str`；
    - `list_documents() -> list[KnowledgeDocument]`（新的在前）；
    - `update_status(id, status, *, error=None, chunk_total=None, item_count=None) -> None`；
    - `delete(id) -> None`（不存在抛 `NotFoundError`）。
- 产出（表，迁移 0008）：
  - `knowledge_documents`：`id`、`user_id`、`title`、`filename`、`media_type`、`size bigint`、`blob_key`、`status`（四种取值的检查约束）、`error`、`chunk_total`、`item_count`、`source_thread_id`（不设外键：删除会话不删文档）、`created_at`、`updated_at`；
  - `knowledge_items.document_id` 加外键 `REFERENCES knowledge_documents(id) ON DELETE CASCADE`；
  - 索引 `(document_id, seq)`。

- [ ] **步骤 1：写失败的测试**

- 原文件存储契约：
  - `test_saves_reads_and_opens`；
  - `test_over_the_limit_leaves_nothing`（`pytest.raises(TooLargeError)`，之后 `open` 抛 `NotFoundError`）；
  - `test_delete_is_idempotent`；
  - `test_keys_cannot_escape_the_root`（`"../x"`、`"/etc/passwd"` 抛 `ValueError`）。
- 文档登记（集成）：
  - `test_create_list_and_update_status`（新的在前；`update_status(..., "failed", error="原因")` 后 `get` 读回）；
  - `test_deleting_a_document_removes_its_chunks`：直接插一条 `document_id` 指向它的 `knowledge_items`，删除文档后条目没了；
  - `test_missing_document_is_not_found`。
- 迁移：`test_knowledge_documents_table_exists`。

- [ ] **步骤 2：运行测试，确认失败**

运行：

```bash
make test-up
uv run pytest agents/tests/contracts/test_blob_store_contract.py -q
uv run pytest -m integration agents/tests/test_document_repo.py backend/tests/test_migrations.py -q
```

预期：收集阶段报错 `ImportError: cannot import name 'BlobStore'`（或 `'DocumentRepo'`）；迁移测试报表不存在。

- [ ] **步骤 3：实现**（按接口块；`LocalDiskBlobStore.save` 先写临时文件，写完再改名）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

---

### 任务 3：知识存储支持文档片段（含 R17 的存储部分）

**文件：**
- 修改：`agents/main_agent/knowledge/models.py`、`base.py`、`pgvector.py`、`tokens.py`、`agents/tests/fakes.py`、`agents/tests/contracts/test_knowledge_contract.py`

**接口：**
- 消费：任务 1 的 `Chunk`；任务 2 的表。
- 产出：
  - `KnowledgeItem` 增加 `seq: int | None`、`section_path: str | None`、`page: int | None`、`document_title: str | None`（查询时连 `knowledge_documents` 取标题）；
  - `KnowledgeStore` 增加：
    - `add_chunks(document_id: UUID, title: str, chunks: Sequence[Chunk]) -> list[KnowledgeItem]`：
      - 一次向量化请求处理传入的全部片段；
      - 向量化与分词用的文字是 `f"《{title}》{section_path or ''}\n{content}"`（带上文档名与章节，按章节名也能找到），存下的 `content` 只是片段本身；
      - `kind="document_chunk"`、`source="document"`；
      - 文档不存在（已被删）抛 `NotFoundError`；
    - `delete_chunks(document_id: UUID) -> int`；
    - `around(item_id: UUID, window: int) -> list[KnowledgeItem]`：同一文档 `seq` 在前后 `window` 以内的片段按顺序；记忆条目只返回它自己；不存在抛 `NotFoundError`。
  - `tokens.warm_up() -> None`：预先加载 jieba 词典（启动时在线程里调用）。
  - R17：
    - `search` 与 `recall` 在事务里先 `SET LOCAL hnsw.iterative_scan = relaxed_order`；
    - `update` 的内容与原来相同时不重新向量化；
    - 分词在 `asyncio.to_thread` 里做；
    - `FakeKnowledgeStore` 实现新方法，并纳入契约测试的"存取"组。

- [ ] **步骤 1：写失败的测试**

契约测试拆成两组：
- 存取组：`make` 参数为 `pgvector`、`fake`；已有的增删改查、列表、常驻不进召回，加上下面四个新测试；
- 检索排序组：已有的混合检索、召回相似度，只跑 `pgvector`。

```python
async def test_chunks_carry_their_location(make, document):      # add_chunks 后 get：kind、source、seq、section_path、page、document_title == "员工手册"
async def test_around_returns_neighbors_in_order(make, document): # 5 段，around(第 2 段, 1) → seq [1, 2, 3]；around(记忆) → [记忆]
async def test_delete_chunks_and_missing_document(make, document):# delete_chunks 返回 5；add_chunks(不存在的文档) 抛 NotFoundError
async def test_chunks_are_found_by_their_section_name(make_pg, document):  # 片段正文不含"请假"，章节是"1.1 请假"：search("请假") 找到它
async def test_updating_only_tags_does_not_embed_again(make_pg):  # 用计数的向量模型：update(tags=…) 前后调用次数不变
```

`document` 夹具：建一条 `knowledge_documents`，标题"员工手册"（假实现直接用 ID）。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration agents/tests/contracts/test_knowledge_contract.py -q`

预期：新测试失败，`AttributeError: ... 'add_chunks'`；`fake` 参数的存取测试按现状通过。

- [ ] **步骤 3：实现**（按接口块）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2，加上 `uv run pytest agents/tests -q`。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

---

### 任务 4：文档处理流程

**文件：**
- 新建：`agents/main_agent/knowledge/library.py`、`agents/tests/test_document_library.py`
- 修改：`agents/main_agent/knowledge/__init__.py`、`common/errors.py`、`backend/api/errors.py`、`agents/main_agent/runtime/agent.py`、`agents/main_agent/bootstrap.py`、`config/settings.py`、`config/app.yaml`、`config/tests/test_settings.py`、`agents/tests/test_bootstrap.py`

**接口：**
- 消费：任务 1～3 的全部公开接口。
- 产出：
  - `UnsupportedError(AppError)`（`common.errors`），接口层映射为 415；
  - `DocumentLibrary(documents: DocumentRepo, store: KnowledgeStore, parser: DocumentParser, blobs: BlobStore, *, chunk_tokens=600, overlap_tokens=80, batch_size=2, max_bytes)`（公开）：
    - `async add(filename: str, chunks: AsyncIterator[bytes], *, media_type: str, source_thread_id: UUID | None = None) -> KnowledgeDocument`：
      - 后缀不支持抛 `UnsupportedError`（消息同任务 1 的"暂不支持这种文件"）；
      - 超过上限抛 `TooLargeError("文件超过 50MB 上限")`；
      - 标题取文件名去掉后缀；状态 pending；
    - `list_documents()`、`get(id)`、`open(id) -> OpenedFile`；
    - `delete(id)`：先删登记（片段随外键删除），再删原文件；
    - `reprocess(id) -> KnowledgeDocument`：处理中时抛 `ConflictError("文档正在处理，请稍后再试")`；否则状态改回 pending、清空原因；
    - `async ingest(id) -> None`：按下面的规则执行。
  - `MainAgent(..., documents: DocumentLibrary | None = None)`，属性 `MainAgent.documents`；
  - 配置：
    - `AdaptersConfig.doc_parser = "markitdown"`、`blob_storage = "local_disk"`；
    - `KnowledgeConfig.chunk_tokens = 600`、`chunk_overlap_tokens = 80`、`ingest_batch_size = 2`、`max_document_mb = 50`；
    - 原文件目录 `workdata/knowledge/`。
  - `bootstrap`：登记 `_DOC_PARSERS`、`_BLOB_STORES`，装配 `DocumentLibrary`；启动时 `await asyncio.to_thread(tokens.warm_up)`。

`ingest` 的规则：
1. 文档不存在 → 直接结束。状态改为 processing。
2. 读原文件并解析。`DocumentParseError` → 状态 failed，原因为它的消息，结束。
3. 切块（在线程里），记下 `chunk_total`；`delete_chunks` 清掉旧片段（重新处理、重启后重做都不重复）。
4. 每 `batch_size` 段调用一次 `add_chunks`，然后更新 `item_count`（页面据此显示进度）。
5. `UpstreamError` → 状态 failed，原因 `f"{错误消息}；向量模型恢复后点"重新处理""`，结束。不自动重试：失败原因留在页面上，比后台悄悄重试几次更清楚。
6. 途中文档被删（`NotFoundError`）→ 安静结束。
7. 全部写完 → 状态 done。

- [ ] **步骤 1：写失败的测试**（集成：真实数据库、`PgKnowledgeStore` + `FakeEmbedder`、`LocalDiskBlobStore(tmp_path)`、`MarkItDownParser`）

```python
async def test_ingest_makes_searchable_chunks_with_locations(library):   # handbook.docx → done；item_count == chunk_total > 0；search("报销") 命中片段，section_path 含 "第二章 报销"
async def test_embedding_requests_stay_small(library_with_counting_embedder):  # design.pdf：每次 embed 的段数 ≤ 2
async def test_unparseable_file_fails_with_reason(library):             # scan.pdf → failed，error 含 "没有提取到文字"
async def test_embedding_down_fails_with_hint_then_reprocess_works(...):# 坏的向量模型 → failed，error 含 "重新处理"；换好的 → reprocess + ingest → done
async def test_reprocess_replaces_chunks(library):                      # ingest 两次：片段数不变
async def test_document_deleted_while_processing_stops_quietly(...):    # 解析器在 parse 里删掉文档 → ingest 不抛异常，没有残余片段
async def test_unsupported_or_too_large_files_are_refused(library):    # add("x.doc") → UnsupportedError；max_bytes=10 时 TooLargeError，原文件目录里没有残留
```

- 配置测试：项目 `app.yaml` 的新取值。
- 组装根测试：`agent.documents` 是 `DocumentLibrary`。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration agents/tests/test_document_library.py agents/tests/test_bootstrap.py -q`、`uv run pytest config/tests -q`

预期：`ImportError: cannot import name 'DocumentLibrary'`；配置没有新字段。

- [ ] **步骤 3：实现**（按接口块与规则）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

---

### 任务 5：智能体用上文档（检索带出处、read_document）

**文件：**
- 修改：`agents/main_agent/runtime/knowledge.py`、`agents/prompts/system.md`、`agents/tests/test_knowledge_runtime.py`、`agents/tests/test_subagents.py`

**接口：**
- 消费：任务 3 的 `KnowledgeItem` 位置字段与 `around`。
- 产出：
  - `citation(item: KnowledgeItem) -> str`：
    - 文档片段为 `[《{document_title}》{位置}](#kb-{id})`；
    - 位置是章节路径、"第 N 页"，或两者都有时"章节路径 · 第 N 页"；都没有时只写文档名；
  - `search_knowledge` 的结果：
    - 文档片段一行写内容，下一行 `出处：{citation}`；
    - 记忆的格式不变；
  - 新工具 `read_document(item_id: str, window: int = 2) -> str`：
    - 返回这一段及前后各 `window` 段（`window` 限制在 0～5），按顺序，每段前标出位置；
    - 编号不对或已删除时，工具结果标为出错："找不到这段内容：可能已被删除"；
  - 系统提示词"记忆与知识"一节补充：用了知识库里的文档时，在相关句子后照抄检索结果给出的出处链接，不改链接地址；需要更多上下文时用 `read_document`。

- [ ] **步骤 1：写失败的测试**

```python
async def test_document_hits_come_with_a_citation(tmp_path):   # FakeKnowledgeStore 里加一段（document_title "员工手册"，section_path "第一章 考勤 › 1.1 请假"，page None）
    assert f"出处：[《员工手册》第一章 考勤 › 1.1 请假](#kb-{chunk.id})" in finished.output
async def test_read_document_returns_the_passage_and_neighbors(tmp_path):  # 3 段，read_document(第 2 段, 1)：三段内容按顺序都在输出里
async def test_read_document_with_a_bad_id_is_reported(tmp_path):  # "not-a-uuid" → ToolFinished.status == "error"，运行照常完成
```

在系统提示词测试的词语清单里加上 `read_document`。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_knowledge_runtime.py agents/tests/test_subagents.py -q`

预期：新测试失败（输出里没有出处、没有 `read_document` 工具）。

- [ ] **步骤 3：实现**（按接口块）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 6：后台任务分道

**文件：**
- 修改：`backend/runtime/jobs.py`、`backend/tests/test_job_queue.py`

**接口：**
- 产出：`TableJobQueue` 只领取、只在启动时放回自己处理程序里有的种类（`kind = ANY(...)`），几条队列可以共用 `jobs` 表各管各的。
- 行为变化：没有处理程序的种类不再记为失败，留在队列里等别的队列处理。M3a 的 `test_unknown_kind_fails_with_a_reason` 改写为 `test_kinds_without_a_handler_are_left_for_other_queues`。

- [ ] **步骤 1：写失败的测试**

```python
async def test_lanes_do_not_block_each_other(db):           # 队列 A 处理 "slow"（等一个事件，最多 3 秒），队列 B 的 "quick" 在此期间完成
async def test_start_requeues_only_its_own_kinds(db):       # 表里两条 running：kind a、b；只处理 a 的队列启动后，b 仍是 running
async def test_kinds_without_a_handler_are_left_for_other_queues(db):  # 登记 "other"，队列只处理 "note"：0.3 秒后 other 仍是 queued、attempts 为 0
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration backend/tests/test_job_queue.py -q`

预期：三个新测试失败。

- [ ] **步骤 3：实现**

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

---

### 任务 7：文档接口与会话文件加入知识库

**文件：**
- 新建：`backend/knowledge/__init__.py`、`backend/knowledge/jobs.py`、`backend/tests/test_documents_api.py`
- 修改：`backend/api/knowledge.py`、`backend/api/router.py`、`backend/api/deps.py`、`backend/main.py`、`backend/tests/conftest.py`、`frontend/src/api/generated/*`（命令生成）

**接口：**
- 消费：任务 4 的 `DocumentLibrary`（`services.agent.documents`）；任务 6 的分道队列。
- 产出（backend）：
  - `DOCUMENT_INGEST = "document_ingest"`；
  - `DocumentJobs(library, jobs)`：`handlers() -> dict[str, JobHandler]`、`submit(document_id) -> None`；
  - `Services.document_jobs: DocumentJobs`、第二条队列 `Services.document_queue: JobQueue`；启动、停止与第一条队列一样。
- 产出（接口，前缀 `/api`）：
  - `POST /knowledge/documents`：请求体就是文件，`X-File-Name`（百分号编码）；返回 201 `KnowledgeDocument` 并登记处理任务；不支持的格式 415，超限 413；
  - `GET /knowledge/documents` → `KnowledgeDocument[]`；`GET /knowledge/documents/{id}`；
  - `DELETE /knowledge/documents/{id}` → 204；
  - `POST /knowledge/documents/{id}/reprocess` → 200 `KnowledgeDocument` 并登记任务；处理中时 409；
  - `GET /knowledge/documents/{id}/content`：原文件，边读边传；带 `Content-Disposition: inline`（文件名百分号编码）、`Content-Security-Policy: sandbox`、`X-Content-Type-Options: nosniff`，与会话文件下载相同；
  - `GET /knowledge/items/{id}/context?window=1`（window 0～5）→ `ItemContext {target_id: UUID, items: KnowledgeItem[], document: KnowledgeDocument | None}`；不存在时 404；
  - `POST /threads/{thread_id}/files/{file_id}/knowledge`：把会话里的这个文件加入知识库（`source_thread_id` 为这个会话），返回 201 `KnowledgeDocument`；别的会话的文件 404。
- 测试夹具：`make_client(..., documents=None, document_jobs=None)`。

- [ ] **步骤 1：写失败的测试**（集成：真实库与 `FakeEmbedder`，任务由测试直接调用处理程序）

```python
async def test_upload_then_process_then_search(...):  # 上传 handbook.docx → 201 pending；执行登记的任务 → GET 为 done；GET /knowledge/items?kind=document_chunk&q=报销 命中
async def test_unsupported_file_is_refused(...):      # x.doc → 415，detail 含 "另存为"
async def test_too_large_file_is_refused(...):        # max_document_mb 设为 0（测试配置）→ 413
async def test_download_reprocess_and_delete(...):    # content 的类型与响应头；reprocess → pending；delete → 204，再 GET 404，片段也查不到
async def test_context_of_a_chunk(...):               # window=1 → 三段，target_id 正确，document.title == "handbook"
async def test_context_of_a_missing_item_is_404(...)
async def test_session_file_joins_the_knowledge_base(...):  # 上传到会话 → POST …/knowledge → 201，source_thread_id 为该会话；删除会话后文档还在
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration backend/tests/test_documents_api.py -q`

预期：全部失败，接口 404 / 405。

- [ ] **步骤 3：实现**（按接口块；上传沿用 `upload_file` 的写法）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make types`、`make check`、`make test-int`。预期：全部通过。

---

### 任务 8：知识库页的文档部分（含 R17 的"加载更多"）

**文件：**
- 新建：`frontend/src/features/knowledge/documents.ts`（及测试）、`DocumentList.tsx`
- 修改：`frontend/src/api/types.ts`、`client.ts`（及测试）、`queries.ts`、`frontend/src/features/knowledge/filters.ts`（及测试）、`KnowledgePage.tsx`、`KnowledgeItemCard.tsx`

**接口：**
- 消费：任务 7 的接口与生成的类型。
- 产出：
  - 类型别名 `KnowledgeDocument`、`ItemContext`；
  - `api.uploadDocument(file: File)`（`X-File-Name` 百分号编码）、`listDocuments()`、`deleteDocument(id)`、`reprocessDocument(id)`、`itemContext(id, window)`、`addFileToKnowledge(threadId, fileId)`；
  - `documentsQuery`：
    - 有文档在 pending / processing 时每 2 秒刷新（`pollWhileProcessing(documents) -> number | false`），全部结束后停止；
    - 增删改后由 `refreshKnowledge` 一并刷新。
  - `documentStatus(doc: KnowledgeDocument) -> { text: string; tone: "muted" | "warning" | "danger" }`：
    - pending →"等待处理"；
    - processing →"处理中 12 / 30 段"（`chunk_total` 为 0 时只写"处理中"）；
    - done →"已完成 · 30 段"；
    - failed →"失败：{error}"。
  - 视图改为 `KnowledgeView = "memory" | "pinned" | "documents"`（默认 memory）：
    - 记忆 → `kind=memory`；
    - 常驻 → `pinned=true`；
    - 文档 → 不搜索时显示文档列表，搜索时为 `kind=document_chunk` 的片段。
  - `knowledgeSearchParams` 增加 `limit`。记忆、常驻视图每次多显示 50 条（"加载更多"按钮，返回条数少于 limit 时隐藏）。
- 界面（`DocumentList`）：
  - 上传按钮与拖放（可多选），上传中显示文件名与转圈；失败原因显示在列表上方；
  - 每个文档：标题、大小、状态（`documentStatus`）、打开原文、重新处理、删除（再点一次确认）。
- 片段条目（`KnowledgeItemCard`）：显示文档名与位置，只读（不显示设常驻、修改），点击打开原文。

- [ ] **步骤 1：写失败的测试**

```ts
// documents.test.ts
documentStatus({status: "processing", chunk_total: 30, item_count: 12, ...}) → {text: "处理中 12 / 30 段", tone: "warning"}
documentStatus({status: "failed", error: "没有提取到文字…"}) → {text: "失败：没有提取到文字…", tone: "danger"}
pollWhileProcessing([done, processing]) → 2000；pollWhileProcessing([done, failed]) → false
// filters.test.ts
knowledgeSearchParams({view: "documents", query: "报销", tag: null, limit: 50}) → "kind=document_chunk&q=报销&limit=50"
knowledgeSearchParams({view: "memory", ...}) 含 "kind=memory"
// client.test.ts
uploadDocument：请求 POST /api/knowledge/documents，X-File-Name 为 encodeURIComponent(文件名)，请求体是文件本身
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/knowledge src/api`

预期：找不到 `./documents`；`uploadDocument is not a function`；参数不符。

- [ ] **步骤 3：实现纯逻辑与接口调用**

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：界面**（按接口块；纯展示部分在任务 10 的浏览器验证里检查）

- [ ] **步骤 6：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 9：回答里的出处与会话文件加入知识库

**文件：**
- 新建：`frontend/src/features/knowledge/citations.ts`（及测试）、`CitationPanel.tsx`；`frontend/src/components/chat/citationActions.ts`
- 修改：`frontend/src/components/chat/parts.tsx`、`frontend/src/components/chat/index.ts`、`frontend/src/features/chat/ChatView.tsx`、`frontend/src/features/files/FilePanel.tsx`

**接口：**
- 消费：任务 7 的 `itemContext`、文档原文地址；任务 8 的 `api.addFileToKnowledge`。
- 产出：
  - `citationTarget(href: string | undefined) -> string | null`：只认 `#kb-<UUID>`，其余返回 `null`；
  - `documentContentUrl(documentId: string, page: number | null) -> string`：`/api/knowledge/documents/{id}/content`，有页码时加 `#page=N`（PDF 阅读器跳到该页）；
  - `OpenCitationContext`（`components/chat/citationActions.ts`，与 `OpenFileContext` 同样的做法）：`(itemId: string) => void`；
  - 回答的 Markdown 链接组件：
    - `citationTarget` 有值时显示成出处按钮（书签图标加链接文字），点击调用 `OpenCitationContext`；
    - 否则是普通链接，`target="_blank" rel="noopener noreferrer"`；
  - `ChatView` 右侧面板状态改为 `{ open: boolean; mode: "files" | "citation"; fileId: string | null; itemId: string | null }`；
  - `CitationPanel({ itemId, onClose })`：
    - 显示文档名、位置；这一段高亮，前后各一段；
    - "打开原文"按钮（PDF 带页码）；
    - 404 时显示"这段内容已不在知识库里"；
    - 是记忆条目时显示内容与"记忆"标记；
  - 文件面板列表每个文件加"加入知识库"按钮：
    - 成功后按钮变为"已加入知识库"（这次打开面板期间保持）；
    - 失败时显示原因；415 时提示格式不支持。

- [ ] **步骤 1：写失败的测试**

```ts
// citations.test.ts
citationTarget("#kb-1f0c2a9e-0000-4000-8000-000000000001") → "1f0c2a9e-0000-4000-8000-000000000001"
citationTarget("#kb-123")、citationTarget("https://example.com")、citationTarget(undefined) → null
documentContentUrl("d1", 3) → "/api/knowledge/documents/d1/content#page=3"；documentContentUrl("d1", null) 不带 "#"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/knowledge/citations.test.ts`

预期：找不到 `./citations`。

- [ ] **步骤 3：实现**（按接口块）

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 10：文档收尾与端到端验证

**文件：**
- 修改：
  - `docs/development/architecture.md`（第 12 节补上文档、两条队列、出处）；
  - `docs/decisions/D10-统一知识库.md`（补充：落地时的调整，见下方"与设计文档的差异"）；
  - `README.md`（知识库页上传文档、出处、处理速度、支持的格式）；
  - `docs/requirements/backlog.md`（R06b、R17 改为"完成"）；
  - `docs/changelog.md`（M3b 小节）；
  - `agents/tests/live/test_smoke.py`。

- [ ] **步骤 1：文档**（按上面的清单）

- [ ] **步骤 2：真实模型冒烟测试**

新加 `test_document_ingest_and_cited_answer`：
1. 用真实向量模型（经网关）与真实数据库（测试库），把 `handbook.docx` 入库；
2. 让 claude-opus-4-6 回答"年假几天"；
3. 回答里要含 `](#kb-` 形式的出处链接，指向"1.1 请假"那一段。

先 `make infra-up`、`make test-up`，再运行：

```bash
uv run pytest -m live -s agents/tests/live/test_smoke.py -k document
```

预期：通过；费用约 0.02 美元。

- [ ] **步骤 3：浏览器端到端验证**

先 `make build`（加了 markitdown，界面改了），打开 http://127.0.0.1:8000，对话模型选 `gemini-3.5-flash`。

1. **上传**：
   - 知识库页 →"文档"，一次拖入 `handbook.docx`、`design.pdf`、`review.pptx`；
   - 状态依次显示"等待处理""处理中 n / m 段""已完成 · m 段"。
2. **处理大文档时照常聊天**：
   - 再上传一份约 50 页的 PDF；
   - 处理期间新建会话问一句：几秒内开始回答；
   - 新会话的标题照常在几秒内生成。
3. **带出处的回答**：新会话问"公司年假几天？差旅报销的期限是多久？"。
   - 回答里有两个出处按钮；
   - 点开右侧"出处"面板，显示文档名、章节、这一段与前后文；
   - "打开原文"能打开文件；
   - 问 PDF 里 `ERR_ORDER_200` 是什么：出处点开后"打开原文"跳到第 2 页。
4. **解析不了的文件**：
   - 上传 `old.doc`：提示"暂不支持……另存为……"；
   - 上传 `scan.pdf`：状态"失败：没有提取到文字……"，可删除。
5. **向量模型停掉**：
   - `podman compose --env-file .env -f deploy/docker-compose.yml stop ollama` 后上传 `faq.html`：状态"失败：向量化服务不可用……重新处理"；
   - `start ollama` 后点"重新处理"：完成。
6. **会话文件加入知识库**：在会话里上传 `sales.xlsx`，文件面板点"加入知识库"，知识库页"文档"里出现它并处理完成。
7. **删除与搜索**：
   - "文档"视图搜索"报销"，结果是片段，显示文档名与章节；
   - 删除 `handbook`：搜索不到它的片段；之前回答里的出处点开显示"这段内容已不在知识库里"。
8. **加载更多**（R17）：记忆超过 50 条时出现"加载更多"。可以用接口批量加 60 条测试记忆，验证后删除。
9. **深浅色**：文档列表、出处面板在两种外观下清晰可读。

预期：以上全部符合描述。验证完删除测试用的文档与会话。

- [ ] **步骤 4：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

收尾：全部通过后，`docs/changelog.md` 的 M3b 小节为"（完成）"；需求池 R06b、R17 为"完成"。若有未通过项，改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖**（第 21 节 M3 行中属于 M3b 的部分）：
  - 文档上传，原文件存 `workdata/knowledge/`，`knowledge_documents` 记一行 → 任务 2、4、7；
  - markitdown 解析、按标题结构切块（约 600 token、重叠约 80）、向量化、jieba 分词、写入 `kind=document_chunk`、状态完成 / 失败（失败可重试）→ 任务 1、3、4；
  - `search_knowledge` 的文档片段带文档名、页码或章节路径 → 任务 3、5；`read_document` → 任务 5；回答引用出处、前端点击打开原文定位 → 任务 5、9；
  - 会话附件可一键加入知识库 → 任务 7、9；
  - 知识库页：按种类筛选与搜索、上传文档、查看处理状态、删除、重新处理 → 任务 8；
  - 接口表"知识库"一行的文档部分（`POST/GET /knowledge/documents`、`GET/DELETE /knowledge/documents/{id}`、`POST …/reprocess`）→ 任务 7；
  - 替换点 `doc_parser`、`blob_storage` → 任务 1、2、4；
  - 需求池 R17 → 任务 3（带筛选的检索、只改标签不重新向量化、分词在线程里、jieba 预热、测试替身纳入契约）、任务 8（加载更多）。
- **与设计文档的差异：**
  1. 知识库页的视图：设计文档是"全部 / 记忆 / 文档"，本计划为"记忆 / 常驻 / 文档"。文档片段动辄成百上千，"全部"会被片段淹没；"常驻"沿用 M3a。
  2. `read_document(document_id, around_item_id, window)` 简化为 `read_document(item_id, window)`：片段编号已经确定了文档。
  3. "失败可重试"做成用户点"重新处理"，后台不自动重试：失败原因（如向量模型没启动）显示在页面上，自动重试只会让状态在"处理中"停几分钟。
  4. 文档处理单独一条后台任务队列（设计文档没有细分）：避免一份大文档挡住标题与记忆提取。
  5. 单个文档上限 50MB（设计文档未定；会话附件仍是 100MB）：解析在内存里进行。
  6. 支持的格式限于 PDF、Word、PPT、Excel 的新格式与 CSV、Markdown、TXT、网页；扫描件不识别图片里的文字。
  7. 出处是回答里的链接，点开在右侧显示这一段与前后文，PDF 打开到对应页；不在原文件里高亮定位。
  8. 9.3 节"上传时可选同时加入知识库"改为上传后在文件面板点"加入知识库"：任何会话文件（含智能体生成的）都能加，上传流程不变。
  9. 向量化与分词用的文字带上文档名与章节路径（设计文档没有说明），按章节名也能找到片段。
  10. 本机向量化约 1.5 秒 / 段（V6 已知并已接受），100 页的 PDF 约 7 分钟；每次只向量化 2 段，对话里的查询最多等约 3 秒。
- **步骤扫描：** 每个代码步骤给出了文件、签名与取值；签名与测试决定不了的只有两处（切块规则、处理流程的规则），已写明。没有"待定 / 以后实现"。
- **类型与命名一致性：** `Chunk`、`KnowledgeDocument`、`DocumentLibrary`、`add_chunks` / `delete_chunks` / `around`、`document_title`、`DOCUMENT_INGEST`、`ItemContext`、`citationTarget` 在各任务的接口块与测试里一致。
- **篇幅：** 约为设计文档相关章节的数倍。函数体都没有写进计划，只保留签名、测试断言与规则。
