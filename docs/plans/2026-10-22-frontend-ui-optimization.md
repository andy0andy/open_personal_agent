# 前端界面优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已审定的设计稿统一界面风格、修正浅色可读性、给对话流降噪并补齐状态与下一步操作。

**Architecture:** 配色与共用组件先改（主题令牌 → 共用组件 → 侧栏），各页面跟着变；对话区的新行为尽量放进可单测的纯函数（`components/chat/tools.ts`、`features/chat/*.ts`），组件只负责显示；只有会话状态点需要后端在会话列表里多带一个字段。

**Tech Stack:** React 19 + Vite + Tailwind 4 + assistant-ui 0.15.28（`MessagePrimitive.GroupedParts`）+ TanStack Query；后端 FastAPI + psycopg；测试 vitest（node 环境，`renderToStaticMarkup`）、pytest（集成）、Playwright。

**Spec:** `docs/specs/2026-10-22-frontend-ui-optimization-design.md`（依据 `docs/reviews/2026-10-20-前端界面与HermesAgent对比.md` 与设计稿）

## Global Constraints

- 技术栈与依赖不变：不新增任何依赖；assistant-ui 只在 `components/chat/` 使用。
- 具体颜色只能写在 `frontend/src/themes/` 与 `frontend/src/styles/`（`no-raw-colors.test.ts`）；组件只用语义样式类。
- 配色取值（设计 2.1）：深色 琥珀 `#ffbd38` / 成功 `#4ade80` / 危险 `#ff5a5f` / 运行中 `#6aa7f0` / 次要文字 62% / 淡底 10%；浅色 琥珀 `#b45309` / 成功 `#1f7a4d` / 危险 `#b42318` / 运行中 `#1d5fa8` / 次要文字 76% / 淡底 7%；输入框边框 35%；焦点框 45%；浅色代码高亮混色 70%。
- 字号：页标题 17/600，区块标题 13/500 次要色，正文 15，次要 13，徽章与页脚 12，最小 11；不用全大写；等宽只给数据。
- 圆角：卡片 `rounded-xl`（12px）、按钮与输入框 `rounded-lg`（8px）、徽章 `rounded-md`（6px）、点与胶囊 `rounded-full`。
- 宽度：阅读类 `max-w-[45rem]`（720px），管理类 `max-w-[55rem]`（880px）。
- 无障碍：可点的都是 `<button>` / `<a>`；只有图标的按钮带 `aria-label`；`:focus-visible` 可见；`prefers-reduced-motion` 时动画与过渡几乎为零。
- 端到端测试依赖的名称保留：新建会话、会话列表、收起 / 展开会话列表、给智能体发消息…、同意、修改后执行、确定，按新参数执行、修改后的参数（实际执行的）、已同意、停止、已停止、会话的模型、对话模型、默认对话模型、我的 MCP 服务、已登记模型、查看工具、复制完整的会话 ID、调用次数、MCP 服务清单。改了的名称在同一任务里同步改测试。
- 项目没有 git：每个任务结束写台账（`.superpowers/sdd/2026-10-22-frontend-ui-optimization/progress.md`），不执行 git 命令；不读 `.env`；端到端只用测试库与假模型。
- 前端单测命令：`cd frontend && PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm exec vitest run <文件>`（下文简写为 `WEB vitest <文件>`）。

## Review Focus

1. 一次审批里有多个操作，部分同意、部分拒绝：每个工具行显示自己的决定，卡片要等全部选完才提交（任务 7 的 `adapter.test.ts`）。
2. 很长的命令、路径、会话标题（几百字、无空格）：工具行、会话列表、顶栏都截断，不撑破页面（任务 6 的渲染测试断言 `truncate`/`min-w-0`；任务 14 在 1024 宽看样式）。
3. 旧会话的历史：思考没有时间差、执行输出没有退出码那一行、会话没有 `activity`：显示降级、不报错（任务 4、6、8 的测试）。
4. 浏览器不让用本地存储（隐私模式）：草稿不保存，但输入照常（任务 10 的 `drafts.test.ts`）。
5. 落地页发送时建会话成功但发消息失败：不丢用户写的字，打开已建的会话并显示失败原因（任务 11 的 `newChat.test.ts`）。

