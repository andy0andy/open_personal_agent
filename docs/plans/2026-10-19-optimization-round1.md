# 第一轮优化实施计划（对话体验 → 配置与数据目录 → 用量）

> **给执行者：** 用 superpowers:executing-plans 逐个任务执行（用户已选方式二：本会话内执行，最后一次整体审查；执行时**约每分钟汇报一次进度与剩余时间**）。步骤用复选框（`- [ ]`）跟踪。开始前先读 `.claude/skills/dev-standards/SKILL.md`、设计文档、D21。
>
> 本计划只写定下来的决定：文件、名称与签名、取值、每个任务用哪些测试证明。函数体由执行者按签名与测试写出。
>
> 没有 git：没有提交步骤。台账放 `.superpowers/sdd/2026-10-19-optimization-round1/progress.md`（手动建，第一行写本计划路径），每完成一个任务记一行"任务号、测试命令与结果"，偏离计划的决定记成 `Ruling:` 行。

**目标：** 按设计文档做完三批优化：会话审批权限三档、输入区改版、去掉预算刹车、失败保留已输出部分、上传统一 50MB、数据分析员读得到技能；普通设置进数据库、`.workdata` 成为唯一数据目录、删除本机安全防护与 MCP 目录；用量只算输入和输出。

**用户已定（2026-10-19）：**
- 设计文档已确认，三批写成**一份计划**，按批次顺序执行。每批结束都跑一次"批次检查"：`make check`、`make test-int`、`make e2e`、`make build`、在 8000 上看过、文档已更新。
- 本机安全防护**全部删除**（用户两次确认，风险写进 D23）。
- gemini-3.5-flash、gpt-5.5-pro 的上下文长度、看图能力与价格取自网关自带的价格表（LiteLLM v1.105.0），2026-10-19 从网关的 `/model/info` 读出。值见任务 12 的 `models.yaml`，交接时请用户确认。

**架构：**
- **会话设置归会话所有**。`threads` 存模型与权限档位，`PATCH /threads/{id}` 是唯一的修改入口。运行开始时从会话上取这两项，权限档位存进这次运行的 `input`，审批后继续也沿用它。
- **审批按档位判定**。档位进 `ApprovalPolicy.decide`；智能体的图按"（模型，档位）"缓存；工具指纹也按档位算。
- **配置只有两处**：
  - 普通设置：代码默认值 → 数据库 `app_settings` 表 → 同名环境变量。
  - 技能、MCP 服务清单、审批规则：`.workdata/` 里的文件。
  - 首次启动从 `config/seed/` 写入默认内容（只补缺的，从不覆盖）；模型经网关接口导入。
- 依赖方向不变：`backend → agents → config → common`。

**技术栈：** 后端 Python 3.12、FastAPI、pydantic 2、pydantic-settings、psycopg 3、Alembic。前端 React 19、TanStack Query 5、Vitest、Playwright。网关 LiteLLM v1.105.0。**不新增任何依赖**。

**设计文档：** `docs/specs/2026-10-19-optimization-round1-design.md`（下称"设计"）。来源：`docs/reviews/2026-10-19-功能梳理与优化建议.md`。

## 全局约束

- 依赖方向 `backend → agents → config → common`；deepagents 只在 `agents/main_agent/runtime/`；backend 只用 agents 各模块 `__init__.py` 公开的内容。
- 权限档位的取值与名称（界面文案逐字使用）：

  | 取值 | 名称 | 一行说明 |
  |---|---|---|
  | `ask`（默认） | 每次先问 | 执行命令先问你；外部工具按 MCP 页的审批规则 |
  | `ask_execute` | 只问执行命令 | 只有执行命令先问你，其余全部自动 |
  | `skip` | 跳过所有审批 | 什么都不问，直接执行，包括命令 |

- 额度用完时运行结束的原因（`RunFinished.error`），逐字使用：`模型额度用完了（模型服务返回余额或配额不足）。已输出的部分已保存，充值后说“继续”接着做。`
- 上传上限一个设置：`max_upload_mb`，默认 `50`。它同时管对话附件、知识库文档、技能包。单张图片 5MB、预览上限（表格 20MB、文字 1MB）不变。
- 代码默认值 = 现在 `config/app.yaml` 里的值（上传上限改为 50）。`config/app.yaml` 在任务 10 删除。
- 环境变量名 = 设置键把 `.` 换成 `__` 再转大写，如 `agent.default_model` → `AGENT__DEFAULT_MODEL`。
- 数据目录（任务 11 起）：`.workdata`（宿主机在项目根目录下，容器里是 `/app/.workdata`）。代码与部署里不再出现不带点的 `workdata` 路径。`docs/` 里的历史计划、决策记录、审视文档保留原样。
- 首次写入的默认内容放 `config/seed/`。写入标记是 `.workdata/.seeded`，每行一个已完成的部分：`files`、`models`。
- 自动化测试只用测试库与临时目录。
- 不读、不打印 `.env`。
- 不点模型页的"测试"，也不在 8000 上发真实对话。这两样都花钱，要用户同意。
- **任务 8～13 期间不执行 `make up`、`make build`、`make restart`**：compose 已改成挂载 `.workdata`，重建后端会让 8000 上的数据"不见了"。迁移在任务 14 做。
- 错误用 `common.errors`，消息是给用户看的一句中文。改了接口或事件要 `make types`，`make check` 会核对生成的类型。
- 在终端直接跑前端命令前先 `export PATH="$HOME/.nvm/versions/node/v$(cat frontend/.nvmrc)/bin:$PATH"`（make 命令自带）。
- 界面文案中文，标识符英文，注释只写"为什么"。

## 重点检查（设计没写明、最容易让使用者踩坑的五类情况）

1. **等审批时改了权限档位**。
   - 预期：这次运行（含审批后继续）仍用开始时的档位，审批照常能提交；选择框旁提示"从下一条消息开始生效"。
   - 测试：任务 1 `test_permission_change_while_waiting_keeps_the_runs_permission`，任务 3 `PermissionSelect` 的提示用例。
2. **刚换完模型或档位马上点发送，或者保存失败**。
   - 预期：发送先等保存完成；保存失败时提示原因、选择框回到原值、这条消息不发。
   - 测试：任务 3 `saveQueue.test.ts`。
3. **设置已被 `.env` 的同名变量覆盖，又在设置页上改它**。
   - 预期：拒绝，说明是哪个变量，以及要改 `.env` 再 `make restart`；数据库里已存的值不动。
   - 测试：任务 10 `test_update_rejects_env_overridden_setting`。
4. **首次写入默认内容时，部分文件已存在、用户删过默认项，或网关暂时连不上**。
   - 预期：已有的不覆盖、删过的不重建；模型下次启动再导入。
   - 测试：任务 12 的 `test_seed.py`。
5. **各家"额度用完"的报错写法不同**：英文、中文、402、被包了几层的异常。
   - 预期：都认得出。普通的频率限制（429 rate limit）不能误判成额度用完。
   - 测试：任务 2 `test_quota.py`。

## 文件结构

| 文件 | 职责 |
|---|---|
| `agents/main_agent/integrations/approval.py` | `PermissionMode`；按档位判定审批 |
| `agents/main_agent/runtime/agent.py` | 运行 / 恢复带档位；图按（模型，档位）缓存；失败保留已输出部分；去预算 |
| `agents/main_agent/runtime/interruption.py` | 按原因生成中断说明；额度用完的提示 |
| `agents/main_agent/models/quota.py`（新） | 判断异常是不是"额度用完" |
| `backend/threads/`、`backend/runs/` | 会话的模型与档位；运行记下档位 |
| `frontend/src/features/chat/`（`ComposerToolbar`、`PermissionSelect`、`permission.ts`、`saveQueue.ts`，均新） | 输入框下方工具条 |
| `config/settings.py` | 代码默认值、`SETTING_SPECS`、`load_settings(stored)`；不再读 yaml |
| `backend/settings/app_settings.py`（新） | 设置表的读写与设置页的视图 |
| `backend/settings/seed.py`（新） | 首次写入默认文件、导入模型 |
| `backend/settings/data_files.py`（新） | `.workdata` 各文件的状态 |
| `config/seed/`（新） | 默认 MCP 服务、审批规则、excel 技能、4 个模型 |
| `deploy/`（compose、Dockerfile、备份脚本）、`Makefile` | `.workdata`、`env_file`、`make restart` 重建容器、备份格式 2 |

---

## 第一批：对话体验（设计 4.1～4.6）

### 任务 1：会话的审批权限三档（后端）与 D23

**文件：**
- 新建：`backend/migrations/versions/0010_thread_permission_mode.py`、`docs/decisions/D23-会话审批权限三档去掉预算刹车删除本机防护.md`。
- 修改：
  - `agents/main_agent/integrations/{approval.py,__init__.py}`、`agents/main_agent/runtime/{__init__.py,agent.py}`；
  - `backend/threads/{schemas.py,repo.py}`、`backend/runs/{schemas.py,repo.py,manager.py}`、`backend/api/router.py`、`backend/models/service.py`；
  - `frontend/src/api/client.ts` 与 `frontend/src/features/chat/ChatView.tsx`（`startRun` 不再带模型，只改到能编译；界面在任务 3 改）；
  - `docs/decisions/README.md`；设计文档第 1 行状态改为"已确认（2026-10-19）；三批写成一份实现计划"。
