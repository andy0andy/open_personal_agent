# 前端管理页面（纯界面）实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md` 与设计文档。
>
> 本计划只写定下来的决定：文件、名称与签名、取值、每个任务用哪些测试证明。函数体由执行者按签名与测试写出。

**目标：** 按设计文档补上新的侧栏、每页一个地址、对话页的会话栏，以及模型、技能、MCP 三页的**纯界面**：用示例数据，能点能看，不连后端。

**本轮范围**（2026-10-18 与用户确认）：
- 交付方式 A：三个新页面用示例数据，操作只改页面里的临时状态，刷新后恢复。每页顶部显示示例提示条；8000 上照常显示（用户选定）。
- 真功能：路由、侧栏、对话页的会话栏，用的都是真实会话数据。
- 不做：
  - 系统页、日志页、配置页（侧栏不放入口）；
  - 在对话里添加技能（要改智能体与事件流，不是纯界面）；
  - 技能编辑与从技能库导入、MCP 目录的分类按钮、侧栏底部的状态块。
- 价格：模型清单显示价格；每个模型都必须有价格，或者标为免费；任何统计都不用价格，用量页不变（用户决定，2026-10-18）。
- 与设计文档的一处偏离：上传 .zip 的技能，设计要求先识别出名称、描述、文件数。纯界面阶段不新增解压库，预览里只提示"接上后端后识别"；文件夹和单个 SKILL.md 照常识别。
- 知识库、用量、设置三页内容不变，只随侧栏与地址变化。

**架构：**
- **路由**：react-router 7.18.4，声明式写法（`BrowserRouter` + `Routes`）。路径集中写在 `src/layout/routes.ts`。后端已经对未知路径返回首页（`backend/frontend.py`），Vite 开发服务器也一样，所以后端不改。
- **布局**：`AppShell` 由侧栏 `Sidebar` 和 `Routes` 组成。对话页 `ChatPage` 由会话栏（`ThreadList`）和对话区（`ChatView`，不改）组成。
- **共用界面组件**：放在 `src/components/ui/`，照 shadcn 的写法手写，只用语义样式类。
- **示例数据**：每个新页面目录里放三样东西：
  - `sample.ts`：类型与初始数据；
  - 纯函数模块：显示格式、表单校验、列表操作的 reducer；
  - 页面组件：用 `useReducer` 持有临时状态。

  以后接后端时，换掉 `sample.ts` 和 reducer 的数据来源即可，页面组件不变。
- **示例数据怎么检查**：
  - 纯函数模块的单元测试进 `make check`；三页的交互放进 `make e2e`；
  - 示例数据只在前端，不进后端，也不进生成的接口类型（`src/api/generated/`）。

**技术栈：** React 19.3、TypeScript 6、Tailwind 4、TanStack Query 5（真实数据）、react-router 7.18.4（新增；8.x 是新的大版本，这次不用）、react-markdown 10.1（技能正文）、Vitest 5、Playwright 1.63。

**设计文档：** `docs/specs/2026-10-18-frontend-admin-ui-design.md`；原型在 `docs/specs/assets/2026-10-18-frontend-admin-ui/`（02 只采用对话页，03～05 对应三个新页面）。

## 全局约束

- 直接依赖写精确版本：`pnpm add -E react-router@7.18.4`；不新增别的依赖。
- 颜色只用 `src/styles/tokens.css` 的令牌，`src/styles/no-raw-colors.test.ts` 必须通过。
- 只有 `src/components/chat/` 能引用 `@assistant-ui/*`（ESLint 规则）。
- 界面文案用中文，标识符用英文，注释只写"为什么"。
- 地址固定为：`/chat`、`/chat/:threadId`、`/knowledge`、`/usage`、`/models`、`/skills`、`/mcp`、`/settings`；`/` 与未知地址都跳到 `/chat`。
- 侧栏分两组，中间留间隔：工作（对话、知识库、用量）、管理（模型、技能、MCP、设置）。选中项用浅色底加左侧竖线。
- 页面骨架：顶部标题栏左边是页面名、右边是搜索或主操作；内容用直角细边框卡片，区块标题用等宽字体、字距稍宽、大写；按钮是描边的大写小按钮，主操作用实心奶油色（`bg-primary`）；长文用中文无衬线体。
- 示例提示条的固定文案：`预览：这一页用的是示例数据，操作只在本页临时生效，刷新后恢复，不会改动真实配置`。
- 删除模型、删除技能都要先弹确认框。
- 价格显示为 `$<输入> / $<输出> 每百万`，或者 `免费`；用量页、顶栏用量都不变。
- 后端代码不改。

## 重点检查（没有现成测试覆盖、最容易让使用者踩坑的五类情况）

