# M2a 沙箱与代码执行 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** M2 的前一半——智能体能在隔离的沙箱里执行代码、生成文件，用户在对话里直接看到、打开、下载这些文件。

- 沙箱镜像与执行服务：命令在独立容器里运行，不能上外网，有资源与时间上限，停止时连同子进程一起结束。
- 每个会话一个工作目录，智能体只能读写自己会话的目录；删除会话时一并删除。
- 智能体技能（首个：Excel / CSV 处理规范）与数据分析员子智能体（跟随主对话所选模型）。
- 产物检测：智能体在 `outputs/` 里新建或改动的文件显示为对话里的卡片（图片直接显示），可打开、下载。

M2 拆成两份（2026-10-15 与用户确认）：**M2a 是本计划**；M2b 是文件上传、右侧文件面板、各类预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型。

**架构：**

- **沙箱**（`deploy/sandbox/`）：单独的镜像，里面只跑一个执行服务（Starlette 小程序，不引用项目代码）。
  - backend 带共享密钥调用 `POST /execute`；命令在 `/workspace/<会话短 ID>/` 下用 bash 运行，单独成一个进程组；
  - 超时、或请求方断开（运行被停止）时杀掉整个进程组；
  - 输出过长时只返回开头一段，完整输出写进会话目录的 `logs/`。
  - compose 里：非 root、根文件系统只读、只接入内部专用网络、限制 CPU / 内存 / 进程数。backend 与沙箱挂载同一个 `workdata/workspace/`。
- **工作区**（`agents/main_agent/workspace/`，新的可替换接口）：
  - `Workspace`：给智能体用的文件后端、列出产物、读文件（下载用）、删除会话目录；
  - `Sandbox`：执行命令；
  - 本地实现 `LocalWorkspace`（deepagents 本地文件后端 + 会话限制 + 执行命令）与 `HttpSandbox`（调用执行服务），在 `bootstrap.py` 按 `config/app.yaml` 的 `adapters.workspace` 装配。
- **运行时**（`agents/main_agent/runtime/`）：
  - `files.py` 组装智能体看到的文件树：`/workspace/`（工作区）、`/skills/`（技能，只读）、`/.agent/`（大段工具输出的转存，存在对话存档里）；
  - 会话短 ID 经运行上下文 `AgentContext` 传给工作区（子智能体继承同一上下文）；
  - 子智能体从 `agents/subagents/*.md` 读取；每次写文件或执行命令后检查 `outputs/`，有新增或改动就发出 `file.created` 事件。
- **产物**（backend + 前端）：
  - 运行管理收到 `file.created` 时用"会话 ID + 路径"算出固定的文件 ID 填进事件再推送，登记 `workspace_files` 表放在后台；
  - 下载接口 `GET /api/threads/{会话}/files/{文件}/content`（`?download=1` 为附件）；
  - 前端把事件记成文件项，显示为产物卡片。

**技术栈：**

- 新增 Python 依赖 `pyyaml==6.0.3`：读子智能体定义文件开头的 YAML。
- 沙箱镜像：
  - 基础镜像 `ghcr.io/astral-sh/uv:0.11.7-python3.12-trixie-slim`；
  - 中文字体 `fonts-wqy-microhei=0.2.0-beta-4`；
  - 预装库与执行服务依赖写死在 `deploy/sandbox/requirements.in`，由 `make sandbox-lock` 生成带哈希的锁定文件。
- 用到的 deepagents 0.7.23 能力：
  - `FilesystemBackend(virtual_mode=True)`、显式继承 `SandboxBackendProtocol`（才会提供 `execute` 工具）；
  - `CompositeBackend(artifacts_root=…)`、`StateBackend`；
  - `create_deep_agent(skills=…, subagents=…, context_schema=…)`；
  - 中间件：langchain `AgentMiddleware.wrap_model_call`。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）——第 9 节（代码执行与文件）、7.3 节（文件按路径分流）、7.4 节（子智能体与技能）、7.6 节（系统提示词）、第 21 节 M2 行。

> 本计划的全部代码在写计划时已于临时目录实际运行验证（`make check`、集成测试全部通过，数量见各任务检查点）。
>
> 也已用真实模型在浏览器里端到端验证（约 0.2 美元）：画带中文的图表、产物卡片、刷新后仍在、打开与下载（响应头正确）、停止正在执行的命令（沙箱里不留进程、卡片显示"已中断"）、数据分析员生成 Excel 与饼图、删除会话后目录与登记都被清除。
>
> 计划中的每段代码由脚本从验证过的文件直接嵌入，并已从改动前的项目出发按本计划逐任务重放、逐字核对。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。
- deepagents 只能出现在 `agents/main_agent/runtime/`；**例外**：`agents/main_agent/workspace/` 可以引用 `deepagents.backends`（工作区实现就是 deepagents 的文件后端，任务 2 把这条例外写进规范）。
- 只新增一个 Python 依赖 `pyyaml==6.0.3`（直接依赖写死版本）。前端不加依赖。沙箱镜像里的库版本写死在 `requirements.in`。
- 第三方服务与镜像一律由 `deploy/docker-compose.yml` 管理；只操作本项目的容器（本机还有其他项目的容器，不要动）。
- 密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。沙箱内部密钥 `SANDBOX_SECRET` 由 `make` 命令在缺少时自动生成并追加到 `.env` 末尾。
- 表结构变更用 Alembic、一律写原生 SQL，文件名带归属模块前缀。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 由命令生成的文件不手改：`frontend/src/api/generated/`（`make types`）、`uv.lock`（`uv lock`）、`deploy/sandbox/requirements.txt`（`make sandbox-lock`）。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 直接运行 Python 测试时要有环境变量 `LITELLM_LOCAL_MODEL_COST_MAP=True`、`LANGGRAPH_STRICT_MSGPACK=true`（Makefile 与根目录 `conftest.py` 已设置）。
- 集成测试先 `make test-up`：本计划起它同时启动测试数据库与测试沙箱（`127.0.0.1:58080`，密钥 `test-secret`，工作目录 `workdata/sandbox-test/workspace/`）。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **智能体访问别的会话目录、用 `..` 跳出、不给路径就搜索** → 工具返回错误（"只能访问本会话的工作目录"），对话继续，不是整次运行失败。测试：
   - 任务 2 `test_other_sessions_and_outside_paths_are_refused`、`test_searches_without_a_path_stay_in_own_session`；
   - 任务 3 `test_files_land_in_this_threads_directory`、`test_data_analyst_works_in_the_same_directory`；
   - 任务 6 浏览器验证第 6 步。
2. **停止正在执行的命令（含它放到后台的子进程）** → 沙箱里的进程全部结束，回答下方"已停止"，工具卡片显示"已中断"而不是一直转圈。测试：
   - 任务 1 `test_stops_when_asked`、`test_timeout_kills_the_whole_process_group`；
   - 任务 2 `test_cancelling_the_request_kills_the_command`（真实沙箱）；
   - 任务 5"工具与子智能体步骤的显示状态"两个测试；
   - 任务 6 浏览器验证第 3 步。
3. **命令输出巨大、命令一直不结束** → 只返回开头一段并告诉智能体完整输出在 `logs/` 的哪个文件；超时后提示"已终止"。测试：任务 1 `test_long_output_is_cut_and_saved_to_a_log`、`test_timeout_kills_the_whole_process_group`、`test_timeout_is_capped`；任务 3 `test_long_command_output_stays_out_of_the_workspace`。
4. **下载别的会话的文件、文件已被删除、智能体生成的 HTML / SVG 里带脚本** → 前两种返回 404（后者说明"文件已不存在"）；直接打开时脚本不执行（响应头 `Content-Security-Policy: sandbox`、`X-Content-Type-Options: nosniff`）。测试：任务 4 `test_download_an_output_file`；任务 2 `test_reads_a_file_for_download`。
5. **沙箱不可用（容器没起来、密钥不对、时限超范围）** → 智能体收到看得懂的原因，对话照常结束，可以换个做法。测试：任务 2 `test_unavailable_sandbox_becomes_a_readable_error`、`test_sends_secret_session_and_time_limit`；任务 1 `test_execute_needs_the_shared_secret`、`test_timeout_is_capped`。

## 先行探测结论（2026-10-15 写计划时实测）

| 问题 | 结论 |
|---|---|
| deepagents 本地文件后端越界时抛什么 | `virtual_mode=True` 遇到 `..` 抛 `ValueError`，会让整次运行失败；deepagents 只把 `OSError` / `RuntimeError` 转成工具错误。所以会话限制一律抛 `PermissionError`（属于 `OSError`），自带的 `ValueError` 也转成它 |
| 在哪里加会话限制 | `FilesystemBackend._resolve_path` 是读、写、编辑、列目录、搜索的共同入口，限制加在这里即可；但 `glob` / `grep` 不给路径时默认搜整个根目录，要把默认路径改成本会话目录 |
| 子智能体能否取到会话短 ID | 能：`get_runtime(AgentContext).context` 在主智能体和子智能体的工具里都能取到（子智能体继承运行上下文） |
| 超长工具结果转存到哪里 | deepagents 把超长工具结果写进文件树的 `large_tool_results/`。用 `CompositeBackend(artifacts_root="/.agent")` 加 `"/.agent/": StateBackend()` 路由后，转存进对话存档，不落进用户的工作目录 |
| 停止能否传到沙箱 | 能：`execute` 工具调用后端的 `aexecute`，运行被取消时一路取消到 HTTP 请求、连接断开；执行服务用 Starlette 的 `request.is_disconnected()` 察觉后杀掉进程组 |
| Mac 上 podman 的共享目录 | backend（root）与沙箱（uid 1000）挂载同一个宿主机目录，双方都能读写、删除对方建的文件；`internal: true` 的网络里访问外网失败；`read_only` 加 `/tmp` 内存盘可用 |
| 中文图表 | 装文泉驿微米黑并在 `matplotlibrc` 设 `font.sans-serif` 后中文正常；模型自己写 `plt.rcParams` 指定 SimHei 等字体时也能回落到它 |
| 沙箱镜像体积 | 约 834MB（主要是 pandas、matplotlib、pymupdf） |
| 产物事件里的文件 ID | 用"会话 ID + 路径"算出固定 ID（uuid5），推送时不必等数据库，登记放后台——处理事件的循环里不能有真正的等待（停止要落在智能体内部） |
| 停止后工具卡片的状态（端到端验证时发现，M1b 起就有） | 停止后没有结束的工具调用、子智能体一直显示"运行中"。assistant-ui 对没有结果的工具片段给出所在消息的状态（已取消 / 出错），卡片据此显示"已中断"（任务 5） |

## 文件结构（本计划涉及）

```
deploy/
├── sandbox/                       # 新：沙箱镜像
│   ├── Dockerfile
│   ├── sandbox_service.py         # 执行服务（只依赖 starlette、uvicorn）
│   ├── test_sandbox_service.py
│   ├── requirements.in            # 预装库与服务依赖（写死版本）
│   ├── requirements.txt           # make sandbox-lock 生成（带哈希）
│   └── matplotlibrc               # 中文字体
└── docker-compose.yml             # 改：sandbox、sandbox-test、内部专用网络
agents/
├── main_agent/
│   ├── context.py                 # 新：运行上下文 AgentContext（会话短 ID 等）
│   ├── workspace/                 # 新：工作区替换点
│   │   ├── base.py                # 接口 Workspace、Sandbox
│   │   ├── local.py               # 本地实现：会话限制 + 执行命令
│   │   ├── sandbox_http.py        # 沙箱客户端
│   │   └── files.py               # workspace_files 表
│   ├── runtime/files.py           # 新：智能体看到的文件树、工作目录提示
│   ├── runtime/subagents.py       # 新：读取子智能体定义
│   ├── runtime/agent.py           # 改：接上工作区、技能、子智能体、产物检测
│   ├── runtime/events.py          # 改：file.created 事件
│   └── bootstrap.py               # 改：装配工作区
├── skills/excel/SKILL.md          # 新：Excel / CSV 处理规范
├── subagents/data_analyst.md      # 新：数据分析员
└── prompts/system.md              # 改：文件与代码一节
backend/
├── runs/manager.py                # 改：传会话短 ID、产物 ID 与登记、删除会话清理
├── api/router.py、deps.py          # 改：下载接口
└── migrations/versions/0005_agents_workspace_files.py   # 新
config/settings.py、config/app.yaml # 改：工作区配置、技能与子智能体目录
frontend/src/
├── features/chat/reducer.ts       # 改：文件项
├── components/chat/               # 改：产物卡片、文件地址、步骤"已中断"
└── api/client.ts                  # 改：文件地址
Makefile、.env.example、pyproject.toml、uv.lock   # 改
docs/                              # 改：编码规范、开发技能、架构、README、需求池、变更记录
```

---

### 任务 1：沙箱镜像与执行服务

**文件：**
- 新建：`deploy/sandbox/sandbox_service.py`、`test_sandbox_service.py`、`requirements.in`、`requirements.txt`（命令生成）、`matplotlibrc`、`Dockerfile`
- 修改：`pyproject.toml`、`Makefile`、`deploy/docker-compose.yml`、`.env.example`、`backend/tests/test_manager.py`

**接口：**
- 产出（执行服务，供任务 2 的 `HttpSandbox` 调用）：
  - `GET /health` → `{"status": "ok"}`（不需要密钥）；
  - `POST /execute`，请求头 `Authorization: Bearer <SANDBOX_SECRET>`，请求体 `{"session": "c_xxxxxxxx", "command": str, "timeout": int | null}`；
  - 返回 `{"output": str, "exit_code": int, "truncated": bool, "timed_out": bool}`；
  - 错误：密钥不对 401 `{"detail": "密钥不正确"}`；会话 ID 不是 `c_` 加 8 位十六进制 400"会话 ID 格式不正确"；时限不在 1～`SANDBOX_MAX_TIMEOUT`（默认 600）秒 400"超时时间须在 1～600 秒之间"。
- 产出（compose）：
  - 服务 `sandbox`：只接入内部专用网络 `sandbox`，挂载 `../workdata/workspace:/workspace`；
  - 服务 `sandbox-test`（test 配置组）：端口 `127.0.0.1:58080`，密钥 `test-secret`，挂载 `../workdata/sandbox-test/workspace`；
  - backend 同时接入 `default` 与 `sandbox` 网络，带 `SANDBOX_SECRET`，等沙箱健康后才启动。
- 产出（Makefile）：`make sandbox-lock`；`make test-up` / `test-down` 包含 `sandbox-test`；`make build` 同时构建沙箱镜像；用到 compose 的命令先确保 `.env` 里有 `SANDBOX_SECRET`、工作区目录存在。

- [ ] **步骤 1：写失败的测试**

执行服务是独立小程序，测试直接导入它：把 `deploy/sandbox` 加进 pytest 的导入路径，`deploy` 加进测试目录。

在 `pyproject.toml` 中，把：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["agents", "backend", "common", "config"]
asyncio_mode = "auto"
```

改为：

```toml
[tool.pytest.ini_options]
pythonpath = [".", "deploy/sandbox"]  # 沙箱执行服务是独立小程序，测试时直接导入
testpaths = ["agents", "backend", "common", "config", "deploy"]
asyncio_mode = "auto"
```

新建 `deploy/sandbox/test_sandbox_service.py`：

```python
import asyncio
import os
import signal
import time
from pathlib import Path

import pytest
import sandbox_service
from httpx import ASGITransport, AsyncClient
from sandbox_service import Settings, create_app, run_command

SECRET = "test-secret"
AUTH = {"authorization": f"Bearer {SECRET}"}


def _settings(root: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "workspace_root": root,
        "secret": SECRET,
        "default_timeout": 5,
        "max_timeout": 10,
        "max_output": 1000,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _client(root: Path, **overrides: object) -> AsyncClient:
    app = create_app(_settings(root, **overrides))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://sandbox")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_dead(pid: int) -> bool:
    for _ in range(50):
        if not _alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_health_needs_no_secret(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}


async def test_execute_needs_the_shared_secret(tmp_path: Path) -> None:
    body = {"session": "c_0123abcd", "command": "echo hi"}
    async with _client(tmp_path) as client:
        assert (await client.post("/execute", json=body)).status_code == 401
        wrong = {"authorization": "Bearer nope"}
        assert (await client.post("/execute", json=body, headers=wrong)).status_code == 401


@pytest.mark.parametrize("session", ["../etc", "c_xyz", "c_0123abcd/..", "", "C_0123ABCD"])
async def test_session_must_look_like_a_short_id(tmp_path: Path, session: str) -> None:
    """会话 ID 用来拼工作目录：只接受 c_ 加 8 位十六进制，杜绝 ../ 之类的越界。"""
    async with _client(tmp_path) as client:
        response = await client.post(
            "/execute", json={"session": session, "command": "pwd"}, headers=AUTH
        )
    assert response.status_code == 400


async def test_runs_in_the_session_directory(tmp_path: Path) -> None:
    body = {"session": "c_0123abcd", "command": "pwd; echo 中文 >&2; exit 3"}
    async with _client(tmp_path) as client:
        result = (await client.post("/execute", json=body, headers=AUTH)).json()
    session_dir = (tmp_path / "c_0123abcd").resolve()
    assert result["exit_code"] == 3
    assert str(session_dir) in result["output"]
    assert "中文" in result["output"]  # 标准错误也收进输出
    assert (result["truncated"], result["timed_out"]) == (False, False)


async def test_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    """超时要杀掉整个进程组：命令派生的后台子进程也不能留下来继续占用资源。"""
    command = "sleep 30 & echo $! > child.pid; sleep 30"
    started = time.monotonic()
    async with _client(tmp_path) as client:
        body = {"session": "c_0123abcd", "command": command, "timeout": 1}
        result = (await client.post("/execute", json=body, headers=AUTH)).json()
    assert time.monotonic() - started < 5
    assert result["timed_out"] is True
    assert "超过 1 秒" in result["output"]
    child = int((tmp_path / "c_0123abcd" / "child.pid").read_text())
    assert await _wait_dead(child)


async def test_timeout_is_capped(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        body = {"session": "c_0123abcd", "command": "true", "timeout": 999}
        response = await client.post("/execute", json=body, headers=AUTH)
    assert response.status_code == 400


async def test_long_output_is_cut_and_saved_to_a_log(tmp_path: Path) -> None:
    """输出超过上限：只返回开头一段，完整内容写进会话目录的 logs/，并告诉智能体去哪里读。"""
    command = "python3 -c \"print('x' * 5000)\""
    async with _client(tmp_path, max_output=1000) as client:
        body = {"session": "c_0123abcd", "command": command}
        result = (await client.post("/execute", json=body, headers=AUTH)).json()
    assert result["truncated"] is True
    head, _, note = result["output"].partition("\n[")
    assert head == "x" * 1000
    logs = list((tmp_path / "c_0123abcd" / "logs").glob("*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().count("x") == 5000
    assert f"logs/{logs[0].name}" in note


async def test_stops_when_asked(tmp_path: Path) -> None:
    """请求方断开（停止运行）时杀掉进程组：用"是否应停止"的回调模拟断开。"""
    session_dir = tmp_path / "c_0123abcd"
    session_dir.mkdir()
    stop_at = time.monotonic() + 0.5

    async def should_stop() -> bool:
        return time.monotonic() >= stop_at

    command = "sleep 30 & echo $! > child.pid; sleep 30"
    result = await run_command(
        session_dir, command, time_limit=10, max_output=1000, should_stop=should_stop
    )
    assert time.monotonic() - stop_at < 2
    assert result.exit_code == -signal.SIGKILL
    assert await _wait_dead(int((session_dir / "child.pid").read_text()))


def test_settings_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_SECRET", "s")
    monkeypatch.setenv("SANDBOX_TIMEOUT", "7")
    settings = sandbox_service.Settings.from_env()
    assert (settings.secret, settings.default_timeout, settings.workspace_root) == (
        "s",
        7,
        Path("/workspace"),
    )
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest deploy/sandbox -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'sandbox_service'`。

- [ ] **步骤 3：实现执行服务**

新建 `deploy/sandbox/sandbox_service.py`：

```python
"""沙箱执行服务（设计文档 9.1、9.2）：只做一件事——在会话目录里执行命令。

运行在沙箱容器里（非 root、根文件系统只读、只接入内部专用网络），只接受 backend 的请求：
- 每个请求带共享密钥（Authorization: Bearer）；
- 命令在 /workspace/<会话短 ID>/ 下运行，并单独成一个进程组；
- 超时、或请求方断开（运行被停止）时杀掉整个进程组，命令派生的子进程一并结束；
- 输出超过上限时只返回开头一段，完整内容写进会话目录的 logs/，并告诉智能体去哪里读。

独立小程序：只依赖 starlette 与 uvicorn，不引用项目代码。
"""

import asyncio
import contextlib
import hmac
import os
import re
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

_SESSION = re.compile(r"c_[0-9a-f]{8}")
_LOG_LIMIT = 20 * 1024 * 1024  # 日志文件最多记录 20MB，防止失控的输出写满磁盘
_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    secret: str
    default_timeout: int  # 秒
    max_timeout: int
    max_output: int  # 返回给智能体的输出上限（字符）

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            workspace_root=Path(os.environ.get("WORKSPACE_ROOT", "/workspace")),
            secret=os.environ.get("SANDBOX_SECRET", ""),
            default_timeout=int(os.environ.get("SANDBOX_TIMEOUT", "120")),
            max_timeout=int(os.environ.get("SANDBOX_MAX_TIMEOUT", "600")),
            max_output=int(os.environ.get("SANDBOX_MAX_OUTPUT", "30000")),
        )


@dataclass(frozen=True)
class Result:
    output: str
    exit_code: int
    truncated: bool
    timed_out: bool


async def run_command(
    cwd: Path,
    command: str,
    *,
    time_limit: int,
    max_output: int,
    should_stop: Callable[[], Awaitable[bool]],
) -> Result:
    """在 cwd 用 bash 执行 command，合并标准输出与标准错误。

    超过 time_limit 秒、或 should_stop() 为真时杀掉整个进程组。
    """
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # 单独成一个进程组，结束时连同子进程一起杀掉
    )
    collector = _Collector(cwd, max_output)
    assert process.stdout is not None
    reading = asyncio.create_task(collector.drain(process.stdout))
    deadline = time.monotonic() + time_limit
    timed_out = False
    try:
        while process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), _POLL_SECONDS)
            except TimeoutError:
                if time.monotonic() >= deadline:
                    timed_out = True
                    _kill_group(process.pid)
                elif await should_stop():
                    _kill_group(process.pid)
    finally:
        if process.returncode is None:
            _kill_group(process.pid)
            await process.wait()
        _kill_group(process.pid)  # 主进程已结束，留在后台的子进程同样结束
        await reading
    output = collector.text()
    if timed_out:
        output += f"\n[命令超过 {time_limit} 秒，已终止]"
    return Result(output, process.returncode or 0, collector.truncated, timed_out)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):  # 进程组可能已全部结束
        os.killpg(pid, signal.SIGKILL)


