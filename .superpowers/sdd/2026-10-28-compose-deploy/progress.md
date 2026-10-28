# SDD ledger — plan: docs/plans/2026-10-28-compose-deploy.md
Task 1: complete (compose 后端镜像模式：image ${BACKEND_IMAGE:-open-personal-agent-backend:latest}、去掉源码挂载与 command（用镜像 CMD）、依赖 ollama-init 跑完；deploy/.env -> ../.env 链接；.dockerignore **/.env；.env.example 加 HOST_TZ。PY 4 条 RED→GREEN。附带：test_paths._files 顺着链接扫到了真正的 .env（只报行号未输出内容），改成跳过链接与 .env，加 test_env_is_never_scanned)
Task 2: complete (Makefile：up 不再依赖 infra-up，直接 START_BACKEND（up -d --wait backend）；restart、build 说明改成镜像模式；新增 bundle。新脚本 deploy/bundle-images.sh：COMPOSE、PLATFORM（DOCKER_DEFAULT_PLATFORM）、SKIP_BUILD、OUT_DIR；compose config --images 列镜像，podman save 加 -m。PY 6 条 RED→GREEN；一条测试自身的子串判断写错（路径里含 build）已改)
Task 3: complete (D27、决策索引、README、使用指南（启动、换机器部署 7 步、时区）、CLAUDE.md 命令表、架构规范（启动与镜像、时区）、测试规范、需求池 R46、changelog)
Final: 独立审查（opus）：Critical 0、Important 3、Minor 8；报告 scratchpad/review-r46-report.md；Review Focus 5 条都成立
Final: fixed I1 .dockerignore 加 dist（test_bundles_never_enter_build_context RED→GREEN）
Final: fixed I2 打包脚本缺 .env 时提示 cp .env.example .env（test_missing_env_says_what_to_do RED→GREEN），使用指南同写
Final: Ruling: I3 ollama-init 下载失败也正常结束（打印提示），后端照常起来、能对话，知识库等模型下好；不然 make restart 会把正在用的后端停掉 — 代价：没联网的第一次启动，知识库检索会报错直到模型下好（make doctor 报 ✗）。test_embedding_download_failure_does_not_stop_backend RED→GREEN
Final: fixed M1 Makefile 取不到系统时区时不导出空 HOST_TZ（测试改成钉住 ifneq；先改代码后改测试，未单独 RED）、M2 usage 时区矛盾、M3 旧注释、M4 SKIP_BUILD+PLATFORM 警告（test_platform_with_skip_build_warns RED→GREEN）与跨芯片替换本机镜像的说明、M5 COMPOSE 不是 docker/podman 时报错、M6 脚本默认用项目里的空 DOCKER_CONFIG、M8 新机器要有 make
Final: minor (deferred): M7 同一秒打包两次文件名相同——几乎不会发生
Final: 修完后 make check 全过；本机切换 18:15（先备份 20261028-181554；cd deploy && podman compose up -d）：后端 healthy，挂载只剩 .workdata、/shared、遮住备份的空目录（不再挂源码），ollama-init 正常结束；数据前后一致（会话 2、记忆 13、文档 1）；make doctor 全部正常；8000 对话、知识库、MCP 页正常，控制台无报错。TZ=UTC：用户的 .env 还没写 HOST_TZ（不读 .env，请用户自己加）
Final: 打包实测 SKIP_BUILD=1 make bundle：存出 6.8G 的文件，podman load 能加载回 4 个镜像（名字与 compose 一致）；验证后已删掉文件；.gitignore 加 dist/
完成
Final: 用户 2026-10-28 追加：构建电脑不依赖 .env——compose 的 env_file 改成 required: false；打包脚本用空环境文件 + 两项密钥占位值解析 compose（test_build_machine_needs_no_env、test_env_file_is_optional_for_building RED→GREEN）；实测没有 .env 的项目副本里 config --images 正常；本机重新 up -d 后后端 healthy、体检全部正常。另：用户要求清理 <none> 镜像，podman image prune 删掉 441 个（25.25GB→12.51GB）