---

### Task 1: 配色令牌按模式设定

**Files:**
- Modify: `frontend/src/themes/types.ts`、`frontend/src/themes/default.ts`、`frontend/src/themes/apply.ts`、`frontend/src/styles/tokens.css`、`frontend/src/themes/themes.test.ts`
- Create: `frontend/src/themes/contrast.test.ts`
- Modify（去掉吃掉焦点框的 `outline-none`，按需）：`frontend/src/**/*.tsx`

**Interfaces:**
- Produces: `ModeColors = { background; primary; danger; success; warning; info; mutedRatio: string; softRatio: string }`（`ThemeDefinition.status` 去掉）；CSS 变量 `--theme-info`、`--theme-muted-ratio`、`--theme-soft-ratio`；Tailwind 语义色 `info`、`input`、`warning-soft`、`success-soft`、`danger-soft`、`info-soft`（即 `bg-info`、`border-input`、`bg-warning-soft` 等）。

- [ ] **Step 1: 写失败的测试** `contrast.test.ts`：对每个主题的深浅两版断言 `contrast(status, background) >= 4.5`（warning/success/danger/info）、`contrast(mix(primary, background, mutedRatio), background) >= 4.5`、在卡片色（正文 4%）上同样 ≥ 4.5；`contrast`、`mix` 写在测试文件里。`themes.test.ts` 改为：深浅两版都提供合法颜色；`tokens.css` 的 `:root` 与 `:root[data-mode="light"]` 分别等于 `themeVariables(theme, "dark" | "light")` 里随模式变化的变量。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/themes` → FAIL（浅色琥珀 1.56 等）。
- [ ] **Step 3: 实现**：类型与默认主题按设计 2.1 的值；`themeVariables` 输出新变量；`tokens.css` 补首屏默认值、`--color-muted-foreground` 用 `var(--theme-muted-ratio)`、新增 `--color-input`（35%）`--color-info` 与四个 `-soft`（`var(--theme-soft-ratio)`），浅色 `--syntax-strength: 70%`；`@layer base` 加 `:focus-visible { outline: 2px solid var(--color-ring); outline-offset: 2px }` 与 `prefers-reduced-motion` 规则。审一遍 `outline-none`：外层用 `focus-within` 显示聚焦的（输入框、编辑框）保留，其余去掉。
- [ ] **Step 4: 运行确认通过** `WEB vitest src/themes src/styles` → PASS；`make check` → 通过。
- [ ] **Step 5: 记台账**

### Task 2: 共用组件与侧栏

**Files:**
- Modify: `frontend/src/components/ui/{Button,Tag,Switch,Panel,PageHeader,Field}.tsx`、`frontend/src/layout/Sidebar.tsx`、`frontend/src/components/ui/ui.test.tsx`
- Create: `frontend/src/components/ui/StatusDot.tsx`
- Modify（按钮名去掉"+ / ↑"符号，改成图标 + 文字）：`features/models/ModelsPage.tsx`、`features/mcp/McpPage.tsx`、`features/skills/SkillsPage.tsx`、`frontend/e2e/{models,mcp,skills}.spec.ts`

**Interfaces:**
- Produces: `Button` 变体名不变（`outline` = 次按钮、`primary`、`danger` = 危险色文字、`ghost` = 文字按钮），样式改为 8px 圆角、句子写法、13px；`Tag` 增加 `tone="solid"`（正文色实心）与 `"info"`，其余为淡底；`StatusDot({ tone: "warning" | "info" | "danger" | "success" | "idle"; pulse?: boolean; label?: string })`（有 `label` 时 `role="img"` + `aria-label`）；`PageHeader({ title, subtitle?, actions? })` 高 60px，副标题在标题下一行；`Panel` 标题 13/500 次要色、12px 圆角；侧栏显示组名、窄于 1280px 只显示图标。

- [ ] **Step 1: 写失败的测试**（`ui.test.tsx`）：`Button` 的 class 不含 `uppercase` 且含 `rounded-lg`；`Switch` 含 `rounded-full`；`StatusDot` 带 `label` 时输出 `role="img"` 与 `aria-label`，`pulse` 时有呼吸动画类；`PageHeader` 输出 `<h1>` 与下一行副标题；`Panel` 标题不含 `uppercase`。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/components/ui` → FAIL。
- [ ] **Step 3: 实现** 各组件与侧栏（当前项强调底 + `font-medium`，不再用左边框；组名 12px 次要色；`xl` 以下 `w-14`、文字隐藏、`title` 显示名字）。三个页面的按钮改成图标 + "新增模型" / "手动添加" / "上传技能"，同步改端到端测试里的按钮名。
- [ ] **Step 4: 运行确认通过** `WEB vitest src/components/ui` → PASS；`make check`；`make e2e` → 全部通过。
- [ ] **Step 5: 记台账**