class _Collector:
    """收集输出：上限以内留在内存；超出后把完整输出写进 logs/，返回值只保留开头一段。"""

    def __init__(self, cwd: Path, limit: int) -> None:
        self._cwd = cwd
        self._limit = limit
        self._chunks: list[bytes] = []
        self._size = 0
        self._log: Path | None = None
        self._logged = 0

    @property
    def truncated(self) -> bool:
        return self._log is not None

    async def drain(self, stream: asyncio.StreamReader) -> None:
        while chunk := await stream.read(65536):
            if self._log is None:
                self._chunks.append(chunk)
                self._size += len(chunk)
                if len(self._head()) > self._limit:
                    self._start_log()
            elif self._logged < _LOG_LIMIT:
                with self._log.open("ab") as file:
                    file.write(chunk)
                self._logged += len(chunk)

    def _head(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")

    def _start_log(self) -> None:
        logs = self._cwd / "logs"
        logs.mkdir(exist_ok=True)
        self._log = logs / f"exec-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{id(self)}.log"
        data = b"".join(self._chunks)
        self._log.write_bytes(data)
        self._logged = len(data)

    def text(self) -> str:
        if self._log is None:
            return self._head()
        head = self._head()[: self._limit]
        note = f"输出过长，只显示开头 {self._limit} 个字符；完整输出已写入 logs/{self._log.name}"
        return f"{head}\n[{note}]"


def create_app(settings: Settings) -> Starlette:
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def execute(request: Request) -> JSONResponse:
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not settings.secret or not hmac.compare_digest(given.encode(), settings.secret.encode()):
            return JSONResponse({"detail": "密钥不正确"}, status_code=401)
        body = await request.json()
        session = str(body.get("session", ""))
        if not _SESSION.fullmatch(session):
            return JSONResponse({"detail": "会话 ID 格式不正确"}, status_code=400)
        timeout = int(body.get("timeout") or settings.default_timeout)
        if not 0 < timeout <= settings.max_timeout:
            return JSONResponse(
                {"detail": f"超时时间须在 1～{settings.max_timeout} 秒之间"}, status_code=400
            )
        cwd = settings.workspace_root / session
        cwd.mkdir(parents=True, exist_ok=True)
        result = await run_command(
            cwd,
            str(body.get("command", "")),
            time_limit=timeout,
            max_output=settings.max_output,
            should_stop=request.is_disconnected,  # 请求方断开 = 运行被停止
        )
        return JSONResponse(
            {
                "output": result.output,
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "timed_out": result.timed_out,
            }
        )

    return Starlette(
        routes=[Route("/health", health), Route("/execute", execute, methods=["POST"])]
    )


app = create_app(Settings.from_env())
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest deploy/sandbox -q`

预期：全部通过（13 个）。

- [ ] **步骤 5：镜像与预装库**

预装库与执行服务依赖（版本写死）：

新建 `deploy/sandbox/requirements.in`：

```text
# 沙箱预装的库（设计文档 9.2），直接依赖一律写精确版本（D12）。
# 修改后在项目根目录运行 make sandbox-lock 重新生成带哈希的 requirements.txt。
# 数据处理与画图
pandas==3.0.6
numpy==2.5.4
matplotlib==3.11.2
seaborn==0.13.2
# 办公文档
openpyxl==3.1.5
python-docx==1.2.0
python-pptx==1.0.2
pymupdf==1.28.2
pillow==12.3.0
# 执行服务（与 backend 的版本保持一致）
starlette==1.7.0
uvicorn==0.54.0
```

中文字体配置（`MATPLOTLIBRC` 指向它）：

新建 `deploy/sandbox/matplotlibrc`：

```text
# 沙箱里的 matplotlib 默认使用中文字体（镜像内置文泉驿微米黑），否则图中中文显示为方框
font.family: sans-serif
font.sans-serif: WenQuanYi Micro Hei, DejaVu Sans
axes.unicode_minus: False
```

新建 `deploy/sandbox/Dockerfile`：

```dockerfile
# 沙箱镜像（设计文档 9.2）：执行智能体代码的隔离环境，内含执行服务。
# 运行时由 compose 限制：非 root、根文件系统只读、只接入内部专用网络、CPU / 内存 / 进程数上限。
FROM ghcr.io/astral-sh/uv:0.11.7-python3.12-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib \
    MATPLOTLIBRC=/opt/sandbox/matplotlibrc

# 中文字体：图表里的中文才不会显示成方框（文泉驿微米黑，约 5MB）
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-wqy-microhei=0.2.0-beta-4 \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# 预装库：严格按带哈希的锁定文件安装；下载走构建缓存，重新构建不必重新下载
COPY deploy/sandbox/requirements.txt /opt/sandbox/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --require-hashes -r /opt/sandbox/requirements.txt

COPY deploy/sandbox/matplotlibrc deploy/sandbox/sandbox_service.py /opt/sandbox/

# 非 root 用户运行；工作目录是挂载进来的 /workspace（每个会话一个子目录）
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin sandbox
USER 1000
WORKDIR /workspace
EXPOSE 8080
CMD ["uvicorn", "--app-dir", "/opt/sandbox", "sandbox_service:app", "--host", "0.0.0.0", "--port", "8080"]
```

Makefile：生成锁定文件的命令；测试配置组加上测试沙箱；`make build` 同时构建沙箱镜像；缺少 `SANDBOX_SECRET` 时自动生成：

在 `Makefile` 中，把：

```makefile
# 用到 compose 的命令先检查 .env：缺少时 compose 只给出难懂的报错
NEED_ENV = @test -f .env || { echo "缺少 .env：先运行 cp .env.example .env（见 README 的首次准备）"; exit 1; }
# 启动后端；失败时直接显示后端日志里的原因（如配置自检不通过），不必再去 make logs 里找
```

改为：

```makefile
# 用到 compose 的命令先检查 .env：缺少时 compose 只给出难懂的报错
# 同时确保沙箱内部密钥（.env 里没有就生成一个追加到末尾）与工作区目录存在
NEED_ENV = @test -f .env || { echo "缺少 .env：先运行 cp .env.example .env（见 README 的首次准备）"; exit 1; }; \
	grep -q '^SANDBOX_SECRET=.' .env || { echo "SANDBOX_SECRET=$$(openssl rand -hex 16)" >> .env && echo "已在 .env 末尾生成沙箱内部密钥 SANDBOX_SECRET"; }; \
	mkdir -p workdata/workspace workdata/sandbox-test/workspace
# 启动后端；失败时直接显示后端日志里的原因（如配置自检不通过），不必再去 make logs 里找
```

在 `Makefile` 中，把：

```makefile

.PHONY: install fmt check check-py check-web types test test-int smoke \
	infra-up up build restart down logs restart-gateway test-up test-down web migrate
```

改为：

```makefile

.PHONY: install fmt check check-py check-web types sandbox-lock test test-int smoke \
	infra-up up build restart down logs restart-gateway test-up test-down web migrate
```

在 `Makefile` 中，把：

```makefile

types: ## 改了接口或事件定义后运行：重新生成前端类型（frontend/src/api/generated/）
```

改为：

```makefile

sandbox-lock: ## 改了 deploy/sandbox/requirements.in 后运行：重新生成带哈希的锁定文件
	cd deploy/sandbox && uv pip compile requirements.in --python-version 3.12 --universal --generate-hashes -o requirements.txt

types: ## 改了接口或事件定义后运行：重新生成前端类型（frontend/src/api/generated/）
```

在 `Makefile` 中，把：

```makefile

test-up: ## 启动测试专用数据库
	$(NEED_ENV)
	$(DC) --profile test up -d --wait postgres-test

test-down:
	$(NEED_ENV)
	$(DC) --profile test rm -sf postgres-test

```

改为：

```makefile

test-up: ## 启动测试专用数据库与测试沙箱
	$(NEED_ENV)
	$(DC) --profile test up -d --wait postgres-test sandbox-test

test-down:
	$(NEED_ENV)
	$(DC) --profile test rm -sf postgres-test sandbox-test

```

在 `Makefile` 中，把：

```makefile

build: ## 重新构建 backend 镜像并启动：依赖文件或前端界面改了以后运行（依赖从本机构建缓存安装，不重新下载）
	$(NEED_ENV)
	$(DC) build backend
	$(START_BACKEND)
```

改为：

```makefile

build: ## 重新构建 backend 与沙箱镜像并启动：依赖文件或前端界面改了以后运行（依赖从本机构建缓存安装，不重新下载）
	$(NEED_ENV)
	$(DC) build backend sandbox
	$(START_BACKEND)
```

生成带哈希的锁定文件（需要联网，约 840 行，不手改）：

运行：`make sandbox-lock`

- [ ] **步骤 6：compose 与环境变量模板**

在 `deploy/docker-compose.yml` 中，把：

```yaml
name: open-personal-agent

```

改为：

```yaml
name: open-personal-agent

x-sandbox: &sandbox # 沙箱容器的公共设置（设计文档 9.2），正式沙箱与测试沙箱共用
  build:
    context: ..
    dockerfile: deploy/sandbox/Dockerfile
  image: open-personal-agent-sandbox:latest
  user: "1000:1000" # 非 root
  read_only: true # 除 /workspace（挂载）与 /tmp（内存盘，重启即清空）外文件系统只读
  tmpfs: ["/tmp:size=512m"]
  cpus: 2
  mem_limit: 2g
  pids_limit: 256
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"]
    interval: 5s
    timeout: 5s
    retries: 20

```

在 `deploy/docker-compose.yml` 中，把：

```yaml

  backend:
```

改为：

```yaml

  sandbox: # 执行代码的隔离容器：只接入内部专用网络，只能被 backend 访问，不能上外网
    <<: *sandbox
    environment:
      SANDBOX_SECRET: ${SANDBOX_SECRET:?请在 .env 中设置 SANDBOX_SECRET（make 命令会自动生成）}
    volumes:
      - ../workdata/workspace:/workspace # 与 backend 共用同一个工作区目录
    networks: [sandbox]

  backend:
```

在 `deploy/docker-compose.yml` 中，把：

```yaml
      LISTEN_ADDRESS: ${LISTEN_ADDRESS:-127.0.0.1}
      WORKDATA_DIR: /app/workdata
```

改为：

```yaml
      LISTEN_ADDRESS: ${LISTEN_ADDRESS:-127.0.0.1}
      # 调用沙箱执行服务时携带的共享密钥（设计文档 9.2）
      SANDBOX_SECRET: ${SANDBOX_SECRET:?请在 .env 中设置 SANDBOX_SECRET（make 命令会自动生成）}
      WORKDATA_DIR: /app/workdata
```

在 `deploy/docker-compose.yml` 中，把：

```yaml
    ports: ["${LISTEN_ADDRESS:-127.0.0.1}:8000:8000"]
    depends_on:
      postgres: { condition: service_healthy }
      litellm: { condition: service_healthy }
    healthcheck:
```

改为：

```yaml
    ports: ["${LISTEN_ADDRESS:-127.0.0.1}:8000:8000"]
    networks: [default, sandbox]
    depends_on:
      postgres: { condition: service_healthy }
      litellm: { condition: service_healthy }
      sandbox: { condition: service_healthy }
    healthcheck:
```

在 `deploy/docker-compose.yml` 中，把：

```yaml

volumes:
```

改为：

```yaml

  sandbox-test: # 自动化测试专用：工作目录在 workdata/sandbox-test，端口只对本机开放
    <<: *sandbox
    profiles: [test]
    environment:
      SANDBOX_SECRET: test-secret
    volumes:
      - ../workdata/sandbox-test/workspace:/workspace
    ports: ["127.0.0.1:58080:8080"]

networks:
  sandbox:
    internal: true # 内部专用网络：沙箱只能与 backend 通信，不能上外网（设计文档 9.2）

volumes:
```

在 `.env.example` 中，把：

```text

# ---- 上游模型网关（公司 LiteLLM 网关；本地网关把模型请求转发给它）----
```

改为：

```text

# ---- 沙箱内部密钥（backend 调用沙箱执行服务时使用）：不用手动填写，make 命令会在本文件末尾自动生成 SANDBOX_SECRET ----

# ---- 上游模型网关（公司 LiteLLM 网关；本地网关把模型请求转发给它）----
```

- [ ] **步骤 7：检查点**

运行：`make check`

一个旧测试原来固定等 0.1 秒就检查事件是否已写进界面历史，刚重建的测试库第一次写入较慢时会误报失败（写计划时重放遇到过一次）。改为最多等 2 秒、轮询到写入为止：

在 `backend/tests/test_manager.py` 中，把：

```python
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)
    await asyncio.sleep(0.1)  # 等一次分批写入

    # 运行还在进行：已推送的内容已经在界面历史里（进程此时退出也不会丢）
    assert [e.type for e in await runs.events(run.id)] == ["run.started", "message.delta"]
```

改为：

```python
    rest = await asyncio.wait_for(_until_first_delta(manager, run.id), timeout=5)
    # 运行还在进行：已推送的内容会分批写进界面历史（进程此时退出也不会丢）。
    # 轮询等待而不是固定等一会儿：刚启动的测试库第一次写入可能较慢
    for _ in range(100):
        if len(await runs.events(run.id)) == 2:
            break
        await asyncio.sleep(0.02)
    assert [e.type for e in await runs.events(run.id)] == ["run.started", "message.delta"]
```

写计划时演练用过测试数据库（它已升级到本计划任务 4 的迁移 0005）和测试沙箱，先删掉，`make test-int` 会自动重新启动它们。第一次启动测试沙箱时会构建镜像（下载约 830MB 的依赖，需要几分钟；写计划时已在本机构建过同名镜像，内容与本计划相同，会直接使用）：

运行：`make test-down`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 119 个、前端 65 个）；`make test-int` 全部通过（集成测试 54 个）。`.env` 末尾多了一行自动生成的 `SANDBOX_SECRET`：用 `grep -c '^SANDBOX_SECRET=' .env` 确认输出 `1`，不要查看内容。

---

### 任务 2：工作区（会话目录限制与执行命令）

**文件：**
- 新建：`agents/main_agent/context.py`、`agents/main_agent/workspace/__init__.py`、`base.py`、`local.py`、`sandbox_http.py`、`agents/tests/contracts/test_workspace_contract.py`、`agents/tests/test_sandbox_http.py`
- 修改：`agents/tests/fakes.py`、`config/settings.py`、`config/app.yaml`、`config/tests/test_settings.py`、`pyproject.toml`、`docs/development/coding-standards.md`、`.claude/skills/dev-standards/SKILL.md`

**接口：**
- 消费：任务 1 的执行服务（`POST /execute`）与测试沙箱 `127.0.0.1:58080`。
- 产出（`agents/main_agent/context.py`）：`AgentContext(thread_id: str, thread_short_id: str, run_id: str)`，不可变数据类，作为运行上下文传给智能体。
- 产出（`agents.main_agent.workspace` 公开）：
  - `CommandResult(output: str, exit_code: int, truncated: bool = False, timed_out: bool = False)`；
  - `Sandbox` 接口：`async run(session: str, command: str, *, time_limit: int | None) -> CommandResult`；
  - `OutputFile(path: str, size: int, modified: float)`，`path` 相对会话目录（如 `outputs/chart.png`）；
  - `Workspace` 接口：
    - 属性 `agent_backend -> SandboxBackendProtocol`；
    - `async list_outputs(short_id) -> list[OutputFile]`；
    - `async read_file(short_id, path) -> bytes`：会话目录外抛 `PermissionError`，不存在抛 `FileNotFoundError`；
    - `async remove(short_id) -> None`；
  - `LocalWorkspace(root: Path, sandbox: Sandbox, *, session=current_session)`：会话目录为 `root/workspace/<短 ID>/`；智能体看到的路径 `/workspace/<短 ID>/…` 与沙箱里的真实路径一致；
  - `HttpSandbox(base_url, secret, *, default_time_limit, transport=None)`：沙箱连不上返回退出码 -1 与"沙箱暂时不可用：…"，被拒绝返回"沙箱拒绝执行：<原因>"。
- 产出（config）：`AdaptersConfig.workspace = "docker_local"`；`WorkspaceConfig(sandbox_url="http://sandbox:8080", command_timeout=120)`；`Settings.workspace`；`Settings.sandbox_secret: SecretStr | None`（`.env` 的 `SANDBOX_SECRET`）。
- 产出（测试替身）：`FakeSandbox(output="ok", exit_code=0, *, hang=False)`，记下 `.calls`（会话、命令、时限），`hang=True` 时一直等待、被取消后 `.cancelled` 为真。

- [ ] **步骤 1：写失败的测试**

测试替身（假沙箱）：

在 `agents/tests/fakes.py` 中，把：

```python
from agents.main_agent.models import ModelInfo
from common.errors import UpstreamError
```

改为：

```python
from agents.main_agent.models import ModelInfo
from agents.main_agent.workspace import CommandResult
from common.errors import UpstreamError
```

在 `agents/tests/fakes.py` 末尾追加：

```python


class FakeSandbox:
    """假沙箱：记下每次执行（会话、命令、时限），按预设返回结果；可设为一直等待（验证停止）。"""

    def __init__(self, output: str = "ok", exit_code: int = 0, *, hang: bool = False) -> None:
        self.calls: list[tuple[str, str, int | None]] = []
        self._result = CommandResult(output=output, exit_code=exit_code)
        self._hang = hang
        self.cancelled = False

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult:
        self.calls.append((session, command, time_limit))
        if self._hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self._result
