# 积压小问题·第一批「前端与界面」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉对话页、会话列表、文件面板、技能 / 设置 / MCP 页与无障碍样式上积压的约 45 条小问题，行为以核对明细的"最小修法"为准。

**Architecture:** 绝大多数改动在 `frontend/src` 的纯函数（reducer、adapter、math、order、cache、kind、settings、skills）与几个组件里，每条先在纯函数层写失败的单测；需要后端多给字段的三条（A11 可疑、B4 命中词、D4 列截断）在事件或接口模型上加字段后 `make types`。焦点管理（H1）新写一个共用 hook，四个弹层组件接上。

**Tech Stack:** React 19、assistant-ui 0.15.28、react-query、Tailwind、vitest（node 环境，组件用 `renderToStaticMarkup`）、Playwright 端到端；后端 Python 3.12、pydantic、FastAPI。

**Spec:** `docs/specs/2026-10-26-minor-fixes-design.md`（已审定）；每条的证据、最小修法与测试见 `docs/specs/2026-10-26-minor-fixes-verification/01-前端.md`（下称"明细"），A11、B4 的后端部分见 `02-后端运行与记忆.md`。

## Global Constraints

- 不新增依赖；依赖方向 `backend → agents → config → common`；deepagents 只在 `agents/main_agent/runtime/`。项目没有 git：台账 `.superpowers/sdd/2026-10-26-minor-fixes-batch1/progress.md`。不读、不打印 `.env`。
- 中文注释只写"为什么"；样式只用语义类（颜色只在 `src/themes/`、`src/styles/` 定义）；改了接口或事件定义在同一任务里 `make types`。
- 不调用真实模型；端到端只用假模型与测试库；8000 上只看、不发真实消息、不点模型"测试"。
- 固定文案（原样使用）：
  - A9 等审批时同一轮里没跑完的自动工具、子智能体：`等待中`。
  - A11 可疑的"已记住"：`已记住，但像是“{原因}”，标为可疑：在知识库页确认前不会用上`。
  - B8 合计：`查了 N 次以前的对话`。
  - C3 删除会话确认框补一句：`它记下的记忆、加入知识库的文档会保留，可在知识库页管理。`
  - D4 表格预览：`只显示前 50 列`。
  - F6 上传技能前的检查：`文件太多：一个技能最多 500 个文件`、`文件太大：合计超过上传上限 {N}MB`。
  - F16 标签页标题：对话页 `{会话标题，没有时写"新会话"} · 个人智能体`，其他页 `{页名} · 个人智能体`，落地页 `对话 · 个人智能体`。
  - H3 浅色：焦点框 58%、输入框边框 58%（开关轨道跟着 `bg-input`）；深色：输入框边框 40%，焦点框保持 45%。
- 前端单测写作 `WEB vitest <文件>`，Python 单测写作 `PY <文件>`；前端命令前缀 `PATH=$HOME/.nvm/versions/node/v24.21.0/bin:$PATH pnpm exec`。

## Review Focus

1. 公式占位符（A12～A16）：现在显示正确的写法（金额、行内与块公式、代码里的 `$`、链接）一个都不能变；占位字符不能漏到最终页面上。
2. 焦点管理（H1）遇到"抽屉里再弹确认框"两层叠加：Tab 与 Esc 只管最上面一层；关闭后焦点回到打开它的那个按钮；抽屉里没有可聚焦元素时焦点落在关闭按钮上。
3. 拖动排序（B1）与改会话设置（B5）时恰好有一次轮询回来：界面不闪回旧顺序、旧模型；保存失败时仍以服务器为准恢复。
4. 移除正在上传的附件（D6）：不显示"上传失败"、文件面板里没有它；其他还在传的附件不受影响。
5. 对比度（H3）只改浅色的焦点框与边框、深色的输入框边框；主题契约测试与写死颜色检查照常通过。

---

### Task 1: 思考状态与审批卡片（A1、A5、A6、A7、A9）