### Task 3: 后端——会话列表带运行状态

**Files:**
- Modify: `backend/threads/schemas.py`、`backend/threads/repo.py`、`frontend/src/api/generated/*`（`make types`）
- Test: `backend/tests/test_repos.py`

**Interfaces:**
- Produces: `ThreadActivity = Literal["running", "waiting", "failed"]`；`Thread.activity: ThreadActivity | None = None`；`ThreadRepo.list_active()` 用 `LEFT JOIN LATERAL` 取每个会话最近一次运行（`ORDER BY created_at DESC LIMIT 1`）：`queued`/`running` → `running`，`interrupted` → `waiting`，`failed` → `failed`，其余 `None`。其他接口返回 `None`。

- [ ] **Step 1: 写失败的测试** `test_list_active_reports_latest_run_activity`：四个会话，最近一次运行分别为 running、interrupted、failed、completed（另一个会话先 failed 后 completed），断言 `activity` 依次为 `running`、`waiting`、`failed`、`None`、`None`；没有运行的会话为 `None`。
- [ ] **Step 2: 运行确认失败** `make test-up && uv run pytest -m integration backend/tests/test_repos.py -k activity` → FAIL（没有 activity 字段）。
- [ ] **Step 3: 实现** 模型字段与查询。
- [ ] **Step 4: 运行确认通过** 同上 → PASS；`make types`；`make check`；`make test-int` → 全部通过。
- [ ] **Step 5: 记台账**

### Task 4: 会话列表——状态点、相对时间、标题过滤

**Files:**
- Create: `frontend/src/features/threads/activity.ts`、`activity.test.ts`
- Modify: `frontend/src/features/threads/ThreadList.tsx`、`frontend/src/api/queries.ts`、`frontend/src/api/queries.test.ts`

**Interfaces:**
- Consumes: `Thread.activity`（任务 3）、`StatusDot`（任务 2）
- Produces: `threadActivity(thread: Pick<Thread, "activity">): { tone: "info" | "warning" | "danger"; label: "运行中" | "待审批" | "出错"; pulse: boolean } | null`；`relativeTime(iso: string, now: Date): string`（今天 `HH:MM`、昨天"昨天"、今年 `M月D日`、更早 `YYYY/M/D`）；`filterThreads<T extends { title: string }>(threads: T[], query: string): T[]`（去掉首尾空白、不分大小写的包含匹配）；`hasActiveThread(threads?: Thread[]): boolean`。