```

契约测试——任何工作区实现都要满足：

新建 `agents/tests/contracts/test_workspace_contract.py`：

```python
"""工作区契约测试（设计文档 4.1、7.3、9.1）：所有 Workspace 实现都必须通过同一套测试。

交给智能体的工作区后端只能读写本会话目录 /workspace/<会话短 ID>/；
越界时返回错误（智能体能看到原因），而不是抛出异常让整次运行失败。
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from agents.main_agent.workspace import LocalWorkspace, Workspace
from agents.tests.fakes import FakeSandbox

ME, OTHER = "c_0123abcd", "c_99999999"

type Factory = Callable[[Path, FakeSandbox], Workspace]


@pytest.fixture(params=[lambda root, sandbox: LocalWorkspace(root, sandbox, session=lambda: ME)])
def make(request: pytest.FixtureRequest) -> Factory:
    factory: Factory = request.param
    return factory


def _seed_other_session(root: Path) -> None:
    other = root / "workspace" / OTHER
    other.mkdir(parents=True)
    (other / "secret.txt").write_text("别人的文件")


def test_reads_and_writes_inside_own_session(tmp_path: Path, make: Factory) -> None:
    backend = make(tmp_path, FakeSandbox()).agent_backend
    assert backend.write(f"/workspace/{ME}/notes/a.txt", "你好").error is None
    assert (tmp_path / "workspace" / ME / "notes" / "a.txt").read_text() == "你好"
    read = backend.read(f"/workspace/{ME}/notes/a.txt")
    assert read.error is None
    assert "你好" in str(read.file_data)


def test_other_sessions_and_outside_paths_are_refused(tmp_path: Path, make: Factory) -> None:
    """越界：别的会话、虚拟根下的其他目录都拒绝，错误信息告诉智能体自己的工作目录。"""
    _seed_other_session(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    for result in (
        backend.write(f"/workspace/{OTHER}/x.txt", "x"),
        backend.read(f"/workspace/{OTHER}/secret.txt"),
        backend.write("/etc/passwd", "x"),
        backend.read(f"/workspace/{ME}/../{OTHER}/secret.txt"),
    ):
        assert result.error is not None
        assert f"/workspace/{ME}/" in result.error or "traversal" in result.error
    assert not (tmp_path / "workspace" / OTHER / "x.txt").exists()


def test_searches_without_a_path_stay_in_own_session(tmp_path: Path, make: Factory) -> None:
    _seed_other_session(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    backend.write(f"/workspace/{ME}/mine.txt", "别人的文件也在找")
    found = backend.glob("**/*.txt")
    assert [m["path"] for m in found.matches or []] == [f"/workspace/{ME}/mine.txt"]
    grepped = backend.grep("别人的文件")
    assert grepped.error is None
    assert [m["path"] for m in grepped.matches or []] == [f"/workspace/{ME}/mine.txt"]


async def test_commands_run_in_the_sandbox_for_this_session(tmp_path: Path, make: Factory) -> None:
    sandbox = FakeSandbox(output="hello", exit_code=2)
    backend = make(tmp_path, sandbox).agent_backend
    response = await backend.aexecute("python run.py", timeout=30)
    assert (response.output, response.exit_code) == ("hello", 2)
    assert sandbox.calls == [(ME, "python run.py", 30)]


async def test_lists_files_under_outputs(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    session = tmp_path / "workspace" / ME
    (session / "outputs" / "charts").mkdir(parents=True)
    (session / "outputs" / "charts" / "a.png").write_bytes(b"png")
    (session / "outputs" / "report.xlsx").write_bytes(b"xlsx!")
    (session / "scratch.py").write_text("不是产物")
    outputs = await workspace.list_outputs(ME)
    assert sorted((f.path, f.size) for f in outputs) == [
        ("outputs/charts/a.png", 3),
        ("outputs/report.xlsx", 5),
    ]
    assert await workspace.list_outputs(OTHER) == []


async def test_reads_a_file_for_download(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    (tmp_path / "workspace" / ME / "outputs").mkdir(parents=True)
    (tmp_path / "workspace" / ME / "outputs" / "a.png").write_bytes(b"png")
    assert await workspace.read_file(ME, "outputs/a.png") == b"png"
    _seed_other_session(tmp_path)
    for path in (f"../{OTHER}/secret.txt", "/etc/passwd", "outputs/../../x"):
        with pytest.raises(PermissionError):
            await workspace.read_file(ME, path)
    with pytest.raises(FileNotFoundError):
        await workspace.read_file(ME, "outputs/missing.png")


async def test_removes_a_session(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    _seed_other_session(tmp_path)
    (tmp_path / "workspace" / ME / "outputs").mkdir(parents=True)
    await workspace.remove(ME)
    await workspace.remove(ME)  # 已删除时不报错
    assert not (tmp_path / "workspace" / ME).exists()
    assert (tmp_path / "workspace" / OTHER / "secret.txt").exists()
```

沙箱客户端：单元测试用模拟传输层；集成测试连接任务 1 的测试沙箱（每个测试结束后删掉它建的会话目录）：

新建 `agents/tests/test_sandbox_http.py`：

```python
"""沙箱执行服务客户端：单元测试用模拟传输层；集成测试连接 compose test 配置组的 sandbox-test。"""

import asyncio
import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agents.main_agent.workspace import CommandResult, HttpSandbox

ROOT = Path(__file__).resolve().parents[2]
TEST_WORKSPACE = ROOT / "workdata" / "sandbox-test" / "workspace"  # sandbox-test 挂载为 /workspace


def _sandbox(handler: httpx.MockTransport) -> HttpSandbox:
    return HttpSandbox("http://sandbox:8080", "s3cret", default_time_limit=120, transport=handler)


async def test_sends_secret_session_and_time_limit() -> None:
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"output": "hi", "exit_code": 0, "truncated": False, "timed_out": False}
        return httpx.Response(200, json=body)

    result = await _sandbox(httpx.MockTransport(reply)).run(
        "c_0123abcd", "echo hi", time_limit=None
    )

    assert result == CommandResult(output="hi", exit_code=0)
    assert seen[0].headers["authorization"] == "Bearer s3cret"
    assert json.loads(seen[0].content) == {
        "session": "c_0123abcd",
        "command": "echo hi",
        "timeout": 120,  # 未指定时用默认时限
    }


async def test_unavailable_sandbox_becomes_a_readable_error() -> None:
    """沙箱没启动、拒绝请求时：智能体看到一句看得懂的原因，运行本身不失败。"""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = await _sandbox(httpx.MockTransport(refuse)).run("c_0123abcd", "ls", time_limit=5)
    assert result.exit_code != 0
    assert "沙箱暂时不可用" in result.output

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "超时时间须在 1～600 秒之间"})

    result = await _sandbox(httpx.MockTransport(reject)).run("c_0123abcd", "ls", time_limit=999)
    assert result.exit_code != 0
    assert "超时时间须在 1～600 秒之间" in result.output


def _real_sandbox() -> HttpSandbox:
    return HttpSandbox("http://127.0.0.1:58080", "test-secret", default_time_limit=30)


@pytest.fixture
def session() -> Iterator[str]:
    """每个测试一个新会话；沙箱会在测试工作区里建会话目录，测试结束后删掉，不越积越多。"""
    name = f"c_{uuid.uuid4().hex[:8]}"
    yield name
    shutil.rmtree(TEST_WORKSPACE / name, ignore_errors=True)


@pytest.mark.integration
async def test_runs_in_the_real_sandbox(session: str) -> None:
    result = await _real_sandbox().run(
        session, "pwd; id -u; python -c 'import pandas'", time_limit=30
    )
    assert result.exit_code == 0
    assert result.output.splitlines()[:2] == [f"/workspace/{session}", "1000"]


@pytest.mark.integration
async def test_root_filesystem_is_read_only(session: str) -> None:
    """除工作目录与 /tmp（内存盘）外只读。断网由内部专用网络保证，测试沙箱要对本机开放端口，
    不在内部网络上，断网在端到端验证里检查。"""
    command = "touch /etc/x 2>/dev/null && echo 可写 || echo 只读; touch /tmp/x && echo tmp可写"
    result = await _real_sandbox().run(session, command, time_limit=10)
    assert result.output.split() == ["只读", "tmp可写"]


@pytest.mark.integration
async def test_cancelling_the_request_kills_the_command(session: str) -> None:
    """停止运行 = 取消请求：沙箱察觉连接断开后杀掉进程组，命令不会在后台继续跑完。"""
    command = "sleep 3; touch finished"
    task = asyncio.create_task(_real_sandbox().run(session, command, time_limit=30))
    await asyncio.sleep(1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(4)
    assert not (TEST_WORKSPACE / session / "finished").exists()
    assert (TEST_WORKSPACE / session).is_dir()
```

在 `config/tests/test_settings.py` 末尾追加：

```python


def test_project_config_selects_the_local_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """项目的 app.yaml：工作区用本地数据卷 + Docker 沙箱，命令默认时限 120 秒。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    monkeypatch.setenv("SANDBOX_SECRET", "sandbox-secret")
    settings = _settings_from(Path(__file__).resolve().parents[1] / "app.yaml")
    assert settings.adapters.workspace == "docker_local"
    assert settings.workspace.sandbox_url == "http://sandbox:8080"
    assert settings.workspace.command_timeout == 120
    assert settings.sandbox_secret is not None
    assert settings.sandbox_secret.get_secret_value() == "sandbox-secret"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/contracts/test_workspace_contract.py agents/tests/test_sandbox_http.py config/tests/test_settings.py -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'agents.main_agent.workspace'`。

- [ ] **步骤 3：实现**

新建 `agents/main_agent/context.py`：

```python
"""一次运行的上下文（LangGraph 运行时上下文，设计文档 7.2）：工作区等据此知道当前是哪个会话。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentContext:
    thread_id: str
    thread_short_id: str  # 形如 c_8f3a2b9d：工作目录 /workspace/<会话短 ID>/
    run_id: str
```

新建 `agents/main_agent/workspace/base.py`：

```python
"""工作区接口（设计文档 4.1：文件 + 执行）。

交给智能体的部分直接用 deepagents 的工作区后端协议（SandboxBackendProtocol，
设计文档 4"不过度包装"）：换成 E2B、Daytona 等云沙箱时，它们有官方适配。
backend 用到的产物列表、下载、删除另列在这里。
"""

from dataclasses import dataclass
from typing import Protocol

from deepagents.backends.protocol import SandboxBackendProtocol


@dataclass(frozen=True)
class CommandResult:
    """在沙箱里执行一条命令的结果。"""

    output: str  # 标准输出与标准错误合并
    exit_code: int
    truncated: bool = False  # 输出过长被截断（完整输出在会话目录的 logs/）
    timed_out: bool = False


class Sandbox(Protocol):
    """执行命令的地方：在会话目录 /workspace/<会话短 ID>/ 下执行。请求被取消时须终止命令。"""

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult: ...


@dataclass(frozen=True)
class OutputFile:
    """会话 outputs/ 下的一个文件（产物）。"""

    path: str  # 相对会话目录，如 outputs/chart.png
    size: int
    modified: float  # 修改时间（Unix 秒）


class Workspace(Protocol):
    @property
    def agent_backend(self) -> SandboxBackendProtocol:
        """交给智能体的工作区后端：只能读写本会话目录，执行命令交给沙箱。"""
        ...

    async def list_outputs(self, short_id: str) -> list[OutputFile]:
        """会话 outputs/ 下的全部文件（含子目录）。"""
        ...

    async def read_file(self, short_id: str, path: str) -> bytes:
        """读取会话目录里的文件（path 相对会话目录）。

        越界抛 PermissionError，不存在抛 FileNotFoundError。
        """
        ...

    async def remove(self, short_id: str) -> None:
        """删除整个会话目录；不存在时什么也不做。"""
        ...
```

新建 `agents/main_agent/workspace/local.py`：

```python
"""工作区实现：本地数据卷 + Docker 沙箱（设计文档 9.1）。

读写文件由 backend 直接做（虚拟根 / 映射到 WORKDATA_DIR，/workspace/<会话短 ID>/ 落在
WORKDATA_DIR/workspace/<会话短 ID>/）；只有执行命令交给沙箱容器，沙箱把同一目录挂载为 /workspace，
所以智能体看到的路径与沙箱里的真实路径一致。
"""

import asyncio
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    ExecuteResponse,
    GlobResult,
    GrepResult,
    SandboxBackendProtocol,
)
from langgraph.runtime import get_runtime

from agents.main_agent.context import AgentContext
from agents.main_agent.workspace.base import OutputFile, Sandbox

_SHORT_ID = re.compile(r"c_[0-9a-f]{8}")


def current_session() -> str:
    """当前运行所属会话的短 ID（从 LangGraph 运行时上下文读取，子智能体同样可读）。"""
    return get_runtime(AgentContext).context.thread_short_id


class LocalWorkspace:
    def __init__(
        self, root: Path, sandbox: Sandbox, *, session: Callable[[], str] = current_session
    ) -> None:
        self._root = root.resolve()
        self._backend = _SessionBackend(self._root, sandbox, session)

    @property
    def agent_backend(self) -> SandboxBackendProtocol:
        return self._backend

    async def list_outputs(self, short_id: str) -> list[OutputFile]:
        return await asyncio.to_thread(self._list_outputs, short_id)

    def _list_outputs(self, short_id: str) -> list[OutputFile]:
        session = self._session_dir(short_id)
        outputs = session / "outputs"
        if not outputs.is_dir():
            return []
        files = []
        for path in outputs.rglob("*"):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                files.append(
                    OutputFile(path.relative_to(session).as_posix(), stat.st_size, stat.st_mtime)
                )
        return files

    async def read_file(self, short_id: str, path: str) -> bytes:
        session = self._session_dir(short_id).resolve()
        target = (session / path).resolve()
        if session not in target.parents:
            raise PermissionError(f"只能读取会话目录里的文件：{path}")
        return await asyncio.to_thread(target.read_bytes)

    async def remove(self, short_id: str) -> None:
        await asyncio.to_thread(shutil.rmtree, self._session_dir(short_id), ignore_errors=True)

    def _session_dir(self, short_id: str) -> Path:
        if not _SHORT_ID.fullmatch(short_id):
            raise PermissionError(f"会话短 ID 格式不正确：{short_id}")
        return self._root / "workspace" / short_id


class _SessionBackend(FilesystemBackend, SandboxBackendProtocol):
    """交给智能体的工作区后端（deepagents 协议）。

    所有文件操作都经过 _resolve_path：在 deepagents 的虚拟根检查之外，再限定在本会话目录。
    越界抛 PermissionError（OSError）：deepagents 只把 OSError 变成工具错误交回智能体，
    其他异常（包括它自己对 .. 抛的 ValueError）会让整次运行失败。
    """

    def __init__(self, root: Path, sandbox: Sandbox, session: Callable[[], str]) -> None:
        super().__init__(root_dir=root, virtual_mode=True)
        self._sandbox = sandbox
        self._session = session

    @property
    def id(self) -> str:
        return "local-workspace"

    def _resolve_path(self, key: str) -> Path:
        try:
            full = super()._resolve_path(key)
        except ValueError as exc:
            raise PermissionError(str(exc)) from None
        allowed = (self.cwd / "workspace" / self._session()).resolve()
        if full != allowed and allowed not in full.parents:
            raise PermissionError(f"只能访问本会话的工作目录 /workspace/{self._session()}/")
        return full

    def _scoped(self, path: str | None) -> str:
        """不指定路径（或指定根目录）的搜索默认限定在本会话目录。"""
        return f"/workspace/{self._session()}/" if path in (None, "", "/", ".") else path

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return super().glob(pattern, self._scoped(path))

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        return super().grep(
            pattern, self._scoped(path), glob, max_count=max_count, context_lines=context_lines
        )

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
        context_lines: int = 0,
    ) -> GrepResult:
        return await super().agrep(
            pattern, self._scoped(path), glob, max_count=max_count, context_lines=context_lines
        )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        raise NotImplementedError("工作区只支持异步执行命令")

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109 - deepagents 协议的参数名，转交给沙箱
    ) -> ExecuteResponse:
        result = await self._sandbox.run(self._session(), command, time_limit=timeout)
        return ExecuteResponse(
            output=result.output, exit_code=result.exit_code, truncated=result.truncated
        )
```

新建 `agents/main_agent/workspace/sandbox_http.py`：

```python
"""沙箱执行服务的客户端（服务端见 deploy/sandbox/sandbox_service.py）。