1. **直接打开或刷新深一层的地址**（如 `/skills`、`/chat/<会话 ID>`）：要回到原来那一页，8000 和 5173 都一样。→ 任务 1 和各页面任务的第一个端到端用例里都刷新一次。
2. **当前会话在别处被删了**（另一个标签页或接口）之后刷新：回到 `/chat` 的空状态，不报错。→ 任务 1 的端到端用例。
3. **抽屉或对话框开着时按 Esc**：关闭；再打开时是空表单，没填完的不会被保存。→ 任务 2 的端到端用例。
4. **表单填了不合法的值**（空、负数、小数、重名）：给中文提示，不保存。→ 任务 2、任务 4 的单元测试。
5. **上传了不支持的文件**（如 .pdf），或者文件夹里没有 SKILL.md：给中文提示，不能安装。→ 任务 3 的单元测试和端到端用例。

---

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `frontend/src/layout/routes.ts` | 路径常量、`chatPath`、侧栏分组 `NAV_GROUPS` | 1（2～4 往分组里加项） |
| `frontend/src/layout/Sidebar.tsx` | 侧栏：品牌字、两组入口、明暗切换 | 1 |
| `frontend/src/layout/AppShell.tsx` | 侧栏 + `Routes`（改写） | 1（2～4 加路由） |
| `frontend/src/App.tsx` | 外面包一层 `BrowserRouter` | 1 |
| `frontend/src/features/chat/ChatPage.tsx` | 对话页：会话栏 + 对话区，读取地址里的会话 ID | 1 |
| `frontend/src/features/threads/ThreadList.tsx` | 顶部改为"会话"、"+ 新建"和收起按钮；外层加 `aria-label` | 1 |
| `frontend/src/components/ui/*.tsx` | 共用组件：Button、PageHeader、Panel、Switch、Tag、Drawer、ConfirmDialog、Tabs、PreviewBanner | 2 |
| `frontend/src/features/models/` | 模型页：`ModelsPage.tsx`、`ModelDrawer.tsx`、`sample.ts`、`models.ts`、`models.test.ts` | 2 |
| `frontend/src/features/skills/` | 技能页：`SkillsPage.tsx`、`SkillDrawer.tsx`、`UploadSkillDialog.tsx`、`sample.ts`、`skills.ts`、`skills.test.ts` | 3 |
| `frontend/src/features/mcp/` | MCP 页：`McpPage.tsx`、`ToolsDrawer.tsx`、`ServerDrawer.tsx`、`InstallDialog.tsx`、`catalog.ts`、`sample.ts`、`mcp.ts`、`mcp.test.ts` | 4 |
| `frontend/e2e/*.spec.ts` | 新增 `navigation`、`models`、`skills`、`mcp`；改 `helpers.ts`、`pages.spec.ts`、`usage-tokens.spec.ts` | 1～4 |

---

### 任务 1：路由、侧栏与对话页的会话栏（真实数据）

**文件：** 新建 `src/layout/routes.ts`、`routes.test.ts`、`src/layout/Sidebar.tsx`、`src/features/chat/ChatPage.tsx`、`e2e/navigation.spec.ts`；修改 `src/App.tsx`、`src/layout/AppShell.tsx`、`src/features/threads/ThreadList.tsx`、`src/features/usage/UsagePage.tsx` 的调用方、`e2e/helpers.ts`、`e2e/pages.spec.ts`、`e2e/usage-tokens.spec.ts`、`package.json` 与 `pnpm-lock.yaml`。

**接口：**
- 产出：
  - `PATHS = { chat: "/chat", knowledge: "/knowledge", usage: "/usage", models: "/models", skills: "/skills", mcp: "/mcp", settings: "/settings" } as const`；
  - `chatPath(threadId?: string | null): string`；
  - `NAV_GROUPS: { title: "工作" | "管理"; items: { label: string; path: string; icon: LucideIcon }[] }[]`；
  - `ThreadList({ selectedId, onSelect, onCollapse? })`。

- [ ] **步骤 1：写失败的测试**
  - `routes.test.ts`：
    - `chatPath()` 与 `chatPath(null)` 都等于 `"/chat"`，`chatPath("abc")` 等于 `"/chat/abc"`；
    - `NAV_GROUPS` 的组名依次为 `["工作", "管理"]`；
    - 工作组的项是 `["对话", "知识库", "用量"]`，管理组这时只有 `["设置"]`（模型、技能、MCP 由任务 2～4 加入）。
  - `e2e/navigation.spec.ts`：
    - `侧栏各页有自己的地址，刷新后回到原页`：依次点侧栏链接"知识库""用量""设置"，地址分别变成 `/knowledge`、`/usage`、`/settings`；每页 `page.reload()` 后，同名的一级标题仍然可见。
    - `首页与未知地址回到对话页`：打开 `/` 与 `/nope`，地址都变成 `/chat`。
    - `对话页地址带会话 ID，刷新回到同一会话`：新建会话并发"打招呼"，地址形如 `/chat/<uuid>`；刷新后"你好，我是测试助手"仍然可见。
    - `会话被删后回到空状态`：先记下当前会话的地址，用 `page.request.delete("/api/threads/<id>")` 删掉它，再打开这个地址，地址变成 `/chat`，并显示"从会话列表选择会话，或新建一个会话开始对话"。
    - `会话栏可以收起`：点"收起会话列表"后，会话列表看不见、出现"展开会话列表"；刷新后仍是收起的状态。
  - 把旧用例里侧栏的 `getByRole("button", { name: "用量" | "设置" })` 改成 `getByRole("link", …)`。
  - `helpers.ts` 改两处：
    - `newThread` 打开 `/chat`，点 `getByRole("button", { name: "新建会话" })`；
    - `openThread` 在 `getByRole("navigation", { name: "会话列表" })` 里点标题。