**Files:** Modify `src/features/chat/reducer.ts`（`closeThinking` 结束这一层所有没结束的思考）、`src/components/chat/adapter.ts`（等审批时同组没结束的工具标 waiting、子智能体加 waiting）、`src/components/chat/parts.tsx`（SubagentCard 传 waiting；NestedItems 的 active 算上等待）、`src/components/chat/approval.tsx`（决定文字 `min-w-0 truncate` 加 title；Esc 看输入法；选完一个操作后焦点留在卡片里）、`src/features/chat/ChatHeader.tsx`、`src/features/threads/ThreadList.tsx`（改名的 Esc 看输入法）。Test: `reducer.test.ts`、`adapter.test.ts`、`approval.test.tsx`。

- [ ] **Step 1: 写失败的测试**
  - `reducer.test.ts`：`同一段思考中间夹进回答文字后又接着思考：下一个同层事件就结束它`（旧历史"思考—用量—思考—工具"与新事件"思考—finished—文字—思考—工具"两种都测：思考的 endedAt 等于工具事件时间，`toThreadMessages` 里这段思考 running=false）。
  - `adapter.test.ts`：`等审批时同一轮里没结束的自动工具与子智能体标为等待，不显示已中断`（自动工具与子智能体的状态都是"等待中"，审批中的那个工具仍是"等待审批"）。
  - `approval.test.tsx`：`子智能体审批的长回复可以截断`（300 字回复所在 span 带 `min-w-0`、`truncate` 与完整 title）。
- [ ] **Step 2**：跑测试，看到失败。
- [ ] **Step 3**：按明细 A1、A5、A6、A7、A9 的最小修法实现。A6 三处 Esc 判断用 `closesOverlay(event.nativeEvent)` 或加 `!isImeComposing(...)`；A7 用 ref + `useEffect` 在 mode 变成 chosen 时聚焦"已选择"那一行（`tabIndex={-1}`）。
- [ ] **Step 4**：`WEB vitest src/features/chat src/components/chat` 全过。

### Task 2: 回答下方的复制按钮与"换个模型"菜单（A8、A10）

**Files:** Modify `src/components/chat/parts.tsx`（AssistantFooter：没有非空正文时不渲染复制按钮；整行没东西时返回 null）、`src/components/chat/errorCard.tsx`（SwitchModel：打开时聚焦第一项、上下方向键移动、Esc 关闭后焦点回到按钮）。把"下一个第几项"抽成 `src/components/ui/menuKeys.ts` 的 `nextIndex(current, count, key)`，ThreadMenu 与 SwitchModel 共用。Test: `src/components/ui/menuKeys.test.ts`（新）。

- [ ] **Step 1**：`menuKeys.test.ts`：`下方向键到下一项、到底回到第一项；上方向键反过来；其他键不动`。
- [ ] **Step 2～4**：实现并接线；`ThreadMenu.test.tsx` 照常通过。A10 的"没有正文不显示复制"靠 Task 15 的端到端断言（失败那一轮没有"复制"按钮）。

### Task 3: 聊天里"已记住"标出可疑（A11）

**Files:** Modify `agents/main_agent/runtime/events.py`（`MemorySaved.suspicious: str | None = None`）、`agents/main_agent/runtime/translator.py`（`_memory_saved` 填 `item.get("suspicious")`）、`make types`、`src/features/chat/reducer.ts`（memory 项带上它）、`src/components/chat/parts.tsx`（MemoryPart 可疑时警告色与固定文案）。Test: `agents/tests/test_knowledge_runtime.py`、`reducer.test.ts`。

- [ ] **Step 1**：`test_knowledge_runtime.py::test_remembering_something_suspicious_marks_it` 加断言 `MemorySaved.suspicious` 等于可疑原因；`reducer.test.ts`：`可疑的记忆在聊天里带着可疑原因`。
- [ ] **Step 2～4**：实现；`make types`；`PY agents/tests/test_knowledge_runtime.py`、`WEB vitest src/features/chat` 通过。

### Task 4: 公式与代码着色（A12～A17、A19）

**Files:** Modify `src/components/chat/math.ts`（占位符做法：patchSegment 里把要躲开框架处理的字符换成私用区字符，`normalizeMath` 最后换回；KaTeX 选项加 `maxSize: 20`）、`src/components/chat/highlight.ts`（try/catch，出错返回 null）；完成后更新 `docs/decisions/D19-代码高亮与数学公式的实现方式.md` 的"代价"一节。Test: `math.test.tsx`、`highlight.error.test.ts`（新）。