请求被取消（运行停止）时连接随之断开，执行服务察觉后杀掉整个进程组（设计文档 10.6）。
沙箱不可用或拒绝执行时返回一段看得懂的原因，让智能体自行应对，而不是让整次运行失败。
"""

import httpx

from agents.main_agent.workspace.base import CommandResult

_EXTRA_SECONDS = 30  # 等待回复的时间比命令时限多留一些：超时由沙箱判定并杀掉进程组


class HttpSandbox:
    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        default_time_limit: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"authorization": f"Bearer {secret}"},
            transport=transport,
        )
        self._default_time_limit = default_time_limit

    async def run(self, session: str, command: str, *, time_limit: int | None) -> CommandResult:
        limit = time_limit or self._default_time_limit
        body = {"session": session, "command": command, "timeout": limit}
        try:
            response = await self._client.post(
                "/execute", json=body, timeout=limit + _EXTRA_SECONDS
            )
        except httpx.HTTPError as exc:
            return CommandResult(output=f"沙箱暂时不可用：{exc}", exit_code=-1)
        if response.status_code != httpx.codes.OK:
            detail = response.json().get("detail", response.text) if response.content else ""
            return CommandResult(output=f"沙箱拒绝执行：{detail}", exit_code=-1)
        data = response.json()
        return CommandResult(
            output=data["output"],
            exit_code=data["exit_code"],
            truncated=data["truncated"],
            timed_out=data["timed_out"],
        )
```

新建 `agents/main_agent/workspace/__init__.py`：

```python
"""工作区（设计文档 4.1、7.3、9）：会话目录里的文件 + 在沙箱里执行命令。"""

from agents.main_agent.workspace.base import (
    CommandResult,
    OutputFile,
    Sandbox,
    Workspace,
)
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.sandbox_http import HttpSandbox

__all__ = ["CommandResult", "HttpSandbox", "LocalWorkspace", "OutputFile", "Sandbox", "Workspace"]
```

在 `config/settings.py` 中，把：

```python
    model_gateway: str = "litellm_proxy"

```

改为：

```python
    model_gateway: str = "litellm_proxy"
    workspace: str = "docker_local"


class WorkspaceConfig(BaseModel):
    """工作区与沙箱（设计文档 9）。"""

    sandbox_url: str = "http://sandbox:8080"  # 沙箱执行服务（compose 内部专用网络）
    command_timeout: int = 120  # 命令默认时限（秒）；超时由沙箱杀掉整个进程组

```

在 `config/settings.py` 中，把：

```python
    agent: AgentConfig
    security: SecurityConfig = SecurityConfig()
```

改为：

```python
    agent: AgentConfig
    workspace: WorkspaceConfig = WorkspaceConfig()
    security: SecurityConfig = SecurityConfig()
```

在 `config/settings.py` 中，把：

```python
    listen_address: str = "127.0.0.1"

```

改为：

```python
    listen_address: str = "127.0.0.1"
    # backend 调用沙箱执行服务时携带的共享密钥（.env 的 SANDBOX_SECRET，make 命令会自动生成）
    sandbox_secret: SecretStr | None = None

```

在 `config/app.yaml` 中，把：

```yaml
  model_gateway: litellm_proxy

```

改为：

```yaml
  model_gateway: litellm_proxy
  workspace: docker_local # 本地数据卷 + Docker 沙箱（设计文档 9）

# 工作区与沙箱：执行代码的容器在 compose 内部专用网络上，不能上外网
workspace:
  sandbox_url: http://sandbox:8080
  command_timeout: 120 # 命令默认时限（秒），超时杀掉整个进程组

```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/contracts/test_workspace_contract.py agents/tests/test_sandbox_http.py config/tests/test_settings.py -q`

运行：`uv run pytest -m integration agents/tests/test_sandbox_http.py -q`

预期：单元测试全部通过（12 个）；集成测试 3 个通过（真实沙箱里：在会话目录运行、用户是 1000；根文件系统只读；取消请求后命令不会在后台跑完）。

- [ ] **步骤 5：依赖规则与规范**

工作区内部只能由 bootstrap 装配，backend 不能直接引用实现；`workspace/` 可以引用 `deepagents.backends`（规则 3 的例外）：

在 `pyproject.toml` 中，把：

```toml
    "agents.main_agent.usage.repo",
]
```

改为：

```toml
    "agents.main_agent.usage.repo",
    "agents.main_agent.workspace.local",
    "agents.main_agent.workspace.sandbox_http",
]
```

在 `docs/development/coding-standards.md` 中，把：

```markdown
- FastAPI：按官方写法用 `APIRouter`、`Depends`、`lifespan`；推送用 `fastapi.sse.EventSourceResponse`（官方 SSE 支持），不额外引入 sse 库。
- LangChain / LangGraph / deepagents：按官方 API 使用；deepagents 只能出现在 `agents/main_agent/runtime/`。
- 命名：模块与函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`；不使用会遮蔽内置名的方法名（如 `list`）。
```

改为：

```markdown
- FastAPI：按官方写法用 `APIRouter`、`Depends`、`lifespan`；推送用 `fastapi.sse.EventSourceResponse`（官方 SSE 支持），不额外引入 sse 库。
- LangChain / LangGraph / deepagents：按官方 API 使用；deepagents 只能出现在 `agents/main_agent/runtime/`。例外：`agents/main_agent/workspace/` 实现 deepagents 的工作区后端协议（`deepagents.backends`），这正是设计文档 4.1 的可替换"工作区"接口（换成 E2B 等云沙箱时有官方适配），只能用这个子包。
- 命名：模块与函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`；不使用会遮蔽内置名的方法名（如 `list`）。
```

在 `.claude/skills/dev-standards/SKILL.md` 中，把：

```markdown
2. 外部依赖必须藏在可替换接口后面，在 `agents/main_agent/bootstrap.py` 装配，并有契约测试；其他地方不预设抽象。
3. deepagents 只能出现在 `agents/main_agent/runtime/`。
4. 所有输入输出异步；边界数据用 pydantic；SQL 参数化；可预期错误用 `common.errors`。
```

改为：

```markdown
2. 外部依赖必须藏在可替换接口后面，在 `agents/main_agent/bootstrap.py` 装配，并有契约测试；其他地方不预设抽象。
3. deepagents 只能出现在 `agents/main_agent/runtime/`；例外是 `workspace/` 可用 `deepagents.backends`（工作区后端协议）。
4. 所有输入输出异步；边界数据用 pydantic；SQL 参数化；可预期错误用 `common.errors`。
```

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 129 个、前端 65 个，依赖规则 2 条全部满足）；`make test-int` 全部通过（集成测试 57 个）。

---

### 任务 3：智能体接上工作区、技能与数据分析员

**文件：**
- 新建：`agents/main_agent/runtime/files.py`、`agents/main_agent/runtime/subagents.py`、`agents/skills/excel/SKILL.md`、`agents/subagents/data_analyst.md`、`agents/tests/test_subagents.py`
- 修改：`agents/main_agent/runtime/agent.py`、`agents/main_agent/bootstrap.py`、`agents/prompts/system.md`、`config/settings.py`、`pyproject.toml`、`uv.lock`（命令生成）、`backend/runs/manager.py`、`agents/tests/fakes.py`、`agents/tests/test_main_agent.py`、`agents/tests/test_bootstrap.py`、`agents/tests/live/test_smoke.py`、`backend/tests/conftest.py`、`backend/tests/test_manager.py`

**接口：**
- 消费：任务 2 的 `AgentContext`、`Workspace`、`LocalWorkspace`、`HttpSandbox`、`FakeSandbox`。
- 产出（runtime）：
  - `MainAgent(*, gateway, checkpointer, system_prompt, workspace: Workspace, skills_dir: Path | None = None, subagents_dir: Path | None = None)`，属性 `.workspace`；
  - `MainAgent.run(*, thread_id, thread_short_id, run_id, message, model)`（新增 `thread_short_id`）；
  - `MainAgent.delete_thread(thread_id, thread_short_id)`：删对话存档，再删会话目录；
  - `build_file_tree(workspace_backend, skills_dir) -> CompositeBackend`、`WorkDirectoryMiddleware`、`AGENT_FILES = "/.agent"`；
  - `SubagentDefinition(name, description, system_prompt, model=None)`、`load_subagents(directory) -> list[SubagentDefinition]`（按文件名排序；缺字段时 `ValueError` 并点名文件）。
- 产出（config）：`AgentConfig.skills_dir`（默认 `agents/skills`）、`AgentConfig.subagents_dir`（默认 `agents/subagents`）。
- 产出（backend）：`RunManager` 调用 `agent.run` 时带上会话短 ID；删除会话调用 `agent.delete_thread(id, short_id)`。
- 产出（测试替身）：`call(name, args, call_id=None) -> AIMessage`——只调用一个工具的模型回复。
- 约定：子智能体定义不写 `model` 时跟随主对话所选模型（2026-10-15 与用户确认）。

- [ ] **步骤 1：写失败的测试**

在 `agents/tests/fakes.py` 中，把：

```python
import asyncio
import json
```

改为：

```python
import asyncio
import itertools
import json
```

在 `agents/tests/fakes.py` 末尾追加：

```python


def call(name: str, args: dict[str, Any], call_id: str | None = None) -> AIMessage:
    """一条只调用一个工具的模型回复（剧本里常用）。"""
    tool_call = {"name": name, "args": args, "id": call_id or f"call-{name}-{next(_ids)}"}
    return AIMessage(content="", tool_calls=[{**tool_call, "type": "tool_call"}])


_ids = itertools.count(1)
```

新建 `agents/tests/test_subagents.py`：

```python
from pathlib import Path

import pytest

from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents

ROOT = Path(__file__).resolve().parents[2]


def test_loads_definitions_from_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "data_analyst.md").write_text(
        "---\nname: data_analyst\ndescription: 分析数据\n---\n\n你是数据分析员。\n"
    )
    (tmp_path / "cheap.md").write_text(
        "---\nname: cheap\ndescription: 便宜\nmodel: gemini-3.5-flash\n---\n简短回答。"
    )
    (tmp_path / "README.txt").write_text("不是定义文件")
    assert load_subagents(tmp_path) == [
        SubagentDefinition("cheap", "便宜", "简短回答。", model="gemini-3.5-flash"),
        SubagentDefinition("data_analyst", "分析数据", "你是数据分析员。"),
    ]


@pytest.mark.parametrize(
    "text",
    ["没有文件头", "---\nname: x\n---\n缺少说明", "---\ndescription: 缺少名称\n---\n正文"],
)
def test_incomplete_definition_names_the_file(tmp_path: Path, text: str) -> None:
    (tmp_path / "broken.md").write_text(text)
    with pytest.raises(ValueError, match=r"broken\.md"):
        load_subagents(tmp_path)


def test_project_definitions_are_valid() -> None:
    """项目自带的子智能体：数据分析员跟随主对话的模型（定义里不写 model）。"""
    definitions = {d.name: d for d in load_subagents(ROOT / "agents" / "subagents")}
    analyst = definitions["data_analyst"]
    assert analyst.model is None
    assert "outputs/" in analyst.system_prompt


def test_project_skills_have_name_and_description() -> None:
    skills = list((ROOT / "agents" / "skills").glob("*/SKILL.md"))
    assert skills
    for skill in skills:
        head = skill.read_text(encoding="utf-8").split("---")[1]
        assert "name:" in head, skill
        assert "description:" in head, skill


def test_system_prompt_explains_files_sandbox_and_delegation() -> None:
    """系统提示词告诉模型：能执行代码、产物放 outputs/、数据分析派 data_analyst、先看技能。"""
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in ("execute", "outputs/", "data_analyst", "/skills/"):
        assert phrase in prompt, phrase
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
import asyncio

```

改为：

```python
import asyncio
import tempfile
from pathlib import Path

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
from agents.main_agent.runtime.interruption import INTERRUPTED_NOTE
from agents.tests.fakes import FailingChatModel, FakeGateway, HangingChatModel, ScriptedChatModel


def _agent(model: ScriptedChatModel) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model), checkpointer=InMemorySaver(), system_prompt="测试助手"
    )
```

改为：

```python
from agents.main_agent.runtime.interruption import INTERRUPTED_NOTE
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    FailingChatModel,
    FakeGateway,
    FakeSandbox,
    HangingChatModel,
    ScriptedChatModel,
    call,
)

SHORT, OTHER_SHORT = "c_000000a1", "c_000000a2"


def _agent(
    model: ScriptedChatModel,
    *,
    workspace: LocalWorkspace | None = None,
    skills_dir: Path | None = None,
    subagents_dir: Path | None = None,
) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills_dir=skills_dir,
        subagents_dir=subagents_dir,
    )
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    agent = _agent(model)
    events = [e async for e in agent.run(thread_id="t1", run_id="r1", message="hi", model="fake")]

```

改为：

```python
    agent = _agent(model)
    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
        async for e in _agent(FailingChatModel(responses=[])).run(
            thread_id="t1", run_id="r1", message="hi", model="fake"
        )
```

改为：

```python
        async for e in _agent(FailingChatModel(responses=[])).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    agent = _agent(model)
    _ = [e async for e in agent.run(thread_id="t1", run_id="r1", message="a", model="fake")]
    _ = [e async for e in agent.run(thread_id="t1", run_id="r2", message="b", model="fake")]

```

改为：

```python
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="fake"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="b", model="fake"
        )
    ]

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
        ]
    )
    events = [
        e async for e in _agent(model).run(thread_id="t1", run_id="r1", message="hi", model="fake")
    ]

    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
```

改为：

```python
        ]
    )
    events = [
        e
        async for e in _agent(model).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
        ]
    )
    events = [
        e async for e in _agent(model).run(thread_id="t1", run_id="r1", message="hi", model="fake")
    ]

    for call_id in ("cA", "cB"):
```

改为：

```python
        ]
    )
    events = [
        e
        async for e in _agent(model).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

    for call_id in ("cA", "cB"):
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    agent = _agent(model)
    _ = [e async for e in agent.run(thread_id="t1", run_id="r1", message="a", model="model-a")]
    _ = [e async for e in agent.run(thread_id="t1", run_id="r2", message="b", model="model-b")]

```

改为：

```python
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="model-a"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="b", model="model-b"
        )
    ]

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    async def consume() -> None:
        async for event in agent.run(thread_id="t1", run_id="r1", message="一", model="fake"):
            if isinstance(event, MessageDelta):
```

改为：

```python
    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="一", model="fake"
        ):
            if isinstance(event, MessageDelta):
```

在 `agents/tests/test_main_agent.py` 中，把：

```python

    events = [e async for e in agent.run(thread_id="t1", run_id="r2", message="二", model="fake")]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "第二次的回答"
```

改为：

```python

    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="二", model="fake"
        )
    ]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "第二次的回答"
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    model = HangingChatModel(responses=[AIMessage(content="好的")])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(thread_id="t1", run_id="r1", message="写长文", model="fake"):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
```

改为：

```python
    model = HangingChatModel(responses=[AIMessage(content="好的")])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        ):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
```

在 `agents/tests/test_main_agent.py` 中，把：

```python

    _ = [e async for e in agent.run(thread_id="t1", run_id="r2", message="一句话", model="fake")]

```

改为：

```python

    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="一句话", model="fake"
        )
    ]

```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    model = HangingChatModel(responses=[])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(thread_id="t1", run_id="r1", message="写长文", model="fake"):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
```

改为：

```python
    model = HangingChatModel(responses=[])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        ):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
    agent = _agent(model)
    _ = [e async for e in agent.run(thread_id="t1", run_id="r1", message="a", model="fake")]
    _ = [e async for e in agent.run(thread_id="t2", run_id="r2", message="b", model="fake")]

    await agent.delete_thread("t1")

```

改为：

```python
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="fake"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t2", thread_short_id=OTHER_SHORT, run_id="r2", message="b", model="fake"
        )
    ]

    await agent.delete_thread("t1", SHORT)

```

在 `agents/tests/test_main_agent.py` 末尾追加：

```python


def _files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


async def _run(agent: MainAgent, message: str = "go") -> list[object]:
    return [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message=message, model="fake"
        )
    ]


async def test_commands_run_in_the_sandbox_for_this_thread(tmp_path: Path) -> None:
    sandbox = FakeSandbox(output="a.csv")
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    assert sandbox.calls == [(SHORT, "ls", None)]


async def test_files_land_in_this_threads_directory(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        responses=[
            call("write_file", {"file_path": f"/workspace/{SHORT}/outputs/a.txt", "content": "x"}),
            AIMessage("写好了"),
        ]
    )
    await _run(_agent(model, workspace=LocalWorkspace(tmp_path, FakeSandbox())))
    assert (tmp_path / "workspace" / SHORT / "outputs" / "a.txt").read_text() == "x"


async def test_prompt_tells_the_model_its_work_directory() -> None:
    model = ScriptedChatModel(responses=[AIMessage("好")])
    await _run(_agent(model))
    system = str(model.received[0][0].content)
    assert f"/workspace/{SHORT}/" in system
    assert f"/workspace/{SHORT}/outputs/" in system


async def test_skills_are_offered_and_read_only(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "excel"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: excel\ndescription: 处理 Excel 的规范\n---\n正文")
    model = ScriptedChatModel(
        responses=[
            call("read_file", {"file_path": "/skills/excel/SKILL.md"}),
            call("write_file", {"file_path": "/skills/excel/x.md", "content": "改"}),
            AIMessage("好"),
        ]
    )
    events = await _run(_agent(model, skills_dir=tmp_path / "skills"))
    assert "处理 Excel 的规范" in str(model.received[0][0].content)
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [(e.name, e.status) for e in finished] == [
        ("read_file", "success"),
        ("write_file", "error"),
    ]
    assert not (skill / "x.md").exists()


async def test_data_analyst_works_in_the_same_directory(tmp_path: Path) -> None:
    """数据分析员子智能体来自定义文件；它跟随主对话的模型，在同一个会话目录里执行代码。"""
    subagents = tmp_path / "subagents"
    subagents.mkdir()
    (subagents / "data_analyst.md").write_text(
        "---\nname: data_analyst\ndescription: 分析数据\n---\n你是数据分析员。"
    )
    sandbox = FakeSandbox(output="均值 3")
    task = {"description": "算均值", "subagent_type": "data_analyst"}
    model = ScriptedChatModel(
        responses=[
            call("task", task),
            call("execute", {"command": "python stats.py"}),  # 子智能体（同一个模型）
            AIMessage("均值是 3"),  # 子智能体交回
            AIMessage("算好了，均值是 3"),
        ]
    )
    agent = _agent(model, workspace=LocalWorkspace(tmp_path, sandbox), subagents_dir=subagents)
    events = await _run(agent)
    assert sandbox.calls == [(SHORT, "python stats.py", None)]
    started = [e for e in events if isinstance(e, SubagentStarted)]
    assert [e.name for e in started] == ["data_analyst"]
    sub_system = str(model.received[1][0].content)
    assert "你是数据分析员。" in sub_system
    assert f"/workspace/{SHORT}/" in sub_system


async def test_long_command_output_stays_out_of_the_workspace(tmp_path: Path) -> None:
    """超长输出由 deepagents 另存（/.agent/，在对话存档里），不在会话目录里留下文件。"""
    model = ScriptedChatModel(responses=[call("execute", {"command": "cat big"}), AIMessage("好")])
    sandbox = FakeSandbox(output="行" * 120_000)
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].status == "success"
    assert "/.agent/large_tool_results/" in finished[0].output
    assert _files(tmp_path) == []


async def test_delete_thread_removes_its_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    (tmp_path / "workspace" / SHORT / "outputs").mkdir(parents=True)
    agent = _agent(ScriptedChatModel(responses=[]), workspace=workspace)
    await agent.delete_thread("t1", SHORT)
    assert not (tmp_path / "workspace" / SHORT).exists()
```

在 `agents/tests/test_bootstrap.py` 中，把：

```python
from agents.main_agent.models import LiteLLMProxyGateway
from common.db import Pool
```

改为：

```python
from agents.main_agent.models import LiteLLMProxyGateway
from agents.main_agent.workspace import LocalWorkspace
from common.db import Pool
```

在 `agents/tests/test_bootstrap.py` 中，把：

```python
        agent=AgentConfig(default_model="m", system_prompt_file=prompt),
    )
```

改为：

```python
        agent=AgentConfig(default_model="m", system_prompt_file=prompt),
        workdata_dir=tmp_path,
    )
```

在 `agents/tests/test_bootstrap.py` 中，把：

```python
    assert isinstance(agent.models, LiteLLMProxyGateway)
    async with pg_pool.connection() as conn:
```

改为：

```python
    assert isinstance(agent.models, LiteLLMProxyGateway)
    assert isinstance(agent.workspace, LocalWorkspace)  # 配置 adapters.workspace: docker_local
    async with pg_pool.connection() as conn:
```

在 `agents/tests/live/test_smoke.py` 中，把：

```python

import os
import statistics
import time
from typing import Any
```

改为：

```python

import hashlib
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any
```

在 `agents/tests/live/test_smoke.py` 中，把：

```python
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
from config import get_settings
```

改为：

```python
from agents.main_agent.runtime import Event, MainAgent, RunFinished, ToolStarted
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeSandbox
from config import get_settings
```

在 `agents/tests/live/test_smoke.py` 中，把：

```python
        system_prompt="你是测试助手，严格按用户要求使用工具，回答尽量简短。",
    )
```

改为：

```python
        system_prompt="你是测试助手，严格按用户要求使用工具，回答尽量简短。",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )
```

在 `agents/tests/live/test_smoke.py` 中，把：

```python
        e
        async for e in agent.run(thread_id=thread_id, run_id="smoke", message=message, model=model)
    ]
```

改为：

```python
        e
        async for e in agent.run(
            thread_id=thread_id,
            thread_short_id="c_" + hashlib.md5(thread_id.encode()).hexdigest()[:8],
            run_id="smoke",
            message=message,
            model=model,
        )
    ]
```

backend 的测试夹具与运行管理测试（构造主智能体时传入工作区）：

在 `backend/tests/conftest.py` 中，把：

```python

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

```

改为：

```python

import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

```

在 `backend/tests/conftest.py` 中，把：

```python
from agents.main_agent.runtime import MainAgent
from agents.tests.fakes import FakeGateway
from backend.api.deps import build_services
```

改为：

```python
from agents.main_agent.runtime import MainAgent
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox
from backend.api.deps import build_services
```

在 `backend/tests/conftest.py` 中，把：

```python
        bus_retain_seconds: float = 60.0,
    ) -> AsyncIterator[AsyncClient]:
```

改为：

```python
        bus_retain_seconds: float = 60.0,
        workspace: LocalWorkspace | None = None,
    ) -> AsyncIterator[AsyncClient]:
```

在 `backend/tests/conftest.py` 中，把：

```python
            system_prompt="测试助手",
        )
```

改为：

```python
            system_prompt="测试助手",
            workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        )
```

在 `backend/tests/test_manager.py` 中，把：

```python
import asyncio
from collections.abc import AsyncIterator
from uuid import UUID
```

改为：

```python
import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID
```

在 `backend/tests/test_manager.py` 中，把：

```python
from agents.main_agent.usage import UsageRepo
from agents.tests.fakes import FakeGateway, HangingChatModel, ScriptedChatModel
from backend.runs import RunCreate, RunManager, RunRecord, RunRepo
```

改为：

```python
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, HangingChatModel, ScriptedChatModel, call
from backend.runs import RunCreate, RunManager, RunRecord, RunRepo
```

在 `backend/tests/test_manager.py` 中，把：

```python
    threads: ThreadRepo | None = None,
) -> RunManager:
```

改为：

```python
    threads: ThreadRepo | None = None,
    workspace: LocalWorkspace | None = None,
) -> RunManager:
```

在 `backend/tests/test_manager.py` 中，把：

```python
    agent = MainAgent(
        gateway=FakeGateway(model), checkpointer=InMemorySaver(), system_prompt="测试助手"
    )
```

改为：

```python
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )
```

在 `backend/tests/test_manager.py` 末尾追加：

```python


async def test_commands_run_in_the_threads_work_directory(db: Pool, tmp_path: Path) -> None:
    sandbox = FakeSandbox()
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    manager = _manager(db, RunRepo(db), model, workspace=LocalWorkspace(tmp_path, sandbox))
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="看看有什么文件"))
    _ = await asyncio.wait_for(_drain(manager, run.id), timeout=5)
    assert sandbox.calls == [(thread.short_id, "ls", None)]


async def test_delete_thread_also_removes_its_workspace(db: Pool, tmp_path: Path) -> None:
    """删除会话 = 删除它的全部内容，包括上传与产物所在的工作目录（设计文档 9.3）。"""
    manager = _manager(db, RunRepo(db), workspace=LocalWorkspace(tmp_path, FakeSandbox()))
    thread = await ThreadRepo(db).create(model="m")
    outputs = tmp_path / "workspace" / thread.short_id / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "chart.png").write_bytes(b"png")

    await manager.delete_thread(thread.id)

    assert not (tmp_path / "workspace" / thread.short_id).exists()
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_main_agent.py agents/tests/test_subagents.py agents/tests/test_bootstrap.py -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'agents.main_agent.runtime.subagents'`。

- [ ] **步骤 3：新增依赖**

子智能体定义文件开头是 YAML（名称、说明）：

在 `pyproject.toml` 中，把：

```toml
    "uvicorn[standard]==0.54.0",
]
```

改为：

```toml
    "uvicorn[standard]==0.54.0",
    "pyyaml==6.0.3",
]
```

运行：`uv lock`

预期：`uv.lock` 新增 `pyyaml 6.0.3`。

- [ ] **步骤 4：实现运行时**

新建 `agents/main_agent/runtime/subagents.py`：

```python
"""子智能体定义（设计文档 7.4）：agents/subagents/ 下每个 Markdown 文件是一个子智能体。