- 测试：`agents/tests/test_approval.py`、`agents/tests/test_approvals_runtime.py`、`backend/tests/test_api.py`、`backend/tests/test_run_control.py`、`backend/tests/test_migrations.py`。

**接口：**
- 产出：
  - `PermissionMode = Literal["ask", "ask_execute", "skip"]`，定义在 `agents/main_agent/integrations/approval.py`，由 `agents.main_agent.integrations` 与 `agents.main_agent.runtime` 导出。
  - `ApprovalPolicy.decide(name, *, server, read_only, mode: PermissionMode = "ask") -> ToolApproval`；`ApprovalPolicy.table(builtin, mcp_tools, mode: PermissionMode = "ask") -> list[ToolApproval]`。
  - `MainAgent.tool_approvals(mode: PermissionMode = "ask")`。`run`、`resume`、`check_answers` 都加关键字参数 `permission: PermissionMode = "ask"`。
  - `Thread.permission_mode: PermissionMode`；`ThreadUpdate(title: str | None, model: str | None, permission_mode: PermissionMode | None)`，三项都没给时校验失败。
  - `ThreadRepo.update(thread_id, *, title=None, model=None, permission_mode=None) -> Thread`，取代 `rename`。
  - `RunRecord.permission: PermissionMode`：读 `runs.input` 的 `permission` 键，没有时为 `"ask"`。`RunRepo.create(..., permission: PermissionMode)`。
  - `RunCreate` 去掉 `model`。运行一律用会话上的模型与档位。
  - `ModelAdmin.require_chat(name: str) -> None`：没有这个模型时抛 `InvalidRequestError("没有这个模型：{name}")`；不是对话模型时抛 `InvalidRequestError("只能选对话模型")`。
  - `PATCH /threads/{id}`：请求体可带 `title`、`model`、`permission_mode` 中的任意几项，返回 `Thread`。

