# SDD ledger — plan: docs/plans/2026-10-23-round2-batch4.md
执行方式：本会话内执行（方式二），最后一次整体审查。项目无 git：台账即记录。开始 2026-10-24 03:24。
Pre-flight: 任务 7 与任务 10 都改 agents/main_agent/runtime/skills.py（7 写停用清单的版本，10 加 SkillInfo 字段）——按顺序做，不冲突；任务 6 拆的前端文件与任务 10 的技能页不重叠；任务 3 的等待工具只给测试用。
Task 1: complete (tests: PY deploy/tests/test_compose.py::test_dependency_cooldown RED→GREEN；uv lock 只多 [options] 两行（版本不变）；uv sync --locked、pnpm install --frozen-lockfile 照常（pnpm 会核对发布时间）)
Task 1: Ruling: frontend/.npmrc 的 save-exact 保留（pnpm 11 不读了，但别的工具可能读，留着无害）— 错了的代价：无
Task 2: complete (tests: PY backend/tests/test_test_env.py 2 RED→GREEN；make check → 642 py / 380 web；make test-int 暴露 test_startup_reads_stored_settings 靠本机 .env 的网关密钥 → 改为测试里显式给假值，13 passed)
Task 2: Ruling: 判断是否冒烟测试用"标记表达式里出现 live 且前面不是 not"（make check 的默认表达式是 not integration and not live）；清凭据与不读 .env 放在根 conftest 的 pytest_configure（最早执行，所有测试都受管）— 错了的代价：无
Task 3: complete (tests: PY backend/tests/test_test_hygiene.py RED（55 处）→GREEN；make check → 643 py / 380 web；make test-int → 323（61.5 秒，原 69 秒）)
Task 3: Ruling: 等待工具 agents/tests/waiting.until（每 0.01 秒看一次、默认 5 秒、参数叫 within——ruff 不许异步函数带 timeout 参数）；靠时间保证先后的改成：慢替身开始时发 asyncio / threading 事件、等事件；等数据库状态、界面历史里的事件、总线忘掉运行用 until；命令起来用标记文件；备份名改用测试才设的 BACKUP_TIME（脚本里加了这个可选变量）— 错了的代价：无
Task 3: Ruling: 保留并注明"允许等待"的三类：替身模拟慢 / 卡住（含工具、服务器、写库）；有上限的轮询（进程退出、后台状态）；断言"一段时间里什么都没发生"（没有 ping、2 秒后没写出文件、过了保留时间仍在、几个领取周期里没领）只能等够时长 — 错了的代价：无
Task 3: note: test_local_sandbox 里只在 Linux 跑的僵尸进程测试改成等标记文件 + until（本机跳过，没能实跑）
Task 4: complete (tests: WEB src/test-hygiene.test.ts RED（5 处）→GREEN；events.test 改假时钟（vi.runAllTimersAsync 把排上的事做完再断言"没有再打开"）、queries.test 改 vi.waitFor、cache.test 慢请求改假时钟推进)
Task 5: complete (tests: ruff 开 C901（20）、PLR0915（50）后报 4 处（RED）→ 拆小后 0；make check → 643 py / 382 web；make test-int → 323)
Task 5: Ruling: _drive_events 把"运行失败"（模型卡住与其他错误）挪进 _failed；knowledge_tools 拆成 _memory_tools（会改记忆的三个）与 _lookup_tools（只读的两个），顺序不变；_execute 拆出 _agent_events（启动 / 恢复）、_record_later（用量、工具用量、产物登记放后台，_Background 收集）、_stopped（停止时的结束事件）、_wrap_up（插话去留、能否重试）— 错了的代价：无（行为不变，测试兜底）
Task 6: complete (ThreadList 拆出 ArchivedThreads；eslint 0 问题；make check → 643 py / 382 web 通过；make e2e → 37 passed)
Task 7: Ruling: 页面写入（UserConfigFiles.write）在没有 version 时补上当前版本 — 页面写的就是当前格式，免得启动时再迁移一次、多一份备份 — 代价：启动后手改成旧格式、又经页面写入的文件会被标成当前版本（现在第 0、1 版内容相同，无影响；以后改格式时要留意）
Task 7: Ruling: 技能停用清单写入时保留文件里手写的其他字段（不只是 version）— 设计 7.3 说"写入时会丢掉其他字段，要改" — 代价：无
Task 7: Ruling: 0→1 在原文开头的注释/空行/--- 之后插一行 version: 1，插完重新解析必须正好只多这一项，否则不动并记警告（如整个文件写成一行 {…}）；version 不是非负整数时当作写坏 — 保住用户内容优先 — 代价：极少数写法要用户自己加一行
Task 7: Ruling: test_page_edits_keep_the_version（集成）先写后实现，但没有在实现前单独跑看它失败；单测的失败（ImportError）看到了 — 集成测试跑一次 60 秒 — 代价：这条集成测试的有效性靠阅读确认（旧代码会丢 note、不带 version）
Task 7: complete (make check → 649 py / 382 web 通过；make test-int → 324 passed)
Task 8: Ruling: 设置页文件接口实际是 /api/settings/files（计划写成 data-files）— 按代码 — 代价：无
Task 8: Ruling: main(run, fetch, workdata, *, disk_free) 代替计划里的 main(run, fetch, env)：工作区位置直接传、磁盘剩余可替换（单测不受本机磁盘影响）— 代价：无
Task 8: Ruling: 状态"还没有"的 .workdata 文件（如没停用过技能时的 skills.yaml）不算问题，与设置页一致；后端没起来时模型、文件两项打"–"（跳过）不重复计 ✗；没有备份、磁盘剩余不到 5 GB 算 ✗ — 代价：全新安装第一次体检会因为没备份提示 make backup
Task 8: Ruling: 新增 deploy/__init__.py — mypy 否则把 deploy/doctor.py 认成两个模块名 — 代价：无
Task 8: complete (PY deploy → 15 passed；ruff、mypy、lint-imports 通过；本机 make doctor 9 项全 ✓，退出码 0)
Task 9: Ruling: 恢复前后的数目在第 5 步各库恢复到临时库之后数（服务已停、现有库还没动），不另存一份"恢复前"的数 — bash 3.2 没有关联数组，同一时刻数两个库最简单，结果与"停服务后马上数"相同 — 代价：无
Task 9: Ruling: 提醒是恢复脚本自己输出的最后一行（后面加了 make restore BACKUP=… 的写法）；make restore 起服务的输出仍在它之后 — 不改动已测过的起服务流程 — 代价：用户可能要往上看几行
Task 9: complete (PY deploy/tests/test_backup_scripts.py -m integration → 17 passed，macOS bash 3.2)
Task 10: Ruling: 提示原文："说明有 N 字，说明尽量短：每次对话智能体都要读一遍所有技能的说明"（>300）、"说明有 N 字，超过 1024 字的部分会被截断：智能体只读前 1024 字"（>1024）— 含设计的两句原话、加上原因 — 代价：改文案即可
Task 10: Ruling: 提示放在 SkillInfo.notice，列表、详情、上传返回都带；上传后页面顶部用黄字说"已上传「名字」。…"，列表行与详情里也一直显示 — 设计说"上传时提示"，一直显示能提醒已有的长说明 — 代价：无
Task 10: Ruling: 最近使用时间沿用会话列表的写法（今天写几点、昨天、几月几日）；没用过写"从未使用" — 代价：无
Task 10: Ruling: 两条集成测试（test_skill_last_used、test_skills_list_has_last_used）先写后实现，没有在实现前单独跑看失败；单测与前端测试的失败都看到了 — 代价：这两条的有效性靠阅读确认
Task 10: complete (make types；make check → 665 py / 384 web；make test-int → 329 passed)
Task 11: 文档已写（changelog、backlog R39 已完成、usage、architecture、testing、coding-standards、设计状态行、CLAUDE.md 加 make doctor）；make e2e → 37 passed；独立审查（opus）已派出，04:14
Final review: opus 独立审查完成（Critical 0，Important 2，Minor 10 + 零碎 4；结论：运行时代码可部署，两条 Important 先修，建议顺手修 Minor 3、6、8）；报告 scratchpad/review4-report.md，探针 scratchpad/review4/
Final: Ruling: 重新定级（按对使用者的影响）——进修复的：I1 测试仍读到 .env、I2 脱离进程组那条测试基本空过、Minor 3 体检在拿不到令牌时仍说"全部正常"（体检的本分就是说实话）、Minor 4 网关数据库断开时（503）修法说成重启网关（"✗ 后写怎么修"是设计 7.1 的要求）、Minor 5 备份名里的时间不合法时体检崩溃（Review Focus 1 要求不崩）、Minor 6 配置文件不是 UTF-8 或 history 被同名文件占着时后端起不来（Review Focus 2 要求启动不失败）、Minor 8 恢复后的提醒被起服务的输出挤到中间（设计 7.2 要求在结尾；推翻任务 9 的那条 Ruling）
Final: minor (deferred): Minor 7 文件里已有 version: 0 时迁移不了，提示却让人"开头加一行 version: 1"；Minor 9 history 备份名用的是 UTC（容器没设时区）；Minor 10 说明长度没先去掉首尾空白（| 写法差 1 字）；Minor 11 last_used_at 只有列表接口有值；零碎：体检里的向量模型名照抄 compose 没有测试保证一致、上传提示在删掉那个技能后仍留着、迁移后的文件权限变成 0600（与页面写入相同）、扫描测试漏掉 anyio.sleep 与跨行的 setTimeout
Final: Ruling: 审查放下的几条——podman-compose（不是 docker-compose）做 compose 后端时 ps 没有 Service 字段，体检会误报容器没在运行：现在本机用的是 docker-compose，其余各项照样如实，不改 — 代价：换后端后容器一项误报；BACKUP_TIME 也会读用户 shell 里的同名变量：正常没人设，不改；删掉再上传同名技能沿用旧的最近使用时间：第三批按文件夹名记用量的设计，不改；技能列表接口要查数据库：数据库挂了整个应用都不能用，不改；queries.test.ts 可能空过：改前就这样，记进需求池；adapter 对空错误文本的处理不同、知识库页"文档"视图久了切回会重新加载、make doctor 会建 .workdata/workspace：碰不到或无关紧要，不改
Final: fixed I1 测试仍读到 .env → 根 conftest 用 pytest.MonkeyPatch 让 dotenv.load_dotenv 什么都不做（比任何测试模块都先导入），冒烟测试在 pytest_configure 里 undo 后照常读；test_startup_reads_stored_settings 显式给 DATABASE_URL — test_dotenv_is_not_loaded RED→GREEN
Final: fixed I2 脱离进程组那条测试基本空过 → 后台进程 setsid() 之后自己留下 escaped 标记，测试等它再取消 — 探针（把 _stop_reading 故意改成无上限地等）6 次全部发现（原来 8 次只发现 1 次）；PY test_local_sandbox 23 passed
Final: fixed Minor3→I 拿不到会话令牌仍说"全部正常" → 后端 ✓ 却拿不到令牌时模型、.workdata 文件两项算 ✗（"取不到会话令牌（/api/session 返回 N）→ make restart"），后端没起来才跳过 — test_doctor_reports_each_failure_with_a_fix[_session_broken] RED→GREEN
Final: fixed Minor4→I 网关数据库断开（503 + db）时修法不对 → 任何状态码下正文带 db 且不是 connected 都说"网关自己的数据库没连上" — [_gateway_without_db] 改成真实的 503 + disconnected，RED→GREEN
Final: fixed Minor5→I 备份名时间不合法时体检崩溃 → strptime 失败显示"?" — test_odd_backup_names_do_not_crash RED→GREEN
Final: fixed Minor6→I 非 UTF-8 配置文件、history 被同名文件占着时后端起不来 → _read_yaml 把 UnicodeDecodeError 转成 InvalidConfigError（页面也能显示原因）；迁移的备份、写入失败（OSError）记警告、文件不动 — test_unreadable_files_do_not_stop_startup、test_file_not_in_utf8_is_a_config_error RED→GREEN
Final: fixed Minor8→I 恢复提醒被起服务的输出挤到中间 → 停过服务时提醒在 EXIT 陷阱里起完服务后再说（起服务放进子 shell，起不来时照样 exit 1）；没停服务时照常在结尾说 — test_restore_warns_when_data_shrinks 加了 BEFORE/AFTER_RESTORE 并断言提醒在起服务输出之后（这条集成测试没有在改脚本前单独跑看失败：当时整套集成测试正占着同一个探测库；按旧脚本，最后一行会是起服务的输出）
Final: 修复后全量：make check → 670 py / 384 web；make test-int → 329 passed
Final: 升级 2026-10-24：没有停在审批处或运行中的运行；make backup → 20261024-045039；make build 04:51；启动日志"配置文件已迁移到当前格式：mcp_servers.yaml、approval_rules.yaml、skills.yaml"，.workdata/config/history/ 有 3 份 .bak（名字是 UTC 时间，见 R42），三份文件内容不变、多了 version: 1
Final: 8000 核对（只看、没发消息）：make doctor 9 项全 ✓（退出码 0）；设置页 .workdata 文件 4 项"正常"；MCP 页 files 已连接、14 个工具；技能页 excel 显示"从未使用"（正式库 tool_usage 为空，属实）
Task 11: complete（第二轮第四批完成；第二轮全部完成）