- [ ] **步骤 2：确认测试失败**
  - 运行：`cd frontend && pnpm exec vitest run src/layout/routes.test.ts`。预期：失败，找不到模块 `./routes`。
  - 运行：`cd frontend && pnpm exec playwright test e2e/navigation.spec.ts`（用现在打包好的版本）。预期：失败，地址不变、找不到"新建会话"。

- [ ] **步骤 3：实现**
  - `pnpm add -E react-router@7.18.4`。
  - `App.tsx` 外面包一层 `BrowserRouter`。
  - `AppShell` 去掉 `useState` 切页和侧栏里的会话列表，改成：
    - `Sidebar` + `<main>` 里的 `Routes`；
    - `/` 与 `*` 都 `<Navigate to="/chat" replace />`；
    - `/chat` 与 `/chat/:threadId` 渲染 `ChatPage`；
    - 知识库、用量、设置三页原样渲染；
    - 用量页的 `onOpenThread` 改成跳到 `chatPath(id)`。
  - `Sidebar`：
    - 从上到下依次是：品牌字 → 两组入口 → 底部的 `AppearanceToggle`；组名用等宽小字、次要文字色；
    - 入口用 `NavLink`，选中时 `bg-accent text-foreground border-l-2 border-primary`；
    - "对话"在 `/chat` 和 `/chat/*` 下都算选中。
  - `ChatPage`：
    - 用 `useParams` 取 `threadId`。会话列表加载完后，如果找不到这个会话，就 `<Navigate to="/chat" replace />`。
    - 有会话时渲染 `ChatView`，否则显示空状态，文案"从会话列表选择会话，或新建一个会话开始对话"。
    - 会话栏收起与否存在 `localStorage` 的 `opa.threadColumn.collapsed` 里。读写都包在 try/catch 里，读不到时按展开处理。
    - 收起后只剩一条窄栏，里面是"展开会话列表"按钮。
  - `ThreadList`：
    - 外层 `<nav aria-label="会话列表">`；
    - 顶部一行：等宽小字"会话"、按钮"+ 新建"（`aria-label="新建会话"`），以及传了 `onCollapse` 时出现的收起按钮（`aria-label="收起会话列表"`）；
    - 选中会话调用 `onSelect`，由 `ChatPage` 跳到 `chatPath(id)`；
    - 重命名、删除、拖拽排序保持原样。

- [ ] **步骤 4：确认测试通过**
  - 运行：`cd frontend && pnpm exec vitest run src/layout && pnpm build && pnpm exec playwright test`。预期：全部通过，包括原来的 10 个端到端用例。

- [ ] **步骤 5：文档**
  - 架构规范第 5 节的表里补上 `src/layout/routes.ts`、`Sidebar.tsx`、`ChatPage.tsx`，并写一句"每页一个地址，路径集中在 routes.ts"。
  - 使用指南第 3 节"对话与换模型"补上：会话列表在对话页第二栏，可以收起；地址里带会话 ID，可以收藏、刷新。

### 任务 2：共用界面组件与模型页（示例数据）

**文件：**
- 新建 `src/components/ui/Button.tsx`、`PageHeader.tsx`、`Panel.tsx`、`Switch.tsx`、`Tag.tsx`、`Drawer.tsx`、`ConfirmDialog.tsx`、`Tabs.tsx`、`PreviewBanner.tsx`、`ui.test.tsx`；
- 新建 `src/features/models/ModelsPage.tsx`、`ModelDrawer.tsx`、`sample.ts`、`models.ts`、`models.test.ts`、`e2e/models.spec.ts`；
- 修改 `routes.ts`（管理组第一项加"模型" `/models`）、`AppShell.tsx`（加路由）、`routes.test.ts`（管理组的项改为 `["模型", "设置"]`）。

**接口：**
- 产出（共用组件）：