- [ ] **Step 1: 写失败的测试**（`math.test.tsx`）：
  - `正文里的 \[1\]、a\[0\] 是文字`（公式 0 个、html 含 "[1]"）。
  - `公式块里的 \\[2pt] 不和后面的 \[…\] 配对`（公式 2 个、报错 0）。
  - `裸地址与 <…> 自动链接里的 $数字 不插反斜杠`（href 为原地址）。
  - `正文的 $HOME/$USER 是文字`，同时 `$AB/BC$ 仍是公式`。
  - `设 $n$2 个不报错`，同时 `价格 $x 和 $5 仍不是公式`。
  - `公式里的尺寸被限住`（html 不含 `width:100000em`）。
  - `最终的 html 里没有占位字符`（对以上全部样例断言）。
  - `highlight.error.test.ts`：`着色出错时原样显示`（mock lowlight 抛错，`highlight()` 返回 null）。
- [ ] **Step 2～4**：实现；`WEB vitest src/components/chat/math.test.tsx src/components/chat/highlight.error.test.ts src/components/chat/code.test.tsx` 全过（原有的公式测试一条都不能改）。

### Task 5: 会话列表（B1、B2、B5、B11、C3、I9）

**Files:** Modify `src/features/threads/order.ts`（`pendingOrder(threads, ids)`）、`ThreadList.tsx`（保存中按 `reorder.variables` 排；I9 两处旧注释）、`titleRefresh.ts`（`TITLE_REFRESH_DELAYS` 补到约 60 秒）、`cache.ts`（`replaceThread` 改 async，先 `cancelQueries({queryKey: threadsQuery.queryKey, exact: true})`；三处调用等它）、`ArchivedThreads.tsx`（每行状态点与状态字）、`archive.ts`（markViewed 同时清归档缓存里的 new）、`DeleteThreadDialog.tsx`（C3 文案）。Test: `order.test.ts`、`titleRefresh.test.ts`、`cache.test.ts`、`DeleteThreadDialog.test.tsx`（新，renderToStaticMarkup）。

- [ ] **Step 1**：`pendingOrder：刷新带回旧顺序时仍按保存中的顺序；新会话放最前`；`最后一次刷新不早于 60 秒；标题变了以后取消剩下的刷新`；`改了会话设置时恰好有一次列表刷新没回来：不会把旧模型写回`（假时钟）；`markViewed 清掉归档列表里的有新回答`；`删除确认框说明记忆与文档会保留`。
- [ ] **Step 2～4**：实现；`WEB vitest src/features/threads src/features/chat` 全过。

### Task 6: 会话搜索按命中词加粗、工具合计（B4、B8）

**Files:** Modify `agents/main_agent/conversations/base.py`、`pg.py`、`agents/tests/fakes.py` 里的替身（`ConversationHit.terms: list[str]`：查询原文小写与分词结果，去掉单字词）、`backend/threads/schemas.py`（`ConversationHitView.terms`）、`make types`、`src/features/threads/search.ts`（`highlightParts` 收词列表）、`ThreadSearchResults.tsx`；`src/components/chat/tools.ts`（新类 `conversations`，合计"查了 N 次以前的对话"）、`toolLine.tsx`（图标 History）。Test: 会话索引契约测试、`search.test.ts`、`tools.test.ts`。

- [ ] **Step 1**：契约 `test_search_reports_the_words_it_matched`（pg 与替身各一，集成）；`search.test.ts`：`"上海的天气"里"上海""天气"都加粗`；`tools.test.ts`：`summarizeTools(["search_conversations","search_knowledge"])` 得到 `查了 1 次以前的对话，检索了 1 次知识库`。
- [ ] **Step 2～4**：实现；`make types`；单测与 `make test-int` 里的契约测试通过。

### Task 7: 文件面板与预览（C11、D2、D3、D4、D6）

**Files:** Modify `src/features/files/FilePanel.tsx`、`src/features/knowledge/CitationPanel.tsx`（`max-w-[50%]`）、`src/features/chat/ChatView.tsx`（run.finished 与 approval.required 时 invalidate `filesQuery`）、`src/features/files/kind.ts`（常见文字后缀 ≤1MB 按文字预览；heic/heif/tiff 只能下载）、`backend/files/preview.py`（`TablePreview.columns_truncated`）、`make types`、`src/features/files/FilePreview.tsx`（"只显示前 50 列"）、`src/api/client.ts`（`uploadFile` 可选 `signal`）、`src/features/chat/useUploads.ts`（每个上传一个 AbortController，remove 时 abort，已中止的不标失败）。Test: `kind.test.ts`、`backend/tests/test_preview.py`、`src/api/client.test.ts`、`src/features/chat/uploads.test.ts`。