新增子智能体只需加一个定义文件，无需写代码。

文件格式与技能文件相同——YAML 文件头 + 正文：
    ---
    name: data_analyst          # 主智能体派任务时用的名字
    description: 何时派它        # 主智能体据此决定是否派它
    model: gemini-3.5-flash     # 可选：指定模型版本；不写则跟随主对话所选的模型
    ---
    正文即它的系统提示词。
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SubagentDefinition:
    name: str
    description: str
    system_prompt: str
    model: str | None = None


def load_subagents(directory: Path) -> list[SubagentDefinition]:
    """读取目录下全部 *.md 定义（按文件名排序）；缺少文件头、名称或说明时报错并指出文件。"""
    return [_load(path) for path in sorted(directory.glob("*.md"))]


def _load(path: Path) -> SubagentDefinition:
    text = path.read_text(encoding="utf-8")
    _, head, body = text.split("---", 2) if text.startswith("---") else ("", "", "")
    meta = yaml.safe_load(head) if head else None
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        raise ValueError(f"子智能体定义不完整（需要 name 与 description 文件头）：{path.name}")
    return SubagentDefinition(
        name=str(meta["name"]),
        description=str(meta["description"]),
        system_prompt=body.strip(),
        model=str(meta["model"]) if meta.get("model") else None,
    )
```

新建 `agents/main_agent/runtime/files.py`：

```python
"""智能体的文件树（设计文档 7.3）：工作区为默认后端，/skills/ 只读，/.agent/ 是智能体内部文件。"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    FileUploadResponse,
    SandboxBackendProtocol,
    WriteResult,
)
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from agents.main_agent.context import AgentContext

# deepagents 把超长工具输出、压缩时移出的对话历史等放在这个根下。路由到"状态内存储"：
# 与对话存档一起按会话保存、随会话删除；放进工作区会被会话目录限制拒绝，也会混进用户的文件
AGENT_FILES = "/.agent"


def build_file_tree(workspace: SandboxBackendProtocol, skills_dir: Path | None) -> CompositeBackend:
    routes: dict[str, Any] = {f"{AGENT_FILES}/": StateBackend()}
    if skills_dir is not None:
        routes["/skills/"] = ReadOnlyFilesystem(skills_dir)
    # 工作区必须是默认后端：deepagents 只把执行命令交给默认后端（设计文档 7.3）
    return CompositeBackend(default=workspace, routes=routes, artifacts_root=AGENT_FILES)


class ReadOnlyFilesystem(FilesystemBackend):
    """只读目录（技能文件随代码版本管理，智能体不能改）。"""

    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root, virtual_mode=True)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=f"{file_path} 是只读的")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error=f"{file_path} 是只读的")

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=f"{file_path} 是只读的")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]


class WorkDirectoryMiddleware(AgentMiddleware):
    """每次调用模型前，在系统提示词末尾写明本会话的工作目录（各会话不同，不能写死在提示词里）。"""

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return handler(self._with_note(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._with_note(request))

    @staticmethod
    def _with_note(request: ModelRequest) -> ModelRequest:
        short_id = cast(AgentContext, request.runtime.context).thread_short_id
        note = (
            f"\n\n当前会话的工作目录是 /workspace/{short_id}/：要执行的代码和中间文件都放在这里，"
            f"交给用户的文件（图表、表格、报告等）放到 /workspace/{short_id}/outputs/。"
        )
        base = request.system_prompt or ""
        return request.override(system_message=SystemMessage(content=base + note))
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
from collections.abc import AsyncIterator
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
```

改为：

```python
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

改为：

```python

from agents.main_agent.context import AgentContext
from agents.main_agent.models import ModelGateway, ModelSwitchCleanupMiddleware
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
)
from agents.main_agent.runtime.interruption import (
```

改为：

```python
)
from agents.main_agent.runtime.files import WorkDirectoryMiddleware, build_file_tree
from agents.main_agent.runtime.interruption import (
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
)
from agents.main_agent.runtime.tracker import Calibration, RunTracker
from agents.main_agent.runtime.translator import Translator

```

改为：

```python
)
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
from agents.main_agent.runtime.tracker import Calibration, RunTracker
from agents.main_agent.runtime.translator import Translator
from agents.main_agent.workspace import Workspace

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    def __init__(
        self, *, gateway: ModelGateway, checkpointer: BaseCheckpointSaver[Any], system_prompt: str
    ) -> None:
        self.models = gateway
        self._checkpointer = checkpointer
        self._system_prompt = system_prompt
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
```

改为：

```python
    def __init__(
        self,
        *,
        gateway: ModelGateway,
        checkpointer: BaseCheckpointSaver[Any],
        system_prompt: str,
        workspace: Workspace,
        skills_dir: Path | None = None,
        subagents_dir: Path | None = None,
    ) -> None:
        self.models = gateway
        self.workspace = workspace
        self._checkpointer = checkpointer
        self._system_prompt = system_prompt
        self._skills_dir = skills_dir
        self._subagents = load_subagents(subagents_dir) if subagents_dir else []
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python

    async def delete_thread(self, thread_id: str) -> None:
        """删除该会话的对话存档（模型上下文）。"""
        await self._checkpointer.adelete_thread(thread_id)

```

改为：

```python

    async def delete_thread(self, thread_id: str, thread_short_id: str) -> None:
        """删除该会话的对话存档（模型上下文）与工作区目录。"""
        await self._checkpointer.adelete_thread(thread_id)
        await self.workspace.remove(thread_short_id)

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    async def run(
        self, *, thread_id: str, run_id: str, message: str, model: str
    ) -> AsyncIterator[Event]:
```

改为：

```python
    async def run(
        self, *, thread_id: str, thread_short_id: str, run_id: str, message: str, model: str
    ) -> AsyncIterator[Event]:
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                version="v2",
            ):
```

改为：

```python
                version="v2",
                context=AgentContext(thread_id, thread_short_id, run_id),
            ):
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                InterruptionMarkerMiddleware(),  # 被打断的一轮补上"已中断"，模型不会重做
            ]
```

改为：

```python
                InterruptionMarkerMiddleware(),  # 被打断的一轮补上"已中断"，模型不会重做
                WorkDirectoryMiddleware(),
            ]
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                middleware=middleware,
                checkpointer=self._checkpointer,
            )
        return self._graphs[model]
```

改为：

```python
                middleware=middleware,
                subagents=[self._subagent(definition) for definition in self._subagents],
                backend=build_file_tree(self.workspace.agent_backend, self._skills_dir),
                skills=["/skills/"] if self._skills_dir else None,
                context_schema=AgentContext,
                checkpointer=self._checkpointer,
            )
        return self._graphs[model]

    def _subagent(self, definition: SubagentDefinition) -> SubAgent:
        """定义文件 → deepagents 子智能体。不指定模型时跟随主对话所选的模型。"""
        spec: SubAgent = {
            "name": definition.name,
            "description": definition.description,
            "system_prompt": definition.system_prompt,
            "middleware": [WorkDirectoryMiddleware()],  # 子智能体同样要知道工作目录
        }
        if definition.model:
            spec["model"] = self.models.chat_model(definition.model)
        return spec
```

在 `config/settings.py` 中，把：

```python
    system_prompt_file: Path = ROOT_DIR / "agents" / "prompts" / "system.md"

```

改为：

```python
    system_prompt_file: Path = ROOT_DIR / "agents" / "prompts" / "system.md"
    skills_dir: Path = ROOT_DIR / "agents" / "skills"  # 给智能体用的技能（SKILL.md），只读
    subagents_dir: Path = ROOT_DIR / "agents" / "subagents"  # 子智能体定义文件

```

在 `agents/main_agent/bootstrap.py` 中，把：

```python
from agents.main_agent.runtime import MainAgent
from common.db import Pool
```

改为：

```python
from agents.main_agent.runtime import MainAgent
from agents.main_agent.workspace import HttpSandbox, LocalWorkspace, Workspace
from common.db import Pool
```

在 `agents/main_agent/bootstrap.py` 中，把：

```python
        s.litellm_base_url, s.litellm_master_key.get_secret_value()
    ),
```

改为：

```python
        s.litellm_base_url, s.litellm_master_key.get_secret_value()
    ),
}

_WORKSPACES: dict[str, Callable[[Settings], Workspace]] = {
    "docker_local": lambda s: LocalWorkspace(
        s.workdata_dir,
        HttpSandbox(
            s.workspace.sandbox_url,
            s.sandbox_secret.get_secret_value() if s.sandbox_secret else "",
            default_time_limit=s.workspace.command_timeout,
        ),
    ),
```

在 `agents/main_agent/bootstrap.py` 中，把：

```python
        system_prompt=settings.agent.system_prompt_file.read_text(encoding="utf-8"),
    )
```

改为：

```python
        system_prompt=settings.agent.system_prompt_file.read_text(encoding="utf-8"),
        workspace=_WORKSPACES[settings.adapters.workspace](settings),
        skills_dir=settings.agent.skills_dir,
        subagents_dir=settings.agent.subagents_dir,
    )
```

- [ ] **步骤 5：技能、子智能体与系统提示词**

新建 `agents/skills/excel/SKILL.md`：

```markdown
---
name: excel
description: 读取、清洗、汇总 Excel / CSV，并输出图表或新表格的规范。处理 .xlsx、.xls、.csv 文件时先读这份规范。
---

# 处理 Excel / CSV 的规范

## 读取

- 先看结构再处理：`pd.ExcelFile(path).sheet_names` 列出工作表；每个表先读前 5 行（`nrows=5`）确认表头在哪一行。
- 表头不在第一行时用 `header=` 指定；合并单元格造成的空值用 `ffill()` 补齐。
- CSV 先试 `encoding="utf-8"`，出现乱码再试 `gbk`。
- 大表（几万行以上）只读需要的列（`usecols=`）。

## 清洗

- 数字列里混入的文字、千分位逗号、百分号先清理再转数值（`pd.to_numeric(..., errors="coerce")`），并说明有多少行转换失败。
- 日期列统一用 `pd.to_datetime`；去重、处理空值前后都报告行数变化。

## 汇总与输出

- 汇总表保存为 `outputs/<名称>.xlsx`（`df.to_excel(..., index=False)`），多张表放进同一个文件的不同工作表。
- 图表用 matplotlib / seaborn：`plt.savefig("outputs/<名称>.png", dpi=150, bbox_inches="tight")`，保存后 `plt.close()`；标题、坐标轴用中文（已配置中文字体）。
- 回答里给出关键数字与结论，并列出产物文件的路径；不要把整张表贴进回答。
```

新建 `agents/subagents/data_analyst.md`：

```markdown
---
name: data_analyst
description: 数据分析员。需要读取或处理 Excel、CSV、PDF 等文件，做统计、计算、画图或生成报表时派它——它在沙箱里写代码、跑代码，只把结论和产物路径交回。只是回答问题、不需要算数据时不要派。
---

你是数据分析员，在沙箱里用 Python 完成数据分析任务。

工作方式：
- 先看清任务描述里给出的文件与要求；文件都在当前会话的工作目录里。
- 用 execute 工具运行 Python（python3）。沙箱已装 pandas、numpy、matplotlib、seaborn、openpyxl、python-docx、python-pptx、pymupdf、pillow；不能上网，不能安装新包。
- 代码先写成文件（write_file）再执行，出错时修改后重跑；大文件分批读取，不要把整张表打印出来。
- 处理 Excel、CSV 前先读技能文件 /skills/excel/SKILL.md 里的规范。
- 图表、表格、报告等交给用户的文件一律保存到工作目录下的 outputs/；图里的中文可以直接写（已配置中文字体）。
- 结束时只交回：结论（用数字说话）、产物文件的路径、必要的注意事项。不要交回代码全文或大段执行输出。
```

在 `agents/prompts/system.md` 末尾追加：

```markdown

文件与代码：
- 每个会话有自己的工作目录（见本提示末尾），你可以在里面读写文件，并用 execute 工具在隔离的沙箱里运行命令：Python 3，已装 pandas、numpy、matplotlib、seaborn、openpyxl、python-docx、python-pptx、pymupdf、pillow；沙箱不能上网，不能安装新包。
- 交给用户的文件（图表、表格、报告等）放到工作目录的 outputs/ 下，回答里说明文件名；用户能在界面上直接查看和下载。
- 需要读取或处理 Excel、CSV、PDF 等文件，或者要统计、计算、画图时，派数据分析员（task 工具，subagent_type 为 data_analyst）去做：在任务描述里写清楚文件路径和要求，它只交回结论与产物路径。简单的问题直接回答，不要派。
- 处理特定类型的任务前，先看技能目录 /skills/ 里有没有对应的规范（可用技能列在下方），有就按规范做。
```

- [ ] **步骤 6：运行管理传会话短 ID**

在 `backend/runs/manager.py` 中，把：

```python
        self._bus.open(str(run.id))
        self._control.track(str(run.id), asyncio.create_task(self._execute(run)))
        await self._threads.touch(thread.id, first_message=body.message)
```

改为：

```python
        self._bus.open(str(run.id))
        self._control.track(str(run.id), asyncio.create_task(self._execute(run, thread.short_id)))
        await self._threads.touch(thread.id, first_message=body.message)
```

在 `backend/runs/manager.py` 中，把：

```python
    async def delete_thread(self, thread_id: UUID) -> None:
        """删除会话及其全部内容：对话存档、运行、界面历史；用量记录保留（费用统计不受影响）。

        有进行中的运行时拒绝，需先停止。先删对话存档再删会话：中途失败时会话仍在列表里，可以重试。
        """
        await self._threads.get(thread_id)
        if await self._runs.has_active(thread_id):
            raise ConflictError("会话正在运行，请先停止")
        await self._agent.delete_thread(str(thread_id))
        await self._threads.delete(thread_id)
```

改为：

```python
    async def delete_thread(self, thread_id: UUID) -> None:
        """删除会话及其全部内容：对话存档、工作区目录、运行、界面历史；用量记录保留（费用统计不受影响）。

        有进行中的运行时拒绝，需先停止。先删对话存档再删会话：中途失败时会话仍在列表里，可以重试。
        """
        thread = await self._threads.get(thread_id)
        if await self._runs.has_active(thread_id):
            raise ConflictError("会话正在运行，请先停止")
        await self._agent.delete_thread(str(thread_id), thread.short_id)
        await self._threads.delete(thread_id)
```

在 `backend/runs/manager.py` 中，把：

```python

    async def _execute(self, run: RunRecord) -> None:
        run_id = str(run.id)
```

改为：

```python

    async def _execute(self, run: RunRecord, thread_short_id: str) -> None:
        run_id = str(run.id)
```

在 `backend/runs/manager.py` 中，把：

```python
            async for event in self._agent.run(
                thread_id=str(run.thread_id), run_id=run_id, message=run.message, model=run.model
            ):
```

改为：

```python
            async for event in self._agent.run(
                thread_id=str(run.thread_id),
                thread_short_id=thread_short_id,
                run_id=run_id,
                message=run.message,
                model=run.model,
            ):
```

- [ ] **步骤 7：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_main_agent.py agents/tests/test_subagents.py agents/tests/test_bootstrap.py -q`

运行：`uv run pytest -m integration backend/tests/test_manager.py -q`

预期：全部通过（24 个；运行管理 19 个）。

- [ ] **步骤 8：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 143 个、前端 65 个）；`make test-int` 全部通过（集成测试 59 个）。

---

### 任务 4：产物检测、登记与下载接口

**文件：**
- 新建：`agents/main_agent/workspace/files.py`、`backend/migrations/versions/0005_agents_workspace_files.py`、`agents/tests/test_workspace_files.py`
- 修改：`agents/main_agent/runtime/events.py`、`agents/main_agent/runtime/__init__.py`、`agents/main_agent/runtime/agent.py`、`agents/main_agent/workspace/__init__.py`、`backend/runs/manager.py`、`backend/api/deps.py`、`backend/api/router.py`、`pyproject.toml`、`conftest.py`、`frontend/src/features/chat/reducer.ts`、`frontend/src/api/generated/*`（命令生成）、`agents/tests/fakes.py`、`agents/tests/test_main_agent.py`、`backend/tests/test_api.py`、`backend/tests/test_manager.py`、`backend/tests/test_migrations.py`、`backend/tests/test_openapi.py`、`frontend/src/features/chat/reducer.test.ts`

**接口：**
- 消费：任务 2 的 `Workspace.list_outputs` / `read_file`，任务 3 的 `MainAgent`、`call`。
- 产出（事件）：`FileCreated(type="file.created", path: str, size: int, media_type: str, file_id: str | None = None)`——智能体发出时 `file_id` 为空，backend 推送前填上。
- 产出（`agents.main_agent.workspace` 公开）：
  - `workspace_file_id(thread_id: UUID, path: str) -> UUID`：同一会话的同一路径始终同一个 ID；
  - `WorkspaceFile`（id、thread_id、path、source、media_type、size、created_at、updated_at）；
  - `WorkspaceFileRepo(pool)`：
    - `record(thread_id, path, *, source: "upload" | "output", size, media_type)`（同一文件再登记时更新大小与时间）；
    - `get(file_id)`（不存在抛 `NotFoundError`）；
    - `for_thread(thread_id)`（按路径排序）；
    - `delete_for_thread(thread_id)`。
- 产出（表）：`workspace_files`，`UNIQUE (thread_id, path)`，`source` 只能是 `upload` / `output`。
- 产出（backend）：`RunManager(..., files: WorkspaceFileRepo, ...)`；`Services.files`；接口 `GET /api/threads/{thread_id}/files/{file_id}/content`（`download=1` 时作为附件）。
- 产出（前端）：`ChatItem` 新增 `{ kind: "file"; id; fileId; path; size; mediaType }`，`id` 为 `file-<运行 ID>-<文件 ID>`。
- 产出（测试替身）：`FakeSandbox(..., effect=None)`，`effect(session, command)` 模拟命令的副作用（如在 `outputs/` 里生成文件）。

- [ ] **步骤 1：写失败的测试（agents 与 backend）**

在 `agents/tests/fakes.py` 中，把：

```python
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any
```

改为：

```python
import json
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any
```

在 `agents/tests/fakes.py` 中，把：

```python

    def __init__(self, output: str = "ok", exit_code: int = 0, *, hang: bool = False) -> None:
        self.calls: list[tuple[str, str, int | None]] = []
        self._result = CommandResult(output=output, exit_code=exit_code)
        self._hang = hang
        self.cancelled = False
```

改为：

```python

    def __init__(
        self,
        output: str = "ok",
        exit_code: int = 0,
        *,
        hang: bool = False,
        effect: Callable[[str, str], None] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, int | None]] = []
        self._result = CommandResult(output=output, exit_code=exit_code)
        self._hang = hang
        self._effect = effect  # 模拟命令的副作用（如代码在 outputs/ 里生成文件）：参数为会话、命令
        self.cancelled = False
```

在 `agents/tests/fakes.py` 中，把：

```python
        self.calls.append((session, command, time_limit))
        if self._hang:
```

改为：

```python
        self.calls.append((session, command, time_limit))
        if self._effect is not None:
            self._effect(session, command)
        if self._hang:
```

在 `agents/tests/test_main_agent.py` 中，把：

```python
from agents.main_agent.runtime import (
    MainAgent,
```

改为：

```python
from agents.main_agent.runtime import (
    FileCreated,
    MainAgent,
```

在 `agents/tests/test_main_agent.py` 末尾追加：

```python


async def test_new_and_changed_outputs_are_reported(tmp_path: Path) -> None:
    """outputs/ 下新增或改动的文件推送 file.created（显示为产物卡片）；其他目录的文件不算产物。"""
    outputs = tmp_path / "workspace" / SHORT / "outputs"

    def make_chart(session: str, command: str) -> None:
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "chart.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[
            call("write_file", {"file_path": f"/workspace/{SHORT}/scratch.py", "content": "x"}),
            call("execute", {"command": "python plot.py"}),
            call("write_file", {"file_path": f"/workspace/{SHORT}/outputs/r.md", "content": "一"}),
            call(
                "write_file", {"file_path": f"/workspace/{SHORT}/outputs/r.md", "content": "二二"}
            ),
            AIMessage("图和报告都好了"),
        ]
    )
    sandbox = FakeSandbox(effect=make_chart)
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    files = [e for e in events if isinstance(e, FileCreated)]
    assert [(f.path, f.size, f.media_type) for f in files] == [
        ("outputs/chart.png", 4, "image/png"),
        ("outputs/r.md", 3, "text/markdown"),
        ("outputs/r.md", 6, "text/markdown"),  # 改动后再报一次
    ]
    assert all(f.agent_path == ["main"] and f.file_id is None for f in files)
    finished = events.index(next(e for e in events if isinstance(e, ToolFinished)))
    assert events.index(files[0]) > finished  # 在产生它的工具结束之后


async def test_files_from_earlier_runs_are_not_reported_again(tmp_path: Path) -> None:
    outputs = tmp_path / "workspace" / SHORT / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "old.csv").write_text("a")
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, FakeSandbox())))
    assert [e for e in events if isinstance(e, FileCreated)] == []
```

新建 `agents/tests/test_workspace_files.py`：

```python
import uuid

import pytest

from agents.main_agent.workspace import WorkspaceFileRepo, workspace_file_id
from common.db import Pool
from common.errors import NotFoundError


def test_file_id_is_fixed_by_thread_and_path() -> None:
    """同一会话同一路径的文件始终是同一个 ID：推送产物事件时不必先查数据库就有下载地址。"""
    thread = uuid.uuid4()
    assert workspace_file_id(thread, "outputs/a.png") == workspace_file_id(thread, "outputs/a.png")
    assert workspace_file_id(thread, "outputs/a.png") != workspace_file_id(thread, "outputs/b.png")
    assert workspace_file_id(thread, "outputs/a.png") != workspace_file_id(
        uuid.uuid4(), "outputs/a.png"
    )


@pytest.mark.integration
async def test_records_updates_lists_and_deletes(db: Pool) -> None:
    repo = WorkspaceFileRepo(db)
    thread = uuid.uuid4()
    first = await repo.record(
        thread, "outputs/a.png", source="output", size=3, media_type="image/png"
    )
    again = await repo.record(
        thread, "outputs/a.png", source="output", size=5, media_type="image/png"
    )
    await repo.record(thread, "outputs/b.csv", source="output", size=1, media_type="text/csv")

    assert first.id == again.id == workspace_file_id(thread, "outputs/a.png")
    stored = await repo.get(first.id)
    assert (stored.thread_id, stored.size, stored.source) == (thread, 5, "output")
    assert stored.updated_at >= stored.created_at
    assert [f.path for f in await repo.for_thread(thread)] == ["outputs/a.png", "outputs/b.csv"]

    await repo.delete_for_thread(thread)
    assert await repo.for_thread(thread) == []
    with pytest.raises(NotFoundError):
        await repo.get(first.id)
```

在 `backend/tests/test_migrations.py` 中，把：

```python
    assert row == {"usage": "llm_usage"}

```

改为：

```python
    assert row == {"usage": "llm_usage"}


async def test_workspace_files_table_exists(pg_pool: Pool) -> None:
    async with pg_pool.connection() as conn:
        cur = await conn.execute("SELECT to_regclass('public.workspace_files')::text AS files")
        row = await cur.fetchone()
    assert row == {"files": "workspace_files"}

```

集成测试每次开始前清空的表里加上 `workspace_files`：

在 `conftest.py` 中，把：

```python
    async with pg_pool.connection() as conn:
        await conn.execute("TRUNCATE threads, runs, run_events, llm_usage CASCADE")
    return pg_pool
```

改为：

```python
    async with pg_pool.connection() as conn:
        await conn.execute("TRUNCATE threads, runs, run_events, llm_usage, workspace_files CASCADE")
    return pg_pool
```

在 `backend/tests/test_manager.py` 中，把：

```python
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, HangingChatModel, ScriptedChatModel, call
```

改为：

```python
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import LocalWorkspace, WorkspaceFileRepo, workspace_file_id
from agents.tests.fakes import FakeGateway, FakeSandbox, HangingChatModel, ScriptedChatModel, call
```

在 `backend/tests/test_manager.py` 中，把：

```python
    workspace: LocalWorkspace | None = None,
) -> RunManager:
```

改为：

```python
    workspace: LocalWorkspace | None = None,
    files: WorkspaceFileRepo | None = None,
) -> RunManager:
```

在 `backend/tests/test_manager.py` 中，把：

```python
        usage=usage or UsageRepo(db),
        agent=agent,
```

改为：

```python
        usage=usage or UsageRepo(db),
        files=files or WorkspaceFileRepo(db),
        agent=agent,
```

在 `backend/tests/test_manager.py` 中，把：

```python

    await manager.delete_thread(thread.id)

    assert not (tmp_path / "workspace" / thread.short_id).exists()
```

改为：

```python

    files = WorkspaceFileRepo(db)
    await files.record(thread.id, "outputs/chart.png", source="output", size=3, media_type="x")

    await manager.delete_thread(thread.id)

    assert not (tmp_path / "workspace" / thread.short_id).exists()
    assert await files.for_thread(thread.id) == []


async def test_created_files_get_an_id_and_are_recorded(db: Pool, tmp_path: Path) -> None:
    """产物事件推送时已带文件 ID（前端据此下载）；登记在后台完成，结束事件推送前已写好。"""
    thread = await ThreadRepo(db).create(model="m")

    def make_chart(session: str, command: str) -> None:
        outputs = tmp_path / "workspace" / session / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "chart.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python plot.py"}), AIMessage("好")]
    )
    workspace = LocalWorkspace(tmp_path, FakeSandbox(effect=make_chart))
    manager = _manager(db, RunRepo(db), model, workspace=workspace)
    run = await manager.start(thread.id, RunCreate(message="画图"))
    events = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    created = [e for e in events if e.type == "file.created"]
    assert [e.data["file_id"] for e in created] == [
        str(workspace_file_id(thread.id, "outputs/chart.png"))
    ]
    record = await WorkspaceFileRepo(db).get(UUID(created[0].data["file_id"]))
    assert (record.path, record.size, record.source, record.media_type) == (
        "outputs/chart.png",
        4,
        "output",
        "image/png",
    )
```

在 `backend/tests/test_api.py` 中，把：

```python
from datetime import datetime
from typing import Any
```

改为：

```python
from datetime import datetime
from pathlib import Path
from typing import Any
```

在 `backend/tests/test_api.py` 中，把：

```python
from agents.main_agent.runtime import MessageDelta
from agents.tests.fakes import (
    FailingChatModel,
    HangingChatModel,
    ScriptedChatModel,
    UnavailableGateway,
)
```

改为：

```python
from agents.main_agent.runtime import MessageDelta
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    FailingChatModel,
    FakeSandbox,
    HangingChatModel,
    ScriptedChatModel,
    UnavailableGateway,
    call,
)
```

在 `backend/tests/test_api.py` 末尾追加：

```python


async def test_download_an_output_file(make_client: ClientFactory, tmp_path: Path) -> None:
    def make_chart(session: str, command: str) -> None:
        outputs = tmp_path / "workspace" / session / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "销售图.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python plot.py"}), AIMessage("好")]
    )
    workspace = LocalWorkspace(tmp_path, FakeSandbox(effect=make_chart))
    async with make_client(model, workspace=workspace) as client:
        thread = (await client.post("/api/threads", json={})).json()
        await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "画图"})
        history = await _wait_finished(client, thread["id"])
        created = next(e for e in history[-1]["events"] if e["type"] == "file.created")
        url = f"/api/threads/{thread['id']}/files/{created['data']['file_id']}/content"

        shown = await client.get(url)
        assert shown.status_code == 200
        assert shown.content == b"png!"
        assert shown.headers["content-type"] == "image/png"
        assert (
            shown.headers["content-disposition"]
            == "inline; filename*=UTF-8''%E9%94%80%E5%94%AE%E5%9B%BE.png"
        )
        # 产物可能是 HTML / SVG：直接打开时不执行其中的脚本，也不按内容猜类型
        assert shown.headers["content-security-policy"] == "sandbox"
        assert shown.headers["x-content-type-options"] == "nosniff"
        downloaded = await client.get(url, params={"download": "1"})
        assert downloaded.headers["content-disposition"].startswith("attachment;")

        other = (await client.post("/api/threads", json={})).json()
        stolen = f"/api/threads/{other['id']}/files/{created['data']['file_id']}/content"
        assert (await client.get(stolen)).status_code == 404  # 别的会话的文件
        unknown = f"/api/threads/{thread['id']}/files/{uuid.uuid4()}/content"
        assert (await client.get(unknown)).status_code == 404

        (tmp_path / "workspace" / thread["short_id"] / "outputs" / "销售图.png").unlink()
        gone = await client.get(url)
        assert gone.status_code == 404
        assert gone.json()["detail"] == "文件已不存在"
```

接口文档里列出的事件类型多了一种：

在 `backend/tests/test_openapi.py` 中，把：

```python
        "usage",
        "run.finished",
```

改为：

```python
        "usage",
        "file.created",
        "run.finished",
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_main_agent.py backend/tests/test_openapi.py -q`（预期失败）

预期：收集阶段报错 `ImportError: cannot import name 'FileCreated' from 'agents.main_agent.runtime'`（有收集错误时 pytest 不再运行其余测试）。

运行：`uv run pytest -m integration agents/tests/test_workspace_files.py backend/tests -q`（预期失败）

预期：`ImportError: cannot import name 'WorkspaceFileRepo'`。

- [ ] **步骤 3：实现产物检测（agents）**

在 `agents/main_agent/runtime/events.py` 中，把：

```python

class RunFinished(_BaseEvent):
```

改为：

```python

class FileCreated(_BaseEvent):
    """outputs/ 下新增或改动了一个文件（产物，设计文档 9.3）。

    file_id 由 backend 登记后填入（下载地址用它）；智能体发出时为空。
    """

    type: Literal["file.created"] = "file.created"
    path: str  # 相对会话目录，如 outputs/chart.png
    size: int
    media_type: str
    file_id: str | None = None


class RunFinished(_BaseEvent):
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python
    | UsageReported
    | RunFinished,
```

改为：

```python
    | UsageReported
    | FileCreated
    | RunFinished,
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    Event,
    InterruptedUsage,
```

改为：

```python
    Event,
    FileCreated,
    InterruptedUsage,
```

在 `agents/main_agent/runtime/__init__.py` 中，把：

```python
    "Event",
    "InterruptedUsage",
```

改为：

```python
    "Event",
    "FileCreated",
    "InterruptedUsage",
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
import logging
from collections.abc import AsyncIterator
```

改为：

```python
import logging
import mimetypes
from collections.abc import AsyncIterator
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    Event,
    InterruptedUsage,
```

改为：

```python
    Event,
    FileCreated,
    InterruptedUsage,
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
    RunStarted,
)
```

改为：

```python
    RunStarted,
    ToolFinished,
)
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
logger = logging.getLogger(__name__)

```

改为：

```python
logger = logging.getLogger(__name__)

# 可能在 outputs/ 里新增或改动文件的工具：它们结束后检查一次产物
_FILE_TOOLS = frozenset({"write_file", "edit_file", "execute"})

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
        partial = ""  # 主智能体正在输出、还没存进对话存档的回答
        try:
            graph = self._graph_for(model)
```

改为：

```python
        partial = ""  # 主智能体正在输出、还没存进对话存档的回答
        outputs = _OutputWatcher(self.workspace, thread_short_id)
        try:
            await outputs.start()
            graph = self._graph_for(model)
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
                    partial = ""  # 模型节点完成：这条回答已存进对话存档
                for event in translator.translate(part):
                    if isinstance(event, MessageDelta) and event.agent_path == [MAIN]:
                        partial += event.text
                    yield event
                for usage in tracker.drain_usage():
```

改为：

```python
                    partial = ""  # 模型节点完成：这条回答已存进对话存档
                touched_files = False
                for event in translator.translate(part):
                    if isinstance(event, MessageDelta) and event.agent_path == [MAIN]:
                        partial += event.text
                    touched_files |= isinstance(event, ToolFinished) and event.name in _FILE_TOOLS
                    yield event
                if touched_files:
                    for created in await outputs.changes():
                        yield created
                for usage in tracker.drain_usage():
```

在 `agents/main_agent/runtime/agent.py` 末尾追加：

```python


class _OutputWatcher:
    """对比 outputs/ 的前后状态，找出本次运行新增或改动的产物（设计文档 9.3）。"""

    def __init__(self, workspace: Workspace, short_id: str) -> None:
        self._workspace = workspace
        self._short_id = short_id
        self._seen: dict[str, tuple[int, float]] = {}

    async def start(self) -> None:
        self._seen = await self._snapshot()

    async def changes(self) -> list[FileCreated]:
        current = await self._snapshot()
        changed = [path for path, state in current.items() if self._seen.get(path) != state]
        self._seen = current
        return [
            FileCreated(
                path=path,
                size=current[path][0],
                media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            )
            for path in sorted(changed)
        ]

    async def _snapshot(self) -> dict[str, tuple[int, float]]:
        files = await self._workspace.list_outputs(self._short_id)
        return {f.path: (f.size, f.modified) for f in files}
```

- [ ] **步骤 4：登记表**

新建 `agents/main_agent/workspace/files.py`：

```python
"""workspace_files 表（设计文档 9.3、11.1）：登记会话里的上传与产物，下载地址用这里的 ID。"""

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from common.db import Pool
from common.errors import NotFoundError

_NAMESPACE = uuid.UUID("6f1c2a5e-8d1b-4b7a-9f3e-2c4d5e6f7a8b")
_COLUMNS = "id, thread_id, path, source, media_type, size, created_at, updated_at"

type FileSource = Literal["upload", "output"]


def workspace_file_id(thread_id: UUID, path: str) -> UUID:
    """会话 + 路径决定文件 ID：改动后仍是同一个文件，推送产物事件时不必先查数据库。"""
    return uuid.uuid5(_NAMESPACE, f"{thread_id}:{path}")


class WorkspaceFile(BaseModel):
    id: UUID
    thread_id: UUID
    path: str  # 相对会话目录，如 outputs/chart.png
    source: FileSource
    media_type: str
    size: int
    created_at: datetime
    updated_at: datetime


class WorkspaceFileRepo:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def record(
        self, thread_id: UUID, path: str, *, source: FileSource, size: int, media_type: str
    ) -> WorkspaceFile:
        """登记一个文件；已登记过（同会话同路径）则更新大小与类型。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO workspace_files (id, thread_id, path, source, media_type, size) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET size = EXCLUDED.size, "
                "media_type = EXCLUDED.media_type, updated_at = now() "
                f"RETURNING {_COLUMNS}",
                (workspace_file_id(thread_id, path), thread_id, path, source, media_type, size),
            )
            row = await cur.fetchone()
        return WorkspaceFile.model_validate(row)

    async def get(self, file_id: UUID) -> WorkspaceFile:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM workspace_files WHERE id = %s", (file_id,)
            )
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(f"文件不存在：{file_id}")
        return WorkspaceFile.model_validate(row)

    async def for_thread(self, thread_id: UUID) -> list[WorkspaceFile]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM workspace_files WHERE thread_id = %s ORDER BY path",
                (thread_id,),
            )
            rows = await cur.fetchall()
        return [WorkspaceFile.model_validate(row) for row in rows]

    async def delete_for_thread(self, thread_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM workspace_files WHERE thread_id = %s", (thread_id,))
```

在 `agents/main_agent/workspace/__init__.py` 中，把：

```python
)
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.sandbox_http import HttpSandbox