- [ ] **Step 1: 写失败的测试** `activity.test.ts`：三种状态的映射、`activity` 缺失或为 `null` 时为 `null`；`relativeTime` 用固定的 `now` 覆盖今天、昨天、今年、往年；`filterThreads` 空查询原样返回、大小写不敏感。`queries.test.ts`：`threadsQuery.refetchInterval` 在数据里有 running / waiting 会话时为 5000，没有时为 `false`（加载失败时仍按原重试规则）。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/features/threads src/api` → FAIL。
- [ ] **Step 3: 实现**：列表每行 = 状态点 + 标题（`min-w-0 truncate`）+ 右侧状态字或相对时间；顶部"搜索会话标题"输入框（`aria-label` 同名）；有搜索词时关闭拖动排序（过滤后的顺序不能写回）。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 5: 对话页顶栏、宽度与上下文占比

**Files:**
- Create: `frontend/src/features/chat/context.ts`、`context.test.ts`
- Modify: `frontend/src/features/chat/ChatView.tsx`、`ComposerToolbar.tsx`、`frontend/src/features/usage/ThreadUsageBadge.tsx`、`frontend/src/components/chat/ChatThread.tsx`

**Interfaces:**
- Produces: `lastMainInputTokens(state: ChatState): number | null`（最后一条 `caller === "main"` 的用量）；`contextLabel(inputTokens: number | null, maxInputTokens: number | null): string | null`（`"上下文 2%"`，0 < 比例 < 1% 时 `"上下文 <1%"`，任一为空时 `null`）；`ThreadUsageBadge({ threadId, context? })`；`ComposerToolbar` 去掉 `filesOpen`、`onToggleFiles`，增加 `context: string | null`。

- [ ] **Step 1: 写失败的测试** `context.test.ts`：`lastMainInputTokens` 跳过子智能体与后台调用、没有时为 `null`；`contextLabel(21500, 1000000) === "上下文 2%"`、`contextLabel(300, 1000000) === "上下文 <1%"`、`contextLabel(null, 1000) === null`、`contextLabel(10, null) === null`。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/features/chat/context.test.ts` → FAIL。
- [ ] **Step 3: 实现**：顶栏 = 标题（17/600、`truncate`）+ 下一行"N 轮"（N = 用户消息数）+ 右侧"文件"按钮（`aria-pressed`）与"更多"菜单（改名、删除，复用 `ThreadMenu` 与 `DeleteThreadDialog`）；对话列与输入框宽 `max-w-[45rem]`；工具条去掉"文件"、显示上下文占比（模型最大输入取 `modelsQuery`）。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 6: 工具行——中文名、合组摘要、执行命令详情

**Files:**
- Create: `frontend/src/components/chat/tools.ts`、`tools.test.ts`、`frontend/src/components/chat/toolLine.test.tsx`
- Modify: `frontend/src/components/chat/parts.tsx`、`frontend/e2e/chat.spec.ts`

**Interfaces:**
- Produces: `toolLabel(name: string, args: Record<string, unknown>): { verb: string; detail: string; kind: ToolKind }`，`ToolKind = "read" | "find" | "write" | "execute" | "knowledge" | "memory" | "todos" | "external" | "other"`（execute→执行命令·`command`；read_file→读取文件；write_file→写入文件；edit_file→修改文件；ls→列出目录；glob→查找文件；grep→搜索文件内容；write_todos→更新待办；search_knowledge→检索知识库·`query`；read_document→读取文档；remember→记住·`content`；其余匹配 `^([a-z0-9-]+)_(.+)$` 的 → 外部工具·`服务 · 工具`；再其余 → 原名）；`summarizeTools(names: string[]): string`（按首次出现的顺序：读取了 N 个文件、查找了 N 次、改动了 N 个文件、运行了 N 条命令、检索了 N 次知识库、记下了 N 条记忆、更新了待办、调用了 N 次外部工具、调用了 N 个工具，用"，"连接）；`parseExecuteOutput(output: string): { text: string; exitCode: number | null }`（去掉末尾 `[Command succeeded|failed with exit code N]`）。