- [ ] **步骤 1：写失败的测试**
  - 审批规则都是 `ApprovalRulesConfig(mcp_default="ask", tools={"*": "ask"})`。
  - `test_skip_mode_auto_for_everything`：
    - `decide("execute", server=None, read_only=None, mode="skip")` 与 `decide("memo_add", server="memo", read_only=False, mode="skip")` 都是 `action == "auto"`；
    - `reason == "本会话跳过所有审批"`。
  - `test_ask_execute_only_asks_for_execute`：
    - `execute` → `ask`，`reason == "本会话只问执行命令"`；
    - `memo_add`（MCP、非只读）与 `write_file` → `auto`，`reason == "本会话只问执行命令，其余自动"`。
  - `test_ask_mode_keeps_rules_and_execute_lock`：
    - 规则改成 `{"*": "auto"}`，`mode="ask"`；
    - `execute` 仍是 `ask`，`reason == EXECUTE_ALWAYS_ASKS`；`memo_add` 按规则 `auto`。
  - `test_skip_permission_runs_without_pause`（runtime）：
    - 用现有的会调 MCP 写工具的假模型剧本，`permission="skip"` 时直到 `RunFinished(completed)` 都没有 `ApprovalRequired`；
    - `permission="ask"` 时出现 `ApprovalRequired`。
  - `test_tools_version_depends_on_permission`：
    - 按 `ask` 暂停后，`check_answers(..., tools_version=<暂停时的>, permission="ask")` 通过；
    - 同样的参数换成 `permission="skip"` 抛 `ConflictError`。
  - `test_patch_thread_sets_model_and_permission`（接口）：
    - PATCH `{"model": "fake-model", "permission_mode": "skip"}` 返回这两项；
    - 再 GET 也是这两项；新会话的 `permission_mode == "ask"`。
  - `test_patch_thread_rejects_unknown_model`：PATCH `{"model": "nope"}` → 400，消息含"没有这个模型"。
  - `test_patch_thread_requires_a_field`：PATCH `{}` → 422。
  - `test_skip_thread_runs_tools_without_approval`（接口，集成）：会话设为 `skip`，发"记笔记"类消息（MCP 写工具），运行直接 `completed`，事件里没有 `approval.required`。
  - `test_permission_change_while_waiting_keeps_the_runs_permission`（集成）：
    - `ask` 下运行停在审批；
    - 把会话改成 `skip`；
    - 再提交"同意"：返回 200，运行跑完；
    - `runs.get(run_id).permission == "ask"`。
  - `test_thread_permission_mode_column`（迁移）：默认值为 `ask`；写入 `'other'` 违反约束。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/test_approval.py agents/tests/test_approvals_runtime.py -q`，再 `make test-int`。
  - 预期：新用例失败（参数或列不存在），原有用例通过。

- [ ] **步骤 3：实现**
  - `decide`：
    - `skip`：一律 auto；
    - `ask_execute`：只有内置 `execute` 是 ask，其余 auto，审批规则不看；
    - `ask`：保持现状（`execute` 固定先问 → 规则 → 内置自动 → MCP 只读自动 → `mcp_default`）。
  - `MainAgent`：
    - `_graphs` 的键改成 `(model, mode)`；
    - `_graph_for(model, mode)` 用 `tool_approvals(mode)` 里 `ask` 的那些组装 `interrupt_on`；
    - `_tools_version(mode)`、`_pending(thread_id, model, mode)` 同样带档位；
    - `reload_integrations`、`update_rules` 清缓存的做法不变；
    - `ApprovalRequired.tools_version` 按本次运行的档位算。
  - 迁移 0010：`ALTER TABLE threads ADD COLUMN permission_mode text NOT NULL DEFAULT 'ask' CHECK (permission_mode IN ('ask','ask_execute','skip'))`；降级删列。写法同 0001～0009（`op.execute` 原始 SQL）。
  - `ThreadRepo.update`：只更新给了值的列。列名来自固定的三项，值走参数。
  - `RunRepo.create`：把 `permission` 写进 `input`；`_COLUMNS` 加 `coalesce(input->>'permission', 'ask') AS permission`。
  - `RunManager`：
    - `start` 用 `thread.model` 与 `thread.permission_mode` 建运行；
    - `_execute` 把 `run.permission` 传给 `agent.run` / `agent.resume`；
    - `resume` 把它传给 `check_answers`。
  - 路由：给了 `model` 时先 `services.models.require_chat`，再 `threads.update`。docstring 改为"改会话的标题、模型或审批权限"。
  - 写 D23（状态"已采纳"，2026-10-19）：
    - 三档权限，与设计 4.1 的表一致；"执行命令固定先问"只在 `skip` 下放开；
    - 去掉预算刹车与额度用完的处理（设计 4.3、4.4）；
    - 删除本机安全防护，把设计 4.8 的三条风险**原文照录**；
    - 修订关系：D18 的预算部分、D20 第 4 条、D21 第 7 条；设计文档 12.2 作废。
  - `docs/decisions/README.md` 加 D23 一行。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`uv run pytest -q`、`make test-int`、`make check`。
  - 预期：全部通过。

---

### 任务 2：去掉预算刹车；失败与额度用完时保留已输出部分

**文件：**
- 删除：`agents/main_agent/runtime/budget.py`、`agents/tests/test_budget.py`。
- 新建：`agents/main_agent/models/quota.py`、`agents/tests/test_quota.py`。
- 修改：
  - `agents/main_agent/runtime/{agent.py,approvals.py,context.py,events.py,tracker.py,translator.py,interruption.py,__init__.py}`、`agents/main_agent/models/__init__.py`、`agents/main_agent/bootstrap.py`；
  - `config/{settings.py,__init__.py,app.yaml}`（删 `BudgetConfig` 与 `budget:` 一节）；
  - `backend/runs/manager.py`、`backend/api/settings.py`（审批视图去掉 `budget`）；
  - 前端：`src/api/types.ts`、`src/features/chat/{reducer.ts,approvals.ts}`、`src/components/chat/approval.tsx`（删 `BudgetRequest`）、`src/features/settings/SettingsPage.tsx`（删预算那行），以及各自的测试。
- 测试：`agents/tests/test_quota.py`、`agents/tests/test_interruption.py`、`agents/tests/test_main_agent.py`、`backend/tests/test_settings_api.py`。

**接口：**
- 产出：
  - `is_quota_exhausted(error: BaseException) -> bool`，由 `agents.main_agent.models` 导出。
  - `agents/main_agent/runtime/interruption.py`：
    - 原因常量：`STOPPED = "用户停止或服务中断"`、`STALLED = "模型长时间没有响应"`、`QUOTA = "模型额度用完"`；
    - `failed_reason(error: BaseException) -> str`：返回 `"调用出错：" + 异常文字的第一行`（最多 100 字；没有文字时用异常类名）；
    - `interrupted_note(reason: str) -> str`：现在 `INTERRUPTED_NOTE` 的全文，括号里的"用户停止或服务中断"换成 `reason`；
    - `INTERRUPTED_NOTE = interrupted_note(STOPPED)`，原文不变；
    - `QUOTA_EXHAUSTED`：全局约束里那句提示。
  - 事件：`ApprovalRequired(requests, tools_version)` 去掉 `budget`；`ApprovalRequest(interrupt_id, agent_path, actions)` 去掉 `kind`；删除 `BudgetStatus`。
  - `RunTracker(calibration=None, model_info=None)` 去掉 `budget`。`AgentContext(thread_id, thread_short_id, run_id, knowledge)` 去掉 `budget`。`MainAgent.__init__` 与 `resume` 去掉 `budget`。`RunManager._execute` 去掉 `budget`。

- [ ] **步骤 1：写失败的测试**
  - `test_quota_errors_are_recognised`（参数化，每条都为 True）：
    - `status_code == 402` 的异常；类名为 `BudgetExceededError` 的异常；
    - 文字分别含 `insufficient_quota`、`You exceeded your current quota`、`Your credit balance is too low`、`Budget has been exceeded!`、`余额不足`、`额度已用完` 的异常；
    - 外面包一层的异常：`raise RuntimeError("x") from <上面任一个>`。
  - `test_rate_limit_is_not_quota`：`status_code == 429`、文字 `Rate limit reached for requests per min` → False。
  - `test_failure_keeps_partial_answer_with_reason`：
    - 假模型先流出"前半段"，再抛 `RuntimeError("upstream exploded")`；
    - 得到 `RunFinished(status="failed", error="RuntimeError: upstream exploded")`；
    - 对话存档最后一条 AI 消息以"前半段"开头，并含"调用出错：upstream exploded"。
  - `test_quota_failure_says_how_to_continue`：
    - 假模型流出文字后抛 402 异常；
    - `RunFinished.error == QUOTA_EXHAUSTED`；
    - 存档里的说明含"模型额度用完"。
  - `test_stall_note_names_the_stall`：现有卡住测试的存档说明含"模型长时间没有响应"，不含"用户停止"。
  - `test_failure_without_output_writes_nothing`：没有输出文字就失败时，存档里不新增 AI 消息（同停止的规则）。
  - `test_approval_view_has_no_budget`（接口）：`GET /settings/approval-rules` 的结果里没有 `budget` 键。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/test_quota.py agents/tests/test_main_agent.py backend/tests/test_settings_api.py -q`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - `is_quota_exhausted`：沿 `__cause__` / `__context__` 往里查（最多 5 层，防止循环）。任一层满足以下任一条就算额度用完：
    - `status_code == 402`；
    - 类名为 `BudgetExceededError`；
    - 小写文字含 `insufficient_quota`、`insufficient quota`、`exceeded your current quota`、`credit balance`、`budget has been exceeded`、`budget exceeded`、`payment required`、`余额不足`、`额度不足`、`额度已用完` 之一。
  - `_drive_events`：
    - 停止：用 `STOPPED`；卡住：用 `STALLED`；
    - 其他异常：额度用完用 `QUOTA`，其余用 `failed_reason(exc)`；
    - 有已输出的文字时都调 `_keep_partial_answer(graph, thread_id, partial, reason)`（写入规则同停止）；
    - 额度用完时 `error=QUOTA_EXHAUSTED`，其余保持 `f"{type(exc).__name__}: {exc}"`。
  - `mark_interruptions` 不变（原因未知时仍用 `STOPPED`）。
  - 删除：`BudgetBrakeMiddleware`（主图与子智能体）、`CONTINUE`、`_is_budget`、`RunBudget`，以及 `bootstrap` 的 `budget=`、`manager.resume` 读预算那行。
  - 前端：
    - 删 `BudgetStatus`、`ApprovalItem.budget`、`toAnswers` 的预算分支、`BudgetRequest`；
    - 审批卡片不再看 `request.kind`；
    - 设置页删预算那行。
  - 旧的预算暂停卡片不做专门显示。**Ruling：** 真实库里 7 个 `approval.required` 事件中没有一个是预算暂停（2026-10-19 只读查询）；旧事件多出来的字段解析时忽略。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make test-int`。
  - 预期：全部通过；`grep -rn "budget\|Budget" agents backend config frontend/src --include='*.py' --include='*.ts' --include='*.tsx'` 只剩无关的命中（如 `token_budget`）。

---

### 任务 3：输入区改版（前端）

**文件：**
- 新建：`frontend/src/features/chat/{ComposerToolbar.tsx,PermissionSelect.tsx,permission.ts,permission.test.ts,saveQueue.ts,saveQueue.test.ts,PermissionSelect.test.tsx}`。
- 修改：
  - `frontend/src/components/chat/ChatThread.tsx`：加 `toolbar?: ReactNode`，渲染在 `ComposerPrimitive.Root` 外、紧贴其下沿；
  - `frontend/src/features/chat/ChatView.tsx`：顶栏只留标题；
  - `frontend/src/features/models/ModelSelect.tsx`、`frontend/src/features/usage/ThreadUsageBadge.tsx`：工具条用的紧凑样式；
  - `frontend/src/api/client.ts`：`updateThread(threadId, patch)` 取代 `renameThread`，调用处跟着改；
  - `frontend/src/features/mcp/ToolsDrawer.tsx`：加一句"这里的规则只在会话权限为“每次先问”时起作用"；
  - `backend/tests/e2e_server.py`：假网关加第二个对话模型 `fake-model-2`；
  - `frontend/e2e/{chat.spec.ts,approval.spec.ts,helpers.ts}`。

**接口：**
- 消费：任务 1 的 `PATCH /threads/{id}`（`Thread.permission_mode`）。
- 产出：
  - `PERMISSIONS: readonly { value: PermissionMode; title: string; description: string; tone: "default" | "warning" | "danger" }[]`：按 `ask`、`ask_execute`、`skip` 的顺序，文案取全局约束的表，`tone` 依次为 `default`、`warning`、`danger`。
  - `PermissionSelect({ value, onChange, pendingHint }: { value: PermissionMode; onChange: (v: PermissionMode) => void; pendingHint: boolean })`。
  - `createSaveQueue(): { run(task: () => Promise<void>): Promise<void>; idle(): Promise<boolean> }`：`idle()` 等排队的保存都结束，最后一次失败时返回 false。
  - `ComposerToolbar({ threadId, permission, onPermission, pendingHint, model, onModel, filesOpen, onToggleFiles })`。

- [ ] **步骤 1：写失败的测试**
  - `permission.test.ts`：
    - `PERMISSIONS.map(p => p.value)` 为 `["ask", "ask_execute", "skip"]`；
    - 标题依次为"每次先问""只问执行命令""跳过所有审批"；
    - `tone` 依次为 `default`、`warning`、`danger`。
  - `PermissionSelect.test.tsx`：
    - 按钮显示当前档位的标题；
    - 点开后有 3 个 `menuitemradio`，当前项 `aria-checked="true"`；
    - 点"跳过所有审批"后 `onChange("skip")` 被调用、列表关闭；
    - 按 Esc 关闭；
    - `pendingHint` 为 true 时显示"从下一条消息开始生效"。
  - `saveQueue.test.ts`：
    - 保存进行中时 `idle()` 不先于它完成；
    - 失败后 `idle()` 为 false；
    - 再成功一次后 `idle()` 为 true。
  - e2e：
    - `chat.spec.ts`"换的模型存在会话上"：选 `fake-model-2`，刷新后仍是 `fake-model-2`；
    - `approval.spec.ts`"只问执行命令：外部工具不再弹审批"：把权限选成"只问执行命令"，发"记笔记"，没有"需要你确认"，直接出现"记好了"；
    - 原有用例里点顶栏控件的地方改为点工具条。

- [ ] **步骤 2：确认测试失败**
  - 运行：`cd frontend && pnpm test src/features/chat`，再 `make test-up && cd frontend && pnpm build && pnpm e2e chat.spec.ts approval.spec.ts`。
  - 预期：新用例失败（模块不存在、找不到控件）。

- [ ] **步骤 3：实现**
  - 工具条：
    - 左边是 `PermissionSelect`：小标签按钮，盾牌图标 + 标题 + 下拉箭头；`warning` / `danger` 档用对应的边框与文字色；
    - 右边依次是会话用量、模型选择、"文件"按钮；
    - 窄于 `sm` 时，"文件"与用量的文字隐藏，只留图标，`title` 里写全称。
  - 列表：
    - 每项是标题 + 一行说明，当前项打勾；
    - 关闭：点外面，或按 Esc（沿用 `components/ui/escape.ts` 的 `closesOverlay`）。
  - `ChatView`：
    - `permission` 与 `model` 跟着 `thread` 同步，写法同现有的 `threadModel`；
    - 一改就乐观更新，再经 `saveQueue.run` 调 `api.updateThread`；
    - 成功：更新会话列表缓存；失败：恢复原值，并 `setNotice("保存失败：…")`；
    - `send` 先 `await saveQueue.idle()`，为 false 时不发送、恢复输入框原文；
    - 运行中或等待审批时改了档位，显示 `pendingHint`，这次运行结束后清掉。
  - 顶栏只留标题。删掉顶栏里的 `ThreadUsageBadge`、`ModelSelect` 与"文件"按钮。

- [ ] **步骤 3a：看样式**
  - 8000 上还是旧后端，不能用来看：先 `make test-up` 与 `cd frontend && pnpm build`，再用 `preview_start` 启动 `.claude/launch.json` 里已有的 `e2e-backend`（端到端测试的假后端，端口 8100）。
  - 深色、浅色、窄窗口（宽 375）各截一张图，看完停掉它。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make check`、`make e2e`。
  - 预期：全部通过。