__all__ = ["CommandResult", "HttpSandbox", "LocalWorkspace", "OutputFile", "Sandbox", "Workspace"]
```

改为：

```python
)
from agents.main_agent.workspace.files import (
    WorkspaceFile,
    WorkspaceFileRepo,
    workspace_file_id,
)
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.sandbox_http import HttpSandbox

__all__ = [
    "CommandResult",
    "HttpSandbox",
    "LocalWorkspace",
    "OutputFile",
    "Sandbox",
    "Workspace",
    "WorkspaceFile",
    "WorkspaceFileRepo",
    "workspace_file_id",
]
```

新建 `backend/migrations/versions/0005_agents_workspace_files.py`：

```python
"""agents 工作区文件表：会话里的上传与产物（设计文档 9.3、11.1）。

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 会话不设外键（threads 归 backend 所有）：删除会话时由运行管理一并删除这些记录
    op.execute(
        """
        CREATE TABLE workspace_files (
            id          uuid PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'me',
            thread_id   uuid NOT NULL,
            path        text NOT NULL,
            source      text NOT NULL CHECK (source IN ('upload', 'output')),
            media_type  text NOT NULL,
            size        bigint NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (thread_id, path)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_files")
```

`files.py` 也属于工作区内部，backend 不能直接引用：

在 `pyproject.toml` 中，把：

```toml
    "agents.main_agent.usage.repo",
    "agents.main_agent.workspace.local",
```

改为：

```toml
    "agents.main_agent.usage.repo",
    "agents.main_agent.workspace.files",
    "agents.main_agent.workspace.local",
```

- [ ] **步骤 5：运行管理与下载接口（backend）**

在 `backend/runs/manager.py` 中，把：

```python

from agents.main_agent.runtime import Event, MainAgent, RunFinished, UsageReported, UsageTotals
from agents.main_agent.usage import UsageRepo
from backend.runs.repo import RunRepo
```

改为：

```python

from agents.main_agent.runtime import (
    Event,
    FileCreated,
    MainAgent,
    RunFinished,
    UsageReported,
    UsageTotals,
)
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import WorkspaceFileRepo, workspace_file_id
from backend.runs.repo import RunRepo
```

在 `backend/runs/manager.py` 中，把：

```python
        usage: UsageRepo,
        agent: MainAgent,
```

改为：

```python
        usage: UsageRepo,
        files: WorkspaceFileRepo,
        agent: MainAgent,
```

在 `backend/runs/manager.py` 中，把：

```python
        self._usage = usage
        self._agent = agent
```

改为：

```python
        self._usage = usage
        self._files = files
        self._agent = agent
```

在 `backend/runs/manager.py` 中，把：

```python
    async def delete_thread(self, thread_id: UUID) -> None:
        """删除会话及其全部内容：对话存档、工作区目录、运行、界面历史；用量记录保留（费用统计不受影响）。

```

改为：

```python
    async def delete_thread(self, thread_id: UUID) -> None:
        """删除会话及其全部内容：对话存档、工作区目录与文件登记、运行、界面历史；
        用量记录保留（费用统计不受影响）。

```

在 `backend/runs/manager.py` 中，把：

```python
        await self._agent.delete_thread(str(thread_id), thread.short_id)
        await self._threads.delete(thread_id)
```

改为：

```python
        await self._agent.delete_thread(str(thread_id), thread.short_id)
        await self._files.delete_for_thread(thread_id)
        await self._threads.delete(thread_id)
```

在 `backend/runs/manager.py` 中，把：

```python
        usage_writes: list[asyncio.Task[None]] = []
        totals = UsageTotals()
```

改为：

```python
        usage_writes: list[asyncio.Task[None]] = []
        file_writes: list[asyncio.Task[None]] = []
        totals = UsageTotals()
```

在 `backend/runs/manager.py` 中，把：

```python
                    )
                envelope = await self._publish(run_id, event, seq=len(published) + 1)
```

改为：

```python
                    )
                if isinstance(event, FileCreated):
                    # 文件 ID 由会话与路径算出，不必等登记：推送立即带上 ID，登记同样放到后台
                    file_id = workspace_file_id(run.thread_id, event.path)
                    event = event.model_copy(update={"file_id": str(file_id)})
                    file_writes.append(asyncio.create_task(self._record_file(run, event)))
                envelope = await self._publish(run_id, event, seq=len(published) + 1)