- [ ] **Step 1**：`.log/.yaml/.ts 按文字显示；.heic/.tiff 只能下载`；`test_wide_table_marks_columns_truncated`；`上传把 signal 交给 fetch`；`移除上传中的附件会中止它、不标失败`（把中止逻辑抽成 `uploads.ts` 的纯函数测）。
- [ ] **Step 2～4**：实现；`make types`；对应单测通过。

### Task 8: 后端重启后的图片与下载（E4）

**Files:** Modify `src/api/session.ts`（`reloadImageOnce(img)`：失败时重取一次令牌、换地址参数重载，每张图只重试一次；`ensureSession()`：下载前确认令牌有效）、`src/components/chat/parts.tsx` 与 `src/features/files/FilePreview.tsx`（`<img onError>`）、下载按钮（`src/components/chat/fileActions.ts` 等用到下载链接的地方）点击时先 `ensureSession()` 再跳转。Test: `src/api/session.test.ts`。

- [ ] **Step 1**：`图片加载失败时只重取一次令牌并换地址重载`；`下载前令牌失效时先重取再下载`（mock fetch / refreshToken）。
- [ ] **Step 2～4**：实现；`WEB vitest src/api` 通过。

### Task 9: MCP 页、技能页、设置页与文档上限（E7、F1、F6、F10、F19、F20 前端）

**Files:** Modify `src/features/mcp/mcp.ts`（`toolsSignature(servers)`）与 `McpPage.tsx`（签名变了 invalidate `approvalSettingsQuery`）；`src/features/skills/skills.ts`（`visibleNotice(notice, skills)`、`skillsStateError(files)`、`inspectUpload` 增加文件数与总大小检查，参数加上限）、`SkillsPage.tsx`、`UploadSkillDialog.tsx`；`src/features/settings/settings.ts`（归不进任何一节的项一律放进"只读项"）；`src/features/knowledge/DocumentList.tsx`（上限取 `appSettingsQuery` 的 `max_upload_mb`，取不到写"上传上限"）。Test: `mcp.test.ts`、`skills.test.ts`、`settings.test.ts`。

- [ ] **Step 1**：`服务连上或工具数变了签名就变`；`删掉那个技能后上传提示不再显示`；`skills.yaml 写坏时给出原因，正常或不存在时为 null`；`文件超过 500 个、或总大小超过上限时不让上传`（固定文案）；`.env 指定、又不属于任何一节的项放进只读项`。
- [ ] **Step 2～4**：实现；对应单测通过。

### Task 10: 浏览器标签页标题（F16）

**Files:** Modify `src/layout/routes.ts`（`pageTitle(pathname, threadTitle?)`）、AppShell（渲染 `<title>`）、对话页传入当前会话标题。Test: `src/layout/routes.test.ts`。

- [ ] **Step 1**：`每页的标签页标题`（模型、技能、MCP、知识库、用量、设置；对话页有标题、没标题、落地页三种）。
- [ ] **Step 2～4**：实现；单测通过。

### Task 11: 对话框焦点与表单可访问性（H1、H2、I10）

**Files:** Create `src/components/ui/dialogFocus.ts`（`useDialogFocus(open, ref, fallbackRef?)`：打开时记下原焦点并聚焦第一个可聚焦元素，没有就聚焦关闭按钮或对话框本身；Tab 在对话框内循环、只管最上面一层（复用 `escape.ts` 的层栈）；关闭时还原焦点；"Tab 下一个是谁"抽成纯函数 `nextFocusIndex(current, count, shift)`）；Modify `Modal.tsx`、`ConfirmDialog.tsx`、`Drawer.tsx`、`src/features/threads/DeleteThreadDialog.tsx` 接上；`escape.ts` 的层栈抽成 `pushLayer`、`popLayer`、`isTopLayer`；`Field.tsx`（多行输入框展开其余属性；提示或错误有 id，输入框 `aria-invalid`、`aria-describedby`）。Test: `src/components/ui/dialogFocus.test.ts`、`escape.test.ts`、`ui.test.tsx`。