---

### 任务 4：上传上限统一 50MB

**文件：**
- 修改：
  - `config/settings.py`：加 `Settings.max_upload_mb`；删 `WorkspaceConfig.max_upload_mb`、`KnowledgeConfig.max_document_mb`；
  - `config/app.yaml`：顶层加 `max_upload_mb: 50`，删两个旧项；
  - `agents/main_agent/bootstrap.py`（文档上限）、`backend/api/router.py`（附件上限）；
  - `backend/settings/skill_upload.py`：上限改为参数；
  - `backend/api/settings.py`：上传技能时传入上限；
  - `backend/tests/conftest.py`：`upload_limit_mb` 改设 `max_upload_mb`；
  - `docs/usage.md`：附件 100MB、技能 20MB 改为 50MB。
- 测试：`config/tests/test_settings.py`、`backend/tests/test_skill_upload.py`、`agents/tests/test_bootstrap.py`。

**接口：**
- 产出：
  - `Settings.max_upload_mb: int = Field(default=50, gt=0)`。
  - `decode_upload(body: SkillUpload, *, max_bytes: int)`、`parse_skill_upload(files, *, max_bytes: int) -> SkillPackage`。超过时抛 `TooLargeError(f"技能太大：最多 {max_bytes // 1024 // 1024}MB")`。`MAX_SKILL_FILES = 500` 不变。

- [ ] **步骤 1：写失败的测试**
  - `test_upload_limit_defaults_to_50mb`：`Settings(...).max_upload_mb == 50`；`WorkspaceConfig` 与 `KnowledgeConfig` 里都没有旧字段。
  - `test_skill_upload_uses_the_given_limit`：`max_bytes=1024*1024` 时 2MB 的包抛 `TooLargeError`，消息为"技能太大：最多 1MB"。
  - `test_documents_use_the_shared_limit`：`build_agent` 组装出的文档库上限是 `settings.max_upload_mb * 1024 * 1024`（按 `test_bootstrap.py` 现有的检查方式）。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest config/tests agents/tests/test_bootstrap.py backend/tests/test_skill_upload.py -q`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**：三处都从 `settings.max_upload_mb` 换算成字节。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make check`、`make test-int`。
  - 预期：全部通过。

---

### 任务 5：数据分析员读得到技能

**文件：**
- 修改：`agents/main_agent/runtime/agent.py`（`_subagent`）、`agents/subagents/data_analyst.md`。
- 测试：`agents/tests/test_subagents.py`。

- [ ] **步骤 1：写失败的测试**
  - `test_custom_subagent_gets_skill_sources`：
    - 用带技能目录的 `MainAgent` 与 `data_analyst` 定义；
    - `_subagent(definition, frozenset())["skills"] == _skill_sources()`；
    - 没有技能目录时没有 `skills` 键。
  - `test_data_analyst_prompt_has_no_hardcoded_paths`：`data_analyst.md` 的正文不含 `/skills/`，也不含"每次执行前都会先请用户确认"。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/test_subagents.py -q`。
  - 预期：两条失败。

- [ ] **步骤 3：实现**
  - `_subagent` 与 `_general_purpose` 一样，有技能来源时加 `skills`。
  - `data_analyst.md`：
    - "处理 Excel、CSV 前先读技能文件 /skills/excel/SKILL.md 里的规范。"改为"处理 Excel、CSV 前先看技能清单里有没有相关技能，有就先读它的 SKILL.md。"；
    - "每次执行前都会先请用户确认"改为"执行命令可能要先请用户确认"。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make check`。
  - 预期：全部通过。

---

### 任务 6：第一批检查

**文件：** `docs/usage.md`、`docs/specs/2026-10-10-personal-agent-design.md`、`docs/development/architecture.md`、`docs/decisions/D18-*.md`、`docs/changelog.md`、`docs/requirements/backlog.md`。

- [ ] **步骤 1：文档**
  - 使用指南：
    - 写三档权限与工具条；
    - 换的模型存在会话上；
    - 额度用完时怎么继续；
    - 上传上限 50MB。
  - 设计文档 10.8（预算刹车）标"已取消（D23）"；10.5 加"审批按会话权限档位"。
  - 架构规范：审批按档位、图按（模型，档位）缓存。
  - D18 的预算部分注明"被 D23 取代"。
  - changelog 加"第一轮优化·第一批：对话体验（2026-10-19，D23）"。
  - 需求池：
    - 加 R35"第一轮优化（设计 2026-10-19）"，状态"进行中：第一批完成"；
    - R26 末尾"因原金额上限暂停的旧运行……"一句划掉，注明预算刹车已去掉。

- [ ] **步骤 2：全部检查**
  - 运行：`make check`、`make test-int`、`make e2e`、`make build`。预期：全部通过，后端启动时执行迁移 0010。
  - 用内置浏览器打开 http://127.0.0.1:8000 ：
    - 深色、浅色各看一遍工具条，以及权限列表的三种颜色；
    - 换模型后刷新，仍是换后的；
    - 不发真实对话。

---

## 第二批：配置与数据目录（设计 4.7～4.10）

### 任务 7：整体快照（动手前）

**文件：** 新建项目外的 `<项目上一级目录>/open_personal_agent-snapshots/20261019-before-batch2/`（只增不删）。

- [ ] **步骤 1：数据库与文件备份**
  - 运行：`make backup`。
  - 预期：`workdata/backups/` 下多一份，`manifest.txt`、`agent.dump`、`litellm.dump`、`files.tar.gz` 齐全且都不为空。
- [ ] **步骤 2：打包整个项目**
  - 把上一步那份备份复制到快照目录的 `backup/`。
  - 在项目根目录运行 `tar -czf <快照目录>/project.tar.gz`，排除 `./frontend/node_modules`、`./.venv`、`./frontend/dist`、`./workdata/cache`、`__pycache__`、`.mypy_cache`、`.ruff_cache`、`.pytest_cache`。
  - 包内含 `.env`：恢复网关数据库要用同一个 `LITELLM_SALT_KEY`。打包时不打印 `.env` 的内容。
- [ ] **步骤 3：写退回说明并核对**
  - 快照目录里写 `README.txt`，写清退回步骤：
    1. `make down`；
    2. 把当前项目目录挪开；
    3. 解开 `project.tar.gz`；
    4. `make infra-up`；
    5. 把 `backup/` 复制进 `workdata/backups/`，用旧代码的 `make restore BACKUP=<名字>`；
    6. `make build`。
  - 核对：
    - `tar -tzf project.tar.gz | grep -c '^./workdata/'` 大于 0；
    - 列出快照目录各文件的大小，记进台账。

---

### 任务 8：删除本机安全防护

**文件：**
- 删除：`backend/security.py`、`backend/tests/test_security.py`、`frontend/src/features/auth/`。
- 修改：
  - 后端与配置：`backend/main.py`、`backend/tests/e2e_server.py`、`config/{settings.py,app.yaml}`（删 `SecurityConfig`、`access_token`、`listen_address` 与 `security:` 一节）；
  - 部署：`deploy/docker-compose.yml`（启动命令去掉 `python -m backend.security &&`；删 `ACCESS_TOKEN`、`LISTEN_ADDRESS`；端口写死 `"127.0.0.1:8000:8000"`）、`.env.example`（删这两项）；
  - 前端：`frontend/src/api/{client.ts,queries.ts}` 及其测试、`frontend/src/layout/AppShell.tsx`、`frontend/src/features/chat/ChatView.tsx`；
  - 文档：`README.md`（删局域网访问一节）、`docs/usage.md`、`docs/development/architecture.md`、设计文档 12.2（标"已作废（D23）"）。
- 测试：`backend/tests/test_api.py`、`frontend/src/api/queries.test.ts`。

**接口：**
- 产出：
  - 删除 `needsAccessToken`、`recheckAccess`。
  - `retryWhileFailing` 对任何错误都每 5 秒重试。
  - `create_app` 不再加安全中间件，也不再挂令牌路由。

