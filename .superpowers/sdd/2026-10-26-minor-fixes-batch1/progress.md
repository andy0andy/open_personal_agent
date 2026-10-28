# SDD ledger — plan: docs/plans/2026-10-26-minor-fixes-batch1.md
执行方式：本会话内执行（方式二），最后一次整体审查。项目无 git：台账即记录。开始 2026-10-26 11:13。
Pre-flight: Task 3（A11 事件字段）、Task 6（B4 命中词）、Task 7（D4 列截断）都改后端模型并 make types——按顺序做，各自生成一次类型；Task 11 的层栈与 Task 2 的菜单方向键都碰 ThreadMenu / escape.ts：Task 2 只抽 nextIndex，Task 11 再动层栈，不冲突。
Task 1: complete (A1 closeThinking 结束这一层所有没结束的思考；A5 决定文字 min-w-0 truncate + title；A6 审批卡片、顶栏改名、会话列表改名与搜索框的 Esc 都用 closesOverlay（输入法选字时不算）；A7 选完操作焦点留在'已选择'；A9 新状态 paused='等待中'。WEB vitest src/features src/components → 342 passed；4 条新测试 RED→GREEN)
Task 2: complete (新 components/ui/menuKeys.ts：nextIndex 纯函数 + moveMenuFocus，会话菜单与'换个模型'共用；'换个模型'打开时聚焦第一项、方向键移动、Esc 关闭后焦点回按钮；回答下方没有正文时不放复制按钮、整行没东西时不渲染。WEB vitest src/components/ui/menuKeys.test.ts RED（找不到模块）→GREEN；src/components src/features/threads → 154 passed)
Task 3: complete (MemorySaved.suspicious（已确认无害的不带）→ make types → reducer 记忆项与 MemoryNoteData 带上 → MemoryPart 可疑时警告色固定文案。PY test_remembering_something_suspicious_marks_it RED→GREEN；WEB '可疑的记忆在聊天里带着可疑原因' RED→GREEN；前端全量 392 passed)
Task 4: complete (math.ts 占位符做法：holdLiteralBrackets（A12）、holdDelimiters 藏起 $$…$$ 里的 \[ 一类（A13）、holdLinkDollars（A14）、$HOME/ 一类环境变量当文字（A15，代价 $ABC/DEF$）、结尾 $ 后紧跟数字且像公式时用占位（A16）、KaTeX maxSize 20（A17）；highlight 出错返回 null（A19）；D19 代价一节已改。WEB math.test 6 条 + highlight.error 1 条 RED→GREEN；原有公式测试一条未改；前端全量 401 passed)
Task 5: complete (B1 order.pendingOrder + 会话列表保存中按它排；B2 标题刷新延到 60 秒；B5 replaceThread 先 cancelQueries(exact) 再写；B11 归档列表显示状态点与状态字、markViewed 同时清归档缓存；C3 删除框说明记忆与文档保留；I9 两处旧注释；顺带：reducer 的 memory.saved 抽成 memoryItem（复杂度上限）。WEB 6 条 RED→GREEN；前端全量 407 passed、eslint 0)
Task 6: complete (B4 ConversationHit.terms（hit_terms：查询原文+分词，去单字、长的在前）→ ConversationHitView.terms → make types → highlightParts 收词列表、queryWords 兜底；B8 新类 conversations '查了 N 次以前的对话'、图标 History。WEB 3 条 RED→GREEN；契约 test_search_reports_the_words_it_matched（集成，pg 与替身）先写后实现、实现后通过（实现前字段不存在，失败无疑）；前端全量 409 passed)
Task 7: complete (C11 两个右侧面板 max-w-[50%]；D2 run.finished、approval.required 时刷新文件列表；D3 常见文字后缀当文字、heic/heif/tiff 只能下载；D4 TablePreview.columns_truncated + make types + '只显示前 50 列'；D6 uploadFile 带 signal、send 遇到自己取消的原样抛出（加 cause 满足 eslint）、useUploads 移除时中止且不标失败。PY test_wide_table_marks_columns_truncated、WEB 4 条 RED→GREEN)
Task 8: complete (session.ts：reloadImageOnce（失败时重取令牌、地址加参数重载，每张只一次）、downloadWithFreshSession（先换令牌再用临时链接下载）；产物卡片与文件预览的图片挂 onError、下载按钮改为先换令牌。WEB 2 条 RED→GREEN；前端全量 415 passed)
Task 9: complete (E7 mcp.toolsSignature 变了就重新拉审批规则；F19 不属于任何一节的项放只读；F1 visibleNotice 只在那个技能还在时显示；F10 技能页用设置页文件接口显示停用清单写坏的原因；F6 inspectUpload 带上限（500 个、合计不超过 max_upload_mb）；F20 文档上传说明按设置里的上限写；新 settings.uploadLimitMb。WEB 7 条 RED→GREEN；前端全量 422 passed)
Task 10: complete (routes.pageTitle：每页页名、对话页会话标题（空写'新会话'、没取到写'对话'）+' · 个人智能体'；AppShell 给非对话页渲染 <title>，ChatPage 自己渲染。WEB 1 条 RED→GREEN；前端全量 423 passed)
Task 11: complete (escape.ts 层栈改成 pushLayer/popLayer/isTopLayer；新 dialogFocus.ts：nextFocusIndex 纯函数 + useDialog（打开时聚焦、Tab 循环、Esc、只管最上面一层、关闭还焦点）；Modal、ConfirmDialog、Drawer（正文没有可聚焦的就聚焦关闭按钮）、DeleteThreadDialog 接上；Field 多行输入框带上其余属性、aria-invalid 与 aria-describedby。WEB 6 条 RED→GREEN；前端全量 429 passed)
Task 12: complete (tokens.css 按模式设 --input-strength/--ring-strength（深色 40%/45%，浅色 58%/58%），--color-input、--color-ring 改用它们；用量图'输出'柱加 bar-hatched 斜纹、两段之间留 1px；Modal、ConfirmDialog 圆角 rounded-xl + 阴影；Tabs 去掉等宽大写。WEB contrast 2 条、ui 1 条 RED→GREEN；前端全量 432 passed；vite build 通过且产物里有 bar-hatched)
Task 13: complete (A3 清理 ChatView 没人传的 initialNotice；I3 components/chat/format.ts（连测试）挪到 components/format.ts，6 处引用与 architecture 第 5 节；I8 smooth 注释挪到它上面；I11 审批卡片的 stop 动作删掉。tsc、eslint、前端全量 432 passed)
Task 14: complete (I15 toolLine.runningLabel 纯函数、drafts.draftSaver（ChatThread 改用它）；I18 queries.test 先等数据进缓存再断言被丢弃——探针：缓存永不丢弃时加强后的断言失败（探针已删）。WEB 2 条 RED→GREEN；前端全量 434 passed)
Task 15: 端到端补了 A10（失败那一轮没有复制按钮）、D2（跑完后文件面板里有产物）、H1（上传技能对话框的焦点）；文档已写（changelog、backlog 新增 R43、usage、architecture、D19）
Ruling: A9 新增步骤状态 paused（"等待中"，沙漏图标），不复用 waiting（"等待审批"）——设计第 5 节"它们本身不需要你审批" — 代价：多一种状态
Ruling: A12 只把两种 \[…\] 当文字：括号里只有数字、逗号、连字符、空白，或 \[ 紧挨字母数字；A15 规则 "$ 后 3 个以上大写字母或下划线、紧跟 /" — 代价：$ABC/DEF$ 这类公式被当成文字（D19 已记）
Ruling: E4 下载改为点击时先 refreshToken 再用临时 <a download> 触发（原链接保留，中键、新标签页打开不受影响）；图片失败只重试一次 — 代价：每次下载多一次很轻的 /api/session 请求
Ruling: F6 还没取到上传上限时只查文件数（合计大小不查），交给后端兜底 — 代价：设置接口很慢时大文件夹仍会先传
Ruling: H3 深色输入框边框 35%→40%（达到 3:1），焦点框保持 45%；浅色两者 58% — 代价：浅色界面边框明显深一些
Ruling: H1 用 useDialog 统一 Modal、ConfirmDialog、Drawer、DeleteThreadDialog（Esc 也由它处理，不再用 useEscape）；PermissionSelect 这类弹出菜单仍用 useEscape，两者共用 escape.ts 的层栈 — 代价：无
Ruling: B4 命中词去掉单字词（到处都是）；服务器没给命中词时退回按空格切查询词 — 代价：单字查询不加粗
Task 15: make test-int 暴露 test_api::test_table_preview_of_an_uploaded_csv 断言整份表格 JSON（D4 多了 columns_truncated）→ 测试补上该字段，通过
Task 15: e2e 新加的 A10 断言写错（页面上还有用户那句话自己的复制按钮）→ 改成只剩 1 个
Final: 独立审查（opus，新上下文）：Critical 0、Important 1（链接或公式里的网址后面同一行的金额变假公式，A14 回退）、Minor 7；报告 scratchpad/review-b1-report.md
Final: Ruling: Minor 1～5 按影响升为 Important（A1 回退、B1 没修完整、H1 删除框还焦点、占位字符与原文冲突、F6 预查没去掉 Mac 元数据）——都是本批自己带进来的回退或没修完整 — 代价：多约 20 分钟
Final: Ruling: Minor 6（文档缺口，计划本就要求）、Minor 7（MCP 页多拉审批规则、可疑记忆两个冒号、图片重试标记跟着元素）也在这一遍修掉——用户要的就是把小问题修干净 — 代价：多约 15 分钟
Final: fixed Important 1 链接或公式里的网址吞掉后面的金额 — math.test 3 条 RED→GREEN（holdLinkDollars 先跳过 "](…)"，裸网址到 { } 为止）
Final: fixed Minor 4 原文里的私用区字符被换掉 — math.test 1 条 RED→GREEN（原文有占位字符时走框架原来的处理）
Final: fixed Minor 1 崩溃那一轮思考显示 1 小时 — reducer.test 1 条 RED→GREEN（closeThinking 只看最后一条用户消息之后）
Final: fixed Minor 2 拖动保存结束时闪回旧顺序 — 新 reorder.ts（reorderMutation 把刷新交回去）+ reorder.test RED→GREEN
Final: fixed Minor 3 删除框关掉后焦点到 body — dialogFocus.focusAfterClose 2 条 RED→GREEN；useDialog 加 returnFocus，ThreadList、ChatHeader 传菜单按钮
Final: fixed Minor 5 技能预查数进 .DS_Store — skills.test 1 条 RED→GREEN
Final: fixed Minor 7 — mcp.toolsChanged 1 条、memoryPart.test 1 条、session.test 1 条 RED→GREEN
Final: Minor 6 文档 — 需求池 R18～R42 状态栏逐行标第一批修了哪几条（R25、R38 完成）、testing.md 纯函数约定、e2e 用量页点会话标题、D19 代价两句、changelog
Final: 全量 make check（664 py、446 web）通过；make e2e 38 passed；make test-int 本轮没改后端，沿用 Task 15 的 331 passed
Final: 部署 12:14（先备份 20261026-121349，make build）；8000 只看核对：标签页标题（对话、会话标题、技能、MCP、设置）、浅色输入框与焦点框 58%、深色 40%、技能页、MCP 页审批规则只取一次、设置页，控制台无报错；没发消息、没点模型测试
第一批完成