- [ ] **Step 1**：`nextFocusIndex：Tab 到底回到第一个，Shift+Tab 反过来`；`两层弹层：只有最上面一层响应 Esc 与 Tab`；`表单项：出错时 aria-invalid 并指向错误文字；多行输入框带上其余属性`。
- [ ] **Step 2～4**：实现并接线；`WEB vitest src/components/ui` 通过；端到端在 Task 15 补"上传技能对话框：打开时焦点在里面、连按 Tab 不出去、Esc 后回到'上传技能'按钮"。

### Task 12: 浅色对比度与组件样式（H3、H5）

**Files:** Modify `src/styles/tokens.css`（按深浅色分别设焦点框与输入框边框的比例，照 `--syntax-strength` 的写法）、`src/features/usage/UsagePage.tsx`（两段之间留 1px 缝、输出段加用颜色变量写的斜纹，图例同样画）、`src/components/ui/Modal.tsx`、`ConfirmDialog.tsx`（`rounded-xl shadow-lg`）、`Tabs.tsx`（去掉 `font-mono tracking-wider uppercase`，改 `text-[13px]`）。Test: `src/themes/contrast.test.ts`、`ui.test.tsx`。

- [ ] **Step 1**：`焦点框、输入框边框在背景与卡片上不低于 3:1`（浅色、深色都测）；`对话框、确认框 12 像素圆角；标签页不用等宽大写`。
- [ ] **Step 2～4**：实现；`WEB vitest src/themes src/styles src/components/ui` 通过（含写死颜色检查）。

### Task 13: 前端代码整理（A3 清理、I3、I8、I11）

**Files:** 删 `ChatView` 没人传的 `initialNotice`；`src/components/chat/format.ts`（连测试）挪到 `src/components/format.ts`，改引用与 `docs/development/architecture.md` 第 5 节的表；`parts.tsx` 那段注释挪到 `smooth={false}` 上方；`approvalActions.ts` 删 `stop`（ChatView 的 useMemo 同步删）。Test: tsc、eslint、全部前端单测。

- [ ] **Step 1～2**：改完 `pnpm exec tsc --noEmit`、`pnpm exec eslint src e2e`、`WEB vitest` 全过。

### Task 14: 测试补缺（I15、I18）

**Files:** Modify `src/components/chat/toolLine.tsx`（把"正在<动词>…"抽成纯函数 `runningLabel(items)`）、`src/features/chat/drafts.ts`（草稿去抖若还在 `ChatThread.tsx` 里，抽成可测的小工具）、`src/api/queries.test.ts`（退订前先 `vi.waitFor` 等到缓存里有数据）。Test: `toolLine.test.tsx`、`drafts.test.ts`、`queries.test.ts`。

- [ ] **Step 1**：`工具组有运行中的写"正在<动词>…"`；`停 400ms 才保存、离开时补存`（假时钟）；`queries.test.ts` 那条改完后，把 gcTime 临时改成 Infinity 应当失败（只在本地验证，不留）。
- [ ] **Step 2～4**：实现；对应单测通过。

### Task 15: 文档、全量检查、审查、部署与 8000 核对

- [ ] **Step 1: 端到端补断言**：失败那一轮没有"复制"按钮（A10）；结束后文件面板里有新产物（D2）；上传技能对话框的焦点（H1）。
- [ ] **Step 2: 文档**：changelog（新节"积压小问题·第一批"）、需求池（本批各条在原 R 号里标"已修 2026-10-26"）、`docs/decisions/D19`（代价一节）、architecture（format.ts 位置、对话框焦点）、testing（新增的纯函数测试约定）。
- [ ] **Step 3**：`make check`、`make test-int`、`make e2e` 全过。
- [ ] **Step 4**：独立审查（opus）→ 修 Critical / Important → 全量再跑。
- [ ] **Step 5**：升级前查运行状态；`make backup`；`make build`；8000 核对（只看）：等审批时的工具状态、公式页面、浅色主题、标签页标题、技能页与设置页。
- [ ] **Step 6**：记台账，汇报一句，接着第二批。