- [ ] **步骤 1：写失败的测试**
  - `test_cross_origin_write_is_accepted`：带 `Origin: http://evil.example` 的 `POST /api/threads` → 201。这条记录的就是 D23 接受的风险。
  - `test_any_host_is_accepted`：`Host: evil.example` 的 `GET /api/threads` → 200。
  - `test_post_without_json_body_is_accepted`：不带请求体的 `POST /api/settings/reload` → 200（原来是 415）。
  - `queries.test.ts`：`retryWhileFailing` 遇到 401 的 `ApiError` 返回 5000。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest backend/tests/test_api.py -q`、`cd frontend && pnpm test src/api`。
  - 预期：新用例失败（403、415、false）。

- [ ] **步骤 3：实现**：按"文件"删除与修改。文件预览的 `Content-Security-Policy: sandbox` 响应头保留——它防的是预览文件里的脚本，不属于这次删的防护。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make test-int`。预期：全部通过。
  - 运行：`grep -rn "ACCESS_TOKEN\|LISTEN_ADDRESS\|SecurityPolicy\|AccessToken" --exclude-dir=node_modules --exclude-dir=docs .`。预期：没有结果。

---

### 任务 9：去掉 MCP 目录

**文件：**
- 删除：`config/mcp_catalog.yaml`。
- 修改：
  - `config/{integrations.py,settings.py,__init__.py}`：删 `McpCatalogItem`、`load_mcp_catalog`、`IntegrationsConfig.mcp_catalog_file`；
  - `backend/settings/{service.py,schemas.py}`：删 `catalog`、`McpCatalogView`；
  - `backend/api/settings.py`：删 `/settings/mcp-catalog`；
  - `backend/tests/e2e_server.py`；
  - 前端：`src/features/mcp/` 里的目录界面与测试、`src/api/{client.ts,queries.ts}` 的目录查询、`e2e/mcp.spec.ts` 的目录步骤；
  - `docs/usage.md` 的 MCP 一节。
- 测试：`backend/tests/test_settings_api.py`。

- [ ] **步骤 1：写失败的测试**：`test_mcp_catalog_is_gone` → `GET /api/settings/mcp-catalog` 返回 404。原来的目录用例删掉。
- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest backend/tests/test_settings_api.py -q`。
  - 预期：这一条失败（200）。
- [ ] **步骤 3：实现**
  - 按"文件"删除。
  - MCP 页保留"我的 MCP 服务"、手动添加、粘贴 JSON、测试连接；添加对话框里不再有"从目录选"。
- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make e2e`。
  - 预期：全部通过。

---

### 任务 10：普通设置进数据库与 D22

**文件：**
- 新建：`backend/migrations/versions/0011_app_settings.py`、`backend/settings/app_settings.py`、`backend/tests/test_app_settings.py`、`docs/decisions/D22-配置进数据库与workdata.md`。
- 删除：`config/app.yaml`。
- 修改：
  - 配置：`config/{settings.py,__init__.py}`；
  - 后端：`backend/main.py`、`backend/api/{deps.py,settings.py}`、`backend/models/{service.py,schemas.py}`；
  - 测试装配：`backend/tests/{conftest.py,e2e_server.py}`、`agents/tests/test_bootstrap.py`、`config/tests/test_settings.py`；
  - 部署：`deploy/docker-compose.yml`（backend 加 `env_file: ../.env`）、`Makefile`、`.env.example`（加一段：设置页的设置可以用同名变量覆盖，覆盖后页面上不能改）。

**接口：**
- 产出：
  - `config/settings.py`：
    - `SettingSpec(BaseModel)`：`key: str`、`label: str`、`apply: Literal["now", "restart"]`、`editable: bool = True`、`note: str | None = None`。
    - `SETTING_SPECS: tuple[SettingSpec, ...]`，内容见下表。
    - `load_settings(stored: Mapping[str, Any] | None = None) -> Settings`：`stored` 的键是点分的设置键。优先级从高到低：构造参数 > 环境变量 > `.env` > `stored` > 代码默认值，按层逐项合并。
    - `env_name(key: str) -> str`。
    - `get_settings()` 只读环境变量与 `.env`，签名不变。
    - 删除 `read_user_app_yaml`、`user_app_yaml`、`_UserAppSettings`，以及 `yaml_file` 相关的设置。
    - `AgentConfig.default_model` 默认值为 `"claude-opus-4-6"`。
  - `backend/settings/app_settings.py`：
    - `AppSettingsRepo(pool)`：`all() -> dict[str, Any]`、`put(key: str, value: Any) -> None`（有则更新）、`delete(key: str) -> None`。
    - `SettingView(BaseModel)`：`key`、`label`、`value: JsonValue`、`default: JsonValue`、`source: Literal["default", "db", "env"]`、`env_name: str`、`editable: bool`、`apply: Literal["now", "restart"]`、`note: str | None`、`restart_pending: bool`。
    - `AppSettingsService(settings: Settings, repo: AppSettingsRepo)`：
      - `views() -> list[SettingView]`（按 `SETTING_SPECS` 的顺序）；
      - `update(key, value) -> SettingView`；
      - `reset(key) -> SettingView`：删掉数据库里的值。
  - 接口：
    - `GET /settings/app` → `list[SettingView]`；
    - `PUT /settings/app/{key}`，请求体 `{"value": ...}` → `SettingView`；
    - `DELETE /settings/app/{key}` → `SettingView`。
    - 键为 `agent.default_model` 的 PUT 交给 `services.models.set_default_chat(value)`，复用模型存在且是对话模型的检查。
  - `ModelAdmin(settings, gateway, threads, app_settings: AppSettingsService)`：
    - 最后一个参数取代原来的 `user_files`；
    - `set_default_chat` 改为 `app_settings.update("agent.default_model", name)`；
    - 删 `ModelsView.config_error`。
  - `Services.app_settings: AppSettingsService`。

`SETTING_SPECS`：

| 键 | 标签 | 生效 | 页面可改 |
|---|---|---|---|
| `agent.default_model` | 默认对话模型 | now | 是 |
| `agent.stream_idle_timeout` | 模型多少秒没有新内容就放弃这次调用 | restart | 是 |
| `workspace.command_timeout` | 命令默认时限（秒） | restart | 是 |
| `workspace.max_command_timeout` | 命令最长时限（秒） | restart | 是 |
| `max_upload_mb` | 上传上限（MB，附件、知识库文档、技能包共用） | restart | 是 |
| `knowledge.embedding_model` | 向量模型 | restart | 否（注：换向量模型要把知识库全部重新向量化，见 R31） |
| `knowledge.recall_top_k` | 每次带上的相关记忆最多几条 | restart | 是 |
| `knowledge.recall_min_similarity` | 相关记忆的相似度下限（0～1） | restart | 是 |
| `knowledge.recall_timeout` | 找相关记忆最多等几秒 | restart | 是 |
| `knowledge.pinned_token_limit` | 常驻条目的建议上限（token） | restart | 是 |
| `knowledge.auto_extract` | 每次对话后自动整理记忆 | restart | 是 |
| `knowledge.chunk_tokens` | 文档每块约多少 token | restart | 是 |
| `knowledge.chunk_overlap_tokens` | 相邻两块重叠多少 token | restart | 是 |
| `knowledge.ingest_batch_size` | 文档入库时每次向量化几段 | restart | 是 |
| `adapters.model_gateway` 等 7 项 | 模型网关 / 工作区 / 向量化 / 知识库索引 / 文档解析 / 原文件存储 / MCP 客户端的实现 | restart | 否（注：目前每项只有一种实现） |
| `models.sources` | 模型来源（模型页新增模型时选） | restart | 否（注：来源里有网关地址，页面上不能改） |

**Ruling（我的决定）：**
- 适配器与模型来源列在设置页上，但只读：每项只有一种实现。设计 4.7 只要求"列出、标明能否改"。
- `knowledge.embedding_model` 标 restart，是为了与"重启后生效"的说法一致；它本身不可改。