- [ ] **Step 1: 写失败的测试** `tools.test.ts`：每个映射；MCP 名 `files_write_file` → `{ verb: "外部工具", detail: "files · write_file" }`；`summarizeTools(["read_file","execute","read_file"]) === "读取了 2 个文件，运行了 1 条命令"`；`parseExecuteOutput("ok\n[Command succeeded with exit code 0]")` → `{ text: "ok", exitCode: 0 }`、`failed with exit code 2` → 2、没有那一行 → `exitCode: null` 原文不变。`toolLine.test.tsx`：工具行的摘要元素带 `truncate` 与 `min-w-0`。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/components/chat/tools.test.ts src/components/chat/toolLine.test.tsx` → FAIL。
- [ ] **Step 3: 实现**：`ToolCard` 改为工具行（`details`/`summary`：箭头、图标、动词、摘要、用时或状态；成功不显示"完成"字样，失败危险色、运行中旋转图标、等待审批琥珀）；执行命令展开为 `$ 命令` + 退出码徽标 + 输出；`AssistantMessage` 改用 `MessagePrimitive.GroupedParts` + `groupPartByType({ "tool-call": ["group-tools"], "tool-call:subagent": [] })`，组内 ≥ 2 个时一行 `summarizeTools` 摘要（有运行中的再接"· 正在<动词>…"），点开逐条显示；只有 1 个时直接显示那一行。端到端"工具卡片"改为断言看到"列出目录"。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 7: 审批——卡片改版，处理完并入工具行

**Files:**
- Modify: `frontend/src/components/chat/adapter.ts`、`adapter.test.ts`、`approval.tsx`、`parts.tsx`、`frontend/src/features/chat/approvals.ts`、`approvals.test.ts`、`frontend/e2e/approval.spec.ts`
- Create: `frontend/src/components/chat/approval.test.tsx`

**Interfaces:**
- Consumes: `toolLabel`（任务 6）、`choiceLabel`（已有）
- Produces: `ToolArtifact = { waiting?: boolean; decision?: { label: string; tone: "success" | "danger" | "muted"; editedArgs?: Record<string, unknown> } }`；`approvalTitle(action: ApprovalAction): string`（执行命令 → "要执行这条命令吗？"；其他 → `要调用${verb}${detail ? ` ${detail}` : ""}吗？`）。

- [ ] **Step 1: 写失败的测试** `adapter.test.ts`：等你决定的审批照旧输出 `data-approval`，且它的工具调用不再单独输出；已处理（resolved）的审批不输出 `data-approval`，两个操作分别同意、拒绝时，两个工具片段的 `artifact.decision` 分别是"已同意"(success) 与"已拒绝"(danger)；"修改后执行"带 `editedArgs`；等待中被停止（stopped）的标"已停止，未执行"(muted)。`approvals.test.ts`：`approvalTitle`。`approval.test.tsx`（渲染）：按钮顺序"拒绝、回复一句话、修改后执行、同意"，按键提示带 `aria-hidden="true"`，主按钮文字是"同意"。
- [ ] **Step 2: 运行确认失败** `WEB vitest src/components/chat src/features/chat/approvals.test.ts` → FAIL。
- [ ] **Step 3: 实现**：转换层按 `call_id` 合并；审批卡片按设计第 3 节第 6 条（琥珀淡底整圈边框、标题、等宽命令块、执行命令说明一句、按钮右对齐、出现时聚焦"同意"、焦点在卡片里时 Esc 拒绝）；工具行显示 `decision`，`editedArgs` 时展开显示"修改后的参数（实际执行的）"。端到端：把"需要你确认"改为新标题。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`；`make e2e` → 全部通过。
- [ ] **Step 5: 记台账**

### Task 8: 思考用时、用户消息、代码块

**Files:**
- Modify: `frontend/src/features/chat/reducer.ts`、`reducer.test.ts`、`frontend/src/components/chat/adapter.ts`、`adapter.test.ts`、`parts.tsx`、`code.tsx`、`code.test.tsx`
- Create: `frontend/src/components/chat/messageContext.ts`

**Interfaces:**
- Produces: 思考项增加 `startedAt?: string; endedAt?: string`（取事件 `ts`：第一段思考的时间、思考之后第一个别的事件的时间）；转换层输出 `data-thinking` 片段 `{ text; seconds: number | null; running: boolean }`（替代 `reasoning`）；`MessageRunningContext`（`createContext(false)`，`AssistantMessage` 提供）；`CODE_COLLAPSE_LINES = 16`。

