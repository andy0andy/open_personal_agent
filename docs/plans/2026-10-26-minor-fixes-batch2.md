# 积压小问题·第二批「后端：会话、记忆、知识库、模型、设置、技能」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉后端会话索引、记忆提取、知识库文档、模型与技能管理、设置接口上积压的约 35 条小问题；知识库重复文件按内容 SHA-256 判断（要数据库迁移）。

**Architecture:** 每条按核对明细的"最小修法"落在原来的模块里：运行收尾在 `backend/runs/`，记忆与文档在 `agents/main_agent/knowledge/`，模型在 `backend/models/`，技能在 `agents/main_agent/runtime/skills.py` 与 `backend/settings/skill_upload.py`，设置在 `backend/settings/`。C12 加一列 `knowledge_documents.content_hash`（迁移 0018），存原文件时算，旧文档在升级后启动时补算一次（照 `.seeded` 的一次性补做）。

**Tech Stack:** Python 3.12、FastAPI、pydantic、psycopg、alembic、pytest（集成测试用测试库）；前端只动两处小地方（用量页工具名、模型页下拉框）。

**Spec:** `docs/specs/2026-10-26-minor-fixes-design.md`（已审定）；每条的证据、最小修法与测试见 `docs/specs/2026-10-26-minor-fixes-verification/02-后端运行与记忆.md` 与 `04-设置技能与运维.md`（下称"明细"）。

## Global Constraints

- 不新增依赖；依赖方向 `backend → agents → config → common`，backend 只用 agents 各模块 `__init__.py` 公开的内容。项目没有 git：台账 `.superpowers/sdd/2026-10-26-minor-fixes-batch2/progress.md`。不读、不打印 `.env`。
- 改了接口或事件定义在同一任务里 `make types`；数据库结构改动写迁移（0018），升级前先备份。
- 不调用真实模型；集成测试只用测试库；8000 上只看、不发真实消息、不点模型"测试"。
- 固定文案（原样使用）：
  - C12：`《{文件名}》已在知识库里（内容相同），要更新请先删除旧的`。
  - C14：`文件是空的：没有内容可以加入知识库`。
  - C8：`文档片段不能单独修改：改原文件后重新上传`、`文档片段不能单独删除：请删除整份文档`。
  - C7：工具里 `找不到这段内容：可能已被删除或重新处理，请重新检索`；接口 404。
  - F4：`模型名不能叫 default：和“设默认模型”的接口地址冲突`。
  - F9：`有对话正在用这个模型（运行中或等审批），等它结束或停止后再删`。
  - F12：`这是默认对话模型，不能改成向量模型：先换一个默认对话模型`。
  - F5：`压缩包里的 {文件} 读不出来：可能已损坏、加了密码或用了不支持的压缩方式`、`技能目录里已有同名文件夹 {名字}（里面没有 SKILL.md）：先删掉或改名`。
  - F11：`有只差大小写的同名文件（如 SKILL.md 与 skill.md），在 Mac 上会互相覆盖：改名后再传`。
  - G1：`时区不认识：{名字}`（422）。
  - B12：用量页的工具名 `派出子智能体`。
- Python 单测写作 `PY <文件>`，集成测试写作 `INT <文件>`，前端写作 `WEB vitest <文件>`。

## Review Focus

1. C12 迁移与补算：旧文档（没有哈希）补算时原文件丢了或读不出，不让启动失败；补算只做一次；同一文件在会话里"加入知识库"与知识库页上传两条路都被挡住；内容不同、名字相同的照常能加。
2. B9 与"用户点停止恰好落在收尾时"：不再接着发起下一轮，插话退回（存进结束事件的"没送达"）；正常顺利结束仍照常接续。
3. C1 记忆提取遇到用户刚改过、刚设常驻、刚删掉的记忆：一律不动并记日志；其余新增、更新照常。
4. F8 页面保存保留开头注释：开头没有注释的文件仍写程序那行说明；开头注释里有 `version:` 以外的 YAML 不会被当成注释吃掉；迁移插入的 `version: 1` 不会重复。
5. F9 删除模型：等审批的运行算"在用"；已结束的运行不挡删除。

---

### Task 1: 会话索引与收尾（B6、B7、B9、`test_seed` 的集成标记）

