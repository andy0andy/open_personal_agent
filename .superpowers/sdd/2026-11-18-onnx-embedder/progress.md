# SDD ledger — plan: docs/plans/2026-11-18-onnx-embedder.md

Ruling: 不按任务提交 — 用户 2026-11-18 明确要求"每个任务先不提交，验收完后再通知提交" — 代价：整体审查按工作区改动做，不按提交范围。
Ruling: 直接在 main 上做，不开工作树 — 项目一直这样做，用户已说"开始执行" — 代价：做到一半时工作区是半成品。
Pre-flight: Task 2 用 Task 1 的 Embedder/EmbedKind/EMBEDDING_DIMENSIONS（一致）；Task 3 用 Task 2 的 OnnxModelSpec（一致）；Task 4 用 Task 2、3（一致）；Task 5 用 Task 1 的 kind 与 Task 3 的 ensure_model（一致）；Task 7 的体检常量对照 Task 2 的 ONNX_MODELS（有测试）。无冲突。
Task 2: complete (不提交；tests: make check → 后端 798 passed / 前端 449 passed；真实 gemma 模型在宿主机上试过：加载加计算 1.2 秒，跨语言排对)
暂停（2026-11-18 17:30，用户要求）：下一步从 Task 3（模型文件的下载与校验）开始。服务仍在跑旧镜像（Ollama 方案），数据库没动；工作区是半成品，不要构建镜像。
Task 3: Ruling: 不做命令行入口（计划早先版本里的 main）— 模型改由后端启动后在后台下载（D28 已写明），用不到 — 代价：想手动预下载只能起后端。
Task 3: complete (不提交；tests: make check 见下一行；真实仓库上试过最小的文件：分段下载 + 校验通过)
Task 4: Ruling: 先做 Task 7 再做 Task 5、6 — 默认清单去掉 Ollama 模型后，体检的'三处是同一个'测试失败，它属于 Task 7 — 代价：无（Task 7 不依赖 5、6）。端到端测试改在 Task 6 之后一起跑。
Task 4: complete (不提交；tests: make check → 后端 810 passed / 前端 449 passed，与 Task 7 一起跑的)
Task 7: complete (不提交；tests: uv run pytest deploy/tests → 49 passed；干净拷贝里 compose config 只列出 postgres、litellm、backend 三个服务与三个镜像)
Task 5: Ruling: 启动时的下载与补算放在新函数 backend.main._prepare_embeddings（单独一个后台任务），不塞进 _seed_models — 两者互不等待，现有 _seed_models 的测试也不用跟着改 — 代价：无。
Task 5: complete (不提交；tests: make check → 后端 814 passed / 前端 449 passed；知识存储契约 36 passed（集成）)
Task 6: complete (不提交；tests: make check → exit 0；pytest -m integration → 384 passed；make e2e → 38 passed)
Task 8: 真实模型测试 4 passed（uv run pytest -m live agents/tests/live/test_onnx_embedding.py）；文档已更新；切换前备份 20261118-204128
Task 8: 本机切换完成（2026-11-18 20:45）：make build → 迁移 0019、模型文件校验通过（预先放好，没下载）、13 条知识条目补算完、网关里的 embed-qwen3-0.6b 已删；make doctor 全部 ✓（容器 3 个）；真实对话验证召回生效；用量表有 embedding / embeddinggemma-300m-q4；后端日志 0 条错误。
Task 8: 最后一遍 make check → 后端 815 passed / 前端 449 passed。待做：整体审查；旧 Ollama 的容器、数据卷、镜像待用户确认后清理。
Final review: 独立审查（最强模型）完成：无 Critical，2 个 Important，6 个 Minor。重新定级后 Important 两条成立。
Final: fixed 下载失败后不再重试、要等手动重启 — test_download_is_retried_until_it_succeeds、test_backfill_waits_while_the_download_keeps_failing、test_retries_a_connection_blip RED→GREEN
Final: fixed 大小对但内容坏了的文件在重新下载期间仍可被加载 — test_invalid_file_is_removed_before_downloading_again RED→GREEN
Final: minor (deferred): embed 被取消（召回超时）后锁已释放而线程还在算，下一批会并发；可用 shield 包住整段计算。
Final: minor (deferred): 下载地址不支持 Range（返回 200 全文）时会在多个连接上各缓冲整个文件、报"内容不完整"；pwrite 的返回值没检查。
Final: minor (deferred): 清理 Ollama 模型只按上游前缀 ollama/ 判断，用户自己接的 Ollama 对话模型也会被删（默认或在用的除外）；可再核对 api_base 是 http://ollama:11434。
Final: minor (deferred): D28 说"把 adapters.embedder 改回 litellm_proxy 即可"，但默认来源里已没有向量来源，还要用 MODELS__SOURCES 加一个；设置页"目前每项只有一种实现"的说明对向量化已不准；ModelsPage.tsx:45 的注释还写"导入的 4 个"。
Final: minor (deferred): 升级的安装会留下还在运行的 ollama 容器、数据卷、镜像（make up 不带 --remove-orphans），README / 使用指南 / 变更记录没写怎么清。
Final: minor (deferred): 测试没覆盖：加载或计算途中被取消、下载途中关闭后端、不支持 Range 的服务器。
Final: Ruling: Hugging Face 的重定向与分段下载（审查没评）— 在宿主机上用真实仓库把整个模型下到临时目录验证（结果见下）— 错了的代价：新机器首次下载失败，体检报 ✗ 并给出换镜像站的办法。
Final: Ruling: .env 里若有 KNOWLEDGE__EMBEDDING_MODEL / ADAPTERS__EMBEDDER 的旧值会让启动报配置错误（审查没评，不读 .env）— 本机新后端已正常启动并用上新模型，说明没有这样的覆盖 — 别的机器若有，报错信息会列出可用的名字。
Final: Ruling: 取消时 pwrite 线程与 os.close 的描述符竞争（审查没评，理论上的）— 不处理 — 代价：极端情况下下载失败一次，随后自动重试。
Final: Ruling: uv.lock 的 exclude-newer 时间戳变了（审查没评）— uv 重新锁定时自动更新，包的版本没变 — 无代价。
Final: 修复后 make check → 后端 818 passed / 前端 449 passed（2026-11-18 20:59）。
阻塞（2026-11-18 20:59 起）：podman 虚拟机无响应（ssh 握手被重置，8000 端口不通，虚拟机进程 4 核占满，原因未查明）。因此修复之后的集成测试没跑成、镜像没重建：正在运行的镜像是 20:43 构建的，不含审查后的两处修复。恢复后要做：podman stats 与后端日志查原因 → make test-int → make build → make doctor。重启虚拟机会连带重启用户的其他容器，要先问用户。
Final: 真实仓库整包下载验证通过（2026-11-18 21:20，宿主机）：三个文件全部下载并校验通过，第二次调用不联网，下载下来的模型能算出 768 维向量；这次网络很慢，共用了 1377 秒（约 23 分钟）。podman 虚拟机 21:20 仍无响应。