- [ ] **Step 1: 写失败的测试** `reducer.test.ts`：两段思考增量后来一个工具事件，思考项的 `startedAt`/`endedAt` 分别是第一段与工具事件的 `ts`。`adapter.test.ts`：`seconds = round((ended - started) / 1000)`，缺一端为 `null`。`code.test.tsx`：20 行代码输出"展开全部 20 行"，16 行不输出；`MessageRunningContext` 为真时不着色（输出里没有 `hljs-` 类）。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**：思考行"思考了 N 秒" / 运行中"思考中…" / 无时长"思考过程"；用户消息改为强调底 + 分隔线边框 + 正文色（去掉反色选中）；代码块超过 16 行折叠（按行高限高 + "展开全部 N 行"/"收起"），运行中不着色。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 9: 待办挪到输入框上方，报错卡片加按钮

**Files:**
- Create: `frontend/src/features/chat/todos.ts`、`todos.test.ts`、`frontend/src/features/chat/retry.ts`、`retry.test.ts`、`frontend/src/components/chat/TodoBar.tsx`、`frontend/src/components/chat/retryActions.ts`
- Modify: `frontend/src/components/chat/parts.tsx`、`ChatThread.tsx`、`frontend/src/features/chat/ChatView.tsx`

**Interfaces:**
- Produces: `todoProgress(todos: TodoItem[]): { done: number; total: number; current: string | null }`；`latestTodos(state: ChatState): TodoItem[] | null`（最后一条用户消息之后最新的待办）；`lastUserText(state: ChatState): string | null`；`isQuotaError(text: string): boolean`（以"模型额度用完了"开头）；`RetryActionsContext`：`{ retry(): void; retryWith(model: string): void; models: string[] }`。

- [ ] **Step 1: 写失败的测试** `todos.test.ts`（进度、当前项、上一轮的待办不算）、`retry.test.ts`（`lastUserText`、`isQuotaError`）。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**：运行中且有待办时输入框上方一条"进度 2/4 · 正在：…"（可展开）；对话流里的待办改成"待办 2/4"一行可展开，运行已结束时进行中的项显示"未完成"；报错卡片按设计第 3 节第 8 条（额度用完不给"重试这一句"；"换个模型再试"是列出其他对话模型的菜单）。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 10: 输入框——草稿按会话保存、粘贴截图

**Files:**
- Create: `frontend/src/features/chat/drafts.ts`、`drafts.test.ts`
- Modify: `frontend/src/features/chat/uploads.ts`、`uploads.test.ts`、`frontend/src/components/chat/ChatThread.tsx`、`frontend/src/features/chat/ChatView.tsx`、`frontend/e2e/chat.spec.ts`

**Interfaces:**
- Produces: `loadDraft(threadId: string): string`、`saveDraft(threadId: string, text: string): void`（空文本即删除）、`clearDraft(threadId: string): void`，键 `opa.draft.<会话 ID>`，读写失败一律忽略；`pastedFiles(data: Pick<DataTransfer, "files">): File[]`。

- [ ] **Step 1: 写失败的测试** `drafts.test.ts`：存取、空文本删除、本地存储抛错时不抛出且读回空串；`uploads.test.ts`：`pastedFiles` 只取文件、没有文件时为空数组。端到端：在会话 A 输入不发送，切到新会话再切回来，输入框里还是原文。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**：会话打开时（输入框为空才）填回草稿；输入变化 400ms 后保存；发送成功后清掉；输入框 `onPaste` 有文件时阻止默认粘贴、交给上传。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 11: 新会话落地页

**Files:**
- Create: `frontend/src/features/chat/newChat.ts`、`newChat.test.ts`、`frontend/src/features/chat/NewChat.tsx`
- Modify: `frontend/src/features/chat/ChatPage.tsx`、`frontend/e2e/navigation.spec.ts`

**Interfaces:**
- Consumes: `api.createThread`、`api.updateThread`、`api.startRun`、`threadActivity`（任务 4）
- Produces: `startNewChat(input: { text: string; model: string; permission: PermissionMode }, deps: { createThread; updateThread; startRun }): Promise<{ threadId: string; error: string | null }>`（建会话 → 模型或权限与新会话不同时才改 → 发消息；发消息失败时返回已建会话的 ID 与原因）。

