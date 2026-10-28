# SDD ledger — plan: docs/plans/2026-10-23-round2-batch1.md

Spec: docs/specs/2026-10-23-optimization-round2-design.md（第 4 节）
执行方式：本会话内执行（方式二），最后一次整体审查。项目无 git：没有提交与 BASE，台账即记录。

## Pre-flight
| 生产方 → 使用方 | 接口 | 结论 |
|---|---|---|
| T2 → T3 | 系统提示词每轮不变（相关记忆挪进用户消息） | 一致：T3 只依赖结果，不依赖名字 |
| T2 → T7 | `user_words(text)` | 一致 |
| T2 → T8 | `MATERIAL_NOTE`、`split_related(text)` | 一致 |
| T5 → T6 | `RunFinished.retryable`、报错项 `runId / errorKind / retryable` | 一致 |
| T4 ↔ T7 | `estimate_input_tokens` 同为真实分词器 | 一致 |

## Tasks
Task 1: complete (tests: PY agents/tests/test_quota.py → 16 passed; ruff ok)
Task 2: Ruling: system.md 第 19 行"而末尾没有列出时"也改成"而常驻信息和系统附加的记忆里都没有时" — 相关记忆已不在提示末尾，原句会让模型以为召回为空 — 代价：一句提示词措辞
Task 2: Ruling: `_related_prefix` 召回到结果后才查一次常驻条目（去重用），没召回到不查 — 少一次查询；`_profile_prompt` 每段运行都查 — 代价：每轮多一次常驻条目查询（本来就有）
Task 2: complete (tests: PY agents/tests/test_knowledge_runtime.py → 22 passed; agents 单测 267 passed; make check → 通过)
Task 3: Ruling: 网关的两条缓存测试放进契约测试 agents/tests/contracts/test_model_gateway_contract.py（复用其中的 _Recorder），不放 test_litellm_proxy.py — 这是网关接口的约定 — 代价：无
Task 3: Ruling: `ModelAdmin.enable_prompt_caching()` 返回 tuple[str, ...] — 类里有名为 list 的方法，挡住了 list[str] 注解 — 代价：无
Task 3: 说明：后端两条集成测试没有单独先跑一遍看失败（导入 enable_prompt_caching_once / 读 spec.supports_prompt_caching 在实现前必然失败）；契约测试与前端测试都先看过 FAIL
Task 3: smoke 先验 test_prompt_caching_request_level → PASS：第 1 次 input 8608、cache_creation 8605；第 2 次 cache_read 8605。公司网关转发缓存标记，默认打开不变。花费约 0.06 美元（8605×6.25/M + 8605×0.5/M）
Task 3: complete (tests: 契约 13 passed；backend seed/models 集成 18 passed；WEB vitest src/features/models 13 passed；make check → 通过)
Task 4: Ruling: 被放弃的那次请求（重发前卡住的）不另做估算、也不显示 — 设计说"不写进用量表、界面不单独显示重试过"；同一次模型调用只有一次开始/结束回调，重发成功后用量按成功那次记 — 代价：卡住那次上游若计费，用量页少算一次输入
Task 4: Ruling: config/models.yaml 的 router_settings.num_retries 要 `make restart-gateway` 才生效，放到任务 10 升级时一起做 — 代价：无
Task 4: complete (tests: PY agents/tests/test_litellm_proxy.py → 8 passed（先看过 3 条按行为失败：不重发 / 客户端重发 3 次）；make check → 通过)
Task 5: Ruling: 只有"失败"在没有输出时也写中断说明；"停止"没有输出时照旧不写 — 停止时 agent 分不清用户停止还是停机，原因本来就是"用户停止或服务中断"，下一轮补上的通用说明即真实原因；少碰一条取消路径 — 代价：无
Task 5: Ruling: 停机测试并进原有 test_shutdown_interrupts_runs_and_records_reason（断言 error_kind），重启补发的结束事件并进 test_api 两条 replay 测试，没有另起计划里的两个新名字 — 代价：无
Task 5: Ruling: 原 test_failure_without_output_writes_nothing 改成 test_failure_without_output_notes_the_real_reason（设计 4.5 要求的新行为）；test_event_bus 的结束事件字段全集多两个字段 — 代价：无
Task 5: 说明：后端两处（停机、补发）没有单独先看失败（字段默认 None，断言 interrupted 在实现前必然失败）；agent 与前端测试都先看过 FAIL；"还没进到这一轮"那条是新行为的护栏，实现前就通过
Task 5: complete (tests: PY agents/tests/test_failures.py → 12 passed；test_main_agent 36 passed；backend manager+api 集成 61 passed；WEB vitest chat+components 167 passed；make check → 通过)
Task 6: Ruling: 迁移文件按项目命名惯例叫 0013_backend_runs_retry_of.py（计划写的是 0013_runs_retry_of.py） — 代价：无
Task 6: Ruling: "能否重试"在后端收尾时按本次运行全部 tool.started（含审批暂停前那段、子智能体内部）判断；被拒绝而没执行的有副作用调用也算有副作用（tool.started 分不出是否执行过） — 宁可只给"继续"也不让同一操作做两遍 — 代价：少数情况下本可以重试却只给"继续"
Task 6: Ruling: 重试后前端用 resync()（按服务器的界面历史重建并接上新运行），不在本地拼状态 — 失败轮收起的逻辑只有 chatFromHistory 一处 — 代价：多一次历史请求
Task 6: Ruling: 删掉 retry.ts 的 lastUserMessage（"重试这一句"重发消息的做法被"重试这一轮"取代）及其测试 — 代价：无
Task 6: Ruling: 进程中途退出（没有结束事件）的失败运行，前端按 interrupted、不能重试处理（只给"继续"） — 不知道中断前做过什么 — 代价：这类少见情况不能一键重试
Task 6: 说明：adapter 的"重试过的失败轮是一行数据片段"与端到端那条是实现之后补的（实现前单测已覆盖对话状态与按钮逻辑并先看过失败）
Task 6: complete (tests: agents fork/副作用 3 passed；backend retry 集成 9 passed；全量集成 246 passed；WEB vitest 311 passed；make check → 通过；make e2e → 34 passed)
Task 7: Ruling: 逐字附上的原话加上限——每条最多 1000 字（"……（后略，原文共 N 字）"），整段最多 6000 字（先丢最早的） — 不加上限时贴长文的会话压缩后附录和原文一样长，压缩形同虚设；全文仍在 deepagents 另存的对话记录文件里 — 代价：贴的长文在摘要里只剩开头
Task 7: Ruling: 计划里"连发长消息触发压缩"的两条主智能体级测试，改成直接用压缩中间件、按消息条数触发的小图测试 + 截下 create_deep_agent 参数的接线测试 — 阈值按上下文比例算，基础提示词一变（如第三批加工具）token 调好的测试就会失效 — 代价：没有一条从主智能体一路跑到压缩的测试（接线与中间件分别测了）
Task 7: Ruling: 多行原话续行缩进两格，下次压缩按"空行或 </summary>"整段取回 — 代价：原话里的换行在附录中多了两格缩进
Task 7: Ruling: 压缩前提取的调用打 nostream 标签、调用方记 memory_extraction（用量记在本次运行名下，不进对话输出流）；没有单独的端到端验证，依据是 langgraph 消息流对 nostream 标签的处理（pregel/_messages.py） — 代价：若标签失效，提取的 JSON 会出现在回答里
Task 7: Ruling: count_tokens 的断言改为"至少是默认估算的 1.5 倍"（实测 o200k 对 400 个汉字算 207，默认估算约 103）— 计划里的 ≥300 是我估错了 — 代价：无
Task 7: complete (tests: PY agents/tests/test_compaction.py → 13 passed（先看过收集期失败：模块不存在）；agents 单测 305 passed；make check → 通过)
Task 8: Ruling: text_of 从 translator.py 挪到新的 runtime/content.py（翻译器 → 跟踪器 → 分段计算 → 翻译器成环）— 代价：无
Task 8: Ruling: "上下文 N%"从用量徽标里拆出来，成为旁边独立的 ContextMeter（按钮，悬停/获得焦点/点击时弹出分段），徽标只显示本会话累计 token — 分段需要可聚焦的元素 — 代价：窄工具条上多占一点宽度
Task 8: Ruling: 分段弹层用 CSS 的 group-hover / group-focus-within 显示（不额外记开关状态）— 代价：触屏上点一下才出现、点别处才收起
Task 8: 更新了三条锁定事件序列的旧测试（test_run_streams_tool_and_answer_events 过滤 ContextUsage；test_events_reach_history... 期望里加 context.usage；test_openapi 的事件全集加 context.usage）— 新行为所致
Task 8: complete (tests: PY test_context_usage/test_tracker/test_main_agent 先看过失败后通过；agents 单测 311 passed；集成 246 passed；WEB vitest 316 passed；make check → 通过)
Task 9: Ruling: 前端没有加 exact 标记 — "思考结束"事件直接写结束时间；别的事件推算结束时只碰还没结束的思考，不会覆盖它 — 代价：无
Task 9: 更新了锁定事件序列的两条旧翻译器测试（内容块分思考与文字、网关的 reasoning_content）与 test_openapi 的事件全集 — 新行为所致
Task 9: complete (tests: PY agents/tests/test_translator.py → 19 passed（先看过收集期失败）；WEB reducer 38 passed（先看过 2 条失败）；make check → 通过)
Task 10: Ruling: 任务 10 拆成两段——文档与全量测试先做；整体审查与修复之后再升级正式环境（备份、make build、8000 检查、部署后的 smoke）— 设计第 8 节的流程是"审查修复 → 测试 → build → 文档"，先审查再上线更稳 — 代价：无
Task 10（前半）：D24、D26、D17 注明、决策索引、changelog、backlog R39、usage.md、architecture.md（9 节 4b～4d、12 节第 0 条）、docs/README.md、设计状态行已更新；make check 通过、make test-int 246 passed、make e2e 34 passed
Final review: 已派独立审查（opus，只读），差异 .superpowers/sdd/2026-10-23-round2-batch1/review.diff（对比回退快照，74 个文件）
第二批预检（等审查时做，只读、用后端镜像的临时容器）：podman 虚拟机内核 6.19.7-200.fc43，LSM 含 landlock；镜像 setpriv 为 util-linux 2.41；默认 seccomp 放行 Landlock——放行目录可写、未放行目录写不了；未放行 /dev 时连 /dev/null 都写不了（规则必须含 /dev）。结论：5.1 可按设计实现，不走"先不管"
Final review: opus 独立审查完成——Critical 0、Important 3、Minor 9，结论"修后可合入"（报告要点见下，复现脚本在 scratchpad/review/）
Final: 重新定级（按对用户的影响）：I1 分段把技能清单算成常驻记忆、I2 以前的原话成批丢失、I3 压缩前提取只看最旧一截且可能重复提取 → 修；M4 重试不认收尾时记下的 retryable（崩溃的运行能经接口重试、MCP 断开时卡片能点却 409）→ 升为 Important 修；M5 收尾 finally 里的副作用判断出错会卡住会话 → 升为 Important 修；M8 前端连点重试冒出误导报错 → 升为 Important 修；M9a 卡住报错写 183.456 秒、没输出也写"已生成的内容保留" → 升为 Important 修；M12 非第一轮的分叉没在 Postgres 存档上测过（出错代价最高）→ 升为 Important 补测试；建议项"网关还没载完模型时 enable_prompt_caching_once 照样记标记" → 升为 Important 修；M11 文档没跟上 → 修；M6 跟踪器估算与分段同一个 try、重复分词 → 并进 I1 一起修；M10 报错正则偏离计划无 Ruling、网址没排除全角括号、锚点不跨次保留 → 并进 I2 一起修
Final: minor (deferred): _fork_point 用 aget_state_history 为每个存档点重建完整快照，长运行重试开头偏慢（可改用 checkpointer.alist 只读元数据）
Final: minor (deferred): 不流式输出思考的慢模型（如 gpt-5.5-pro）在首字时限内可能还没开口，会被自动重发一次（设计要求的行为，费用可能翻倍）；可考虑按模型放宽首字时限
Final: minor (deferred): 子智能体压缩时把主智能体派的任务说明也列在"用户说过的原话"下（标题不准）；同步路径的摘要没有附录（项目全异步，不会触发）
Final: minor (deferred): 压缩前提取写入的记忆不推 memory.saved（界面看不到"已记住"）
Final: minor (deferred): 生成摘要那次调用同样带缓存断点（写缓存贵 25%），可评估让内部调用不打断点
Final: fixed M9a 卡住报错秒数取整、没有输出时不说"已生成的内容保留"（ModelStalledError 加 started）— test_stall_message_rounds_seconds_and_tells_whether_anything_was_output、test_second_stall_before_output_gives_up(match) RED→GREEN
Final: fixed I1 分段把技能清单算成常驻记忆（常驻段只到 </user_profile>）+ M6 分段出错不再清零中断估算、整体估算复用不重复分词 — test_skills_after_the_profile_count_as_system_prompt、test_context_failure_keeps_the_interrupted_estimate RED→GREEN
Final: fixed I2 以前的原话成批丢失、模型照抄标题时取错（附录前加系统标记 APPENDIX_MARK，按最后一个标记逐条取回原话与锚点，超限从最早逐条丢）+ M10 报错行误收代码、网址吞全角括号、锚点不跨次保留 — test_earlier_words_survive_the_cap_item_by_item、test_model_copying_the_header_does_not_hide_the_verbatim_words、test_anchors_carry_over_from_previous_summary、test_error_lines_skip_code_that_mentions_errors、test_url_stops_at_fullwidth_paren RED→GREEN（其中两条起初测试数据写错，改正后的版本在旧实现下同样会失败）
Final: fixed I3 压缩前提取只看最旧一截、重试/继续时重复提取（只送本进程未提取过的消息，按消息 ID 记、最近 200 个会话；用户话与回答各送最近 4000 字）— test_extract_before_compaction_reads_the_most_recent_part、test_extract_before_compaction_skips_messages_already_extracted RED→GREEN
Final: Ruling: I3 里"和每轮结束后的提取重叠"——用户 2026-10-23 已定要做，本轮保留并收窄范围；在批次汇报里向用户说明重叠、建议可以去掉 — 代价：每次压缩仍多一次模型调用
Final: fixed M4（升为 Important）重试以收尾时记下的 retryable 为准，界面历史里没有结束事件（进程中途退出）的由后端拒绝 — test_retry_refuses_runs_that_ended_without_a_finish_event、test_retry_follows_the_recorded_decision RED→GREEN
Final: fixed M5（升为 Important）收尾前的副作用判断出错时按不能重试处理，不再让运行卡在"运行中" — test_side_effect_check_failure_still_finishes_the_run RED（推送一直不结束）→GREEN
Final: fixed 建议项（升为 Important）网关清单里还没有数据库里的模型时不记 prompt_caching 标记 — test_prompt_caching_waits_until_the_gateway_has_loaded_its_models RED→GREEN
Final: fixed M8（升为 Important）前端连点"重试这一轮"只发一次请求（features/chat/guard.ts 的 createGuard）— guard.test.ts RED（模块不存在）→GREEN
Final: fixed M12（升为 Important）非第一轮的分叉在 Postgres 存档上的测试 — test_retry_forks_from_before_the_failed_run_on_postgres（针对已实现的行为，直接通过）+ 对照 test_resending_without_fork_keeps_the_failed_round（证明断言分得清分叉与否）
Final: fixed M11 文档没跟上（architecture.md 第 12 节流程图、9 节 4b' 附录与 4c 重试以记下的 retryable 为准；usage.md 常见问题补"回答迟迟不开始"；changelog 补审查后的修复）
Final: 修复轮全量：make check → 通过（pytest 单测 415 passed、vitest 320 passed）；make test-int → 252 passed；make e2e → 34 passed
Final: Ruling: 相关记忆放进用户消息（防注入取舍）— 用户 2026-10-23 已定（D24），实现与设计一致 — 代价：无
Final: Ruling: 压缩前提取做不做 — 用户已定要做；本轮收窄范围（I3 修复），批次汇报里请用户再定是否去掉 — 代价：每次压缩多一次模型调用
Final: Ruling: 原话的长度上限（每条 1000 字、整段 6000 字）— 维持；全文在 deepagents 另存的对话记录里 — 代价：贴的长文在附录里只剩开头
Final: Ruling: 停止且没有输出时不写中断说明 — 维持；通用说明就是真实原因 — 代价：无
Final: Ruling: 重发前被放弃的那次请求不估算、不显示用量 — 维持（设计两种读法都通）— 代价：卡住那次若计费，用量页少算一次输入
Final: Ruling: 前端不加 exact 标记 — 维持；thinking.finished 最终覆盖结束时间，运行中可能短暂显示推算值 — 代价：思考进行中的秒数偶尔先按推算显示
Final: Ruling: 任务 10 后半段（备份、重启网关、make build、8000 检查、部署后 smoke）— 接下来就做 — 代价：无
Final: Ruling: 一个步骤做到一半失败时已完成的并行工具结果会丢 — 本批之前就如此，不在本批范围，不修 — 代价：失败后"继续"时模型可能重做那几个并行调用
Final: Ruling: 压缩阈值用 gpt-4o 分词器估 Claude 的 token、不乘校准比例 — 设计明确要求 litellm.token_counter；上下文超长时 deepagents 还会兜底压缩 — 代价：触发时机与真实用量有偏差
Final: Ruling: 第二批起的内容（令牌、Host、MCP 重连等）— 不在本批 — 代价：无
Task 10（后半）：正式库无进行中/待审批运行；make backup → 20261023-143303（904K）；make restart-gateway → 健康、日志无报错；make build → 后端健康，迁移 0013，.seeded 记上 prompt_caching，/api/settings/models 显示 claude-opus-4-6 已开缓存且其余设置不变（注意：改动是"新增再删旧"，模型页里它排到了最后）
Task 10：8000 检查（内置浏览器，只看不改）：模型页 claude 有"缓存"标签、抽屉里"提示缓存"勾着、gemini 抽屉没有该开关（均未保存）；旧会话历史正常、工具条"上下文 <1%"按旧算法显示、控制台无报错；未发消息、未点"测试"
Task 10：部署后 smoke test_agent_second_turn_reads_cache → PASS：第 1 轮 input 6202、cache_write 6199；第 2 轮 input 6263、cache_read 6199、cache_write 61，8.6s → 4.2s；本批真实模型花费合计约 0.11 美元
Task 10: complete（D24 填入实测；changelog 同步）
Final: Ruling: 项目没有 git，台账就是唯一的记录，不按技能说的删掉工作区目录（只删审查用的 review.diff）— 代价：.superpowers/ 下多一个小目录