## 2026-11-18 22:26 起：用户决定"重启虚拟机，修 1、4、5，清掉旧的 Ollama"

- 虚拟机：22:26 时 CPU 已降到 0 但仍连不上；`podman machine stop` 正常停止超时、走了强制停止，22:28 重新启动成功。上一次启动的系统日志停在 20:48:40（最后一条是同一台虚拟机里、与本项目无关的另一个容器的崩溃转储，它一直在崩溃重启）；后端到那时健康检查都是 200。卡死的直接原因没有证据能定论。
- 重启后所有容器都是 Exited：把卡死前在运行的、用户的其他容器启动了，一直崩溃的那个和之前就停着的没动。`make up` 后三个容器健康、8000 端口 200。
- Final: fixed minor 1（取消后锁被放开、下一批并发）— test_cancelled_call_keeps_its_turn_until_the_batch_finishes RED→GREEN；另加 test_cancelled_call_does_not_leave_an_unretrieved_error（去掉取走异常的那行会失败，已验证）。
- Final: fixed minor 4 — test_adapter_notes_say_how_many_implementations_exist RED→GREEN；D28"换回经网关的实现"改成完整的四步；ModelsPage.tsx 注释改对。
- Final: fixed minor 5 — 使用指南第 2 节、README、变更记录、D28 写明升级后要手工清旧 Ollama 的三条命令。
- 22:34 清掉旧 Ollama：两个容器、数据卷 open-personal-agent_ollama-models、镜像 ollama:0.40.3；虚拟机磁盘 31 GB → 26 GB。
- 仍延后的小问题：2（不支持 Range 的服务器）、3（清理只按 ollama/ 前缀）、6（测试缺口里除"计算途中取消"外的两项）。
- 22:35～22:40 修完后的验证：make check 通过（后端 821、前端 449）；make test-int 384 通过；make build 后 make doctor 9 项全 ✓；界面上英文问句搜到中文记忆；make e2e 结果见最终汇报。