```ts
Button(props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "outline" | "primary" | "danger" | "ghost" })
PageHeader(props: { title: string; subtitle?: ReactNode; actions?: ReactNode })   // 渲染 <h1>{title}</h1>
Panel(props: { title: string; note?: ReactNode; action?: ReactNode; children: ReactNode })
Switch(props: { checked: boolean; onChange: (next: boolean) => void; label: string })  // role="switch" aria-checked aria-label
Tag(props: { children: ReactNode; tone?: "default" | "warning" | "success" | "danger" })
Drawer(props: { title: string; open: boolean; onClose: () => void; footer?: ReactNode; children: ReactNode })  // 右侧；role="dialog" aria-modal aria-label=title；Esc 与点遮罩关闭
ConfirmDialog(props: { title: string; open: boolean; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void; children: ReactNode })  // role="alertdialog"
Tabs(props: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void })  // role="tablist" / "tab" + aria-selected
PreviewBanner()   // 显示 PREVIEW_NOTICE
export const PREVIEW_NOTICE: string  // 全局约束里的固定文案
```

- 产出（模型页，`sample.ts` 与 `models.ts`）：

```ts
type ModelKind = "chat" | "embedding";
type Capability = "thinking" | "vision" | "tools";
type Price = { input: number; output: number } | "free";   // 美元 / 每百万 token
interface PreviewModel { name: string; source: string; vendorId: string; kind: ModelKind;
  contextTokens: number | null; outputTokens: number | null; dimensions: number | null;
  capabilities: Capability[]; price: Price; sessions: number; test: "ok" | { error: string } }
MODEL_SOURCES = ["公司 LiteLLM 网关", "本机 Ollama"] as const
SAMPLE_MODELS: PreviewModel[]
SAMPLE_DEFAULTS = { chat: "claude-opus-4-6", embedding: "embed-qwen3-0.6b" }
formatPrice(price: Price): string
modelMeta(model: PreviewModel): string
interface ModelForm { source: string; vendorId: string; name: string; kind: ModelKind; capabilities: Capability[];
  contextTokens: string; outputTokens: string; dimensions: string; free: boolean; priceInput: string; priceOutput: string }
validateModelForm(form: ModelForm, otherNames: string[]): Partial<Record<keyof ModelForm, string>>
type ModelsState = { models: PreviewModel[]; defaults: { chat: string; embedding: string } }
type ModelsAction = { type: "add"; model: PreviewModel } | { type: "update"; original: string; model: PreviewModel }
  | { type: "remove"; name: string } | { type: "setDefault"; kind: ModelKind; name: string }
modelsReducer(state: ModelsState, action: ModelsAction): ModelsState
canDelete(state: ModelsState, name: string): boolean   // 默认模型不能删
```

- `SAMPLE_MODELS`：与 `config/models.yaml` 同名的 4 个，价格是示例值。

| 模型 | 来源 | 上下文 / 输出 | 能力 | 价格 | 会话数 | 测试结果 |
|---|---|---|---|---|---|---|
| claude-opus-4-6 | 公司 LiteLLM 网关 | 1M / 128000 | 思考、看图、工具 | $5 / $25 | 12 | 成功 |
| gemini-3.5-flash | 公司 LiteLLM 网关 | 1M / 64000 | 工具 | $0.3 / $2.5 | 3 | 成功 |
| gpt-5.5-pro | 公司 LiteLLM 网关 | 400000 / 128000 | 工具 | $15 / $120 | 3 | 失败：`网关返回 401：密钥无效` |
| embed-qwen3-0.6b | 本机 Ollama | 1024 维（向量模型） | — | 免费 | 0 | 成功 |

- [ ] **步骤 1：写失败的测试**
  - `models.test.ts`：
    - `formatPrice({ input: 5, output: 25 })` 等于 `"$5 / $25 每百万"`，`formatPrice({ input: 0.3, output: 2.5 })` 等于 `"$0.3 / $2.5 每百万"`，`formatPrice("free")` 等于 `"免费"`。
    - `modelMeta(claude)` 等于 `"公司 LiteLLM 网关 · 上下文 1M · 输出 128k · $5 / $25 每百万"`（token 用现有的 `formatTokens`）；`modelMeta(embed)` 等于 `"本机 Ollama · 1024 维 · 免费"`。
    - `validateModelForm`（列出的是返回结果里要有的字段）：
      - 价格两栏都空、没勾免费 → `{ priceInput: "填写价格，或标为免费" }`；
      - 勾了免费 → 没有价格错误；
      - `priceInput: "-1"` → `"价格要是不小于 0 的数字"`；
      - 显示名为空 → `{ name: "填写显示名" }`；
      - 显示名与 `otherNames` 重复 → `{ name: "已有同名模型" }`；
      - 厂商模型 ID 为空 → `{ vendorId: "填写厂商模型 ID" }`；
      - 对话模型的 `contextTokens: "1.5"` → `{ contextTokens: "填写正整数" }`；
      - 向量模型不校验上下文，只校验 `dimensions`（正整数）。
    - `modelsReducer`：
      - 删除默认模型时，状态原样返回；删除别的模型就移除它；
      - `setDefault` 改默认；
      - `update` 改了默认模型的名字时，默认值跟着改名。
  - `ui.test.tsx`：
    - `renderToStaticMarkup(<Switch checked label="启用 excel" onChange={…} />)` 里有 `role="switch"`、`aria-checked="true"`、`aria-label="启用 excel"`；
    - `<PreviewBanner />` 包含 `PREVIEW_NOTICE`。
  - `e2e/models.spec.ts`：
    - `模型页：示例提示、价格、默认模型不能删`：
      - 点侧栏"模型"，地址变成 `/models`，能看到 `PREVIEW_NOTICE`；
      - claude-opus-4-6 那行有 `"$5 / $25 每百万"` 和标签"默认"，它的删除按钮是禁用的，`title` 为"先换掉默认再删"；
      - embed 那行有"免费"；
      - 刷新后仍在模型页。
    - `测试结果显示在该行`：gemini 那行点"测试"后出现"✓ 可用"；gpt-5.5-pro 那行出现"✗"和"密钥无效"。
    - `删除先确认`：点 gpt-5.5-pro 的删除，对话框里有"删除 gpt-5.5-pro？"和"有 3 个会话正在用它"；点"删除"后这一行消失。
    - `新增模型：价格必填，Esc 关闭抽屉`：
      - 打开"+ 新增模型"，填显示名、厂商模型 ID、上下文与输出上限，点"保存并重载"，出现"填写价格，或标为免费"；
      - 勾"免费"再保存，清单里多出这一行，并显示"免费"；
      - 再打开抽屉、按 Escape，抽屉关闭；再打开时表单是空的。