**Files:** `backend/runs/repo.py`（`retried(run_id) -> bool`；`fail_unfinished` 改成 `RETURNING id` 返回 ID 列表）、`backend/runs/followups.py`（`index_conversation` 读到运行后已被重试就返回；`index_later(run_id)`）、`backend/main.py`（标记中断后给这些运行登记写索引）、`backend/runs/manager.py`（`_finalize` 写库前、`_continue` 开头再看停机与"已请求停止"：插话放进结束事件的 `undelivered`，不再发起下一轮）、`backend/tests/test_seed.py`（`test_backfill_indexes_old_runs_once` 补 `@pytest.mark.integration`）。Test: `INT backend/tests/test_followups.py`（`test_turn_replaced_by_retry_is_not_written_back`、`test_crashed_run_is_indexed_with_its_partial_answer`）、`INT backend/tests/test_repos.py::test_fail_unfinished`、`INT backend/tests/test_manager.py`（`test_shutdown_during_wrap_up_gives_interjections_back`、`test_stop_during_wrap_up_gives_interjections_back`）。

- [ ] Step 1：写失败的测试 → Step 2：看到失败 → Step 3：按明细 B6、B7、B9 实现 → Step 4：通过。

### Task 2: 派出子智能体计入工具用量（B12，推翻第三批 T15）

**Files:** `backend/runs/manager.py::_record_later`（收到 `SubagentStarted` 记一次工具用量 `task`：它来自主智能体的模型输出，恢复审批时不重发）、`frontend/src/components/chat/tools.ts`（BUILTIN 补 `task`：动词"派出子智能体"）。Test: `INT backend/tests/test_usage_api.py::test_subagent_dispatch_counts_once_even_after_approval`、`WEB vitest src/components/chat/tools.test.ts`（`toolLabel("task", {}).verb === "派出子智能体"`）。

### Task 3: 记忆提取（C1、C2）

**Files:** `agents/main_agent/knowledge/extraction.py`（`_apply` 更新、删除前 `store.get`：取不到、已是常驻、或更新时间与取候选时不同就跳过并记警告；做完记一条 INFO：新增、更新、删除各几条与条目 ID，不记原文）。Test: `PY agents/tests/test_memory_extraction.py`（`test_memory_edited_or_pinned_meanwhile_is_left_alone`、`test_applied_changes_are_logged`）。

### Task 4: 知识库文档（C5、C6、C7、C8、C9、C13、C14）

**Files:** `backend/api/knowledge.py`（`upload_document` 先看 Content-Length；`update_item`、`delete_item` 遇到文档片段 422；出处上下文取不到 404）、`agents/main_agent/runtime/knowledge.py`（`citation` 里方括号换全角；`read_document` 取不到目标抛 ToolException）、`agents/main_agent/knowledge/library.py`（`ingest` 遇到已完成或已失败的文档直接返回）、`agents/main_agent/knowledge/chunking.py`（长表格切开后每块补表头）、`agents/main_agent/knowledge/markitdown_parser.py`（空文件的原因）。Test: 明细 C5～C14 行里的测试名（单元与集成各自标明）。

### Task 5: 向量化超时（C10）

**Files:** `agents/main_agent/models/embedding.py`（`httpx.Timeout(30, connect=5)`，改注释）。Test: `PY agents/tests/test_embedding.py::test_gives_up_after_30_seconds`。

### Task 6: 重复文档按内容判断（C12，迁移 0018）

**Files:** Create `backend/migrations/versions/0018_*.py`（`knowledge_documents.content_hash text` + 索引）；Modify `agents/main_agent/knowledge/documents.py`（`DocumentRepo`：存哈希、按哈希查）、`library.py::add`（存原文件时算 SHA-256；已有同哈希的文档就删掉刚存的原文件并抛 `ConflictError`，固定文案）、`backend/settings/seed.py`（`backfill_document_hashes_once`：没有哈希的旧文档从原文件补算，读不出的跳过并记警告，`.seeded` 记 `document_hash`）、`backend/main.py`（启动时调用）。Test: `INT agents/tests/test_document_library.py`（`test_adding_the_same_content_twice_is_refused`、`test_same_name_different_content_is_allowed`）、`INT backend/tests/test_documents_api.py`（会话文件"加入知识库"与知识库页上传两条路都 409）、`INT backend/tests/test_seed.py::test_backfill_document_hashes_once`、迁移测试照 `test_migrations.py` 的写法。