```

在 `backend/runs/manager.py` 中，把：

```python
            finalizing = asyncio.create_task(
                self._finalize(run, writer, usage_writes, [*published, tail], finished, totals)
            )
```

改为：

```python
            finalizing = asyncio.create_task(
                self._finalize(
                    run, writer, [*usage_writes, *file_writes], [*published, tail], finished, totals
                )
            )
```

在 `backend/runs/manager.py` 中，把：

```python
        writer: EventWriter,
        usage_writes: list[asyncio.Task[None]],
        events: list[EventEnvelope],
```

改为：

```python
        writer: EventWriter,
        writes: list[asyncio.Task[None]],
        events: list[EventEnvelope],
```

在 `backend/runs/manager.py` 中，把：

```python
        try:
            await asyncio.gather(*usage_writes)  # 前端收到结束事件后会查用量，此时须已写完
            await writer.finish(events)
```

改为：

```python
        try:
            # 前端收到结束事件后会查用量、下载产物，此时须已写完
            await asyncio.gather(*writes)
            await writer.finish(events)
```

在 `backend/runs/manager.py` 中，把：

```python

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
```

改为：

```python

    async def _record_file(self, run: RunRecord, event: FileCreated) -> None:
        """登记一个产物文件。写库失败不影响运行，只留日志（该文件暂时无法下载）。"""
        try:
            await self._files.record(
                run.thread_id,
                event.path,
                source="output",
                size=event.size,
                media_type=event.media_type,
            )
        except Exception:  # 后台任务边界：登记失败不能中断对话
            logger.exception("运行 %s 的产物 %s 登记失败", run.id, event.path)

    async def _publish(self, run_id: str, event: Event, *, seq: int) -> EventEnvelope:
```

在 `backend/api/deps.py` 中，把：

```python
from agents.main_agent.usage import UsageRepo
from backend.runs import RunManager, RunRepo
```

改为：

```python
from agents.main_agent.usage import UsageRepo
from agents.main_agent.workspace import WorkspaceFileRepo
from backend.runs import RunManager, RunRepo
```

在 `backend/api/deps.py` 中，把：

```python
    usage: UsageRepo
    manager: RunManager
```

改为：

```python
    usage: UsageRepo
    files: WorkspaceFileRepo
    manager: RunManager