- [ ] **步骤 1：写失败的测试**
  - `test_defaults_match_the_old_app_yaml`：
    - 不给任何存储值时，各项等于原 `config/app.yaml` 的值：命令时限 120 / 600；`max_upload_mb` 50；`default_model` `claude-opus-4-6`；`stream_idle_timeout` 120；`embedding_model` `embed-qwen3-0.6b`；召回 5 / 0.3 / 5；常驻上限 2000；`auto_extract` True；切块 600 / 80；入库批量 2；
    - 适配器各项为原值。
  - `test_stored_value_overrides_default`：`load_settings({"knowledge.recall_top_k": 3}).knowledge.recall_top_k == 3`。
  - `test_env_overrides_stored`：设环境变量 `KNOWLEDGE__RECALL_TOP_K=7`，存储值 3 → 7。
  - `test_every_spec_key_resolves`：每个 `SETTING_SPECS` 的键都能在 `Settings` 上按点取到值。
  - `test_settings_read_no_yaml`：`Settings.model_config.get("yaml_file") is None`，`config/app.yaml` 不存在。
  - `backend/tests/test_app_settings.py`（集成）：
    - `test_lists_settings_with_sources`：
      - `monkeypatch` 设 `AGENT__STREAM_IDLE_TIMEOUT` → 该项 `source == "env"`、`editable is False`；
      - 库里有 `knowledge.recall_top_k` → `"db"`；
      - 其余为 `"default"`。
    - `test_update_saves_and_marks_restart_pending`：PUT `knowledge.recall_top_k` 为 3 → `source == "db"`、`restart_pending is True`；运行中的 `services.settings.knowledge.recall_top_k` 不变。
    - `test_update_default_model_applies_now`：
      - 这条测试给假网关两个对话模型 `fake-model`、`fake-model-2`（`FakeGateway(model, models=[...])`）；
      - PUT `agent.default_model` 为 `fake-model-2` → 新建会话的模型就是它，`restart_pending is False`。
    - `test_update_rejects_env_overridden_setting`：
      - 覆盖了的项 → 409，消息含 `AGENT__STREAM_IDLE_TIMEOUT` 与 `make restart`；
      - 库里原来的值不变。
    - `test_update_rejects_invalid_value`：`workspace.command_timeout` 为 0 → 400，消息以"取值不合规"开头。
    - `test_update_rejects_read_only`：`knowledge.embedding_model` → 409，消息为"这一项不能在页面上改"。
    - `test_unknown_key_is_404`。
    - `test_reset_returns_to_default`：DELETE 后 `source == "default"`。
    - `test_startup_reads_stored_settings`：`repo.put("max_upload_mb", 20)` 之后，`load_settings(await repo.all()).max_upload_mb == 20`。
  - 迁移测试：`app_settings` 表存在，`key` 是主键。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest config/tests -q`、`make test-int`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - 迁移 0011：`CREATE TABLE app_settings (key text PRIMARY KEY, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())`；降级删表。
  - 存储值这一层：一个自定义的 pydantic-settings 来源，把点分键展开成嵌套字典。`load_settings` 用一个只在函数里定义的 `Settings` 子类把它插在 `.env` 之后。
  - 判断"被环境变量覆盖"：`env_name(key)` 不分大小写地出现在 `os.environ` 里。
  - `update` 的检查顺序：
    1. 键不存在 → `NotFoundError("没有这个设置项：{key}")`；
    2. 不可改 → `ConflictError("这一项不能在页面上改")`；
    3. 被覆盖 → `ConflictError("已由环境变量 {ENV} 指定：要改请改 .env，然后执行 make restart")`；
    4. 用 `load_settings({**现有存储值, key: value})` 校验，失败 → `InvalidRequestError("取值不合规：" + 第一条错误)`；
    5. 写库。
  - `apply == "now"` 时把新值写进运行中的 `settings`。
  - `restart_pending`：`load_settings(存储值)` 算出的值与运行中的值不同（只看 `apply == "restart"` 的项）。
  - `lifespan` 分两步：
    1. `get_settings()` 拿数据库地址，打开连接池；
    2. `settings = load_settings(await AppSettingsRepo(pool).all())`，之后的组装都用它。
  - Makefile：
    - `restart` 改为 `$(DC) up -d --force-recreate --wait backend`，失败时显示日志，同 `START_BACKEND`；
    - `restart-gateway` 改为 `$(DC) up -d --force-recreate --wait litellm`；
    - 说明里写"改了 .env 也用它"。
  - compose：
    - backend 加 `env_file: ../.env`，原 `environment` 各项保留（它们覆盖 `.env` 里给宿主机用的值，如数据库地址）；
    - 把"只传后端需要的变量"那段注释改成 D22 的说法；
    - 核对 `.env.example` 里每个变量进容器后不改变后端行为（只看 `.env.example`）。
  - 核对密钥不外流：后端容器整份读入 `.env` 之后，命令只拿白名单里的变量（D20）。再看 MCP 库启动本地服务时传哪些环境变量：配置里没写 `env` 时，预期只传默认的几项。结论记进 D22。
  - 写 D22（状态"已采纳"，2026-10-19）：
    - 设计 4.7 的取值顺序、设置表、`.workdata` 唯一数据目录、首次写入与模型导入、迁移与退回；
    - 取代 D21 第 1、2 条与第 6 条；保留第 3 条（模型走网关接口）与"技能不许同名"。
  - `docs/decisions/README.md` 加 D22 一行。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make test-int`。
  - 预期：全部通过。

---

### 任务 11：数据目录改名 `.workdata`；备份改为格式 2

**文件：**
- 修改（全部不带点的 `workdata` 引用）：
  - 配置：`config/settings.py`（`workdata_dir` 默认 `ROOT_DIR / ".workdata"`）；
  - 部署：
    - `deploy/docker-compose.yml`：挂载 `../.workdata:/app/.workdata`；`WORKDATA_DIR: /app/.workdata`；`npm_config_cache: /app/.workdata/cache/npm`；`SHARED_DIR` 默认 `../.workdata/shared`；
    - `deploy/backend.Dockerfile`：`ln -s /app/.workdata/workspace /workspace`；
    - `deploy/{backup.sh,restore.sh}`；
  - `Makefile`：`NEED_ENV`、`START_BACKEND`、`BACKUP_ENV`、`restore` 列表；
  - 忽略清单：`.gitignore`、`.dockerignore`、`pyproject.toml`（ruff、mypy 的排除）；
  - 其余引用：`agents/`、`backend/`、前端 `src/` 与 `e2e/`、`.env.example`、`CLAUDE.md`、`README.md`、`docs/usage.md`、`docs/development/{architecture.md,testing.md}`。
- 新建：`deploy/tests/test_paths.py`。
- 测试：`deploy/tests/test_backup_scripts.py`、`config/tests/test_settings.py`。

**接口：**
- 产出：
  - `manifest.txt` 多一行 `format=2`。
  - `restore.sh` 遇到没有 `format=2` 的备份时拒绝，消息为：`这份备份是旧格式（第一轮优化之前做的），不能恢复到现在的版本；需要时先用 2026-10-19 的整体快照退回旧版本（见快照里的 README.txt）`。