- [ ] **步骤 2：确认测试失败**
  - 运行：`cd frontend && pnpm exec vitest run src/features/models src/components/ui`。预期：失败，找不到模块。
  - 运行：`pnpm exec playwright test e2e/models.spec.ts`。预期：失败，侧栏里没有"模型"。

- [ ] **步骤 3：实现**
  - 共用组件：
    - 直角（`rounded-none`）细边框（`border border-border`）；
    - 区块标题 `font-mono text-xs tracking-widest uppercase`；
    - 按钮：描边、大写、小号，`primary` 用 `bg-primary text-primary-foreground`；
    - Drawer 与 ConfirmDialog 打开时，焦点移到里面的第一个可聚焦元素。
  - `ModelsPage`：
    - 标题栏：标题"模型"，副标题"{n} 个已登记"，操作按钮"重载网关"和"+ 新增模型"。点"重载网关"后，标题栏显示 3 秒"已重载网关（示例）"。
    - 第一张卡"默认模型"，备注"新会话的起点；对话里仍可按会话切换"：两个下拉框"对话模型""向量模型"，分别只列对话模型、向量模型，选了就 dispatch `setDefault`。
    - 第二张卡"已登记模型"：
      - 每行：名称、默认时带标签"默认"、`modelMeta`、能力标签（思考 / 看图 / 工具；向量模型显示"向量"）；
      - 右侧：测试、编辑、删除（垃圾桶图标，`aria-label="删除 {name}"`）；
      - 点"测试"先显示"测试中…"，600 毫秒后显示"✓ 可用 · 820ms"，或者"✗ " 加上错误原因。
    - 删除确认框：
      - 标题"删除 {name}？"；
      - 正文"将从 models.yaml 移除这条记录并重载网关。"；会话数大于 0 时加一段"有 {n} 个会话正在用它，这些会话之后会改用默认模型 {默认对话模型}。"；最后一段"历史消息和用量记录保留，不受影响。"；
      - 按钮"取消"和"删除"（`danger`）。
  - `ModelDrawer`：
    - 标题"新增模型"或"编辑 {name}"；
    - 字段依次为：来源（下拉）、厂商模型 ID、显示名、类型（对话 / 向量）、能力（思考 / 看图 / 工具，向量模型时不可选）、上下文上限、输出上限（对话模型）或向量维度（向量模型）、价格（美元 / 每百万 token：输入、输出，以及"免费"勾选框）；
    - "自动查询"按钮：厂商模型 ID 在 `SAMPLE_MODELS` 里能找到时，填上它的上下文、输出上限与价格；找不到时提示"没查到，请手动填写"；
    - 底部按钮"测试连接"（点后显示"✓ 连接正常（示例）"）和"保存并重载"：先校验，错误显示在对应字段下面；校验通过就 dispatch `add` 或 `update`，然后关闭抽屉；
    - 编辑时左下角有"删除"，走同一个确认框，默认模型时禁用。
  - 每次打开抽屉都从空表单（新增）或该模型当前的值（编辑）开始。

- [ ] **步骤 4：确认测试通过**
  - 运行：`cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test e2e/models.spec.ts e2e/navigation.spec.ts`。预期：全部通过。

### 任务 3：技能页（示例数据）

**文件：** 新建 `src/features/skills/SkillsPage.tsx`、`SkillDrawer.tsx`、`UploadSkillDialog.tsx`、`sample.ts`、`skills.ts`、`skills.test.ts`、`e2e/skills.spec.ts`；修改 `routes.ts`（管理组第二项加"技能" `/skills`）、`AppShell.tsx`、`routes.test.ts`（管理组的项改为 `["模型", "技能", "设置"]`）。

