# SDD ledger — plan: docs/plans/2026-10-23-round2-batch3.md

Spec: docs/specs/2026-10-23-optimization-round2-design.md（第 6 节）
执行方式：本会话内执行（方式二），最后一次整体审查。项目无 git：台账即记录。
现状调查：三个只读搜索助手（会话·搜索·导出·归档、插话、记忆·附件·用量）的报告已并入计划。

## Pre-flight
| 生产方 → 使用方 | 接口 | 结论 |
|---|---|---|
| T1 → T2、T3、T4 | `ConversationIndex`（index/retitle/delete_thread/search/around/turn/recent/missing） | 一致 |
| T2 → T10 | 收尾写索引时 user_text 带本轮插话 | T10 补上（计划 T2 写了"任务 9 起"） |
| T7 ↔ T8 | 会话列表查询同时加 archived 过滤与 activity "new" | 不冲突，T8 在 T7 的查询上加 |
| T9 → T10 | `Interjections`、`user.interjected`、`RunFinished.undelivered` | 一致 |
| T11 → T12、T13 | 常驻上限检查 `pinned_room`；可疑检查在 store.add / update 里 | T13 的 update_memory 复用两者 |
| 第二批 T8 → T15 | `ToolRunning` 事件加 name、skill；中间件挪到 McpCallMiddleware 之后 | 一致 |