- [ ] **步骤 1：写失败的测试**
  - `test_no_plain_workdata_left`：
    - 扫描 `agents`、`backend`、`common`、`config`、`deploy`、`frontend/src`、`frontend/e2e`、`Makefile`、`pyproject.toml`、`.env.example`、`.gitignore`、`.dockerignore`、`README.md`、`CLAUDE.md`、`docs/usage.md`、`docs/development/`；
    - 按行匹配路径写法 ``(?<![.\w-])workdata(?=/|:/|["'`]|$)|=workdata\b``，结果为空；
    - 这个写法只认路径（如 `workdata/`、`"workdata"`、`../workdata:/app`、`WORKDATA=workdata`），不误伤变量名 `workdata: Path` 与临时目录前缀 `e2e-workdata-`；
    - 本测试文件自己除外。
  - `test_default_workdata_dir_is_hidden`：`Settings(...).workdata_dir == ROOT_DIR / ".workdata"`。
  - `test_manifest_has_format_2`（集成）：备份后 `manifest.txt` 含 `format=2`。
  - `test_restore_refuses_old_format`（集成）：删掉 `format=2` 那一行后恢复 → 非零退出，输出含"旧格式"，测试库里的数据不变。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest deploy/tests/test_paths.py config/tests -q`、`make test-int`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - 逐个改路径。
  - `restore.sh` 先查 `format=`，再做恢复前的自动备份。
  - `.env.example` 里 `SHARED_DIR` 的说明同步改。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make check`、`make test-int`、`make e2e`。
  - 预期：全部通过。
  - 注意：此后 `make test-up` 会在宿主机建出空的 `.workdata/workspace`，任务 14 处理。

---

### 任务 12：去掉叠加；首次写入默认内容；模型导入网关

**文件：**
- 新建：
  - 默认文件：`config/seed/workdata/config/mcp_servers.yaml`、`config/seed/workdata/config/approval_rules.yaml`、`config/seed/workdata/skills/excel/`（从 `agents/skills/excel/` 整个移过来）；
  - 模型：`config/seed/models.yaml`；
  - 代码与测试：`backend/settings/seed.py`、`backend/tests/test_seed.py`。
- 删除：`config/mcp_servers.yaml`、`config/approval_rules.yaml`、`agents/skills/`。
- 修改：
  - 配置：`config/{integrations.py,settings.py,__init__.py}`；
  - 智能体：
    - `agents/main_agent/runtime/{skills.py,files.py,agent.py}`；
    - `agents/main_agent/bootstrap.py`；
    - `agents/main_agent/models/{base.py,litellm_proxy.py}`：删 `ModelInfo.builtin`；
    - `agents/tests/fakes.py`；
  - 后端：`backend/settings/{service.py,store.py}`、`backend/models/service.py`、`backend/api/settings.py`、`backend/main.py`、`backend/tests/{conftest.py,e2e_server.py}`；
  - 前端：`src/features/{models,skills,mcp}/` 里"自带"的标记与只读逻辑，以及各自的测试和 e2e。

**接口：**
- 产出：
  - `config/integrations.py`：
    - `load_mcp_servers(data: dict[str, Any], env: Mapping[str, str], *, label: str) -> list[McpServerConfig]`；
    - `load_approval_rules(data: dict[str, Any], *, label: str) -> ApprovalRulesConfig`；
    - 删 `merge_mcp_servers`、`raw_mcp_servers`、`merge_approval_rules`、`McpServerConfig.builtin`（`_LOADER_FIELDS` 同步去掉）。
  - `Settings` 的属性：
    - `config_dir`（= `workdata_dir / "config"`）、`mcp_servers_file`、`approval_rules_file`、`skills_state_file`（`config/skills.yaml`）、`skills_dir`（= `workdata_dir / "skills"`）。
    - 删 `IntegrationsConfig`、`user_config_dir`、`user_skills_dir`、`AgentConfig.skills_dir`。
    - `SEED_DIR = CONFIG_DIR / "seed"`。
  - `SkillCatalog(skills_dir: Path | None, state_file: Path | None = None)`：
    - 删 `SkillInfo.origin`；任何技能都能删；
    - 文件树只挂一处 `/skills/`（`SKILLS_ROOT = "/skills/"` 取代 `SKILL_SOURCES`）；
    - `_skill_sources()` 返回 `["/skills/"]` 或 `None`。
  - `backend/settings/seed.py`：
    - `seed_files_once(workdata: Path, seed_dir: Path) -> list[str]`：
      - 标记里没有 `files` 时，把 `seed_dir/"workdata"` 里缺的项写进去，再记上 `files`；
      - `config/` 下按文件、`skills/` 下按整个技能文件夹，从不覆盖；
      - 返回写入的相对路径。
    - `load_seed_models(path: Path) -> list[ModelInput]`。
    - `async seed_models_once(workdata: Path, models: ModelAdmin, items: Sequence[ModelInput]) -> list[str]`：
      - 标记里没有 `models` 时，加网关里还没有的名字，全部成功后记上 `models`；
      - 网关出错（`UpstreamError`）时记日志、不记标记，返回已加的名字。
  - `IntegrationSettings`、`ModelAdmin`：去掉"自带"的分支，全部条目能改能删。

`config/seed/models.yaml`。价格是"美元 / 每百万 token"；来源 `upstream` 即"公司 LiteLLM 网关"。

| name | 来源 / upstream_id | mode | 上下文 / 输出上限 | 价格 输入 / 输出 | 思考 / 看图 / 工具 |
|---|---|---|---|---|---|
| claude-opus-4-6 | upstream / claude-opus-4-6 | chat | 1000000 / 128000 | 5 / 25 | 是 / 是 / 是 |
| gemini-3.5-flash | upstream / gemini-3.5-flash | chat | 1048576 / 65535 | 1.5 / 9 | 是 / 是 / 是 |
| gpt-5.5-pro | upstream / gpt-5.5-pro | chat | 1050000 / 128000 | 30 / 180 | 是 / 是 / 是 |
| embed-qwen3-0.6b | ollama / qwen3-embedding:0.6b | embedding | — | 0 / 0 | 否 / 否 / 否 |

默认的 `mcp_servers.yaml` 与现在 `config/mcp_servers.yaml` 的 `files` 条目相同，说明改为"共享文件夹（本机 .workdata/shared/，.env 的 SHARED_DIR 可改成别的文件夹）"。默认的 `approval_rules.yaml` 是 `mcp_default: ask` 加空的 `tools`，开头注释写：执行命令固定先问；这些规则只在会话权限为"每次先问"时起作用。

- [ ] **步骤 1：写失败的测试**
  - `test_first_start_writes_seed_files`：
    - 空的临时目录 → 写入 `config/mcp_servers.yaml`、`config/approval_rules.yaml`、`skills/excel/SKILL.md`；
    - `.seeded` 含 `files`。
  - `test_existing_files_are_not_overwritten`：已有自己内容的 `config/mcp_servers.yaml` 原样保留，缺的照写。
  - `test_deleted_items_are_not_recreated`：第一次写入后删掉 `skills/excel`，再调一次什么都不写。
  - `test_seed_models_adds_missing_only`：
    - 假网关里已有 `claude-opus-4-6` → 只加另外 3 个；
    - `.seeded` 含 `models`。
  - `test_seed_models_retries_when_gateway_is_down`：
    - 假网关第一次报错 → 不记标记；
    - 第二次正常 → 加上、记标记。
  - `test_seed_models_file_matches_the_table`：`load_seed_models(SEED_DIR / "models.yaml")` 的 4 项与上表逐项相同。
  - `test_mcp_servers_come_only_from_workdata`：`load_mcp_servers({"servers": {"memo": {"command": "echo"}}}, {}, label="x")` 只有 `memo`；写了 `builtin` 字段的条目报"不认识的字段"。
  - `test_any_server_can_be_removed`（接口）：删除 `files` 服务 → 204，它的审批规则一并删掉。
  - `test_any_skill_can_be_deleted`（接口）：删除首次写入的 `excel` → 204。
  - `test_every_model_is_editable`：`ModelAdmin.update` 能改导入的模型，不再有"自带模型只读"。
  - 前端：三页的测试里删掉"自带"相关断言，加"所有条目都有删除按钮"。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest -q`、`make test-int`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - `lifespan` 里的顺序：
    1. 读设置（任务 10）之后先 `seed_files_once`，再组装智能体；
    2. 模型导入放进后台任务，与 MCP 连接一起：`seed_models_once(...)` 之后 `integrations.load()`。
  - `UserConfigFiles` 写文件的开头注释改为 `# 由管理页面写入，也可以手改（D22）`。
  - e2e 与接口测试的临时目录按新结构放文件：`config/mcp_servers.yaml`、`config/approval_rules.yaml`、`skills/excel/`。
  - **先行验证**（同 D21 的做法：测试库加临时网关容器，不花钱）：
    - `config/models.yaml` 只留 `model_list: []`、`litellm_settings`、`general_settings` 时，v1.105.0 能启动；
    - 能接受 `/model/new`；
    - 结论记进台账。
    - 正式文件在任务 14 才改。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make test-int`、`make e2e`。
  - 预期：全部通过。

---

### 任务 13：设置页改版

**文件：**
- 新建：`backend/settings/data_files.py`、`frontend/src/features/settings/{settings.ts,settings.test.ts}`。
- 修改：`backend/api/settings.py`、`frontend/src/features/settings/SettingsPage.tsx`、`frontend/src/api/{client.ts,queries.ts}`、`frontend/e2e/pages.spec.ts`。
- 测试：`backend/tests/test_settings_api.py`。

**接口：**
- 产出：
  - `DataFileView(BaseModel)`：`path: str`（如 `.workdata/config/mcp_servers.yaml`）、`purpose: str`、`state: Literal["ok", "missing", "error"]`、`detail: str | None`。
  - `data_file_views(settings: Settings, integrations: IntegrationSettings, skills: SkillCatalog | None) -> list[DataFileView]`。依次四项：
    - `config/mcp_servers.yaml`："MCP 服务清单"；
    - `config/approval_rules.yaml`："审批规则"；
    - `config/skills.yaml`："停用的技能"；
    - `skills/`："技能（N 个）"。
    - 写坏时 `detail` 为现有的报错原因。
  - `GET /settings/files` → `list[DataFileView]`。
  - 前端纯函数：
    - `groupSettings(views) -> { title: string; items: SettingView[] }[]`：
      - 分组依次为"对话与模型"（`agent.*`）、"工作区"（`workspace.*`、`max_upload_mb`）、"知识库"（`knowledge.*`）、"实现与来源"（`adapters.*`、`models.sources`）；
    - `sourceLabel(view) -> string`："默认"/"已改"/"环境变量 {env_name}"；
    - `applyLabel(view) -> string`：
      - now →"立即生效"；
      - restart → `restart_pending` 时"已保存，重启后生效（终端执行 make restart）"，否则"重启后生效（终端执行 make restart）"（设计 4.7 的原话）；
    - `parseInput(view, raw: string) -> { ok: true; value: unknown } | { ok: false; error: string }`：数字项要合法数字。

- [ ] **步骤 1：写失败的测试**
  - `test_data_files_report_state`（接口）：
    - 临时目录里 `mcp_servers.yaml` 写坏、`skills.yaml` 不存在 → 状态分别为 `error`（`detail` 含文件名）与 `missing`；
    - 其余为 `ok`。
  - `settings.test.ts`：
    - `groupSettings` 的分组标题与归类：`agent.*` 在"对话与模型"，`adapters.*` 与 `models.sources` 在"实现与来源"；
    - `sourceLabel` 三种情况；
    - `applyLabel` 三种情况；
    - `parseInput` 把 `"abc"` 判为不合法、`"30"` 判为 30。
  - e2e `pages.spec.ts`"设置页"：
    - 有"默认对话模型"一行；
    - 把"每次带上的相关记忆最多几条"改成 3 后显示"已保存，重启后生效"；
    - 点"恢复默认"后回到"默认"；
    - 页面上没有"审批规则与预算""重新加载"。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest backend/tests/test_settings_api.py -q`、`cd frontend && pnpm test src/features/settings`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - 设置页从上到下两块：
    - "设置"：分组列出。每行：标签、键名（小字等宽）、取值控件、来源标签、生效说明；`source == "db"` 时有"恢复默认"。控件：
      - 数字：输入框，回车或失焦保存；
      - 开关：`Switch`；
      - 默认对话模型：对话模型下拉；
      - 不可改的：只读文字，附 `note`。
    - "`.workdata` 里的文件"：路径、用途、状态，写坏时显示原因。
  - 删掉：外观、模型、MCP 服务、审批规则与预算、技能几块，以及顶栏的"重新加载"（MCP 页保留它自己的）。
  - 明暗切换只留侧栏那一处。**Ruling（我的决定）：** 侧栏任何页面都能一键切换，设计 4.7 允许二选一。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make e2e`。
  - 预期：全部通过。

---

### 任务 14：迁移你的数据（先确认）与第二批检查

**文件：** `config/models.yaml`（只留网关自身的设置），文档：`docs/usage.md`、`README.md`、`docs/development/architecture.md`、`docs/decisions/D21-*.md`（标被 D22 部分取代）、`docs/changelog.md`、`docs/requirements/backlog.md`。

- [ ] **步骤 1：向用户确认（停点）**
  - 说明以下几步要做什么，用户同意后再动：
    - 停服务；
    - `workdata` 改名 `.workdata`；
    - 处理旧的覆盖文件；
    - 改 `config/models.yaml`；
    - 重建并启动。
  - 退回办法：任务 7 的快照。
- [ ] **步骤 2：停服务并改名**
  - 停之前记下迁移前的数，供步骤 6 核对：`/api/threads` 的会话数、知识库的条目数（记忆与文档片段）、`/api/settings/skills` 的技能数。
  - `make down`。
  - 若 `.workdata` 已存在（任务 11 之后 make 命令建的），只删其中的空目录（`find .workdata -type d -empty -delete`），之后 `.workdata` 必须已不存在。不是空的就停下来问用户。
  - `mv workdata .workdata`。
- [ ] **步骤 3：处理旧的覆盖文件**
  - 再看一遍 `.workdata/config/` 下的旧覆盖文件。
  - 2026-10-19 核对时为 `mcp_servers.yaml: servers: {}`、`skills.yaml: disabled: []`，没有 `approval_rules.yaml` 与 `app.yaml`。
  - 仍是这样：删掉 `mcp_servers.yaml`，由首次写入补上默认的 `files` 服务；`skills.yaml` 留着。
  - 有了别的内容：按 D21 的覆盖规则手工合并成完整的文件，先给用户看再写。
- [ ] **步骤 4：模型只留在网关数据库里**
  - `config/models.yaml` 改成只有 `model_list: []`、`litellm_settings`、`general_settings`。
  - 开头注释写：模型全部在网关数据库里，首次启动时由后端按 `config/seed/models.yaml` 导入，在模型页增删改。
- [ ] **步骤 5：重建并启动**
  - 运行：`make infra-up`、`make build`。
  - 预期：后端日志里有"写入默认内容""导入模型"各一次；`.workdata/.seeded` 含 `files` 与 `models`。
- [ ] **步骤 6：核对没有丢东西（设计 2 的反目标）**
  - `curl -s http://127.0.0.1:8000/api/models`：4 个模型，价格与任务 12 的表相同，都能改能删。
  - 会话数、知识库条目数与步骤 2 记下的一致；技能数一致（迁移前的 excel 来自 `agents/skills/`，迁移后来自 `.workdata/skills/`）。
  - MCP 页 `files` 已连接；技能页有 `excel`。
  - `/api/settings/app` 各项来源正确；`/api/settings/files` 四项都是 `ok`。
  - `make backup` 成功，产物在 `.workdata/backups/`；`make restore` 不带名字时列出备份。
- [ ] **步骤 7：文档**
  - 使用指南、README：`.workdata`；设置页；改 `.env` 后 `make restart`；没有局域网访问与令牌；MCP 页没有目录。
  - 架构规范：配置来源两处、首次写入、两步启动。
  - changelog 加"第一轮优化·第二批：配置与数据目录（2026-10-19，D22、D23）"。
  - 需求池：
    - R35 更新为"第二批完成"；
    - R34 里"用正式 yaml 的测试会读到本机 workdata/config/app.yaml""编辑自带 MCP 服务时整份表单写成覆盖"两条划掉，注明 D22 后不存在。
- [ ] **步骤 8：第二批检查**
  - 运行：`make check`、`make test-int`、`make e2e`。
  - 用内置浏览器在 8000 上，深色、浅色各看一遍：设置页、MCP 页（没有目录、写明规则只在"每次先问"起作用）、模型页（没有"自带"）、技能页（excel 可删）、对话页工具条。
  - 不发真实对话，不点"测试"。

---

## 第三批：用量（设计 4.11）

### 任务 15：用量只算输入与输出，后台不算费用

**文件：**
- 新建：`backend/migrations/versions/0012_drop_usage_cost.py`。
- 修改：
  - 智能体：`agents/main_agent/runtime/{events.py,tracker.py,agent.py}`、`agents/main_agent/usage/{schemas.py,repo.py}`、`agents/main_agent/models/embedding.py`、`agents/main_agent/bootstrap.py`；
  - 前端：`src/features/usage/{UsagePage.tsx,summary.ts}`、`src/components/chat/parts.tsx`、`src/features/chat/reducer.ts`，以及各自的测试和 `e2e/usage-tokens.spec.ts`。
- 测试：`agents/tests/{test_tracker.py,test_usage_repo.py,test_embedding.py}`、`backend/tests/{test_usage_api.py,test_migrations.py}`。

**接口：**
- 产出：
  - 去掉 `cost` 的：`UsageReported`、`UsageTotals`（及 `add`）、`InterruptedUsage`、`UsageRecord`、`ModelUsage`、`UsageBucket`、`EmbeddingUsage`。
  - 删 `UsageSummary.unpriced_models`。
  - `UsageBucket` 只留 `calls`、`input_tokens`、`output_tokens`。`llm_usage` 仍记缓存读写两列（调用明细），汇总与界面不再给出。
  - `RunTracker(calibration=None)`：去掉 `model_info`；`Calibration` 只留 `token_ratio`；不再读 `response_cost`。
  - 嵌入调用不再读 `x-litellm-response-cost` 响应头。

- [ ] **步骤 1：写失败的测试**
  - `test_usage_has_no_cost`：`UsageReported`、`UsageTotals`、`InterruptedUsage` 的字段里没有 `cost`。
  - `test_tracker_ignores_gateway_cost`：带 `response_cost` 的回复记下的用量没有费用，输入、输出与 `usage_metadata` 一致。
  - `test_interrupted_estimate_has_tokens_only`：中断估算只有输入、输出两个数。
  - `test_summary_reports_input_and_output_only`（集成）：`GET /usage/summary` 的 `total` 只有 `calls`、`input_tokens`、`output_tokens`；没有 `unpriced_models`。
  - `test_usage_cost_column_dropped`（迁移）：`llm_usage` 没有 `cost` 列；旧行的其他列不变。
  - `summary.test.ts`：补零的日子只有三个数。
  - e2e `usage-tokens.spec.ts`：用量页与每轮页脚都没有"缓存"与"$"。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests -q`、`make test-int`、`cd frontend && pnpm test src/features/usage`。
  - 预期：新用例失败。

- [ ] **步骤 3：实现**
  - 迁移 0012：`ALTER TABLE llm_usage DROP COLUMN cost`。降级加回可空的列（旧值不恢复，要旧值用任务 7 的快照）。
  - `runs.usage` 里旧的 `cost` 键解析时忽略。
  - 界面：
    - 用量页的合计写"输入 X · 输出 Y"，表格删缓存两列；
    - 趋势图按输入加输出。

- [ ] **步骤 4：确认测试通过**
  - 运行：`make types`、`make check`、`make test-int`、`make e2e`。
  - 预期：全部通过。

---

### 任务 16：第三批检查与收尾

**文件：** `docs/usage.md`（用量一节）、设计文档 7.7 与 12.1（标出口径变化）、`docs/changelog.md`、`docs/requirements/backlog.md`、记忆 `round1-decisions.md`。

- [ ] **步骤 1：文档**
  - 使用指南写清"输入（实际发给模型的全部输入，含命中缓存的部分）、输出"；后台调用按调用方分开、计入会话累计；价格只是模型资料。
  - changelog 加"第一轮优化·第三批：用量（2026-10-19）"。
  - 需求池：
    - R35 → 完成；
    - R24"端到端里的费用"、R26"前端测试数据还带旧的 cost / max_cost 字段"划掉。
  - 记忆 `round1-decisions.md` 末尾补一句"2026-10-19 三批已完成"。
- [ ] **步骤 2：第三批检查**
  - 运行：`make check`、`make test-int`、`make e2e`、`make build`。
  - 在 8000 上看用量页、每轮页脚、工具条里的会话用量（深色、浅色各一遍）。
- [ ] **步骤 3：交给整体审查**：按 executing-plans 的"最终审查"做，把本计划"重点检查"一节原文交给审查者。