**接口：**
- 用到：任务 2 的共用组件。
- 产出：

```ts
type SkillOrigin = "builtin" | "upload" | "chat";   // 来源不显示，只决定能不能删
interface PreviewSkill { name: string; description: string; enabled: boolean; origin: SkillOrigin;
  location: string; addedAt: string /* YYYY-MM-DD */; body: string /* SKILL.md 正文 */; files: string[] }
SAMPLE_SKILLS: PreviewSkill[]   // 下面 3 个
parseSkillMd(text: string): { name: string; description: string } | { error: string }
type UploadFile = { path: string; text?: string }   // path 带文件夹层级；只有 SKILL.md 带 text
type UploadResult =
  | { kind: "ok"; name: string; description: string; fileCount: number; replaces: boolean }
  | { kind: "zip"; fileName: string }               // 预览里不解析压缩包
  | { kind: "error"; message: string }
inspectUpload(files: UploadFile[], existingNames: string[]): UploadResult
filterSkills(skills: PreviewSkill[], filter: "all" | "enabled" | "disabled", query: string): PreviewSkill[]
canDeleteSkill(skill: PreviewSkill): boolean   // origin !== "builtin"
```

- `SAMPLE_SKILLS`：
  - `excel`：项目自带、已启用，正文照 `agents/skills/excel/SKILL.md`，位置 `agents/skills/excel/`；
  - `周报写作`：上传的、已启用；
  - `旅行规划`：上传的、已停用。

- [ ] **步骤 1：写失败的测试**
  - `skills.test.ts`：
    - `parseSkillMd`：
      - 开头是 `---\nname: excel\ndescription: 处理表格\n---\n正文` 时，得到 `{ name: "excel", description: "处理表格" }`；
      - 没有开头的 `---` → `{ error: "SKILL.md 开头要有 --- 包起来的 name 与 description" }`；
      - 缺 description → `{ error: "SKILL.md 开头缺少 description" }`。
    - `inspectUpload`：
      - 只有一个 `SKILL.md` → `ok`，`fileCount` 为 1；
      - 文件夹 `会议纪要/SKILL.md` 加两个别的文件 → `fileCount` 为 3；
      - 名字和已有的重复 → `replaces: true`；
      - 文件夹里没有 SKILL.md → `{ kind: "error", message: "文件夹里没有 SKILL.md" }`；
      - `报告.pdf` → `{ kind: "error", message: "只能上传技能文件夹、.zip 或 SKILL.md" }`；
      - `x.zip` → `{ kind: "zip", fileName: "x.zip" }`。
    - `filterSkills`：按"已启用 / 已停用"筛选；`query` 同时匹配名称和描述，不分大小写。
  - `e2e/skills.spec.ts`：
    - `开关与筛选`：
      - 点侧栏"技能"，能看到 `PREVIEW_NOTICE` 和"已启用 2 / 共 3"；
      - 关掉"周报写作"的开关后变成"已启用 1 / 共 3"，那一行的透明度是 `0.5`；
      - 刷新后仍在技能页。
    - `查看与删除`：
      - excel 的抽屉里，SKILL.md 标签页能看到"处理 Excel / CSV 的规范"，没有"删除技能"按钮；
      - 周报写作有"删除技能"，确认后从列表消失。
    - `上传 SKILL.md`：
      - 用 `setInputFiles` 传一个 `SKILL.md`（内容 name `会议纪要`、description `整理会议记录`），识别结果显示名称"会议纪要"，点"安装"后列表里出现它；
      - 再传一次同名的，提示"安装将覆盖它"。
    - `不支持的文件`：传 `报告.pdf`，显示"只能上传技能文件夹、.zip 或 SKILL.md"，"安装"按钮禁用。

- [ ] **步骤 2：确认测试失败**
  - 运行：`cd frontend && pnpm exec vitest run src/features/skills`。预期：失败，找不到模块。

- [ ] **步骤 3：实现**
  - 标题栏：标题"技能"，副标题"已启用 {n} / 共 {m}"，操作区是搜索框（placeholder "搜索技能"）和"↑ 上传技能"。
  - 左侧筛选：全部 / 已启用 / 已停用，后面带数量。
  - 列表每行：开关（`label` 为"启用 {name}"）、名称、一句描述（太长时截断，悬停显示全文）、"查看"；停用的行 `opacity-50`。
  - `SkillDrawer`（只读）：
    - 顶部是开关；
    - 往下依次是描述、存放位置、添加时间；
    - 两个标签页："SKILL.md"用 react-markdown + remark-gfm 渲染正文，套用现有的 `markdown` 样式类；"文件"列出全部文件；
    - `canDeleteSkill` 为真时底部有"删除技能"，确认框标题"删除技能 {name}？"，正文"删除后智能体就用不到它了，文件夹一并删除。"
  - `UploadSkillDialog`：
    - 一块拖放区，加两个按钮"选择文件夹"（`<input type="file" webkitdirectory>`）和"选择文件"（`accept=".zip,.md"`）；
    - 只读出 SKILL.md 的文字（`File.text()`），交给 `inspectUpload`；
    - 识别成功时显示名称、描述、文件数；`replaces` 为真时提示"已有同名技能「{name}」，安装将覆盖它"；
    - 压缩包显示"压缩包里的内容要接上后端后才能识别（预览）"；
    - 出错时显示错误原因；
    - "安装"只在识别成功时可点，装完就加入或替换列表里的同名项（`origin: "upload"`，已启用，添加时间为今天）。