## Tasks
Task 1: Ruling: 迁移编号按任务顺序：0014 会话索引、0015 会话最后查看时间、0016 知识条目可疑标记、0017 工具用量（计划写的是 0015 会话索引、0014 最后查看时间）— 先做的先编号，链条才接得上 — 错了的代价：无
Task 1: complete (tests: PY -m integration test_conversation_index_contract.py + test_migrations.py → 36 passed; make check 通过)；注：新模块的测试先写好，但第一次运行是在实现之后（缺模块必然导入失败，未单独跑一遍看它失败）
Task 2: complete (tests: PY -m integration test_followups.py + test_seed.py → 19 passed，test_api 改名同步 1 passed；make check → 543 py / 337 web；make test-int → 282 passed)
Task 2: Ruling: 写索引走任务队列（同标题、记忆），排在两者之后；顺利、失败、被停（含等审批时被停）都登记；主智能体没有会话索引时不登记（现有测试不受影响）— 不拖慢收尾、重启后接着做 — 错了的代价：结束到能搜到之间有几秒延迟
Task 2: Ruling: 补建只登记任务、登记完就记 .seeded（任务在库里，中途重启也会接着做）；"回答全文"提成 backend/runs/answers.py 的 answer_text — 错了的代价：无
Task 2: 注：改名同步（router 里 retitle）的实现先于测试写好，测试没单独看它失败
Task 3: complete (tests: PY test_api search 1 passed；WEB vitest search.test.ts 4 passed；make check → 543 py / 341 web)
Task 3: Ruling: 防抖写在结果组件里（useEffect + setTimeout），测试钉住 300 毫秒常量与纯函数；搜索框改叫"搜索会话"（占位"搜索会话标题与内容"）；有字时列表上方标"标题匹配"，服务器找到的已归档会话补在结果区 — 错了的代价：无
Task 4: complete (tests: PY test_conversations_tool.py 4 + test_main_agent 工具绑定 → passed；WEB conversationLinks.test.ts 3 passed；make check → 548 py / 344 web)
Task 4: Ruling: search_conversations 用 action 参数分四种用法；读整轮不截断，前后翻看每段原文最多 4000 字；子智能体也给（只读）；没有会话索引时内置工具清单里不列它 — 错了的代价：无
Task 4: Ruling: 滚到那一轮靠用户消息里一个 data-message-id 的定位点，打开后等 300 毫秒（对话区先自己滚到底）再滚；列表里没有的会话按 ID 取，取的时候显示"加载中…"，取不到才回 /chat — 错了的代价：慢机器上偶尔要等对话区滚完才看到效果
Task 5: complete (tests: PY test_export.py 5 + test_api 导出 1 → passed；WEB ThreadMenu.test.tsx 2 passed；make check 见下一行)
Task 5: Ruling: 导出每轮写"第 N 轮 · 时间"，用户原文、附件名、"助手"下按发生先后排回答段落与工具、审批、产物、报错、"已停止"；子智能体只写"派出子智能体：说明"；文件名把标题里的 \ / : * ? " < > | 换成下划线；前端用临时链接触发下载（靠 Content-Disposition，不离开页面）— 错了的代价：无
Task 5: make check → 553 py / 346 web（含 make types）
Task 6: complete (tests: PY test_api 一步建会话 3 passed；WEB newChat.test.ts 4 passed；make check → 553 py / 345 web)
Task 6: Ruling: 带消息时先校验模型（不对就连会话都不建），之后建会话、设权限、发起运行任何一步失败都删掉刚建的会话再报原因；不带消息时照旧（不校验模型，兼容现有调用）；"建好会话但没发出去时带着原因打开"那条前端路径随之删掉 — 错了的代价：无
Task 6: Ruling: 生成的类型把有默认值的请求字段也标成必填，前端请求参数用 Partial<ThreadCreate> — 错了的代价：无
Task 7: complete (tests: PY test_repos 归档、test_api 归档与看过 → passed；WEB ThreadMenu 归档 1 passed；make check → 553 py / 348 web)
Task 8: complete (tests: PY test_repos 状态点（原测试改为没看过的完成会话亮 new）、test_migrations 0015 → passed；WEB activity new、已归档标签 → passed)
Task 7/8: Ruling: 归档列表按最近改动排；归档的会话也算"有新回答"；"看过了"在打开会话时、以及正看着它跑完时记（先记再刷新列表）；归档、取消归档改完后按 ID 取的那份换成新的，正打开的会话不会跳走 — 错了的代价：无
Task 9: complete (tests: PY agents/tests/test_interjection.py 4 passed；test_api 插话 2 passed；test_openapi 事件集合加 user.interjected → passed)
Task 9: Ruling: 插话队列 Interjections 放在 agents/main_agent/interjections.py，经 agents.main_agent.runtime 公开（后端只用公开入口）；中间件只装在主智能体上，送达时消息前加"（用户在你工作时插话）"并带 additional_kwargs.interjection — 错了的代价：无
Task 10: complete (tests: PY test_manager 剩余插话 3 + test_followups_include_interjections + test_export 插话 → RED→GREEN；WEB reducer 插话 5 + adapter 插话 3 → RED→GREEN；e2e interject.spec.ts 3 passed；make check → 558 py / 356 web；make test-int → 296 passed)
Task 10: Ruling: 前端"已排队"放在 ChatState.queued（不进 items），显示在这一轮末尾；送达事件按原文对上移走第一条；等审批时保留，运行结束时清空 — 错了的代价：同一句话插两次时先移走的是先排的那条，显示上无差别
Task 10: Ruling: 运行中回车由我们先拦下送插话（assistant-ui 运行中不处理回车；没用它的 queue 适配器，那套会自己排队再发新运行，和后端送达的语义不同）；"插话"按钮在停止按钮左边，输入框空着时不能点 — 错了的代价：无
Task 10: Ruling: 没送达的放回输入框只在实时推送（以及"等审批时停止"后按历史取）时做，重放历史不做；放回时放在已输入内容前面；导出 Markdown 把插话单独成段"**你（插话）**：…" — 错了的代价：无
Task 10: Ruling: 端到端测试加慢工具 demo_wait（跑 2 秒）与"等一会儿/改成英文"剧本，三条：送达留在这一轮、没赶上接着发起下一轮、停止后放回输入框 — 错了的代价：无
Task 10: 全量 e2e 36/37 → mcp.spec.ts 钉了演示服务的工具数（加了 demo_wait 后是 3 个），改为 3 后 mcp.spec.ts 5 passed
Task 11: complete (tests: PY test_knowledge_runtime 常驻上限 3 + test_memory_extraction 陈述句 1 → RED→GREEN；test_knowledge_api 上限、文档片段不能常驻 2 → RED→GREEN；WEB filters.test.ts 8 passed；make check → 562 py / 356 web（含 make types）)
Task 11: Ruling: 没给 KnowledgeStore 加 pinned_tokens：pinned_room 用已有的 pinned() 求和（常驻条目本来就少），省掉两个实现与契约的改动；pinned_room 收内容自己估 token（与 PG 实现记 token_count 同一个估算）— 错了的代价：常驻条目很多时多读几行
Task 11: Ruling: 超限用 409（与当前常驻冲突）、文档片段设常驻用 422；remember 超限时工具结果"没有记住：<拒绝原文>"；页面上改了常驻条目内容（变长）也检查，改的那条原来的大小不算 — 错了的代价：无
Task 11: Ruling: 提示词里"常驻信息已用 X / 上限 token。"单独一行放在资料说明之后、"常驻信息（关于用户、始终有效）："之前；没有常驻时整段不出现 — 错了的代价：无
Task 12: complete (tests: PY test_suspicious 21（五类中英各一 + 11 句正常的不误伤）、契约 3（两种实现标记与检索、文档片段不查、PG 召回）、运行时 2、提取 1、接口 1、迁移 0016 1 → RED→GREEN；WEB KnowledgeItemCard.test.tsx 2 → RED→GREEN；make check → 586 py / 358 web；make test-int → 305 passed)
Task 12: Ruling: 只查记忆，不查文档片段（讲提示词注入的文档里出现这些话很正常，查了会让文档检索不到）；可疑模式只认针对智能体的说法（"执行以下命令"、"把聊天记录发到 邮箱/网址"），不认"运行脚本""上传文件"这类正常个人信息 — 错了的代价：换个说法的注入漏网（仍有资料标记与转义兜底）
Task 12: Ruling: pinned() 照常返回可疑的常驻（知识库页要显示它们），拼提示词与提取时跳过；可疑的常驻仍占常驻额度（"已用 X"按全部常驻算，与 pinned_room 一致）；remember 记下可疑内容时工具结果说明"标为可疑，确认前不会用上" — 错了的代价：无
Task 12: Ruling: 两个旧测试（伪造结束标记的转义）原内容会被标为可疑而进不了提示词；改为先"确认无害"再验证转义照样生效（两道防线都在）— 错了的代价：无
Task 13: complete (tests: PY 契约 find_memories 1、运行时 4（唯一命中改、多条给候选、只删记忆不碰文档片段且找不到时说明、改内容过常驻上限与可疑检查）、test_main_agent 子智能体没有三个写记忆工具、test_subagents 提示词、test_export 工具中文名（收紧：不能退成"外部工具"）→ RED→GREEN；WEB tools.test.ts 4 → RED→GREEN；make check → 590 py / 362 web；make test-int → 307 passed)
Task 13: Ruling: 找不到、对上不止一条都作为工具出错返回（这一步没做成），候选最多 5 条、每条开头 60 字，候选包进 <资料> 并转义；不分大小写；可疑的记忆也找得到（用户可能要忘掉它）— 错了的代价：无
Task 13: Ruling: 原有的工具名单测试会把带下划线的内置工具名当 MCP 工具（"外部工具"）而照样通过，收紧为不能退成"外部工具"；前端顺手补上原来缺的 delete（"删除文件"，与导出一致）；更正、忘掉单独一类 memory_change（合计说"更正或忘掉了 N 条记忆"）— 错了的代价：无
Task 13: 部署注意：新工具改变工具指纹，升级前处理掉停在审批处的运行（Task 16 升级步骤里做）
Task 14: complete (tests: PY test_attachments 提示 2 + 原测试改为带提示、test_subagents 系统提示词与数据分析员各一句 → RED→GREEN；16 passed)
Task 14: Ruling: 按扩展名（不分大小写）判断，几个附件只提示一次；确认过执行命令的 PATH 含虚拟环境 bin（local_sandbox._environment），markitdown 命令行可直接用 — 错了的代价：无
Task 15: complete (tests: PY test_tool_running 8（读技能记技能名、分页往下读不记、只认 read_file）、test_translator 2、test_approvals_runtime 暂停挡下的不推 tool.running、test_usage_repo 2（按名汇总、跟时间范围）、test_usage_api 一次运行三个工具记三行 + 技能、迁移 0017 → RED→GREEN；WEB CountTable 2 + toolUsageLabel 1 → RED→GREEN；make check → 601 py / 365 web；make test-int → 311 passed)
Task 15: Ruling: 工具用量写在已有的 UsageRepo 上（add_tool_use，summary 加 by_tool、by_skill），不另建 ToolUsageRepo：运行管理不多一个依赖；表的时间列叫 created_at（同 llm_usage，按时区算范围的条件共用）— 错了的代价：无
Task 15: Ruling: 派出子智能体（task）不记工具用量（恢复审批时它会重新执行一遍，原本就不推 tool.running）；子智能体内部的工具照记；ToolRunning 的 name、skill 给默认值（旧历史没有）— 错了的代价：用量页看不到派了几次子智能体
Task 15: Ruling: 用量页的工具名用对话里工具行的中文说法，后面跟原名；两张表在"这段时间没有调用模型"时不显示（有工具调用必有模型调用）— 错了的代价：无
暂停（用户 19:01）：第三批 16 个任务完成（make check 601/365、test-int 311、e2e 37），文档已写；独立审查已派出、结果未处理；未修复、未升级部署、8000 未核对。第四批只做了只读调研（未写计划）。恢复后从"处理审查结果"接着做。
Final review: opus 独立审查完成（Critical 0，Important 3，Minor 18；结论：修完 Important 再部署）；报告存在 scratchpad/review3-report.md，探针在 scratchpad/review3/。暂停中，尚未处理。
恢复（用户 10-24 02:45 说继续）：开始处理审查结果
Final: Ruling: 重新定级（按对使用者的影响）——进修复的：I1 可疑误报（连同 Minor 11 中英紧挨绕过、Minor 12 长文本卡住事件循环，同一处正则重写）、I2 会话搜索人名搜不到、I3 归档会话里删除后页面不动、Minor 1 审批后"已排队"消失（会让人重发）、Minor 2 Safari 输入法回车送出半句插话、Minor 3 搜索超过 200 字永远"搜索失败"、Minor 4 删会话与写索引撞上留下能搜到的已删内容、Minor 9 不在页面时没送达的插话在历史里看不见（用户输入悄悄丢失）、Minor 13 更正/忘掉成功时把（可能是注入的）原文不加资料标记回显给模型
Final: minor (deferred): Minor 5 补建中途被停后重跑会把被重试掉的一轮写回；Minor 6 崩溃中断的运行不进索引；Minor 10 归档列表不显示"有新回答"；Minor 14 派出子智能体不计入工具用量；Minor 15 补建与标题、记忆提取共用一条任务队列；Minor 16 搜索结果加粗只按空格切词；Minor 17 search_conversations 合计说成"检索了 N 次知识库"
Final: fixed I1 可疑误报（连同 Minor 11 绕过、Minor 12 长文本耗时）→ 规则重写：往外发信息只认"把聊天记录 / 密码这类东西发到邮箱网址"与对智能体说"请 / 你把……发到"；冒充系统只认【系统】【系统消息】等、"系统提示："、让"你"进入管理员模式、"你是 DAN"；执行命令只认"以下 / 下面"的命令与"执行 / 运行 + 危险命令"；英文词边界改为"前后不是英文字母数字"；去掉零宽字符再查；各段长度设上限、邮箱用 ASCII 字符类（2 万字从 5.5 秒降到约 10 毫秒）；知识库页加"可疑（N）"视图（store.list_items(flagged=)、GET /api/knowledge/items?suspicious=true）— test_suspicious.py 新增 12 句误报、10 句漏报、4 条耗时，契约 test_list_only_suspicious_memories、接口 test_suspicious_view_lists_only_flagged_memories、WEB filters.test 3 → RED→GREEN（57 + 37 + 21 passed）；审查探针复跑：误报只剩"curl … | sh 装 uv"（按设计就算可疑），注入全部认出
Final: Ruling: 规则已是线性时间（2 万字约 10 毫秒），没再改成在线程里调用 — 错了的代价：写入一条很长的记忆时事件循环多停几毫秒
Final: fixed I2 会话搜索人名搜不到 → 除分词全文检索外再按原文整段查（ILIKE，转义同 search_titles），整段出现的排前面，两路合并去重；替身同样处理 — 契约 test_names_glued_to_neighbors_are_found、test_whole_query_in_the_text_comes_first（pg、替身各一）RED→GREEN（30 passed）
Final: fixed I3 在已归档会话里删除后页面不走、归档列表不更新 → 新函数 threads/cache.forgetThread（从列表移除、按 ID 取的那份与归档列表都标为要重查；查不到时对话页按已有逻辑回 /chat），对话顶栏与会话列表两处删除都用它 — WEB cache.test.ts 新增 1 RED→GREEN（29 passed）；部署后在 8000 用自建的空会话实测
Final: fixed Minor1→I 运行开始、审批通过时排队的插话被清掉 → reducer 的 run.started / approval.required / approval.resolved 都用 keepQueued 带上 — WEB reducer.test 新增 1 RED→GREEN（47 passed）
Final: fixed Minor2→I Safari 输入法确认候选词的回车被当成插话送出 → 抽出 components/chat/interjectKey.sendsInterjection，用项目已有的 isImeComposing（认 keyCode 229）— WEB interjectKey.test.ts 3 RED（找不到模块）→GREEN
Final: fixed Minor3→I 搜索词超过 200 字时 422、界面一直"搜索失败" → 接口截到前 200 字照常搜（参数上限放宽到 1 万字防滥用）— test_long_search_query_is_cut_not_refused RED→GREEN
Final: fixed Minor4→I 删会话与写索引撞上留下能搜到的已删内容 → 写索引任务写完再查会话，不在就删掉这一行；删会话最后再删一次索引（覆盖写入落在"删索引之后、删会话之前"的情形）— test_followups 新增 test_index_written_after_the_thread_is_deleted_is_dropped、test_index_written_while_the_thread_is_being_deleted_is_dropped RED→GREEN
Final: fixed Minor9→I 不在页面上时没送达的插话在历史里看不见 → reducer 处理 run.finished 的 undelivered：在这一轮末尾加"没送达"的插话行（实时、重放都显示；页面开着时照旧放回输入框）— WEB reducer.test、adapter.test 各 1 RED→GREEN（76 passed）
Final: fixed Minor13→I 忘掉记忆成功时原文不加资料标记回显 → 包进 <资料> 并转义（同检索结果）— test_forgetting_a_suspicious_memory_does_not_hand_it_back_as_is RED→GREEN，原测试改为资料格式（32 passed）
Final: fixed Minor7→I 收尾写库失败时剩下的插话被悄悄吞掉 → 失败分支把它们放进结束事件的 undelivered 退回界面 — test_leftover_is_returned_when_saving_the_run_fails RED→GREEN
Final: fixed Minor8→I 发起运行后更新会话时间失败会让调用方以为没发起（插话接续退回后再发会做两遍；一步建会话返回 500 还删不掉）→ start 里这一步失败只记日志 — test_started_run_is_returned_even_if_bookkeeping_fails RED→GREEN（manager 45 passed）
Final: minor (deferred): Minor 18 服务停止恰好落在收尾时仍会用插话接着发起下一轮（窗口极小，难以稳定复现）；聊天里"已记住"不标出可疑（知识库页已有"可疑"视图）
Task 16 Step 5（8000，第一次）：迁移到 0017；补建登记 20 次运行，索引 20 行、任务清空；旧条目未标可疑；搜索框"香格里拉"标题无、内容 2 处；导出接口 200、17 轮；知识库页四个页签、常驻 0/2000；用量页工具、技能"这段时间没有"；自建空会话归档 → 已归档（1）→ 取消归档 → 再归档 → 在里面删除 → 回到 /chat、已归档消失（I3 修复实测通过）
Final: fixed（8000 实测发现）长对话里点搜索结果跳不到那一轮：300 毫秒后滚一次会被对话区渲染完后的"自动滚到底"盖掉 → features/chat/scrollToTurn.keepScrolledTo：每 200 毫秒看一次，不在视口就再滚，连续两次在视口就停，最多 3 秒，用户滚动或按键就不管 — WEB scrollToTurn.test.ts 4 RED（找不到模块）→GREEN
Final: fixed（8000 实测发现）导出 Markdown 每轮的时间按 UTC 写（北京时间 11:01 写成 03:01）→ 导出接口加 tz（同用量页，不认识的时区 422），前端带上浏览器时区 — test_turn_times_are_in_the_given_timezone、test_export_downloads_markdown 加时区、WEB ThreadMenu.test exportUrl RED→GREEN
Final: minor (deferred): 删除确认框里新会话的名字显示成空的「」（应为"新会话"）
Final: fixed（8000 复查发现）后端刚重启后第一次打开长对话，3 秒内那一轮还没渲染出来就放弃了 → 改为那一轮出现后再管 3 秒、最多等它出现 10 秒 — WEB scrollToTurn.test 新增 2（1 RED→GREEN），5 passed；导出时间 8000 复查为 11:01（北京时间）
Task 16 Step 5（8000，最终）：部署 3 次（最后一次 03:20）；长对话点搜索结果、后端刚重启后第一次打开都停在那一轮；导出第 1 轮 11:01（北京时间）
Task 16: complete（make check → Python 639 / 前端 380；make test-int → 323；make e2e → 37；备份 20261024-030639；迁移 0014～0017；会话索引补建 20 轮）
