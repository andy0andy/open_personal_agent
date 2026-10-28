# SDD ledger — plan: docs/plans/2026-10-22-frontend-ui-optimization.md
Spec: docs/specs/2026-10-22-frontend-ui-optimization-design.md（用户 2026-10-22 授权：中途不审批，按最优解实施，最后汇报选择）
Setup: 项目没有 git——不建工作树、不提交；改动前整体快照 ../open_personal_agent-snapshots/20261022-before-ui/project.tar.gz（frontend 不含 node_modules/dist、backend、docs、Makefile）。每个任务的完成记录写"tests: 命令 → 结果"，没有 commit 范围。
Pre-flight:
- 任务 3 → 任务 4：Thread.activity（Literal running/waiting/failed | None）对上 threadActivity(Pick<Thread,"activity">)；任务 4 要求缺失或 null 时为空，任务 3 默认 None：一致。
- 任务 2 → 任务 4/11/13：StatusDot({tone, pulse, label})；任务 13 的 serverStatus 用 tone "success"|"info"|"danger"|"idle"，StatusDot 的 tone 含 "success" 与 "idle"：一致。
- 任务 6 → 任务 7：toolLabel(name,args) → {verb, detail, kind}；任务 7 的 approvalTitle 用 verb/detail：一致。
- 任务 8 → 任务 9：任务 9"运行已结束时进行中的项显示未完成"要知道消息是否在运行——用任务 8 的 MessageRunningContext（任务 9 的 Interfaces 没写出来，这里补上）。
- 任务 5 → 任务 11：ComposerToolbar 去掉文件按钮；落地页直接用 PermissionSelect 与 ModelSelect，不用 ComposerToolbar：无冲突。
- 任务 6 ↔ 任务 8：任务 8 把 reasoning 片段换成 data-thinking；任务 6 的分组只对 tool-call，思考片段不参与分组：无冲突。
Task 1: Ruling: 15 处 outline-none 都保留——外层都有替代的聚焦提示（输入框外框变色、ModelSelect 外层 focus-within 描边、菜单项 focus-visible 底色）；全局 :focus-visible 管其余按钮与链接 — 代价：无。
Task 1: complete (tests: vitest src/themes src/styles → 12 passed（先红 5 条：浅色对比度与缺字段）；make check → pytest 347 passed/1 skipped（原有）、前端 209 passed)
Task 2: Ruling: 侧栏不写单元测试 — 单测是 node 环境、看不到响应式与悬停，靠端到端（侧栏按名字点链接）与任务 14 的截图核对 — 代价：窄屏图标栏若有问题要到任务 14 才发现。
Task 2: Ruling: 外观切换在侧栏只显示图标时竖着排（计划未写） — 56px 宽放不下三个横排按钮 — 代价：无。
Task 2: Ruling: 输入框聚焦不再改边框色，统一用全局 :focus-visible 焦点框；保留 bg-background（下拉框在深色下才不会出白底） — 少一套聚焦写法 — 代价：焦点框比原来醒目一些。
Task 2: complete (tests: vitest src/components/ui → 10 passed（先红 6 条）；make check → pytest 347 passed/1 skipped、前端 215 passed；make e2e → 31 passed)
Task 3: complete (tests: pytest -m integration test_repos.py -k activity → 先红（Thread 没有 activity）后绿；test_repos.py 11 passed；make types；make check → pytest 347 passed/1 skipped、前端 215 passed；make test-int → 234 passed)
Task 4: Ruling: 没有标题的会话按显示出来的"新会话"参与搜索 — 用户搜的是看到的字 — 代价：无。
Task 4: Ruling: 新增 cache.ts 的 replaceThread，改名、改会话设置后保留列表里的 activity（计划未写） — 其他接口 activity 为空，直接替换会让状态点闪掉 5 秒 — 代价：无。
Task 4: Ruling: 收到 approval.required / run.finished 时立刻刷新会话列表（计划只写了 5 秒轮询） — 当前会话的状态点不用等下一次轮询 — 代价：每次运行多两次列表请求。
Task 4: Ruling: 行右侧的状态字 / 时间在悬停或聚焦时让位给"⋯"按钮；列表行的焦点框往里画（-outline-offset-2） — 列表在滚动容器里，往外画会被裁掉 — 代价：无。
Task 4: complete (tests: vitest src/features/threads src/api → 43 passed（先红 12 条）；make check → pytest 347 passed/1 skipped、前端 227 passed；make e2e → 31 passed)
Task 5: Ruling: 对话列宽度保持 max-w-3xl（48rem）+ px-6，不改成计划写的 max-w-[45rem] — 内边距在宽度里面，现有写法的正文宽度正好 720px（设计 2.3），照计划改会变成 672px — 代价：无。
Task 5: Ruling: 会话列表栏宽 240 → 280px（设计稿取值，规格没写） — 标题 + 状态字 + 时间要放得下 — 代价：1024 宽时对话区少 40px。
Task 5: Ruling: 顶栏改名在顶栏里原地编辑；"更多"按钮名"更多操作"（与列表行一致）；没有消息时副标题写"还没有对话" — 规格只写了"N 轮" — 代价：无。
Task 5: complete (tests: vitest src/features/chat/context.test.ts → 4 passed（先红 4 条）；make check-web → 前端 231 passed（本任务没改 Python，Python 部分上一次 make check 已通过）)
Task 6: Ruling: 事件处理器给工具记起止时间（取事件时间 ts），等过审批的记 waited、不显示用时 — 计划要"用时"但原来没有数据；等审批的时间不该算进工具用时 — 代价：工具条目多三个字段。
Task 6: Ruling: 工具行与工具组放在新文件 components/chat/toolLine.tsx（计划写在 parts.tsx） — parts.tsx 已有 500 行 — 代价：无。
Task 6: Ruling: 展开后只有写入 / 外部 / 不认识的工具显示参数 JSON；读取、查找、检索、记忆、待办只显示输出 — 摘要已说清楚参数；写入的内容仍要看得到 — 代价：读文件的 offset/limit 看不到。
Task 6: Ruling: 工具组的摘要行有出错时追加"N 个出错"（危险色） — 收起时也看得到失败 — 代价：无。
Task 6: Ruling: 子智能体内部的工具也用中文名 + 摘要 — 与主对话一致 — 代价：无。
Task 6: complete (tests: vitest tools.test.ts + toolLine.test.tsx → 25 passed（先红 24 条）；reducer.test.ts 先红 3 条后绿；make check-web → 前端 257 passed；make e2e → 31 passed)
Task 7: Ruling: 审批标题的写法：外部工具"要调用 服务 · 工具 吗？"、内置工具"要<动词>吗？"（如"要写入文件吗？"）、不认识的"要调用 <原名> 吗？"，不照计划拼成"要调用写入文件 /a 吗？" — 规格写的是"要调用 X 吗？"，计划的拼法读起来别扭；参数在下面的等宽块里 — 代价：无。
Task 7: Ruling: "回复一句话"的决定用中性色（不是危险色） — 它是改道而不是出错 — 代价：无。
Task 7: Ruling: 处理完的审批，工具不在这一层（如子智能体里的工具）时保留一行结果，不收进工具行 — 否则决定会看不到 — 代价：这类情况仍多一行。
Task 7: Ruling: 正在修改参数或写回复时按 Esc 只退回按钮，不当作拒绝 — 防止误拒 — 代价：无。
Task 7: Ruling: 拒绝、回复、停止的工具行只写决定，不再另写"出错""已中断" — 它们本来就没执行 — 代价：无。
Task 7: complete (tests: vitest src/components/chat src/features/chat → 138 passed（先红 13 条）；make check → pytest 347 passed/1 skipped；make check-web → 前端 271 passed；make e2e → 31 passed（新增：卡片出现时焦点在"同意"、处理完卡片收起）)
Task 8: Ruling: 思考的开始时间取"上一个事件的时间"（ChatState 新增 clock），不是计划写的"第一段思考的时间" — 界面历史把逐字片段合并成一个、时间留的是最后一段，照计划算历史里会显示"思考了 0 秒"；从上一个事件算起实时与重放一致，也算上了模型开始输出前的等待 — 代价：用时比纯思考略长（含首字等待）。
Task 8: Ruling: 不到 1 秒写"思考了不到 1 秒"，超过 60 秒写"思考了 1 分 15 秒" — 计划只写了"N 秒" — 代价：无。
Task 8: Ruling: 折叠的代码块用 CSS 按代码自己的行高限高（16lh）+ 底部渐隐，按钮放在 pre 里 — 包一层 div 会破坏"标题栏 + 代码"连成一个框的样式 — 代价：老浏览器不认 lh 单位时不折叠（只是不折叠，不影响阅读）。
Task 8: complete (tests: vitest reducer/adapter/code → 先红 8 条后绿；make check-web → 前端 276 passed（本任务没改 Python）；make e2e → 31 passed)
Task 9: Ruling: lastUserText 改为 lastUserMessage（连同附件），"重试这一句"原样带上那条消息的文件 — 只重发文字会丢掉原来带的表格、图片 — 代价：send 多一个可选参数。
Task 9: Ruling: 对话流里的待办"未完成"按"这一轮是否还在进行"判断（回答在输出，或有待审批的卡片），不只看回答在不在输出 — 等审批时这一轮并没有结束 — 代价：无。
Task 9: Ruling: 报错卡片的"重试这一句""换个模型再试"只在最后一轮出错时出现；"复制详情"总在 — 重试早先某一轮会重发最新那句，容易误会 — 代价：要重试更早的那句得自己复制。
Task 9: Ruling: 进行中的待办转圈图标用"运行中"的蓝色（原来是琥珀） — 颜色只表示状态（设计 2.1：琥珀 = 等你处理） — 代价：无。
Task 9: complete (tests: vitest todos.test.ts + retry.test.ts → 先红 7 条后绿，附件再红 2 条后绿；make check-web → 前端 283 passed；make e2e → 31 passed)
Task 10: Ruling: 离开会话时把还没来得及保存（400ms 内）的草稿也存上；只有空白的草稿当作空 — 切得快也不丢字 — 代价：无。
Task 10: Ruling: 粘贴的截图保留浏览器给的文件名（image.png） — 后端同名会自动加"(2)"，不用前端改名 — 代价：文件名不够直观。
Task 10: complete (tests: vitest drafts.test.ts + uploads.test.ts → 先红 5 条后绿；make check-web → 前端 288 passed；make e2e → 32 passed（新增"草稿：切到别的会话再回来"）)
Task 11: Ruling: startNewChat 返回 { thread, error }（计划写 { threadId, error }） — 页面要先把新会话放进会话列表再跳转，否则对话页找不到会话会退回 /chat — 代价：无。
Task 11: Ruling: 落地页组件文件叫 NewChatLanding.tsx（计划写 NewChat.tsx） — macOS 文件名不分大小写，与 newChat.ts 冲突 — 代价：无。
Task 11: Ruling: 落地页输入框用不同的提示文字"想做点什么？"、名称"新会话的第一条消息" — 端到端的 newThread 等用"给智能体发消息…"找输入框，同名会抢先匹配到落地页 — 代价：无。
Task 11: Ruling: 发消息失败时用路由状态把原因带给新会话页；"最近的会话"按更新时间取前 3 个（不按手动顺序） — "最近"指最近用过 — 代价：刷新页面时那条原因会再显示一次。
Task 11: complete (tests: vitest newChat.test.ts → 先红 4 条后绿；make check-web → 前端 292 passed；make e2e → 33 passed（空状态文字改为"今天想做点什么？"，新增"落地页直接发消息"）)
Task 12: Ruling: 设置页分节：对话与模型、工作区、知识库、只读项（页面上不能改的，如向量模型、各接口的实现、模型来源）、.workdata 文件；.env 指定的项留在原来那节、写明变量名 — 规格的分节；原来的"实现与来源"并入只读项 — 代价：无。
Task 12: Ruling: 生效时机每节一句；同一节里有立即生效的项时，那几项另标"立即生效" — 对话与模型这一节两种都有 — 代价：无。
Task 12: Ruling: 分节导航用按钮滚动到对应卡片（不用 #锚点改地址），窄于 768px 时隐藏 — 地址不变、刷新不乱跳 — 代价：没法用链接直达某一节。
Task 12: Ruling: 去掉每行的"默认 / 已改 / 环境变量"来源标签与"重启后生效（终端执行 make restart）"整句，改为行内"已改""已改 · 待重启"徽章 + 页顶提示条 — 规格要求生效时机每节说一次 — 代价：无（端到端要的"已保存，重启后生效""已改"文字仍在行内）。
Task 12: complete (tests: vitest settings.test.ts → 先红 4 条后绿；make check-web → 前端 293 passed；端到端放到任务 13 一起跑)
Task 13: Ruling: 用量图纵轴顶端取 1.5、3、6 × 10ⁿ（计划写 1、2、5 × 10ⁿ），全为 0 时顶端为 3 — 三等分刻度要是整数（如 600k、400k、200k），1、2、5 三等分会出现 333.3k — 代价：柱子最高可能只到图高的一半左右。
Task 13: Ruling: MCP 列表没有"测试"按钮（探测在编辑抽屉里），不在行下加测试结果；没连上的原因写在行下（缺环境变量时说怎么补） — 规格写"测试结果显示在行下"，但列表本来没有测试 — 代价：无。
Task 13: Ruling: 模型的"测试"进行中按钮显示"测试中…"并停用；删除按钮停用时说明原因（默认对话模型 / 在用的向量模型） — 规格要求说明原因 — 代价：无。
Task 13: Ruling: 用量页副标题不写"不算费用" — 旧规则（设计 2026-10-19 4.11）要求页面不出现"费用"二字，端到端在守 — 代价：无。
Task 13: complete (tests: vitest mcp.test.ts + summary.test.ts → 先红 4 条后绿；make check → pytest 347 passed/1 skipped、前端 295 passed；make e2e → 33 passed（第一次 1 条失败：副标题含"费用"，已改）)
Task 14: Ruling: 审批卡片执行命令下的那句说明改为"在本会话的目录里运行，能上网，也能读到项目里的大部分文件、连到本项目的数据库"（规格原写"能读写会话里的文件"，规格里一并注明更正） — 去掉沙箱后（D20、D23）命令碰得到的不止会话文件，原句把风险说轻了，与使用指南矛盾 — 代价：卡片多几个字。
Task 14: Ruling: 看样式改用无界面 Playwright 截图（1440 深浅、1024 深色，8 个页面），不用内置浏览器 — 内置浏览器面板只有 800 宽，只截得到一角 — 代价：无（同样只读：只打开页面，不点按钮、不发消息）。
Task 14: complete (docs: usage.md、changelog、backlog R37、architecture、docs/README 索引、规格更正；tests: make check → pytest 347 passed/1 skipped、前端 295 passed；make test-int → 234 passed；make e2e → 33 passed；make build → 8000 健康、会话列表带 activity；截图对照设计稿一致)
Final review: opus 整体审查（只读，看了全部改动、跑了单测、在 8000 只读查看并写脚本复现）→ With fixes：1 严重、4 重要、14 次要。
Final: re-grade：审查的第 6 条（工具组把拒绝算成出错）由次要提为重要——红色"N 个出错"在没出错时出现，颜色只表示状态的约定被打破，用户会以为出了事。其余次要维持次要。
Final: fixed 审批卡片抢焦点（打字时一个空格或回车就"同意"） — e2e approval.spec "审批：同意后接着做完" 改为断言输入框保持焦点 RED→GREEN，suite 33/33
Final: fixed 长输出看不到退出码 — test_translator.py::test_long_command_output_keeps_exit_status_line RED→GREEN；toolLine.test "命令失败（退出码不是 0）收起时也看得出来" RED→GREEN，suite pytest 348/348（1 skipped）、vitest 300/300
Final: fixed 用量图悬停浮层被卡片裁掉日期 — e2e pages.spec "用量页" 加浮层位置断言 RED→GREEN，suite 33/33
Final: fixed 从 Excel、Word 粘贴变成上传图片 — uploads.test "从 Excel、Word 复制的内容……按文字粘贴" RED→GREEN（另加"非图片文件照样当附件"）
Final: fixed 落地页发出第一句后会话列表不刷新 — newChat.test "放进会话列表，并让列表马上刷新" RED→GREEN
Final: fixed 工具组把拒绝算成出错 — toolLine.test "工具组的出错数不算拒绝、回复、停止的" RED→GREEN
Final: Ruling: 长输出保留退出码需要在后端多改一处（translator 截断时留下末尾状态行），规格原写"后端只改一处"——用户授权按最优解决定，这处改动小、只影响执行命令的长输出，规格已注明 — 代价：推送给前端的长输出中间多一个"…"。
Final: Ruling: 审批卡片干脆不自动聚焦（不做"不在输入框里才聚焦"之类的判断） — 任何自动挪焦点都可能让正在按键的人误点"同意"；键盘用户用 Tab 进卡片，Esc 拒绝、回车按当前按钮照常 — 代价：键盘用户多按几次 Tab。
Final: Ruling（审查未评项）: 有会话在等审批时列表一直每 5 秒刷新 — 规格 3.1 明确要求；本机请求很轻 — 代价：挂着审批的那几天里浏览器一直在后台请求列表。
Final: Ruling（审查未评项）: 红色出错点要等下一次运行成功才消失 — 规格第 5 节按最近一次运行算，"最近一次失败了"就是用户该看到的 — 代价：放弃的会话一直挂着红点。
Final: Ruling（审查未评项）: 思考秒数含首字等待 — 见任务 8 的裁决 — 代价：比纯思考略长。
Final: Ruling（审查未评项）: 规格第 6 节不做的项（跳过审批不弹确认、全文搜索、按日期分组、窄屏抽屉、文件面板与知识库页改版） — 用户认可的范围 — 代价：无。
Final: Ruling（审查未评项）: MCP 行下不显示测试结果 — 列表没有测试按钮（任务 13 裁决） — 代价：无。
Final: Ruling（审查未评项）: tools.ts 放在 components/chat、被 features/chat 引用 — 计划指定，已有同类先例 — 代价：无。
Final: Ruling（审查未评项）: 用量图 90 天时有 90 个 Tab 停留点 — 规格要求柱子能聚焦；改成方向键切换留到以后 — 代价：键盘用户在 90 天视图里要按很多次 Tab。
Final: Ruling（审查未评项）: 审批卡片对执行命令只显示命令、不显示 timeout 等参数 — 规格"命令用等宽块显示"，timeout 不改变命令做什么；要看可选"修改后执行" — 代价：无。
Final: Ruling（审查未评项）: "换个模型再试"会把会话的模型改掉 — 规格 3.8 原文如此，之后的消息也用新模型才合理 — 代价：想只试一次的人要再改回来。
Final: Ruling（审查未评项）: 删除会话后它的草稿留在浏览器本地存储 — 每条几百字节 — 代价：可忽略。
Final: minor (deferred): 同一段思考中间夹进同层事件（如用量）后会一直显示"思考中…"直到运行结束（20 次真实运行里没遇到）；clock 是全局的，并行子智能体内部思考的起点实时与重放不一致（子智能体里不显示秒数）
Final: minor (deferred): 刷新 /chat/<会话ID> 时先闪一下落地页；会话列表加载失败时停在落地页
Final: minor (deferred): 落地页带过去的失败原因，刷新或后退后会再出现一次
Final: minor (deferred): 落地页发送失败且浏览器不让用本地存储时，写的字会丢
Final: minor (deferred): 子智能体里的审批处理完后，很长的"已回复：…"会撑出横向滚动条
Final: minor (deferred): 审批卡片写回复、改参数时与顶栏改名时，输入法选字中按 Esc 会直接收起输入框
Final: minor (deferred): 读屏与键盘：一张卡里有多个操作时，选完第一个后焦点掉到页面最外层
Final: minor (deferred): 浅色下几处图形对比度低于 3:1——焦点框 2.5、关着的开关滑块对轨道 2.0、输入框边框 2.0、用量图输入柱与输出柱只靠颜色区分（改要动规格数值）
Final: minor (deferred): 设置页里被 .env 覆盖的只读项（adapters.*、models.sources）会整项不显示
Final: minor (deferred): 拖动排序保存还没返回时，5 秒轮询可能带回旧顺序，列表跳一下
Final: minor (deferred): 共用组件 Tabs（等宽大写）、Modal 与 ConfirmDialog（直角）没跟着改
Final: minor (deferred): "换个模型再试"的菜单声明成菜单却不能用方向键
Final: minor (deferred): 测试缺口：工具组摘要的"正在…"、草稿去抖保存与发送失败恢复（只有端到端）、同层事件夹在思考中间
Final: suite after fix pass — make check-web 300 passed、pytest 348 passed/1 skipped、make test-int 234 passed、make e2e 33 passed；make build 后 8000 健康