- [ ] **步骤 4：确认测试通过**
  - 运行：`cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test e2e/skills.spec.ts`。预期：全部通过。

### 任务 4：MCP 页（示例数据）与收尾

**文件：** 新建 `src/features/mcp/McpPage.tsx`、`ToolsDrawer.tsx`、`ServerDrawer.tsx`、`InstallDialog.tsx`、`catalog.ts`、`sample.ts`、`mcp.ts`、`mcp.test.ts`、`e2e/mcp.spec.ts`；修改 `routes.ts`（管理组第三项加"MCP" `/mcp`）、`AppShell.tsx`、`routes.test.ts`（管理组的项改为 `["模型", "技能", "MCP", "设置"]`），以及文档。

**接口：**
- 用到：任务 2 的共用组件。
- 产出：

```ts
type ServerKind = "local" | "network";
interface PreviewTool { name: string; description: string; readOnly: boolean; action: "auto" | "ask" }
interface PreviewServer { name: string; description: string; kind: ServerKind; enabled: boolean;
  status: "connected" | { error: string }; command: string; tools: PreviewTool[];
  secrets: Record<string, string> /* 只存 maskSecret 之后的值 */ }
interface CatalogItem { id: string; name: string; description: string; kind: ServerKind; needsKey: boolean;
  fields: { key: string; label: string; secret: boolean }[]; command: string; tools: PreviewTool[] }
SAMPLE_SERVERS: PreviewServer[]
CATALOG: CatalogItem[]
maskSecret(value: string): string
type ParsedServer = { name: string; kind: ServerKind; command?: string; args?: string[]; url?: string }
parseMcpJson(text: string): { servers: ParsedServer[] } | { error: string }
statusLabel(server: PreviewServer): string
filterCatalog(items: CatalogItem[], query: string): CatalogItem[]
interface ServerForm { name: string; description: string; kind: ServerKind; command: string; args: string;
  env: string; url: string; headers: string }
validateServerForm(form: ServerForm, existingNames: string[]): Partial<Record<keyof ServerForm, string>>
```

- `SAMPLE_SERVERS`：
  - `files`：本地进程、已连接，命令 `npx -y @modelcontextprotocol/server-filesystem /shared`；工具有 `list_allowed_directories`、`read_text_file`、`list_directory`（这三个只读）和 `write_file`、`edit_file`；
  - `notes`：本地进程，状态 `{ error: "启动失败：找不到命令 notes-mcp" }`，有 1 个工具。
- `CATALOG`：6 项。
  - 不需要密钥的：`files`（已安装）、`fetch`（网页抓取，本地进程）、`sqlite`、`time`；
  - 需要密钥的：`brave-search`（字段 `BRAVE_API_KEY`）、`github`（字段 `GITHUB_TOKEN`）。

- [ ] **步骤 1：写失败的测试**
  - `mcp.test.ts`：
    - `maskSecret`：`"sk-abcdef1234"` → `"••••1234"`，`"1234"` → `"••••"`。
    - `parseMcpJson`：
      - `{"mcpServers": {"a": {"command": "npx", "args": ["x"]}, "b": {"url": "https://h/mcp"}}}` → 两个服务，`a` 是 `local`，`b` 是 `network`；
      - 不带 `mcpServers` 的同样结构也认；
      - `"{"` → `{ error: "不是有效的 JSON" }`；
      - `{"mcpServers": {"c": {}}}` → `{ error: "c 缺少 command 或 url" }`；
      - `[]` → `{ error: "没找到 MCP 服务的配置" }`。
    - `statusLabel`：停用 → `"已停用"`；`connected` → `"已连接"`；出错 → `"出错：启动失败：找不到命令 notes-mcp"`。
    - `validateServerForm`：
      - 名称为空 → `"填写服务名"`；名称重复 → `"已有同名服务"`；
      - 本地进程没填命令 → `{ command: "填写启动命令" }`；
      - 网络地址填 `"h/mcp"` → `{ url: "地址要以 http:// 或 https:// 开头" }`。
  - `e2e/mcp.spec.ts`：
    - `我的服务：状态与开关`：
      - 点侧栏"MCP"，能看到 `PREVIEW_NOTICE`；files 行有"已连接"和"5 个工具"，notes 行有"出错：启动失败"；
      - 关掉 files 的开关后变成"已停用"；
      - 刷新后仍在 MCP 页。
    - `从目录安装`：
      - 搜索"brave"后只剩 brave-search 一张卡；点"安装"，不填密钥就点"安装并连接"，提示"必填"；
      - 填 `sk-test-abcd1234` 后再点，"我的 MCP 服务"里出现 brave-search 并显示"已连接"，卡片变成"已安装"；
      - 打开它的"编辑"，密钥显示为 `••••1234`。
    - `粘贴 JSON`："手动添加"抽屉的"粘贴 JSON"标签页里贴入两个服务，点"识别"后显示"识别到 2 个服务"；点"保存并连接"后两行都出现。
    - `按工具设置审批`：在 files 的"查看工具"抽屉里，`write_file` 一行从"先问"切到"自动"后，"自动"处于按下状态（`aria-pressed="true"`）。