- [ ] **Step 1: 写失败的测试** `newChat.test.ts`：调用顺序；模型与权限都是默认时不调 `updateThread`；`startRun` 失败时返回 `{ threadId, error }`。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现** 落地页（设计第 3 节第 11 条）；发消息失败时打开已建的会话并在输入框上方显示原因、文字填回草稿。端到端：空状态文字改为"今天想做点什么？"；新增"落地页直接发消息会建会话并打开"。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`；`make e2e`。
- [ ] **Step 5: 记台账**

### Task 12: 管理页（一）——设置、技能、知识库

**Files:**
- Modify: `frontend/src/features/settings/SettingsPage.tsx`、`settings.ts`、`settings.test.ts`、`frontend/src/features/skills/SkillsPage.tsx`、`frontend/src/features/knowledge/KnowledgePage.tsx`

**Interfaces:**
- Produces: `pendingRestartCount(views: SettingView[]): number`；`sectionPending(views: SettingView[]): boolean`。

- [ ] **Step 1: 写失败的测试** `settings.test.ts`：两个函数。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**：设置页按设计第 4 节（分节导航、页顶提示条与复制、每节说一次生效时机、行内"已改 · 待重启"徽章且保留"已保存，重启后生效"与"已改"文字、环境变量锁形说明、只读原因）；技能说明 `line-clamp-2`；知识库用 `PageHeader` 与阅读宽度。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`。
- [ ] **Step 5: 记台账**

### Task 13: 管理页（二）——模型、MCP、用量

**Files:**
- Modify: `frontend/src/features/models/ModelsPage.tsx`、`frontend/src/features/mcp/McpPage.tsx`、`mcp.ts`、`mcp.test.ts`、`frontend/src/features/usage/UsagePage.tsx`、`summary.ts`、`summary.test.ts`

**Interfaces:**
- Produces: `serverStatus(server: McpServerView): { tone: "success" | "info" | "danger" | "idle"; text: string; pulse: boolean }`（已连接 · N 个工具 / 连接中… / 没有连上 / 已停用）；`chartScale(values: number[]): { max: number; ticks: number[] }`（`max` 取 1、2、5 × 10ⁿ 中不小于最大值的最小者，`ticks = [max, max*2/3, max/3, 0]`，全为 0 时 `max = 1`）。

- [ ] **Step 1: 写失败的测试** `mcp.test.ts`（四种状态文字与色调，保留"缺少环境变量：XXX"原因文字）、`summary.test.ts`（`chartScale([0,0]).max === 1`、`chartScale([434000]).max === 500000`、刻度四个）。
- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**：模型页"默认"实心徽章、能力标签中性带图标、测试结果显示在行下、默认模型删除按钮变淡并说明原因、页底提示；MCP 每行状态点 + 文字、连接方式中性标签、原因与测试结果在行下；用量图按设计第 4 节（每天一根、两色叠放、刻度与网格、首中尾日期、悬停或聚焦浮层、数字列右对齐等宽）。
- [ ] **Step 4: 运行确认通过** → PASS；`make check`；`make e2e`。
- [ ] **Step 5: 记台账**

### Task 14: 收尾——文档、全量检查、上线、看样式

**Files:**
- Modify: `docs/usage.md`、`docs/changelog.md`、`docs/requirements/backlog.md`、`docs/development/architecture.md`（对话区的新文件与职责）

- [ ] **Step 1**：文档同步（使用指南：会话状态点、审批快捷键、草稿、粘贴截图、落地页、重试；变更记录一节；需求池登记本轮并标完成）。
- [ ] **Step 2**：`make check`、`make test-int`、`make e2e` → 全部通过。
- [ ] **Step 3**：`make build`（前端打进镜像、后端加载新代码）→ 8000 健康。
- [ ] **Step 4**：用 Playwright 只读截图（1440 深浅、1024 深色），对照设计稿检查；不点会改数据的按钮、不发消息、不动"询问助手功能介绍"会话。
- [ ] **Step 5**：记台账，派整体审查。