```

在 `backend/api/deps.py` 中，把：

```python
    usage = UsageRepo(pool)
    manager = RunManager(
```

改为：

```python
    usage = UsageRepo(pool)
    files = WorkspaceFileRepo(pool)
    manager = RunManager(
```

在 `backend/api/deps.py` 中，把：

```python
        usage=usage,
        agent=agent,
```

改为：

```python
        usage=usage,
        files=files,
        agent=agent,
```

在 `backend/api/deps.py` 中，把：

```python
    return Services(
        settings=settings, agent=agent, threads=threads, runs=runs, usage=usage, manager=manager
    )
```

改为：

```python
    return Services(
        settings=settings,
        agent=agent,
        threads=threads,
        runs=runs,
        usage=usage,
        files=files,
        manager=manager,
    )
```

在 `backend/api/router.py` 中，把：

```python
"""接口路由：会话、运行（含推送）、用量、模型、健康检查。"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

改为：

```python
"""接口路由：会话、运行（含推送）、文件、用量、模型、健康检查。"""

from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

在 `backend/api/router.py` 中，把：

```python
from backend.threads import Thread, ThreadCreate, ThreadOrder, ThreadUpdate

```

改为：

```python
from backend.threads import Thread, ThreadCreate, ThreadOrder, ThreadUpdate
from common.errors import NotFoundError

```

在 `backend/api/router.py` 中，把：

```python

@api_router.post("/threads/{thread_id}/runs", status_code=status.HTTP_202_ACCEPTED)
```

改为：

```python

@api_router.get(
    "/threads/{thread_id}/files/{file_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def file_content(
    thread_id: UUID, file_id: UUID, services: ServicesDep, download: bool = False
) -> Response:
    """读取会话里的一个文件：默认在页面里直接显示，download=1 时作为附件下载。"""
    thread = await services.threads.get(thread_id)
    record = await services.files.get(file_id)
    if record.thread_id != thread.id:
        raise NotFoundError("文件不存在")
    try:
        content = await services.agent.workspace.read_file(thread.short_id, record.path)
    except FileNotFoundError:
        raise NotFoundError("文件已不存在") from None
    name = quote(PurePosixPath(record.path).name)
    disposition = "attachment" if download else "inline"
    return Response(
        content,
        media_type=record.media_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{name}",
            # 产物可能是智能体生成的 HTML / SVG：直接打开时禁止脚本执行，也不让浏览器按内容猜类型
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@api_router.post("/threads/{thread_id}/runs", status_code=status.HTTP_202_ACCEPTED)
```

- [ ] **步骤 6：重新生成前端类型，运行测试，确认通过**

接口与事件都改了，重新生成前端类型（`test_openapi.py` 会核对生成结果是否最新）：

运行：`make types`

运行：`uv run pytest agents/tests/test_main_agent.py backend/tests/test_openapi.py -q`

运行：`uv run pytest -m integration agents/tests/test_workspace_files.py backend/tests -q`

预期：全部通过（单元 24 个、集成 56 个）。

- [ ] **步骤 7：前端文件项**

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts

  it("用量事件记为用量项", () => {
```

改为：

```ts

  it("产物文件记为文件项；同一次运行里同一文件再次改动时原地更新", () => {
    const created = (seq: number, size: number): EventEnvelope => ({
      ...base,
      seq,
      type: "file.created",
      data: { path: "outputs/chart.png", size, media_type: "image/png", file_id: "f1" },
    });
    const state = [created(1, 10), events[3], created(3, 20)].reduce(applyEvent, emptyChat);
    expect(state.items).toEqual([
      {
        kind: "file",
        id: "file-r1-f1",
        fileId: "f1",
        path: "outputs/chart.png",
        size: 20,
        mediaType: "image/png",
      },
      { kind: "assistant", id: "msg-m1", text: "你" },
    ]);
  });

  it("用量事件记为用量项", () => {
```

运行：`cd frontend && pnpm exec vitest run src/features/chat`（预期失败）

预期：新测试失败（`file.created` 没有变成文件项）。

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  | { kind: "usage"; id: string; usage: UsageData }
  // 一轮运行的开始 / 结束时间（取自开始、结束事件），用于显示耗时
```

改为：

```ts
  | { kind: "usage"; id: string; usage: UsageData }
  // 智能体在 outputs/ 里生成的文件（产物），fileId 用于下载
  | { kind: "file"; id: string; fileId: string; path: string; size: number; mediaType: string }
  // 一轮运行的开始 / 结束时间（取自开始、结束事件），用于显示耗时
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
      ];
  }
```

改为：

```ts
      ];
    case "file.created": {
      const { file_id: fileId, path, size, media_type: mediaType } = event.data;
      if (!fileId) return items; // backend 推送前总会填上 ID；没有 ID 就无法下载，不显示
      // 同一次运行里同一文件只显示一张卡片，再次改动时原地更新
      const id = `file-${event.run_id}-${fileId}`;
      const file: ChatItem = { kind: "file", id, fileId, path, size, mediaType };
      return items.some((item) => item.id === id)
        ? items.map((item) => (item.id === id ? file : item))
        : [...items, file];
    }
  }
```

运行：`cd frontend && pnpm exec vitest run src/features/chat`

预期：全部通过（20 个）。

- [ ] **步骤 8：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 146 个、前端 66 个）；`make test-int` 全部通过（集成测试 63 个）。

---

### 任务 5：产物卡片与步骤"已中断"

**文件：**
- 新建：`frontend/src/components/chat/format.ts`、`format.test.ts`
- 修改：`frontend/src/api/client.ts`、`client.test.ts`、`frontend/src/components/chat/adapter.ts`、`adapter.test.ts`、`parts.tsx`、`ChatThread.tsx`、`frontend/src/features/chat/ChatView.tsx`

**接口：**
- 消费：任务 4 的文件项与下载接口。
- 产出：
  - `fileContentUrl(threadId, fileId, download: boolean) -> string`（`api/client.ts`）；
  - `formatSize(bytes) -> string`（`components/chat/format.ts`）；
  - `adapter.ts`：
    - `type FileUrl = (fileId: string, download: boolean) => string`；
    - `FileCardData { name, path, size, mediaType, url, downloadUrl }`；
    - `toThreadMessages(state, fileUrl)`（新增第二个参数）：文件项映射为数据片段 `data-file`；
    - `type StepState = "running" | "success" | "error" | "interrupted"`；
    - `stepState(result, isError, partStatus) -> StepState`、`itemState(status, active) -> StepState`；
  - `ChatThread` 新增必填属性 `fileUrl`，由 `ChatView` 按所在会话提供。

- [ ] **步骤 1：写失败的测试**

在 `frontend/src/api/client.test.ts` 中，把：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, needsAccessToken, readableError } from "./client";

```

改为：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  errorMessage,
  fileContentUrl,
  needsAccessToken,
  readableError,
} from "./client";

```

在 `frontend/src/api/client.test.ts` 末尾追加：

```ts

describe("fileContentUrl", () => {
  it("默认在页面里打开；download 为真时作为附件下载", () => {
    expect(fileContentUrl("t1", "f1", false)).toBe("/api/threads/t1/files/f1/content");
    expect(fileContentUrl("t1", "f1", true)).toBe("/api/threads/t1/files/f1/content?download=1");
  });
});
```

新建 `frontend/src/components/chat/format.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { formatSize } from "./format";

describe("文件大小的显示", () => {
  it("按 B / KB / MB / GB 换算，保留一位小数", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2048)).toBe("2.0 KB");
    expect(formatSize(3.5 * 1024 * 1024)).toBe("3.5 MB");
    expect(formatSize(1.25 * 1024 ** 3)).toBe("1.3 GB");
  });
});
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
import type { ChatState } from "../../features/chat/reducer";
import { SUBAGENT_TOOL, toThreadMessages } from "./adapter";

```

改为：

```ts
import type { ChatState } from "../../features/chat/reducer";
import { SUBAGENT_TOOL, itemState, stepState, toThreadMessages } from "./adapter";

const fileUrl = (fileId: string, download: boolean) => `/f/${fileId}${download ? "?d" : ""}`;

```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
  it("用户消息之间的工具调用与回答合并为一条助手消息，顺序不变", () => {
    const messages = toThreadMessages(finished);
    expect(messages.map((message) => message.role)).toEqual([
```

改为：

```ts
  it("用户消息之间的工具调用与回答合并为一条助手消息，顺序不变", () => {
    const messages = toThreadMessages(finished, fileUrl);
    expect(messages.map((message) => message.role)).toEqual([
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
  it("失败的运行映射为带错误原因的未完成消息", () => {
    expect(toThreadMessages(finished)[3]?.status).toEqual({
      type: "incomplete",
```

改为：

```ts
  it("失败的运行映射为带错误原因的未完成消息", () => {
    expect(toThreadMessages(finished, fileUrl)[3]?.status).toEqual({
      type: "incomplete",
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
    };
    expect(toThreadMessages(state)).toEqual([
      {
```

改为：

```ts
    };
    expect(toThreadMessages(state, fileUrl)).toEqual([
      {
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
    };
    const [, assistant] = toThreadMessages(running);
    expect(assistant?.status).toEqual({ type: "running" });
```

改为：

```ts
    };
    const [, assistant] = toThreadMessages(running, fileUrl);
    expect(assistant?.status).toEqual({ type: "running" });
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
  it("思考为思考片段，待办为数据片段，子智能体为带内部步骤的工具调用片段", () => {
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.content).toEqual([
```

改为：

```ts
  it("思考为思考片段，待办为数据片段，子智能体为带内部步骤的工具调用片段", () => {
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
  it("本轮用量合计包含子智能体的调用；未知费用不计入", () => {
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.metadata?.custom?.usage).toEqual({
```

改为：

```ts
  it("本轮用量合计包含子智能体的调用；未知费用不计入", () => {
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.metadata?.custom?.usage).toEqual({
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
    };
    const [, assistant] = toThreadMessages(stopped);
    expect(assistant?.status).toEqual({ type: "incomplete", reason: "cancelled" });
```

改为：

```ts
    };
    const [, assistant] = toThreadMessages(stopped, fileUrl);
    expect(assistant?.status).toEqual({ type: "incomplete", reason: "cancelled" });
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
    };
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.metadata?.custom).toEqual({
```

改为：

```ts
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.metadata?.custom).toEqual({
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
    };
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.content).toEqual([{ type: "text", text: "好" }]);
```

改为：

```ts
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([{ type: "text", text: "好" }]);
```

在 `frontend/src/components/chat/adapter.test.ts` 末尾追加：

```ts

describe("产物文件", () => {
  it("文件项映射为文件数据片段，带文件名与打开、下载地址", () => {
    const state: ChatState = {
      running: false,
      items: [
        { kind: "user", id: "u1", text: "画图" },
        {
          kind: "file",
          id: "file-r1-f1",
          fileId: "f1",
          path: "outputs/图表/chart.png",
          size: 20,
          mediaType: "image/png",
        },
      ],
    };
    const [, assistant] = toThreadMessages(state, fileUrl);
    expect(assistant?.content).toEqual([
      {
        type: "data-file",
        data: {
          name: "chart.png",
          path: "outputs/图表/chart.png",
          size: 20,
          mediaType: "image/png",
          url: "/f/f1",
          downloadUrl: "/f/f1?d",
        },
      },
    ]);
  });
});

describe("工具与子智能体步骤的显示状态", () => {
  it("有结果按结果显示；没有结果时，所在消息还在运行才算运行中，否则是被停止或失败打断的", () => {
    expect(stepState("ok", false, { type: "complete" })).toBe("success");
    expect(stepState("boom", true, { type: "complete" })).toBe("error");
    expect(stepState(undefined, undefined, { type: "running" })).toBe("running");
    expect(stepState(undefined, undefined, { type: "incomplete" })).toBe("interrupted");
  });

  it("子智能体内部的步骤：子智能体已不在运行时，未结束的步骤显示为已中断", () => {
    expect(itemState("running", true)).toBe("running");
    expect(itemState("running", false)).toBe("interrupted");
    expect(itemState("success", false)).toBe("success");
    expect(itemState("error", true)).toBe("error");
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/api/client.test.ts src/components/chat`（预期失败）

预期：`format.test.ts` 找不到 `./format`；`fileContentUrl is not a function`、`stepState is not a function`、`itemState is not a function`；文件项映射测试得到空数组。

- [ ] **步骤 3：实现**

在 `frontend/src/api/client.ts` 中，把：

```ts

export const api = {
```

改为：

```ts

/** 会话里一个文件的地址：默认在页面里打开，download 为真时作为附件下载。 */
export function fileContentUrl(threadId: string, fileId: string, download: boolean): string {
  const url = `/api/threads/${threadId}/files/${fileId}/content`;
  return download ? `${url}?download=1` : url;
}

export const api = {
```

新建 `frontend/src/components/chat/format.ts`：

```ts
const UNITS = ["KB", "MB", "GB"];

/** 文件大小：不足 1KB 显示字节数，否则换算成 KB / MB / GB，保留一位小数。 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`;
}
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts

/** 一轮回答的用量（含子智能体）：显示在回答下方，可展开每次调用明细。 */
```

改为：

```ts

/** 工具调用、子智能体这类步骤的显示状态。 */
export type StepState = "running" | "success" | "error" | "interrupted";

/**
 * 步骤片段的显示状态。没有结果时，assistant-ui 给的片段状态就是所在消息的状态：
 * 消息还在运行才算"运行中"，否则是被停止或运行失败打断的（不能一直转圈）。
 */
export function stepState(
  result: unknown,
  isError: boolean | undefined,
  partStatus: { type: string },
): StepState {
  if (result !== undefined) return isError ? "error" : "success";
  return partStatus.type === "running" ? "running" : "interrupted";
}

/** 子智能体内部步骤的显示状态：子智能体已不在运行（active 为假）时，未结束的步骤是被打断的。 */
export function itemState(status: "running" | "success" | "error", active: boolean): StepState {
  return status === "running" && !active ? "interrupted" : status;
}

/** 文件地址：由页面按所在会话提供（download 为真时作为附件下载）。 */
export type FileUrl = (fileId: string, download: boolean) => string;

/** 产物文件卡片的数据（数据片段 data-file）。 */
export interface FileCardData {
  name: string;
  path: string;
  size: number;
  mediaType: string;
  url: string;
  downloadUrl: string;
}

/** 一轮回答的用量（含子智能体）：显示在回答下方，可展开每次调用明细。 */
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
 */
export function toThreadMessages(state: ChatState): ThreadMessageLike[] {
  const groups: ChatItem[][] = [];
```

改为：

```ts
 */
export function toThreadMessages(state: ChatState, fileUrl: FileUrl): ThreadMessageLike[] {
  const groups: ChatItem[][] = [];
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
    }
    const parts = group.flatMap(toPart);
    const error = group.find((item) => item.kind === "error")?.text;
```

改为：

```ts
    }
    const parts = group.flatMap((item) => toPart(item, fileUrl));
    const error = group.find((item) => item.kind === "error")?.text;
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts

function toPart(item: ChatItem): AssistantPart[] {
  switch (item.kind) {
```

改为：

```ts

function toPart(item: ChatItem, fileUrl: FileUrl): AssistantPart[] {
  switch (item.kind) {
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
      return [{ type: "data-todos", data: item.todos }];
    default:
```

改为：

```ts
      return [{ type: "data-todos", data: item.todos }];
    case "file": {
      const data: FileCardData = {
        name: item.path.split("/").at(-1) ?? item.path,
        path: item.path,
        size: item.size,
        mediaType: item.mediaType,
        url: fileUrl(item.fileId, false),
        downloadUrl: fileUrl(item.fileId, true),
      };
      return [{ type: "data-file", data }];
    }
    default:
```

产物卡片：图片直接显示缩略图，其他文件显示名称与大小，都可在新标签页打开或下载。工具与子智能体卡片改用 `stepState`：没有结果、所在消息又已结束（停止或失败）时显示"已中断"；子智能体内部的步骤同理。

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  Copy,
  Gauge,
```

改为：

```tsx
  Copy,
  Download,
  ExternalLink,
  FileText,
  Gauge,
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
} from "lucide-react";
import { useEffect, useState } from "react";
import remarkGfm from "remark-gfm";
```

改为：

```tsx
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import remarkGfm from "remark-gfm";
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
} from "../../features/usage/format";
import { SUBAGENT_TOOL, type SubagentArtifact, type TurnUsage } from "./adapter";

```

改为：

```tsx
} from "../../features/usage/format";
import {
  SUBAGENT_TOOL,
  itemState,
  stepState,
  type FileCardData,
  type StepState,
  type SubagentArtifact,
  type TurnUsage,
} from "./adapter";
import { formatSize } from "./format";

```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

function StatusLabel({ done, isError }: { done: boolean; isError: boolean | undefined }) {
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">
      {!done && <LoaderCircle className="size-3.5 animate-spin" />}
      {done && isError && <TriangleAlert className="size-3.5 text-danger" />}
      {done && !isError && <Check className="size-3.5 text-success" />}
      {!done ? "运行中" : isError ? "出错" : "完成"}
    </span>
```

改为：

```tsx

const STEP_LABELS: Record<StepState, { icon: ReactNode; text: string }> = {
  running: { icon: <LoaderCircle className="size-3.5 animate-spin" />, text: "运行中" },
  success: { icon: <Check className="size-3.5 text-success" />, text: "完成" },
  error: { icon: <TriangleAlert className="size-3.5 text-danger" />, text: "出错" },
  interrupted: { icon: <CircleStop className="size-3.5" />, text: "已中断" },
};

function StatusLabel({ state }: { state: StepState }) {
  const { icon, text } = STEP_LABELS[state];
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 text-xs">
      {icon}
      {text}
    </span>
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
/** 工具调用卡片：默认折叠，展开后显示参数与结果。 */
export const ToolCard: ToolCallMessagePartComponent = ({ toolName, argsText, result, isError }) => {
  const done = result !== undefined;
  return (
```

改为：

```tsx
/** 工具调用卡片：默认折叠，展开后显示参数与结果。 */
export const ToolCard: ToolCallMessagePartComponent = ({
  toolName,
  argsText,
  result,
  isError,
  status,
}) => {
  const state = stepState(result, isError, status);
  return (
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
        <span className="font-mono text-foreground">{toolName}</span>
        <StatusLabel done={done} isError={isError} />
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        <pre className="overflow-x-auto font-mono text-xs text-muted-foreground">{argsText}</pre>
        {done && (
          <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap">
```

改为：

```tsx
        <span className="font-mono text-foreground">{toolName}</span>
        <StatusLabel state={state} />
      </summary>
      <div className="space-y-2 border-t border-border px-3 py-2">
        <pre className="overflow-x-auto font-mono text-xs text-muted-foreground">{argsText}</pre>
        {result !== undefined && (
          <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap">
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx

/** 子智能体内部步骤：回答原文、思考、工具调用，嵌套的子智能体递归显示。 */
function NestedItems({ items }: { items: ChatItem[] }) {
  return (
```

改为：

```tsx

/** 子智能体内部步骤：回答原文、思考、工具调用，嵌套的子智能体递归显示。active：子智能体仍在运行。 */
function NestedItems({ items, active }: { items: ChatItem[]; active: boolean }) {
  return (
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
                <span className="font-mono text-foreground">{item.name}</span>
                <StatusLabel done={item.status !== "running"} isError={item.status === "error"} />
              </p>
```

改为：

```tsx
                <span className="font-mono text-foreground">{item.name}</span>
                <StatusLabel state={itemState(item.status, active)} />
              </p>
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
                </p>
                <NestedItems items={item.items} />
              </div>
```

改为：

```tsx
                </p>
                <NestedItems items={item.items} active={active && item.status === "running"} />
              </div>
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
/** 子智能体卡片（设计文档 13.1：工具调用片段里的嵌套内容）：默认折叠，展开看它的每一步。 */
export const SubagentCard: ToolCallMessagePartComponent = ({ artifact, result, isError }) => {
  const subagent = artifact as SubagentArtifact;
  const done = result !== undefined;
  return (
```

改为：

```tsx
/** 子智能体卡片（设计文档 13.1：工具调用片段里的嵌套内容）：默认折叠，展开看它的每一步。 */
export const SubagentCard: ToolCallMessagePartComponent = ({
  artifact,
  result,
  isError,
  status,
}) => {
  const subagent = artifact as SubagentArtifact;
  const state = stepState(result, isError, status);
  return (
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
        <span className="truncate">{subagent.description}</span>
        <StatusLabel done={done} isError={isError} />
      </summary>
      <div className="space-y-3 border-t border-border px-3 py-2 text-xs">
        <NestedItems items={subagent.items} />
        {done && (
          <div className="border-t border-border pt-2">
```

改为：

```tsx
        <span className="truncate">{subagent.description}</span>
        <StatusLabel state={state} />
      </summary>
      <div className="space-y-3 border-t border-border px-3 py-2 text-xs">
        <NestedItems items={subagent.items} active={state === "running"} />
        {result !== undefined && (
          <div className="border-t border-border pt-2">
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
      </ul>
    </div>
```

改为：

```tsx
      </ul>
    </div>
  );
};

const LINK_BUTTON = "rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground";

/** 产物文件卡片：图片直接显示；其他文件显示名称与大小。都可以在新标签页打开或下载。 */
export const FilePart: DataMessagePartComponent = ({ data }) => {
  const file = data as FileCardData;
  return (
    <div className="my-2 max-w-md overflow-hidden rounded-lg border border-border bg-card text-sm">
      {file.mediaType.startsWith("image/") && (
        <a href={file.url} target="_blank" rel="noopener noreferrer">
          <img
            src={file.url}
            alt={file.name}
            loading="lazy"
            className="max-h-80 w-full bg-muted object-contain"
          />
        </a>
      )}
      <div className="flex items-center gap-2 px-3 py-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate" title={file.path}>
          {file.name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
        <span className="ml-auto flex shrink-0 gap-1">
          <a
            href={file.url}
            target="_blank"
            rel="noopener noreferrer"
            className={LINK_BUTTON}
            aria-label="打开"
            title="打开"
          >
            <ExternalLink className="size-3.5" />
          </a>
          <a
            href={file.downloadUrl}
            download={file.name}
            className={LINK_BUTTON}
            aria-label="下载"
            title="下载"
          >
            <Download className="size-3.5" />
          </a>
        </span>
      </div>
    </div>
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
        tools: { by_name: { [SUBAGENT_TOOL]: SubagentCard }, Fallback: ToolCard },
        data: { by_name: { todos: TodosPart } },
      }}
```

改为：

```tsx
        tools: { by_name: { [SUBAGENT_TOOL]: SubagentCard }, Fallback: ToolCard },
        data: { by_name: { todos: TodosPart, file: FilePart } },
      }}
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages } from "./adapter";
import { AssistantMessage, UserMessage } from "./parts";
```

改为：

```tsx
import type { ChatState } from "../../features/chat/reducer";
import { toThreadMessages, type FileUrl } from "./adapter";
import { AssistantMessage, UserMessage } from "./parts";
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  onCancel: () => Promise<void>;
}

/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({ state, notice, onDismissNotice, onSend, onCancel }: ChatThreadProps) {
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
  const messages = useMemo(() => toThreadMessages(state), [state]);
  const runtime = useExternalStoreRuntime({
```

改为：

```tsx
  onCancel: () => Promise<void>;
  /** 产物文件的打开 / 下载地址（由页面按所在会话提供）。 */
  fileUrl: FileUrl;
}

/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({
  state,
  notice,
  onDismissNotice,
  onSend,
  onCancel,
  fileUrl,
}: ChatThreadProps) {
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
  const messages = useMemo(() => toThreadMessages(state, fileUrl), [state, fileUrl]);
  const runtime = useExternalStoreRuntime({
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
```

改为：

```tsx
import { LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, fileContentUrl, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
  const stopWhenStarted = useRef(false);

```

改为：

```tsx
  const stopWhenStarted = useRef(false);
  const fileUrl = useCallback(
    (fileId: string, download: boolean) => fileContentUrl(thread.id, fileId, download),
    [thread.id],
  );

```

在 `frontend/src/features/chat/ChatView.tsx` 中，把：

```tsx
        onCancel={cancel}
      />
```

改为：

```tsx
        onCancel={cancel}
        fileUrl={fileUrl}
      />
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/api/client.test.ts src/components/chat`

预期：全部通过（25 个）。

- [ ] **步骤 5：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 146 个、前端 71 个）。

---

### 任务 6：文档收尾与端到端验证

**文件：**
- 修改：`docs/development/architecture.md`、`README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`

- [ ] **步骤 1：架构规范、README**

架构规范新增第 10 节"工作区、沙箱与产物"（原第 10 节"本机安全防护"顺延为第 11 节）：

在 `docs/development/architecture.md` 中，把：

```markdown

## 10. 本机安全防护（设计文档 12.2）

```

改为：

````markdown

## 10. 工作区、沙箱与产物（设计文档第 9 节）

```
智能体读写文件 → 工作区（agents/main_agent/workspace/local.py）直接读写 workdata/workspace/<会话短 ID>/
智能体执行命令 → HttpSandbox → 沙箱容器的执行服务（deploy/sandbox/sandbox_service.py）
                 → 在 /workspace/<会话短 ID>/ 下用 bash 运行（两个容器挂载同一个目录）
写文件或执行命令之后 → 检查 outputs/ 的新增或改动 → file.created 事件 → 产物卡片
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/workspace/base.py` | 替换点：`Workspace`（文件后端、列出产物、读文件、删除会话目录）与 `Sandbox`（执行命令）；契约测试在 `agents/tests/contracts/test_workspace_contract.py` |
| `agents/main_agent/workspace/local.py` | 本地实现：deepagents 本地文件后端加上"只能访问本会话目录"的限制与执行命令能力 |
| `agents/main_agent/workspace/sandbox_http.py` | 沙箱客户端：带内部密钥调用执行服务；沙箱不可用时把原因作为命令输出交给智能体 |
| `agents/main_agent/workspace/files.py` | `workspace_files` 表：登记上传与产物；文件 ID 由会话 ID 与路径算出（同一文件始终同一个 ID） |
| `agents/main_agent/runtime/files.py` | 智能体看到的文件树：`/workspace/`（工作区）、`/skills/`（技能，只读）、`/.agent/`（大段工具输出的转存，存在对话存档里） |
| `deploy/sandbox/` | 沙箱镜像：执行服务、预装库的锁定文件（`make sandbox-lock` 生成）、中文字体配置 |
| `agents/skills/`、`agents/subagents/` | 智能体技能（每个技能一个目录，内含 `SKILL.md`）与子智能体定义（每个一个 `.md`，开头 YAML 写名称与说明，正文是提示词；不写 `model` 时跟随主对话所选模型） |

约定：
1. **会话隔离**：会话短 ID 从运行上下文（`AgentContext`）取得，子智能体继承同一上下文。越界访问抛 `PermissionError`——deepagents 只把 `OSError` / `RuntimeError` 转成工具错误，抛别的异常会让整次运行失败。
2. **停止**：智能体的执行请求被取消时，HTTP 连接随之断开；执行服务每 0.2 秒检查一次连接，发现断开就杀掉整个进程组。
3. **产物**：只看 `outputs/`。backend 收到 `file.created` 时直接算出文件 ID 填进事件再推送，登记在后台完成（处理事件的循环里不能有真正的等待，见第 9 节约定 2）；收尾时等登记写完再推送结束事件，前端收到后即可下载。
4. **下载**：先核对文件属于该会话（不属于时返回 404），再按登记的路径读取；响应带 `Content-Security-Policy: sandbox` 与 `X-Content-Type-Options: nosniff`，智能体生成的 HTML / SVG 直接打开时不执行脚本。
5. **改了沙箱**：`deploy/sandbox/` 下的执行服务或依赖改了以后运行 `make build`；改依赖先改 `requirements.in` 再运行 `make sandbox-lock`。

## 11. 本机安全防护（设计文档 12.2）

````

在 `README.md` 中，把：

```markdown

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

改为：

```markdown

智能体执行的代码在单独的沙箱容器里运行（不能上外网），每个会话的文件在 `workdata/workspace/<会话短 ID>/`，生成的文件放在其中的 `outputs/`，对话里会显示可打开、下载的卡片。沙箱与后端之间的内部密钥 `SANDBOX_SECRET` 由 `make` 命令首次运行时自动写进 `.env`，无需手动填写。

`make up` 只在第一次（还没有镜像时）构建镜像，之后直接启动。改了东西后：
```

在 `README.md` 中，把：

```markdown
| 依赖（`pyproject.toml`、`uv.lock`、`frontend/package.json`、`pnpm-lock.yaml`）、前端界面、`deploy/backend.Dockerfile` | `make build`（重新构建镜像；依赖从本机构建缓存安装，不重新下载） |

```

改为：

```markdown
| 依赖（`pyproject.toml`、`uv.lock`、`frontend/package.json`、`pnpm-lock.yaml`）、前端界面、`deploy/backend.Dockerfile` | `make build`（重新构建镜像；依赖从本机构建缓存安装，不重新下载） |
| 沙箱的执行服务或预装库（`deploy/sandbox/`） | 改预装库先改 `requirements.in` 再运行 `make sandbox-lock`；然后 `make build` |

```

- [ ] **步骤 2：需求池与变更记录**

需求池：R05 拆成 R05a（本计划，完成）与 R05b（M2b，计划）；新增 R15（设计文档 9.2 里本期没做的两项可选能力）：

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R04c | 本机安全防护（含可选访问令牌）、前端类型自动生成、决策记录 D1～D15、M1a / M1b / 体验优化遗留小问题、运行进行中刷新不重复显示 | M1c | 高 | 完成 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
```

改为：

```markdown
| R04c | 本机安全防护（含可选访问令牌）、前端类型自动生成、决策记录 D1～D15、M1a / M1b / 体验优化遗留小问题、运行进行中刷新不重复显示 | M1c | 高 | 完成 |
| R05a | 沙箱镜像与执行服务、每个会话隔离的工作目录、执行代码（停止时连同子进程结束）、智能体技能与数据分析员子智能体、产物检测与产物卡片（可打开 / 下载）、删除会话时清理工作目录 | M2a | 高 | 完成 |
| R05b | 文件上传、右侧文件面板、预览（图片 / CSV / Excel / PDF / Markdown / HTML）、图片发给能看图的模型 | M2b | 高 | 计划 |
| R06 | 统一知识库（文档 + 记忆 + 常驻条目） | M3 | 高 | 计划 |
```

在 `docs/requirements/backlog.md` 末尾追加：

```markdown
| R15 | 沙箱的可选能力（设计文档 9.2）：配置开关允许联网（如 `pip install`）；带 LibreOffice 的镜像变体（文档格式互转） | 待定 | 低 | 待定 |
```

在 `docs/changelog.md` 中，把：

```markdown
## 未发布

```

改为：

```markdown
## 未发布

### M2a 沙箱与代码执行（完成）

- 新增：沙箱（设计文档 9.1、9.2）——智能体可以执行命令和 Python 代码（`execute` 工具）。命令在独立的沙箱容器里运行：非 root、根文件系统只读、只接入内部专用网络（不能上外网）、2 核 CPU / 2GB 内存 / 256 个进程上限；默认 120 秒超时（最长 600 秒），超时或点"停止"时连同它派生的子进程一起结束；输出超过 3 万字符时只返回开头一段，完整输出写进会话目录的 `logs/`。预装 pandas、numpy、matplotlib、seaborn（含中文字体，图表里的中文不再是方框）、openpyxl、python-docx、python-pptx、pymupdf、pillow。沙箱与后端之间用内部密钥认证（`.env` 的 `SANDBOX_SECRET`，`make` 命令首次运行时自动生成）。
- 新增：每个会话一个工作目录 `workdata/workspace/<会话短 ID>/`，智能体只能读写自己会话的目录（越界时工具报错，不会中断对话）；大段工具输出的转存放在对话存档里，不写进工作目录。删除会话时工作目录一并删除。
- 新增：智能体技能（`agents/skills/`，首个技能：Excel / CSV 处理规范）与数据分析员子智能体（`agents/subagents/data_analyst.md`，跟随主对话所选模型）；新增技能、子智能体只需加文件。
- 新增：产物——智能体在 `outputs/` 里新建或改动的文件在对话里显示为卡片（图片直接显示），可在新标签页打开或下载（`GET /api/threads/{id}/files/{文件 ID}/content`，`?download=1` 为下载）。直接打开智能体生成的 HTML / SVG 时不执行其中的脚本。产物记入 `workspace_files` 表（迁移 0005）。
- 修复：停止或运行失败后，没有结束的工具调用、子智能体（及其内部步骤）一直显示"运行中"——现在显示"已中断"。

```

- [ ] **步骤 3：浏览器端到端验证**

先运行 `make build`（新增了 Python 依赖、前端也改了，要重新构建 backend 与沙箱镜像；沙箱镜像如已构建会直接用缓存），再打开 http://127.0.0.1:8000。以下会调用真实模型，费用约 0.3 美元；第 5、6 步可选 `gemini-3.5-flash` 省钱。

1. **画图**：新建会话，发送"用 Python 画一张柱状图：一月 120、二月 98、三月 150，标题'一季度销售额'，保存到 outputs/sales.png。"
   - 依次出现 `write_file`、`execute` 工具卡片；回答中出现产物卡片，直接显示图片，卡片下方是 `sales.png` 与大小；
   - 图里的中文（标题、月份）正常显示，不是方框。
2. **刷新、打开、下载**：
   - 刷新页面、重新打开该会话，产物卡片与图片仍在；
   - 点卡片右侧"打开"，新标签页显示图片；点"下载"，保存为 `sales.png`；
   - 终端运行 `curl -sI "http://127.0.0.1:8000$(<在页面里复制的打开地址>)"`（或在浏览器开发者工具的网络面板查看），响应头有 `content-security-policy: sandbox` 与 `x-content-type-options: nosniff`。
3. **停止正在执行的命令**：
   - 发送"用 execute 工具原样执行这条命令（不要改写）：sleep 120 & sleep 121; echo 完成"；
   - `execute` 卡片显示"运行中"后，点停止：回答下方显示"已停止"，`execute` 卡片显示"已中断"（不再转圈）；
   - 终端运行 `podman exec open-personal-agent-sandbox-1 sh -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline; echo; done' | grep sleep`（用 docker 的把 `podman` 换成 `docker`），没有任何输出（两个 sleep 都已结束）。
4. **断网**：发送"用 execute 运行：python -c \"import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)\""，命令输出是连接失败类的报错（如 `URLError`），智能体说明无法联网。
5. **数据分析员**：新建会话，发送"请派数据分析员来做：生成一个 12 行的示例销售表（日期、地区、金额，地区只有华东、华南、华北），保存为 outputs/sales.xlsx；再按地区汇总金额，画饼图保存为 outputs/region.png，告诉我各地区合计。"
   - 出现 `data_analyst` 子智能体卡片（展开可看它的每一步）；
   - 出现 `region.png`（饼图，中文正常）与 `sales.xlsx` 两张产物卡片；
   - 下载 `sales.xlsx`，能用 Excel / Numbers 打开，有 12 行数据；回答里的各地区合计与表格一致。
6. **越界访问**：在同一会话发送"用 ls 工具列出 /workspace/ 目录"，工具结果是"只能访问本会话的工作目录 /workspace/c_…/"，智能体照常回答（运行没有失败）。
7. **删除会话**：
   - 运行 `ls workdata/workspace`，记下目录；
   - 在左侧删除第 5 步的会话，再运行一次：少了该会话的目录（目录名是会话短 ID，可用 `curl -s http://127.0.0.1:8000/api/threads` 对照 `short_id`）。

预期：以上全部符合描述。

- [ ] **步骤 4：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 146 个、前端 71 个）；`make test-int` 全部通过（集成测试 63 个）。

收尾：
- 全部通过后，`docs/changelog.md` 的 M2a 小节保持"（完成）"、`docs/requirements/backlog.md` 的 R05a 保持"完成"；
- 若浏览器验证有未通过项，两处改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖**（第 21 节 M2 行，按 M2a / M2b 拆分）：
  - 沙箱镜像与执行服务 → 任务 1；工作区实现 → 任务 2、3；
  - 产物检测 → 任务 4；下载 → 任务 4、5；上传与预览 → M2b（R05b）；
  - 数据分析员子智能体、智能体技能 → 任务 3；待办清单 → M1b 已完成。
  - 9.2 节安全边界逐条：
    - 不能上外网（内部专用网络）、降权运行（uid 1000、根文件系统只读、`/tmp` 内存盘）、资源上限（2 核、2GB、256 个进程）→ 任务 1 的 compose；
    - 命令超时 120 秒并杀掉整个进程组、输出截断、内部认证 → 任务 1 的执行服务；
    - 预装库与中文字体 → 任务 1 的镜像。
  - 9.3 节：产物推送 `file.created` 与产物卡片 → 任务 4、5；记入 `workspace_files`、删除会话时连同目录删除 → 任务 3、4；下载防越界 → 任务 2（`read_file` 拒绝会话目录外的路径）与任务 4（按登记的文件 ID 下载，不接受路径参数）。
- **与设计文档的差异：**
  1. 9.1 节写"实现 `execute()`"：改为实现异步的 `aexecute()`，同步版本直接报错。执行服务是异步的，而且停止要能一路取消到 HTTP 请求。
  2. 9.2 节"超过 30KB 的输出写入文件"：按字符计（3 万字符），返回给智能体的本来就是文字；完整输出写在会话目录的 `logs/`。
  3. 9.2 节"可在配置中开启联网"与"LibreOffice 可选镜像变体"本期不做，登记为 R15。
  4. 超长工具结果的转存放进对话存档（`/.agent/`），不落进用户的工作目录（设计文档没有规定）：用户的目录里只有自己和智能体有意生成的文件，删除会话时随对话存档一起删除。
  5. 端到端验证时发现 M1b 起就有的问题：停止后没有结束的工具卡片一直转圈。因为本期的命令可能运行很久，这个问题会经常出现，所以在任务 5 一并修好。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：** 已用严格类型检查、mypy 与重放验证。
  - `AgentContext` 在工作区、文件树中间件、主智能体里一致；
  - `thread_short_id` 在 `MainAgent.run` / `delete_thread`、`RunManager` 里一致；
  - `FileCreated` 的字段在事件定义、生成的类型、事件处理器、转换函数里一致；
  - `toThreadMessages(state, fileUrl)` 的两个调用处（`ChatThread`、测试）一致。