- [ ] **步骤 2：确认测试失败**
  - 运行：`cd frontend && pnpm exec vitest run src/features/mcp`。预期：失败，找不到模块。

- [ ] **步骤 3：实现**
  - 标题栏：标题"MCP"，操作按钮"重新加载"（点后显示 3 秒"已重新加载（示例）"）和"+ 手动添加"。
  - "我的 MCP 服务"卡片：
    - 每行：开关、名称、描述、类型标签（本地进程 / 网络）、"{n} 个工具"、`statusLabel`（出错时用 `danger` 色）；
    - 右侧"查看工具""编辑"。
  - "目录"卡片：
    - 搜索框加卡片网格，不要分类按钮；
    - 每张卡：名称、描述、类型标签，需要密钥时加"需要密钥"标签；右侧"安装"，已安装的显示为禁用的"已安装"。
  - `InstallDialog`：
    - 标题"安装 {name}"；
    - 字段：服务名（默认填 `id`），以及 `fields` 里的每一项（`secret` 的用密码输入框）；空着时提示"必填"；
    - "测试连接"点后显示"✓ 连接正常（示例）"；
    - "安装并连接"后加入一个已连接的服务：工具取自目录项，密钥存 `maskSecret` 之后的值。
  - `ToolsDrawer`：
    - 标题"{name} 的工具"；
    - 启动命令放在代码块里；
    - 说明文字"没写规则时：服务声明只读的工具自动执行，其余先问你"；
    - 每个工具一行：名称、描述，只读的加"只读"标签；右侧两个按钮"自动""先问"，当前的那个 `aria-pressed="true"`。
  - `ServerDrawer`：
    - 标题"手动添加 MCP 服务"或"编辑 {name}"；
    - 公共字段：服务名、描述（可空）；
    - 三个标签页：
      - 本地进程：命令、参数（每行一个）、环境变量（每行 `KEY=VALUE`）；
      - 网络地址：地址、请求头（每行 `名称: 值`）；
      - 粘贴 JSON：文本框和"识别"按钮，识别后列出"识别到 {n} 个服务：…"；
    - 编辑时，已保存的密钥只显示 `maskSecret` 之后的值；
    - 底部按钮"测试连接"和"保存并连接"：先校验，粘贴 JSON 时一次加入全部识别到的服务；其中有和已有服务重名的，提示"已有同名服务：{名称}"，一个都不加。
  - 开关只改 `enabled`；停用后状态显示"已停用"。

- [ ] **步骤 4：确认测试通过**
  - 运行：`cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test`。预期：全部通过（原有 10 个加新增的端到端用例）。

- [ ] **步骤 5：文档**
  - 使用指南第 3 节：
    - 侧栏分"工作""管理"两组；
    - 模型、技能、MCP 三页目前是**预览**（示例数据，操作不保存），真正的修改仍按第 4 节改配置文件；
    - 设置页照旧显示真实状态。
  - 架构规范第 5 节：补上 `src/components/ui/`、三个页面目录，以及"示例数据页的写法：`sample.ts` + 纯函数模块 + `useReducer`，接后端时只换数据来源"。
  - changelog 新增一节"前端管理页面（纯界面）"。
  - 需求池新增三条：
    - "管理页面接上后端"（交付方式 B / C；先解决设计文档第 9 节的五个冲突点）；
    - "系统页与日志页"（设计文档第 8 节）；
    - "在对话里添加技能（确认卡片）"。
  - R22 备注"界面预览已做（2026-10-18）"。

- [ ] **步骤 6：全部检查**
  - 运行：`make check`、`make e2e`。预期：全部通过。
  - 运行：`make build`，然后打开 http://127.0.0.1:8000 ，在深色、浅色两版下各看一遍侧栏、对话页、模型页、技能页、MCP 页。预期：颜色都来自主题；每个示例页的顶部都有提示条；知识库、用量、设置三页和原来一样。