### Task 7: 用量与调用归属（G1、G2、G3、I5、I6）

**Files:** `agents/main_agent/usage/repo.py`（PostgreSQL 不认识的时区 → `InvalidRequestError`）、`backend/runs/manager.py`（后台写库任务用新的 `contextvars.Context()`）、`agents/main_agent/models/litellm_proxy.py`（`extra_body.metadata` 与 tags 按键合并）。Test: 明细 G1、G2、G3、I5、I6 行的测试。

### Task 8: 模型管理（F4、F9、F12）

**Files:** `backend/models/service.py`（`add` 拒绝 `default`；`delete` 先查在用的运行；`update` 默认对话模型不能改成向量）、`backend/runs/repo.py`（`count_active(model)`：queued、running、interrupted）、`backend/api/deps.py`（`ModelAdmin` 多传 runs）、`frontend/src/features/models/ModelsPage.tsx`（下拉框当前值不在对话模型里时也列出）。Test: `INT backend/tests/test_models_api.py`（`test_model_cannot_be_named_default`、`test_delete_model_in_use_conflicts`、`test_default_chat_model_cannot_become_embedding`）。

### Task 9: 技能（F2、F3、F5、F7、F11）

**Files:** `agents/main_agent/runtime/skills.py`（说明头 strip，空了算不完整；`install` 遇到已有的同名文件夹 409）、`agents/main_agent/runtime/files.py`（停用隐藏按 casefold）、`backend/settings/skill_upload.py`（压缩包条目读坏转成中文原因；只差大小写的路径拒绝）、`backend/api/settings.py`（详情、启停也填 `last_used_at`）。Test: 明细 F2、F3、F5、F7、F11 行的测试。

### Task 10: 页面保存保留开头注释（F8）

**Files:** `backend/settings/store.py::write`、`agents/main_agent/runtime/skills.py::_write_state`（用原文开头连续的注释与空行代替程序那行说明；原文没有开头注释时才加说明；判断开头注释复用 `seed.py` 的 `_is_preamble` 一类规则，抽到 `config/` 共用）、`config/seed/files/config/*.yaml`（正文里的示例注释挪到开头说明）。Test: `PY backend/tests/test_settings_store.py::test_page_write_keeps_leading_comments`、`PY agents/tests/test_skills.py::test_state_write_keeps_leading_comments`、`PY config/tests/test_integrations.py::test_seed_examples_are_in_the_header`。

### Task 11: 设置接口（F17）

**Files:** `backend/settings/app_settings.py`（存校验后的值）、`backend/api/settings.py`（"恢复默认"被环境变量覆盖时不再检查代码里的默认模型）。Test: `PY backend/tests/test_app_settings_service.py::test_update_stores_validated_value`（用内存替身）。

### Task 12: 旧说法（F20 后端与体检）

**Files:** `backend/api/router.py`、`backend/api/knowledge.py`（知识库未启用的说法）、`agents/main_agent/integrations/mcp_adapters.py`（缺环境变量的说法改成"在 .env 里设置后执行 make restart"）、`deploy/doctor.py`（向量模型的修法改成"在模型页添加向量模型（来源选'本机 Ollama'）"）。Test: `PY agents/tests/test_mcp_adapters.py::test_missing_env_hint_points_to_dotenv`；其余由第四批 I14 的扫描把关。

### Task 13: 测试补缺（I12、I13）

**Files:** `backend/tests/test_api.py`（等审批时改权限的 PATCH 断言 200）、Create `backend/tests/test_main_lifespan.py`（替身跑一遍 `lifespan`，断言启动与关闭的先后）。

### Task 14: 文档、全量检查、审查、升级与 8000 核对

- [ ] 文档：changelog（"积压小问题·第二批"）、backlog R43 进度、usage（重复文档、模型删除、技能上传）、architecture（迁移 0018、补算）、必要时决策记录（B12 推翻 T15）。
- [ ] `make check`、`make test-int`、`make e2e` 全过；独立审查 → 修 Critical / Important → 全量再跑。
- [ ] 升级：查运行状态 → `make backup`（有迁移）→ `make build` → 看启动日志（迁移 0018、补算哈希）→ `make doctor` → 8000 只看核对（知识库页、模型页、技能页、用量页）。
- [ ] 记台账、汇报一句，接着第三批。
