# SDD ledger — plan: docs/plans/2026-10-26-minor-fixes-batch2.md
Spec: docs/specs/2026-10-26-minor-fixes-design.md（已审定）；明细 02-后端运行与记忆.md、04-设置技能与运维.md、01-前端.md（F12）
Pre-flight:
- Task 1（RunRepo.fail_unfinished 改返回 ID 列表、RunFollowups.index_later）↔ Task 13（lifespan 顺序测试）：Task 13 在 Task 1、6 之后写，断言里包含"给中断的运行登记写索引"与后台补算哈希
- Task 1（RunRepo.retried）↔ Task 8（RunRepo.count_active）：同一文件不同方法，无冲突
- Task 2（_record_later 收到 SubagentStarted 记 task）↔ Task 7（G2：_record_later 建任务用新 Context）：同一函数，两处改动都落在 create_task 上，Task 7 统一改成 _spawn 辅助函数
- Task 6（seed.py 补算哈希）↔ Task 10（seed._is_preamble 抽到 config/ 共用）：同一文件不同函数，无冲突
Task 1: complete (B6 RunRepo.retried + index_conversation 跳过已被重试替换的；B7 fail_unfinished 返回 ID 列表、RunFollowups.index_later、启动时给中断的运行登记写索引；B9 _stop_requested + _continue 前判断停机或已请求停止、_give_back 用新的 RunRepo.update_event 把插话存进结束事件；test_seed 的补建测试补 integration 标记。INT 5 条 RED→GREEN；相关 5 个文件 126 passed)
Task 1: Ruling: B9 只在接续前判断一次（不在 writer.finish 前另判），退回的插话用 update_event 补存进历史 — 覆盖整个收尾窗口、只一个判断点 — 代价：退回时多一次写库
Task 1: Ruling: _continue 判断通过后、start() 里几次写库的毫秒级窗口内停机，下一轮仍可能发起（停机返回后它会被下次启动记成中断）——不再加锁 — 代价：极少见
Task 2: complete (B12 _record_later 收到 SubagentStarted 记一次 task，_record_tool 改收工具名与技能名；前端 BUILTIN 补 task：派出子智能体（kind other）。INT test_subagent_dispatch_counts_once_even_after_approval RED→GREEN（子智能体里等审批、恢复后 task 仍只 1 次）；WEB tools.test 1 条 RED→GREEN；test_usage_api + test_manager 54 passed)
Task 3: complete (C1 _apply 改动前 store.get 核对：取不到、已是常驻、更新时间变了都跳过并记警告；C2 extract_memories 末尾记一条 INFO：新增、更新、删除各几条与条目 ID，不记原文。PY 2 条 RED→GREEN；test_memory_extraction 14 passed)
Task 3: Ruling: C2 没有改动时也记一条（"新增 0…条目 ID：无"）— 能看出提取跑过 — 代价：每轮多一行 INFO（只进容器日志）
Task 4: complete (C5 upload_document 先看声明的大小；C6 出处链接文字的方括号换全角（_link_text）；C7 工具与接口：取不到目标那段分别 ToolException（固定文案）与 404；C8 片段不能单独改（422 固定文案）、不能单删（422）；C9 ingest 遇到已完成或已失败直接返回；C13 长表格切块后每块补表头；C14 空文件"文件是空的"。PY/INT 12 条 RED→GREEN；知识库相关 199 passed)
Task 5: complete (C10 向量请求超时 httpx.Timeout(30, connect=5)，注释改成按入库每批几段说。PY test_gives_up_after_30_seconds RED→GREEN；test_embedding 10 passed)
Task 6: complete (C12 迁移 0018 knowledge_documents.content_hash + 索引；DocumentRepo.find_by_hash/without_hash/set_hash，create 带哈希；DocumentLibrary.add 边存边算 SHA-256，同内容 409 固定文案（报已有那份的文件名）并删掉刚存的原文件；backfill_hashes 从原文件补算，读不出的跳过记警告；seed.backfill_document_hashes_once（.seeded 记 document_hash），main 后台调用。INT 迁移、库层 2 条、接口两条路、补算一次 RED→GREEN；相关 5 个文件通过)
Task 6: Ruling: C12 用普通索引不用唯一约束 — 旧文档里可能本来就有内容相同的两份，补算时唯一约束会失败；两个请求同时传同一文件的竞争在单用户下不现实 — 代价：极少见时两份同内容都进去
Task 6: Ruling: 重复时报已在知识库里那份的文件名（不是这次上传的名字）— 用户要删的是它 — 代价：无
Task 7: complete (G1 UsageRepo.summary 把 PostgreSQL 不认识的时区转成 InvalidRequestError"时区不认识：…"（422）；G2 新 models.detached_context()（复制上下文、只去掉调用归属），RunManager 的收尾与后台写库任务都经 _spawn 用它；G3 _with_tags 把标签并进已有 extra_body（metadata 按键合并、tags 接在后面）；I5 test_bootstrap 补向量化用量归属测试；I6 test_usage_repo 补跨天与范围边界测试。G1、G2、G3 RED→GREEN，I5、I6 只补测试（通过）；相关 74+20+16 passed，lint-imports 2 kept)
Task 7: Ruling: G2 用"复制当前上下文再去掉调用归属"而不是空的 Context() — 其余上下文变量照常带着 — 代价：无
Task 8: complete (F4 ModelAdmin.add 拒绝名叫 default（422 固定文案）；F9 RunRepo.count_active（queued、running、interrupted），ModelAdmin 多收 runs，delete 先查在用 409 固定文案；F12 update 把默认对话模型改成非对话 409，前端 selectableNames 让下拉框当前值不在对话模型里也列出。INT 4 条（含参数化）RED→GREEN、WEB 1 条 RED→GREEN；test_models_api + test_manager 67 passed)
Task 9: complete (F2 read_front_matter 名称与说明先去首尾空白、空了算不完整；F3 详情与启停返回经 _with_last_used 带上最近使用时间；F5 压缩包读一项时坏、加密、压缩方式不认识转成"读不出来"（422），install 遇到没有 SKILL.md 的同名文件夹 409；F7 停用隐藏按 casefold；F11 去掉外层文件夹后只差大小写的路径拒绝。PY/INT 9 条（含参数化 3 条）RED→GREEN；test_skills + test_skill_upload 43 passed，test_settings_api 31 passed)
Task 10: complete (F8 config 新增 leading_comments、is_preamble_line（seed._is_preamble 改用它）；UserConfigFiles.write 与 SkillCatalog._write_state 用原文开头的注释代替程序那行说明，原文没有开头注释时才写说明；默认的 mcp_servers.yaml、approval_rules.yaml 把正文里的示例和 version 行尾说明挪到开头注释段。PY 5 条 RED→GREEN（store 2、skills 1、seed 文件 2 参数化）；旧测试 test_seed_rule_examples_work_when_uncommented 改成按开头的例子核对，另加 MCP 服务例子可用的测试；相关 5 个文件通过)
Task 10: Ruling: 例子挪到开头后用"在 tools 下加一行 files_write_file: auto"的说法，不再要求"去掉行首 #"——正文里的注释页面一保存就会丢 — 代价：手改时多一步
Task 11: complete (F17 AppSettingsService._validate 返回校验后的设置，update 存 read_setting(校验后, key)；默认对话模型被环境变量指定时"恢复默认"不再检查代码里的默认模型。INT 2 条 RED→GREEN（第二条先回退修改看到 422 再恢复）；test_app_settings + test_settings_api 46 passed)
Task 12: complete (F20 后端说法：知识库未启用两处改成"请检查设置页只读项里的 adapters.…"；MCP 缺环境变量改成"在 .env 里设置后执行 make restart"；体检里没有向量模型的修法改成"在模型页添加向量模型（来源选“本机 Ollama”）"。PY 2 条 RED→GREEN（test_missing_env_hint_points_to_dotenv、test_doctor 新增一种故障）；扫过 config/app.yaml 已无残留)
Task 13: complete (I12 test_api 两处改会话权限的 PATCH 断言 200；I13 新 backend/tests/test_main_lifespan.py：替身跑一遍 lifespan，断言启动顺序（日志→连接池→读设置→迁移配置→写默认文件→组装智能体→组装服务→标记中断并登记写索引→连 MCP→两条队列与后台导入）与关闭顺序（停运行→停两条队列→关智能体→关连接池）。I12 2 passed；I13 1 passed，并把关闭里"停运行"与"停任务队列"对调做过一次反证：测试失败，改回后通过)
Final: 独立审查（opus，新上下文）：Critical 0、Important 0、Minor 5；报告 scratchpad/review-b2-report.md，台账 8 条 Ruling 都同意
Final: Ruling: Minor 1（两个不同空文件，第二个被当成重复、提示第一个的名字）、Minor 2（补算一份出意外就卡住后面的）按影响升为 Important——本批自己带来的 — 代价：无
Final: Ruling: Minor 3 补算改成每次启动给还没有哈希的补（去掉 .seeded 的 document_hash 与 backfill_document_hashes_once），原文件读不出的记占位空字符串——从升级前的备份恢复后也补得上 — 代价：每次启动多一次查询
Final: fixed Minor 1 — DocumentLibrary.add 大小为 0 当场 422"文件是空的"（EMPTY_FILE 挪到 parsing.py 共用）；test_empty_file_is_refused_at_once RED→GREEN
Final: fixed Minor 2 — backfill_hashes 每份单独 except Exception 记日志继续；test_one_unexpected_failure_does_not_stop_the_backfill RED→GREEN
Final: fixed Minor 3 — main._seed_models 每次调 documents.backfill_hashes()；test_document_hashes_are_backfilled_on_every_start RED→GREEN，test_old_documents_get_their_hash_filled_in 加"第二次补 0 份、没有 NULL"RED→GREEN
Final: fixed Minor 4 — resume() 开头与 _finish_idle 清掉 _stop_requested；test_cancel_during_pause_finalization_stops_the_run 加断言 RED→GREEN
Final: Minor 5 文档 — backlog R26 改"待定（…在 R43 后续批次处理）"、R34 加"决定不修 F6 后端部分"；approval_rules.yaml 例子写"空两格"；D10 加修订（C12 按内容只留一份）；迁移 0018、architecture、changelog 改成每次启动补算
Final: 全量 make check（694 py、448 web）、make test-int 360、make e2e 38 都通过
Final: 部署 13:16（先备份 20261026-131548，make build）；启动日志：迁移到 0018，"补算文档内容哈希：1 份"；make doctor 全部正常；8000 只看核对：知识库页、模型页下拉框（当前 claude-opus-4-6）、用量页，控制台无报错；没发消息、没点模型测试
第二批完成
