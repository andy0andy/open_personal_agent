# 测试规范

## 1. 分层与命令

| 层次 | 标记 | 命令 | 需要什么 |
|---|---|---|---|
| 单元测试（含契约测试、离线先行验证） | 无 | `make test`（`make check` 也会跑） | 什么都不需要 |
| 集成测试 | `@pytest.mark.integration` | `make test-int` | 自动启动 compose `test` 配置组的 `postgres-test`（端口 55432）；用完可 `make test-down` 关掉 |
| 真实模型冒烟测试 | `@pytest.mark.live` | `make smoke` | `make infra-up` + `.env` 中的模型密钥；会产生少量费用 |
| 前端单元测试 | — | `cd frontend && pnpm test` | 什么都不需要 |
| 端到端测试 | — | `make e2e` | 自动启动 `postgres-test`；本机已装的 Chrome（Playwright 用 `channel: "chrome"`，不另下载浏览器） |

默认 `pytest` 只跑单元测试（`pyproject.toml` 的 `addopts` 排除了 integration 与 live）。

## 2. 写测试的规则

- 先写测试、看它失败，再写实现。
- **临时目录**：测试用 `tmp_path`；测试与被测代码里 `tempfile.mkdtemp` 之类建的目录，根 `conftest.py` 已把它们换到 pytest 的临时目录下（只留最近 3 次），不会留在系统临时目录里（R45）。
- **不碰真实密钥**（设计 2026-10-23 7.6）：根目录 `conftest.py` 在测试开始前清掉名字以 `_KEY`、`_TOKEN`、`_SECRET`、`_PASSWORD` 结尾的环境变量，构造设置时不读 `.env`，并让 `dotenv.load_dotenv` 什么都不做（litellm、magika 一导入就读 `.env`，比清凭据还早，库地址也会带进来）；`-m live` 除外，照常读 `.env`。测试要用密钥时自己给假值（`monkeypatch.setenv`）。
- **不靠固定等待保证先后顺序**：等事件（慢替身开始时 set 一个 `asyncio.Event` / `threading.Event`）或等条件（`agents/tests/waiting.until(条件, within=秒数)`，每 0.01 秒看一次）；前端用假时钟（`vi.useFakeTimers`）或 `vi.waitFor`。确实要等够时长的（替身模拟慢或卡住、有上限的轮询、断言一段时间里什么都没发生）写"允许等待：原因"（Python 写在 sleep 那一行；前端写在这次 setTimeout 调用跨过的某一行）；`backend/tests/test_test_hygiene.py`（`asyncio`、`time`、`anyio`、`trio` 的 sleep）与 `frontend/src/test-hygiene.test.ts`（按括号配对找整次 `setTimeout` 调用，跨行写的、prettier 拆行后末尾带逗号的也认；配括号时不管字符串里的括号，`1_000` 这种写法也不认）扫描把关。
- **不调用真实模型**：用 `agents/tests/fakes.py` 里的 `ScriptedChatModel`（按剧本回复，支持工具调用、思考过程、用量与逐字流式，并记下每次收到的消息）、`HangingChatModel`（第一次调用输出一个字后一直等待，用于验证停止）、`BreakingChatModel`（先输出一段再抛出指定的错误，用于验证失败时保留已输出的部分与额度用完的提示）、`FailingChatModel`、`FakeGateway`。LangChain 自带的 `GenericFakeChatModel` 在流式模式下不支持工具调用，不要用。
- **契约测试**：每个可替换接口有一套测试，用参数化列出全部实现；新实现必须加进列表并跑通。agents 的接口在 `agents/tests/contracts/`；backend 的运行时替换点在 `backend/tests/`（如 `test_run_control.py`）。
- **执行命令的测试**：`agents/tests/test_local_sandbox.py` 在临时目录里真的执行命令（超时与停止杀掉进程组、长输出写日志、不传密钥类环境变量、共用智能体的 Python）。数僵尸进程、Landlock 写入限制、补杀脱离进程组的进程（`test_reaper.py`）这几项只在 Linux 上跑（要读 `/proc`、要内核支持），macOS 上跳过：要在后端容器里验证（宿主机上的孤儿进程由系统回收，测不出来）。镜像不带开发依赖，用临时装的 pytest 跑，不改动镜像环境：`podman compose ... exec -w /app -e PYTHONPATH=/app backend uv run --no-sync --with pytest==9.1.1 --with pytest-asyncio==1.4.0 pytest -p no:cacheprovider agents/tests/test_local_sandbox.py`（需要联网下载 pytest）。注意：以 root 跑 pytest 时它建的临时目录是 0700，换成 uid 1000 的命令进不去，涉及换用户的测试会成片失败——这类行为改用探针脚本在后端镜像的临时容器里验证（`podman run --rm --init`，挂上当前的 `agents`、`common`、`config`，工作区放在自己建的、权限放开的目录下，如 `/var/wd`；积压小问题第三批的做法）。
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
- **迁移测试**：改动已有数据的迁移要测"旧数据升级后的样子"：用 `alembic_config` 夹具退回到上一版（`command.downgrade`），写入旧格式的数据，再升级并核对；`finally` 里升回 `head`（见 `backend/tests/test_migrations.py`）。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`；`backend/main.py` 里真实的启动与关闭顺序由 `backend/tests/test_main_lifespan.py` 用替身单独测（积压小问题 I13）。客户端默认带着本机令牌（`X-Session-Token`，D25），Host 是 `localhost`；要测没带令牌的情况时自己从 `client.headers` 里去掉。本机守卫本身在 `backend/tests/test_local_guard.py` 里单独测（不要数据库）。
- **MCP 断线重连的测试**（`agents/tests/contracts/test_mcp_client_contract.py`）：真的启动测试用服务进程再杀掉它，时间间隔经 `ReconnectTiming` 调小（ping 0.2 秒、重试 0.1 秒）；测试用服务用环境变量开关模拟"启动即退出""多一个工具""启动几秒后自己退出""以网络方式（streamable-http）运行"（见 `fixtures/mcp/demo_server.py` 开头）；取工具清单时一直不回的服务是 `fixtures/mcp/hang_list_server.py`。等状态变化用隔一会儿看一次的方式，最多等 15 秒。只属于这个实现、不属于接口约定的行为（如有调用在进行时不 ping）放在 `agents/tests/test_mcp_adapters.py`。
- **离线先行验证**放在 `agents/tests/spikes/`：用于固定"第三方库的关键行为"，库升级后它们会第一时间报警。
- 前端：纯逻辑（如 `features/chat/reducer.ts`、`components/chat/adapter.ts`）必须有 Vitest 单元测试；事件序列用接近真实的样例。
- 前端测试跑在 node 里、没有页面（组件用 `renderToStaticMarkup` 只看得到首次渲染），所以组件里的判断与时序先抽成纯函数再测（积压小问题第一批的约定）：如对话框里 Tab 的去向 `nextFocusIndex`、关闭后焦点回到谁 `focusAfterClose`、菜单方向键 `nextIndex`、保存中的顺序 `pendingOrder`、工具清单变没变 `toolsChanged`、上传前的预查 `inspectUpload`。和 TanStack 缓存时序有关的（如拖动排序的保存）直接拿选项对象配 `QueryClient`、`MutationObserver` 与假时钟测（`features/threads/reorder.test.ts`）。键盘与焦点的整体效果由端到端测试把关（如 `e2e/skills.spec.ts` 的上传对话框）。
- 前端设计系统有两条自动检查：主题契约（`src/themes/themes.test.ts`）与写死颜色检查（`src/styles/no-raw-colors.test.ts`），改动主题或组件后它们必须通过。测试文件里的类名不会生成样式（`src/index.css` 的 `@source not`），可以放心写反例。
- **前端类型**：由 `make types` 生成（`src/api/generated/`）。`make check` 会核对两件事：`generated/openapi.json` 与后端当前的接口和事件定义一致（`backend/tests/test_openapi.py`），`schema.d.ts` 与 `openapi.json` 一致（`pnpm types:check`）。改了接口或事件却没重新生成时，按提示运行 `make types`。

- **端到端测试**（`frontend/e2e/`，Playwright）：
  - 后端是 `backend/tests/e2e_server.py`：真实的 backend，外部依赖换成替身，数据库只能用测试库实例里的 `agent_e2e` 库，每次启动清空，不连网关、不花钱。`.workdata` 在系统临时目录下的 `opa-e2e-workdata`，同样每次启动先清空（Playwright 停服务时直接强杀，收尾删不掉）。
  - 假模型 `KeywordChatModel`：按最后一条用户消息里的关键词选剧本，第几步看那之后已有几条回复，与调用顺序无关。加场景就是在 `scripted_model()` 里加一个"关键词 → 步骤"，测试里发含这个关键词的消息。步骤可以是函数，按对话内容生成，如从系统提示词里取本会话的工作目录。
  - 标题生成回空字符串，会话保留首条消息作标题，测试按它在侧栏里找会话。
  - 演示 MCP 服务 `demo` 有三个工具：`demo_add_note`、只读的 `demo_list_notes`、只读且跑 2 秒的 `demo_wait`（"运行中插话"用：工具跑着时插话，下一次调用看到的最后一条用户消息就是插的话，剧本按它选）。改了工具数，MCP 页测试里的"3 个工具"跟着改。
  - 定位元素按用户看得见的东西（按钮名、占位文字、可见文字）。折叠着的工具卡片里常有同样的文字，必要时 `filter({ visible: true })`。
  - 绕过界面直接调接口时（如 `page.request.delete(…)`），先用 `helpers.ts` 的 `tokenHeaders(page)` 取本机令牌、带在请求头里：写操作只认请求头（D25）。
  - 不进 `make check`（要测试库和 Chrome），改了界面或运行流程后运行 `make e2e`。
- **备份脚本测试**（`deploy/tests/test_backup_scripts.py`，集成）：在测试库实例里建专用库 `backup_probe`，用临时目录当 workdata，经环境变量把脚本指过去；绝不对正式数据库执行恢复。恢复前后的对比在 `backup_probe` 里建同名的 `threads`、`runs` 两张表来测。备份名用测试才设的 `BACKUP_TIME`，不靠等过一秒。
- **旧说法扫描**（`deploy/tests/test_wording.py`，单元）：代码、部署与在用的文档里不再出现过时的说法（范围同 `test_paths.py`，跳过各处 `tests/` 与前端的 `*.test.*`、`*.spec.*`）；改了某个说法的依据（如删掉一个设置项）时，把旧说法连同理由加进表里。
- **打包镜像**（`deploy/tests/test_bundle.py`，单元）：用记下参数的替身代替 docker / podman 执行 `deploy/bundle-images.sh`，只核对构建、拉取、保存的调用与芯片参数，不真的构建。扫描类测试（`test_paths.py`、`test_wording.py`）跳过 `.env` 与链接，不读密钥。
- **体检**（`deploy/tests/test_doctor.py`，单元）：执行命令与发请求的函数都换成替身，不碰容器；超时用一个只接受连接、不回话的本机端口和一条卡住的命令来测。

## 3. 完成一个任务前

`make check` 全部通过；涉及数据库的改动还要 `make test-int` 通过。
