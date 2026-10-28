# SDD ledger — plan: docs/plans/2026-10-26-minor-fixes-batch4.md
Spec: docs/specs/2026-10-26-minor-fixes-design.md（已审定）；明细 04-设置技能与运维.md（G、I）、03-执行命令文件与MCP.md（D15）
Pre-flight:
- Task 3（G10 store.write_text 保持权限）↔ 第二批 F8（store.write 保留开头注释）：同一文件，write 调 write_text，各改各的
- Task 5（I14 旧说法扫描）↔ 第二批 F20、本批 G6：扫描在这些都改完之后加，否则一加就失败
Task 1: complete (G4 backup.sh 只在 EMIT_NAME 时打印 BACKUP_NAME=，restore.sh 调用时带 EMIT_NAME=1；G5 .seeded 存在时一起打包、manifest 记 seeded=yes/no，恢复时备份里有就整份替换、没有就不动现有的；G13 usage 第 5 节补"项目目录里的 config/ 不在备份里""进行中的对话会被打断"、备份范围加 .seeded。INT 3 条 RED→GREEN（test_backup_output_is_for_humans、test_seeded_marker_travels_with_backup、test_restoring_a_backup_without_seeded_keeps_the_current_one）；test_backup_scripts 20 passed)
Task 2: complete (D15 Dockerfile 加 RUN python -m pip uninstall -y pip；G6 CMD 去掉 backend.security；G7 NEED_ENV 一并建 .workdata/shared，START_BACKEND 去掉重复的 mkdir；G8 Makefile 导出 HOST_TZ（readlink /etc/localtime 去掉 …/zoneinfo/），compose 只给 backend 设 TZ: ${HOST_TZ:-UTC}。PY 4 条 RED→GREEN（test_image_cmd_only_runs_existing_modules、test_system_python_has_no_pip、test_backend_timezone_follows_host、test_makefile.py::test_restart_prepares_shared_dir）；本机 make 算出 HOST_TZ=Asia/Shanghai。临时容器（当前镜像）实测：卸掉 pip 后 pip、pip3 找不到命令（sh 退出码 127），健康检查用的系统 python、虚拟环境里的 pandas/matplotlib 照常，TZ=Asia/Shanghai 生效；新镜像构建后再查一次)
Task 2: Ruling: 计划写"Linux 容器里 command -v pip 退出码 1"，容器里的 sh 是 dash，找不到时退出码是 127 — 都是"找不到"，按 127 记 — 代价：无
Task 3: complete (G9 _add_version：已经写了 version 的把顶格的 version: 0 按行改成 1（行尾注释留着），没写的照旧在开头注释后插一行，之后照旧读回来核对；警告改成"请手动把 version 改成 1（没有这一项就加上 version: 1）"。G10 UserConfigFiles.write_text、SkillCatalog._write_state 写临时文件时 fchmod：原文件的权限照旧（0600 保持 0600），新文件 0644。PY 3 条 RED→GREEN（test_explicit_version_0_is_migrated、test_page_write_keeps_file_mode、test_state_write_keeps_file_mode），test_broken_file_is_not_touched 跟着改断言（先 RED）；test_seed、test_settings_store、test_skills 39 passed，ruff、mypy 通过)
Task 4: complete (G12 _json_lines 先试整段 json.loads（是列表就直接用），_service 从 Service 或 Labels["com.docker.compose.service"] 取服务名，_unhealthy 没有 Health 时看 Status 里的 "(unhealthy)"；G11 只加测试。PY test_containers_understand_podman_ps_output RED→GREEN；test_embedding_name_matches_compose_and_seed 直接通过（本来就一致，钉住）；test_doctor 16 passed。真实的 podman ps --format json（343 行的整段数组）交给 _containers 得到 ✓；make doctor 全部正常)
Task 5: complete (I7 e2e_server 新增 E2E_WORKDATA（系统临时目录下的 opa-e2e-workdata）与 _fresh_workdata（先删再建），build_e2e_app 改用它；以前留下的 90 个 e2e-workdata-* 已删。I14 新增 deploy/tests/test_wording.py（扫描范围同 test_paths、跳过 tests/ 目录；旧说法表带理由：config/app.yaml、docker-compose.yml 里传给、backend.security、向量模型写在 config/models.yaml、不超过 50MB、max_document_mb），扫出 usage.md 知识库上传"单个不超过 50MB"、architecture.md 不存在的 knowledge.max_document_mb，都改成设置页的上传上限 max_upload_mb。I17 Python 规则加 anyio、trio，扫描跳过规则自测本身，demo_server 的 hang 注明"允许等待：模拟一直不返回的工具"；前端改成按括号配对找整次 setTimeout 调用，跨过的任何一行写了"允许等待："就放过。PY test_e2e_workdata_is_reused_and_cleared、test_rule_catches_every_sleep、test_no_stale_wording RED→GREEN（test_rules_catch_stale_wording 规则自测）；前端跨行自测先用旧的逐行规则跑 RED（expected [] to deeply equal [2]），换新规则 3 passed；eslint、tsc、prettier 通过)
Task 5: Ruling: I7 明细"现状"里顺带提到的 _IsolatedSettings 仍读 shell 里同名环境变量，不在批准的修法里，这次不改（要改设置来源的组合，影响端到端里设置页的行为，得另外核对）— 记进需求池 — 代价：本机 shell 导出了同名变量（如 MAX_UPLOAD_MB）时端到端结果会跟着变
Final: 全量检查（审查前）：make check（后端 739 passed 4 skipped、前端 449 passed）、make test-int 367 passed；端到端在跑；独立审查（opus，新上下文）进行中，对照 scratchpad/b4.diff 与 minors-b4-base/
Final: make e2e 38 passed（1.1 分钟）；端到端用的是固定的 $TMPDIR/opa-e2e-workdata（config、skills、workspace），没有再生成 e2e-workdata-* 目录
Final: 独立审查（opus，新上下文）：Critical 0、Important 2、Minor 11；报告 scratchpad/review-b4-report.md；Review Focus 5 条都通过
Final: fixed Important 1 — 前端 WAITS_MS 允许最后一个参数后的逗号（prettier 拆行写法）：自测 "setTimeout(\n  resolve,\n  50,\n);" RED（expected [] to deeply equal [1]）→GREEN，", 0," 仍放过；test-hygiene 3 passed
Final: Important 2 处理 — 照已批准的修法（明细 G10"现在已经是 0600 的文件需要手动改一次"），升级时在宿主机上 chmod 644 本机三个 0600 的配置文件；先查过 mcp_servers.yaml 里没有 headers（不含明文请求头）；changelog 写明"已经是 0600 的不会自动放宽" — 运维一步，没有代码测试，升级后 ls 核对
Final: fixed Minor 8 — _fresh_workdata 不再吞掉删除失败（先 exists 再 rmtree）：test_e2e_workdata_that_cannot_be_cleared_says_why RED（FileExistsError 盖住了真正的 PermissionError）→GREEN
Final: fixed Minor 3 — config/settings.py 两处、backend/models/service.py、.env.example 的"写在 config/models.yaml"旧注释改成默认清单 config/seed/models.yaml 或模型页；扫描表加"config/models.yaml 里的/的/增加…条目"：test_no_stale_wording RED（3 处命中）→GREEN，规则自测钉住"写在 config/models.yaml 里的模型没有编号"不算
Final: fixed Minor 4 — 旧说法扫描跳过前端 *.test.*、*.spec.*（_scanned + test_tests_are_skipped；新判断，现存没有可先失败的命中）
Final: fixed Minor 2（"（D15）"改"积压小问题 D15，修订 D20"）、Minor 5②（说明与 testing.md 写清"允许等待"写在哪）、Minor 5③（Python 扫描加 common/tests、config/tests）、Minor 6（时区一条从第 11 节挪到第 10 节第 11 条）、Minor 7（使用指南：容器里没有的旧时区名按 UTC）、Minor 1（使用指南：恢复 10-24 之前的备份后删掉 .seeded 的 conversation_index 行再 make restart 补建索引）——都是注释、文档与扫描范围
Final: Ruling: Minor 5①（配括号不管字符串里的括号、1_000 不认）不改，写进 testing.md — 很少见 — 代价：这种写法的固定等待漏扫
Final: Ruling: Declined 3（ensurepip 自带的 pip 安装包）不删 — 用户定的是"pip 命令找不到"，绕路要显式用系统 Python，装上的包虚拟环境也看不到；记进 R45 待定 — 代价：很会绕的模型能给系统 Python 装包
Final: Ruling: Declined 4（podman-compose 的 ps -a 会列出已退出的同名容器）不处理 — 现在用的是 docker-compose — 代价：换成 podman-compose 且留着已退出的旧容器时，体检可能按旧容器报
Final: minor (deferred): Minor 9 单元、集成测试的 mkdtemp 临时目录越积越多 → R45
Final: minor (deferred): Minor 11 原子写入两份代码可合到 config/ → R45
Final: 补 Task 5 Ruling 的"记进需求池"：新增 R45（_IsolatedSettings 读 shell 同名变量等），R43 里引用的 R45 现在存在
Final: 修完后全量：make check（后端 741 passed 4 skipped、前端 449 passed）、make test-int 367 passed、make e2e 38 passed
Final: 部署 15:37（查过没有进行中的运行；先备份 20261026-153647——输出里已没有 BACKUP_NAME=，包里有 .seeded；宿主机上 chmod 644 三个原为 0600 的配置文件；make build）：构建日志里 "Successfully uninstalled pip-25.0.1"；启动日志无报错、时间是本地时间（15:37:47），容器环境 TZ=Asia/Shanghai；make doctor 全部正常；新镜像一次性容器（每次新开 sh）：pip、pip3 找不到（127），python -m pip 报 No module named pip，虚拟环境 pandas/matplotlib 与系统 python 照常，健康检查 healthy；8000 只看核对：MCP 页（1/1、14 个工具）、模型页、对话页，控制台无报错；没发消息、没点模型测试
Final: Ruling: 四批的台账（.superpowers/sdd/2026-10-26-minor-fixes-batch1～4/）都留着不删 — 项目没有 git，台账是唯一的执行记录 — 代价：多几个小文件
第四批完成
