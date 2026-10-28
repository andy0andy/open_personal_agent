# M1c 安全与稳固 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。

**目标：** 补上 M1 的最后一块。

- 本机安全防护：只接受本机主机名与本项目前端，并提供可选的访问令牌；可选的局域网访问（必须同时设置访问令牌）。
- 前端类型改为从后端自动生成，忘了生成时 `make check` 会报错。
- 决策记录 D01～D15 逐条成文。
- 收掉 M1a、M1b 与"体验优化"三次审查留下的小问题：
  - 停止、续传、用量、会话列表各处的边角问题；
  - 写计划时新发现的两个缺陷：运行中刷新文字重复；并行子智能体刷新后丢字。

**架构：**

- **安全防护**：backend 新增一个 ASGI 中间件 `backend/security.py`（在请求进入路由之前检查每个请求）：
  - 主机名、来源、POST 内容类型和可选令牌四项检查，策略来自 `config/app.yaml` 与 `.env`；
  - 局域网访问：`config/app.yaml` 的允许主机名支持网段（默认三个私有网段）；compose 按 `.env` 的 `LISTEN_ADDRESS` 绑定端口，对局域网开放时必须设置令牌，否则服务拒绝启动；
  - 令牌通过只供服务器读取的 Cookie 携带，前端遇到 401 显示令牌页。
- **类型生成**：`backend/openapi.py` 导出 FastAPI 的接口文档，并把 agents 的事件定义以 `AgentEvent` 并入。
  - `openapi-typescript` 由此生成 `frontend/src/api/generated/schema.d.ts`；`types.ts` 只起别名。
  - 两道核对保证生成结果不过期：pytest 核对 openapi.json 与当前代码一致，`pnpm types:check` 核对 d.ts 与 openapi.json 一致。
- **小问题**：按归属分在后端（运行管理、合并、跟踪器）、前端（事件处理器、对话区、会话列表）、工具（Makefile、测试夹具）三处修。

**技术栈：** 新增一个前端开发依赖 `openapi-typescript@7.13.0`（只在生成类型时用，不进打包结果）。用到的现有能力：

- Starlette 纯 ASGI 中间件；
- pydantic `json_schema_serialization_defaults_required`（导出类型时把有默认值的字段标为必有）；
- TanStack Query 的 `cancelQueries` / `isMutating`；
- Tailwind 4.3 的 `@source not`；
- Alembic `command.downgrade/upgrade`（迁移测试）。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）：

- 第 3 节（决策 D1～D16）、10.4 节（续传）、12.2 节（本机安全防护）；
- 第 13 节（前端，"前端类型自动生成"在 10.3 节末与 12.2 节末）；
- 第 21 节 M1 行。

M1 拆成三份：M1a、M1b 已完成，**M1c 是最后一份**。

> 本计划的全部代码在写计划时已于临时目录实际运行验证（`make check`、集成测试全部通过，数量见各任务检查点）。界面交互（令牌页之外的操作菜单键盘与贴边、发送失败提示、发送未返回时点停止、复制按钮聚焦、侧栏提示自动消失）已在浏览器中验证。计划中的每段代码由脚本从验证过的文件直接嵌入，并已从改动前的项目出发按本计划逐任务重放、逐字核对。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。
- 只新增一个依赖：前端开发依赖 `openapi-typescript`，版本写死 `7.13.0`（`pnpm add -D -E`）。Python 不加依赖。
- 第三方服务一律由 `deploy/docker-compose.yml` 管理（D13）；密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。
- 表结构与已存数据的变更用 Alembic、一律写原生 SQL，文件名带归属模块前缀。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- `frontend/src/api/generated/` 下的文件只由 `make types` 生成，不手改。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 直接运行 Python 测试时要有环境变量 `LITELLM_LOCAL_MODEL_COST_MAP=True`、`LANGGRAPH_STRICT_MSGPACK=true`（Makefile 与根目录 `conftest.py` 已设置）。集成测试先 `make test-up`。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **用别的地址访问**：
   - 局域网 IP（私有网段内）→ 放行，从该地址打开的页面能正常发消息；
   - 其他主机名、公网 IP → 400 和可读的"不允许的主机名"，文档说明在 `config/app.yaml` 补上；
   - 端口对局域网开放却没设置令牌 → 服务拒绝启动并说明原因。
   - 测试：任务 1 `test_accepts_lan_ips_in_configured_networks`、`test_same_origin_writes_are_accepted`、`test_lan_listening_requires_access_token`、`test_rejects_other_host_names_even_for_pages`，任务 9 浏览器验证第 2 步。
2. **设置了访问令牌后，已打开的旧页面或新浏览器**：接口返回 401 时，页面应切到令牌页，而不是一片报错；令牌正确后恢复正常，推送也能连上。测试：任务 1 `test_login_sets_cookie_that_unlocks_api`、前端 `needsAccessToken`、任务 9 浏览器验证第 2 步。
3. **运行进行中刷新页面、断线重连** → 文字不重复、不丢。测试：任务 3 `test_subscribe_after_events_already_shown`、`test_parallel_subagents_each_keep_their_full_text`，任务 4 `activeRun` 各测试，任务 9 浏览器验证第 3 步。
4. **停止的时机落在各种缝隙里**：发送请求还没返回、刚写完一次用量、停止后紧接着服务停止。期望是都能停下，已输出的内容进对话存档，会话不被卡住。测试：
   - 任务 3 `test_cancel_while_recording_usage_keeps_the_answer`、`test_cancel_all_does_not_interrupt_a_run_already_stopping`、`test_cancel_run_that_is_not_executing_ends_its_stream`；
   - 任务 9 浏览器验证第 4 步。
5. **升级后打开以前的会话**（M1b 之前存的结束事件没有 `usage`，体验优化时存的带 `interrupted`）：照常显示，"被中断的调用"估算仍在。测试：任务 5 `test_finished_events_use_interrupted_usage`、任务 9 浏览器验证第 5 步。

## 先行探测结论（2026-10-14 写计划时实测）

| 问题 | 结论 |
|---|---|
| `LANGGRAPH_STRICT_MSGPACK=true` 是否影响现有对话存档 | 不影响：开启后全部单元与集成测试通过（存档里只有 LangChain 消息等已登记类型） |
| openapi-typescript 能否用于本项目 | 7.13.0 可用（对 TypeScript 6 只有对等依赖提示，不影响）；`--check` 能发现生成文件过期 |
| 有默认值的字段生成后是"可能没有" | pydantic 默认不把有默认值的字段列为必有；`default_factory` 的字段（如 `agent_path`、`ts`）以及 FastAPI 去掉了 `null` 默认值的字段都会变成可选。给输出模型设 `json_schema_serialization_defaults_required=True` 后全部为必有 |
| FastAPI 与事件定义里同名的类型 | `UsageTotals` 两边都有：FastAPI 导出时去掉了 `default: null`，事件定义里保留，其余相同——合并时比较"去掉默认值后是否相同"，不同则报错 |
| `pnpm pkg set` 能否加 `types:check` 脚本 | 不能（属性路径不允许冒号）：改为 `pnpm add` 之后按编辑块修改 `package.json` |
| Tailwind 是否扫描测试文件 | 会：颜色检查测试里的反例（`bg-[red]` 等）会生成进打包的 CSS。用 `@source not "./**/*.test.ts"` 排除后打包里不再出现 |
| 没有 `.env` 时 compose 能否只启动测试数据库 | 不能：compose 对整个文件求值，`${LITELLM_MASTER_KEY:?…}` 直接报错；`.env.example` 自带占位密钥，复制后即可。改为 Makefile 先检查 `.env` 并给出明确提示 |
| 局域网访问需要改什么 | 只改 `config/app.yaml` 不够：后端端口在 compose 里绑定 `127.0.0.1`，局域网连不上。改为 `"${LISTEN_ADDRESS:-127.0.0.1}:8000:8000"` 后，compose 展开为 `host_ip: 127.0.0.1`（默认）或 `0.0.0.0`（`.env` 设置时），与预期一致 |
| 运行中刷新是否会重复显示 | 会（新发现）：页面用界面历史重建了已存部分，推送却从第 1 个事件开始重放，逐字片段被追加两遍 |
| 并行子智能体的历史是否完整 | 不完整（新发现）：合并逐字片段时只合并相邻的，两个子智能体交错输出时各自被切成多段、每段都标"全文"，刷新后只剩最后一段 |
| 后台写用量的顺序 | 并发写入会让后一条先落库（调用明细按写入时间排列）：改为同一运行按调用顺序依次写 |

## 文件结构（本计划涉及）

```
backend/
├── security.py                    # 新：本机安全防护中间件与令牌登录接口（含局域网访问规则）
├── openapi.py                     # 新：导出接口文档（并入事件定义），供 make types 使用
├── main.py                        # 改：挂上安全中间件与令牌接口
├── frontend.py                    # 改：不存在的接口任何方法都是 404
├── api/router.py                  # 改：推送接口支持 after 参数
├── runs/manager.py                # 改：用量后台按序写入；停止没有后台任务的运行时补结束事件；字段改名
├── runs/compaction.py             # 改：按智能体合并、带到此为止的全文
├── runs/schemas.py                # 改：运行状态改为固定取值
├── runtime/run_control.py         # 改：全部取消也只取消一次
├── runtime/envelope.py            # 改：导出类型时 ts 为必有
├── threads/schemas.py             # 改：排序拒绝重复 ID
└── migrations/versions/0004_backend_interrupted_usage.py   # 新：结束事件字段改名、补齐
agents/main_agent/
├── runtime/events.py              # 改：输出模型字段必有；interrupted → interrupted_usage
├── runtime/tracker.py             # 改：按实际平均输入价格估算；估算失败只提示一次
├── runtime/agent.py               # 改：校准值类型
└── models/base.py                 # 改：ModelInfo 字段必有
config/settings.py、config/app.yaml   # 改：security 配置、access_token
conftest.py                        # 改：严格反序列化；alembic_config 夹具
Makefile、deploy/*、.env.example    # 改：严格反序列化、ACCESS_TOKEN、make types、.env 检查
frontend/
├── package.json、pnpm-lock.yaml、.prettierignore、eslint.config.js   # 改：类型生成
└── src/
    ├── api/generated/             # 新：make types 生成（不手改）
    ├── api/types.ts               # 改：只给生成的类型起别名
    ├── api/client.ts、queries.ts、events.ts   # 改：ApiError、令牌、after 订阅、重试
    ├── features/auth/AccessTokenGate.tsx      # 新：令牌页
    ├── features/chat/reducer.ts、ChatView.tsx # 改：activeRun、按 ID 合并、提示、停止、重新同步
    ├── features/threads/          # 改：排序、菜单键盘与贴边、提示自动消失
    ├── components/chat/           # 改：提示条、恢复原文、复制按钮、缓存转换、字段改名
    └── index.css、styles/、themes/            # 改：不扫描测试文件、颜色检查、存储键守护
docs/decisions/D01～D15            # 新：决策记录
docs/                              # 改：架构、编码、测试规范，README、CLAUDE.md，需求池，变更记录
```

---

### 任务 1：本机安全防护

**文件：**
- 新建：`backend/security.py`、`backend/tests/test_security.py`、`frontend/src/features/auth/AccessTokenGate.tsx`
- 修改：`config/settings.py`、`config/app.yaml`、`backend/main.py`、`backend/tests/conftest.py`、`backend/tests/test_frontend.py`、`conftest.py`、`Makefile`、`deploy/backend.Dockerfile`、`deploy/docker-compose.yml`、`.env.example`、`frontend/src/api/client.ts`、`client.test.ts`、`queries.ts`、`queries.test.ts`、`frontend/src/layout/AppShell.tsx`、`docs/development/architecture.md`、`README.md`

**接口：**
- 产出（backend）：
  - `SecurityPolicy(allowed_hosts, allowed_networks, allowed_origins, access_token)`，带 `.from_settings(settings)`：配置里带"/"的条目解析为网段；`listen_address` 不是本机地址而令牌为空时抛 `ValueError`（服务启动失败）；
  - `rejection(policy, scope) -> tuple[int, str] | None`；
  - 中间件 `SecurityMiddleware`，策略从 `app.state.security` 读取，没有时用默认值；
  - 接口 `POST /api/auth/token`（请求体 `{"token": str}`，正确时写入 Cookie `opa_token`，返回 204）；
  - `TOKEN_COOKIE = "opa_token"`。
- 产出（config）：`SecurityConfig(allowed_hosts: list[str], allowed_origins: list[str])`（`allowed_hosts` 默认含 `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`）；`Settings.security`、`Settings.access_token: SecretStr | None`、`Settings.listen_address: str = "127.0.0.1"`（`.env` 的 `LISTEN_ADDRESS`）。
- 产出（前端）：
  - `ApiError(status, message)`：非 2xx 响应一律抛它；
  - `needsAccessToken(error) -> boolean`；
  - `api.login(token)`；
  - `threadsQuery` / `modelsQuery` 带 `retry: 0`；`retryWhileFailing` 遇到 401 不重试。
- 规则（按顺序检查，第一项不通过即返回）：
  - Host 既不在允许的主机名里、也不是允许网段里的 IP → 400"不允许的主机名"，前端页面也一样；
  - 以下只针对 `/api` 下的路径：
    - 写操作带了 Origin，且既不与请求地址同源（`scheme://Host`）、也不在允许列表 → 403"不允许的来源"；
    - POST 不是 JSON → 415"只接受 JSON 请求"；
    - 配置了令牌而请求没带对（Cookie 或 `Authorization: Bearer`）→ 401"需要访问令牌"；`/api/health` 与 `/api/auth/token` 不需要令牌。
- 约定：测试客户端地址一律用 `http://localhost`。

- [ ] **步骤 1：写失败的后端测试**

新建 `backend/tests/test_security.py`：

```python
from ipaddress import ip_network
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.types import Scope

from backend.main import create_app
from backend.security import TOKEN_COOKIE, SecurityPolicy, rejection
from config import Settings
from config.settings import AgentConfig

JSON = {"content-type": "application/json"}


def _scope(
    path: str = "/api/threads", method: str = "GET", headers: dict[str, str] | None = None
) -> Scope:
    merged = {"host": "localhost:8000", **(headers or {})}
    return {
        "type": "http",
        "path": path,
        "method": method,
        "headers": [(k.lower().encode(), v.encode()) for k, v in merged.items()],
    }


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:5173"])
def test_accepts_local_host_names(host: str) -> None:
    assert rejection(SecurityPolicy(), _scope(headers={"host": host})) is None


@pytest.mark.parametrize("host", ["evil.example:8000", "", "localhost.evil.example"])
def test_rejects_other_host_names_even_for_pages(host: str) -> None:
    """DNS 重绑定：恶意域名解析到 127.0.0.1 后，请求头里的主机名仍是那个域名。"""
    for path in ("/api/threads", "/", "/assets/app.js"):
        assert rejection(SecurityPolicy(), _scope(path, headers={"host": host})) == (
            400,
            "不允许的主机名",
        )


def test_accepts_bracketed_ipv6_when_configured() -> None:
    policy = SecurityPolicy(allowed_hosts=frozenset({"::1"}))
    assert rejection(policy, _scope(headers={"host": "[::1]:8000"})) is None


LAN = SecurityPolicy(
    allowed_hosts=frozenset({"localhost", "127.0.0.1"}),
    allowed_networks=(ip_network("10.0.0.0/8"), ip_network("192.168.0.0/16")),
)


def test_accepts_lan_ips_in_configured_networks() -> None:
    """局域网访问：Host 是允许网段里的 IP 即可（电脑换了局域网 IP 也不用改配置）。"""
    for host in ("10.2.32.237:8000", "192.168.1.5"):
        assert rejection(LAN, _scope(headers={"host": host})) is None
    for host in ("8.8.8.8:8000", "10.2.32.237.evil.example", "172.16.0.1"):
        assert rejection(LAN, _scope(headers={"host": host})) == (400, "不允许的主机名")


def test_same_origin_writes_are_accepted() -> None:
    """从局域网地址打开的页面发消息：来源与请求地址相同，放行；局域网里别的设备上的网页不行。"""
    headers = {"host": "10.2.32.237:8000", **JSON}
    own = _scope(method="POST", headers={**headers, "origin": "http://10.2.32.237:8000"})
    other = _scope(method="POST", headers={**headers, "origin": "http://10.2.32.99:8000"})
    assert rejection(LAN, own) is None
    assert rejection(LAN, other) == (403, "不允许的来源")


def test_rejects_writes_from_other_origins() -> None:
    scope = _scope(method="DELETE", headers={"origin": "https://evil.example"})
    assert rejection(SecurityPolicy(), scope) == (403, "不允许的来源")


def test_accepts_writes_from_own_frontend_or_without_origin() -> None:
    own = _scope(method="POST", headers={"origin": "http://localhost:5173", **JSON})
    no_origin = _scope(method="POST", headers=JSON)  # 命令行工具（curl 等）不带 Origin
    assert rejection(SecurityPolicy(), own) is None
    assert rejection(SecurityPolicy(), no_origin) is None


def test_reads_are_not_origin_checked() -> None:
    """读操作的结果跨站网页本来就读不到（浏览器同源策略），无需检查来源。"""
    scope = _scope(headers={"origin": "https://evil.example"})
    assert rejection(SecurityPolicy(), scope) is None


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_post_must_be_json(content_type: str | None) -> None:
    """表单和纯文本是跨站网页不经预检就能发出的"简单请求"，一律拒绝。"""
    headers = {"content-type": content_type} if content_type else {}
    scope = _scope(method="POST", headers=headers)
    assert rejection(SecurityPolicy(), scope) == (415, "只接受 JSON 请求")


def test_post_json_with_charset_is_accepted() -> None:
    scope = _scope(method="POST", headers={"content-type": "application/json; charset=utf-8"})
    assert rejection(SecurityPolicy(), scope) is None


def test_token_is_not_needed_when_not_configured() -> None:
    assert rejection(SecurityPolicy(), _scope()) is None


def test_token_required_when_configured() -> None:
    policy = SecurityPolicy(access_token="s3cret")
    assert rejection(policy, _scope()) == (401, "需要访问令牌")
    wrong = _scope(headers={"authorization": "Bearer nope"})
    assert rejection(policy, wrong) == (401, "需要访问令牌")


def test_token_accepted_from_cookie_or_bearer() -> None:
    policy = SecurityPolicy(access_token="s3cret")
    cookie = _scope(headers={"cookie": f"other=1; {TOKEN_COOKIE}=s3cret"})
    bearer = _scope(headers={"authorization": "Bearer s3cret"})
    assert rejection(policy, cookie) is None
    assert rejection(policy, bearer) is None


def test_health_login_and_pages_do_not_need_token() -> None:
    """令牌页本身、健康检查不需要令牌，否则浏览器连令牌页都打不开。"""
    policy = SecurityPolicy(access_token="s3cret")
    for path in ("/api/health", "/", "/threads/abc", "/assets/app.js"):
        assert rejection(policy, _scope(path)) is None
    login = _scope("/api/auth/token", method="POST", headers=JSON)
    assert rejection(policy, login) is None


def _client(
    tmp_path: Path, policy: SecurityPolicy | None = None, host: str = "localhost"
) -> TestClient:
    (tmp_path / "index.html").write_text("<html>首页</html>", encoding="utf-8")
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path)
    if policy is not None:
        app.state.security = policy
    return TestClient(app, base_url=f"http://{host}")


def test_middleware_rejects_with_readable_json(tmp_path: Path) -> None:
    with _client(tmp_path, host="evil.example") as client:
        response = client.get("/api/health")
        assert response.status_code == 400
        assert response.json() == {"detail": "不允许的主机名"}
        assert client.get("/").status_code == 400


def test_middleware_rejects_form_posts(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/threads", data={"title": "x"})
        assert response.status_code == 415


def test_login_sets_cookie_that_unlocks_api(tmp_path: Path) -> None:
    with _client(tmp_path, SecurityPolicy(access_token="s3cret")) as client:
        # 未装配服务对象：用不存在的接口路径看"是否被拦下"（放行后是 404）
        assert client.get("/api/not-exist").status_code == 401
        assert "首页" in client.get("/").text

        wrong = client.post("/api/auth/token", json={"token": "nope"})
        assert wrong.status_code == 401
        assert wrong.json() == {"detail": "访问令牌不正确"}

        right = client.post("/api/auth/token", json={"token": "s3cret"})
        assert right.status_code == 204
        cookie = right.headers["set-cookie"]
        assert f"{TOKEN_COOKIE}=s3cret" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        # TestClient 会保存 Cookie：之后的请求自动带上，不再被拒
        assert client.get("/api/not-exist").status_code == 404


def test_login_without_configured_token_is_a_no_op(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/auth/token", json={"token": "anything"})
        assert response.status_code == 204
        assert "set-cookie" not in response.headers


def _settings(access_token: str, listen_address: str = "127.0.0.1") -> Settings:
    return Settings(
        database_url="postgresql://unused",
        litellm_master_key="sk-test",
        agent=AgentConfig(default_model="m"),
        access_token=access_token,
        listen_address=listen_address,
    )


def test_policy_from_settings_treats_empty_token_as_none() -> None:
    """.env 里写了 ACCESS_TOKEN= 但没填值，等于不设置令牌。"""
    assert SecurityPolicy.from_settings(_settings("")).access_token is None
    policy = SecurityPolicy.from_settings(_settings("s3cret"))
    assert policy.access_token == "s3cret"
    assert "s3cret" not in repr(policy)


def test_policy_from_settings_reads_lan_networks() -> None:
    """配置里带"/"的是网段；默认允许三个私有网段。"""
    policy = SecurityPolicy.from_settings(_settings(""))
    assert ip_network("10.0.0.0/8") in policy.allowed_networks
    assert ip_network("192.168.0.0/16") in policy.allowed_networks
    assert "10.0.0.0/8" not in policy.allowed_hosts
    assert rejection(policy, _scope(headers={"host": "10.2.32.237:8000"})) is None


def test_lan_listening_requires_access_token() -> None:
    """端口对局域网开放时必须设置令牌：主机名可以伪造，挡住局域网里的程序只能靠令牌。"""
    with pytest.raises(ValueError, match="ACCESS_TOKEN"):
        SecurityPolicy.from_settings(_settings("", listen_address="0.0.0.0"))
    assert SecurityPolicy.from_settings(_settings("s3cret", listen_address="0.0.0.0")).access_token
    assert (
        SecurityPolicy.from_settings(_settings("", listen_address="localhost")).access_token is None
    )
```

测试客户端改用本机名（之后所有接口测试都要通过主机名检查）：

在 `backend/tests/conftest.py` 中，把：

```python
        app.state.services = build_services(settings, db, agent, bus=bus)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
```

改为：

```python
        app.state.services = build_services(settings, db, agent, bus=bus)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            yield client
```

在 `backend/tests/test_frontend.py` 中，把：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app) as client:
        assert "首页" in client.get("/").text
```

改为：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert "首页" in client.get("/").text
```

在 `backend/tests/test_frontend.py` 中，把：

```python
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
```

改为：

```python
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").status_code == 404
```

在 `backend/tests/test_frontend.py` 中，把：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app) as client:
        assert client.get("/assets/app-old.js").status_code == 404
```

改为：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/assets/app-old.js").status_code == 404
```

在 `backend/tests/test_frontend.py` 中，把：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app) as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
```

改为：

```python
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_security.py -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'backend.security'`。

- [ ] **步骤 3：实现后端**

在 `config/settings.py` 中，把：

```python
    model_gateway: str = "litellm_proxy"

```

改为：

```python
    model_gateway: str = "litellm_proxy"


class SecurityConfig(BaseModel):
    """本机安全防护（设计文档 12.2）：允许的主机名（带"/"的是局域网网段）与额外的前端来源。"""

    allowed_hosts: list[str] = [
        "localhost",
        "127.0.0.1",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]
    allowed_origins: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

```

在 `config/settings.py` 中，把：

```python
    agent: AgentConfig

```

改为：

```python
    agent: AgentConfig
    security: SecurityConfig = SecurityConfig()
    # 可选访问令牌（.env 的 ACCESS_TOKEN）：设置后 /api 需要令牌，前端会先显示令牌页
    access_token: SecretStr | None = None
    # 后端端口对外开放的地址（.env 的 LISTEN_ADDRESS，compose 用它绑定端口）：
    # 默认只有本机；0.0.0.0 表示局域网也能访问，此时必须设置 access_token
    listen_address: str = "127.0.0.1"

```

在 `config/app.yaml` 末尾追加：

```yaml

# 本机安全防护（设计文档 12.2）
security:
  # 允许的主机名（浏览器地址栏里的那部分）；带"/"的是网段，网段里的局域网 IP 都放行。
  # 局域网访问还要在 .env 设置 LISTEN_ADDRESS=0.0.0.0 与 ACCESS_TOKEN（见 README）。
  allowed_hosts:
    - localhost
    - 127.0.0.1
    - 10.0.0.0/8 # 局域网 IP（三个私有网段）
    - 172.16.0.0/12
    - 192.168.0.0/16
  # 与页面同一地址的请求总是放行；这里列出其他允许写操作的来源
  allowed_origins:
    - http://localhost:8000
    - http://127.0.0.1:8000
    - http://localhost:5173 # make web 开发服务器
    - http://127.0.0.1:5173
```

新建 `backend/security.py`：

```python
"""本机安全防护（设计文档 12.2）。

只监听本机地址并不安全：浏览器里打开的任何网页都能向 127.0.0.1:8000 发请求，而本服务能执行代码、
调用工具。所以每个请求都要检查：
1. Host 请求头只接受本机名与允许网段里的 IP（局域网访问），防止 DNS 重绑定
   （恶意域名解析到 127.0.0.1 后读取接口：请求头里是那个域名，不是 IP）；
2. 写操作（POST / PUT / PATCH / DELETE）如果带了 Origin，必须与请求的地址同源或在允许列表中；
3. POST 必须是 JSON：迫使跨站请求先发预检请求而被浏览器拦下（PUT / PATCH / DELETE 本来就要预检）；
4. 配置了访问令牌（.env 的 ACCESS_TOKEN）时，/api 下的请求需要令牌：
   Cookie（前端在令牌页提交后由服务器写入）或 Authorization: Bearer 请求头。
前端页面本身不需要令牌（否则无法显示令牌页），只检查 Host。

端口对局域网开放（LISTEN_ADDRESS 不是本机地址）时必须设置令牌：局域网里的程序可以伪造 Host，
挡得住它们的只有令牌。
"""

import hmac
import re
from dataclasses import dataclass, field
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Receive, Scope, Send

from config import Settings

TOKEN_COOKIE = "opa_token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TOKEN_FREE_PATHS = frozenset({"/api/health", "/api/auth/token"})
_HOST = re.compile(r"^\[?(?P<name>[^\]]*?)\]?(:\d+)?$")

type Network = IPv4Network | IPv6Network


@dataclass(frozen=True)
class SecurityPolicy:
    allowed_hosts: frozenset[str] = frozenset({"localhost", "127.0.0.1"})
    allowed_networks: tuple[Network, ...] = ()  # 局域网访问：Host 是这些网段里的 IP 也放行
    allowed_origins: frozenset[str] = frozenset(
        {
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }
    )
    access_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecurityPolicy":
        """按配置生成策略；端口对局域网开放却没设置令牌时拒绝（ValueError），服务不会启动。"""
        token = settings.access_token.get_secret_value() if settings.access_token else None
        if not token and not _is_loopback(settings.listen_address):
            raise ValueError(
                f"LISTEN_ADDRESS={settings.listen_address} 会让局域网里的设备也能访问，"
                "必须同时在 .env 设置 ACCESS_TOKEN（主机名可以伪造，只有令牌挡得住局域网里的程序）"
            )
        entries = settings.security.allowed_hosts
        return cls(
            allowed_hosts=frozenset(entry for entry in entries if "/" not in entry),
            allowed_networks=tuple(ip_network(entry) for entry in entries if "/" in entry),
            allowed_origins=frozenset(settings.security.allowed_origins),
            access_token=token or None,
        )


def rejection(policy: SecurityPolicy, scope: Scope) -> tuple[int, str] | None:
    """检查一个请求；不放行时返回 (状态码, 原因)。"""
    headers = Headers(scope=scope)
    host = headers.get("host", "")
    match = _HOST.match(host)
    if match is None or not _host_allowed(policy, match["name"]):
        return status.HTTP_400_BAD_REQUEST, "不允许的主机名"
    path: str = scope["path"]
    if not path.startswith("/api/"):
        return None
    method: str = scope["method"]
    if method in _UNSAFE_METHODS:
        origin = headers.get("origin")
        same_origin = origin == f"{scope.get('scheme', 'http')}://{host}"  # ASGI：缺省为 http
        if origin is not None and not same_origin and origin not in policy.allowed_origins:
            return status.HTTP_403_FORBIDDEN, "不允许的来源"
        if method == "POST" and not headers.get("content-type", "").startswith("application/json"):
            return status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "只接受 JSON 请求"
    token = policy.access_token
    if token and path not in _TOKEN_FREE_PATHS and not _has_token(token, headers):
        return status.HTTP_401_UNAUTHORIZED, "需要访问令牌"
    return None


def _host_allowed(policy: SecurityPolicy, name: str) -> bool:
    if name in policy.allowed_hosts:
        return True
    try:
        address = ip_address(name)
    except ValueError:  # 不是 IP 的主机名只认允许列表
        return False
    return any(address in network for network in policy.allowed_networks)


def _is_loopback(address: str) -> bool:
    if address == "localhost":
        return True
    try:
        return ip_address(address).is_loopback
    except ValueError:
        return False


def _has_token(expected: str, headers: Headers) -> bool:
    cookie = cookie_parser(headers.get("cookie", "")).get(TOKEN_COOKIE, "")
    authorization = headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    return any(
        hmac.compare_digest(given.encode(), expected.encode())
        for given in (cookie, bearer)
        if given
    )


class SecurityMiddleware:
    """对每个 HTTP 请求执行检查。策略取自 app.state.security（启动时按配置写入）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            policy = getattr(scope["app"].state, "security", SecurityPolicy())
            if (reason := rejection(policy, scope)) is not None:
                code, detail = reason
                await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class TokenLogin(BaseModel):
    token: str


auth_router = APIRouter()


@auth_router.post("/auth/token", status_code=status.HTTP_204_NO_CONTENT)
async def login(body: TokenLogin, request: Request, response: Response) -> None:
    """提交访问令牌：正确时写入只供服务器读取的 Cookie，之后浏览器的请求（含推送）自动带上。"""
    policy: SecurityPolicy = getattr(request.app.state, "security", SecurityPolicy())
    if policy.access_token is None:
        return
    if not hmac.compare_digest(body.token.encode(), policy.access_token.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "访问令牌不正确")
    response.set_cookie(
        TOKEN_COOKIE,
        policy.access_token,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="strict",
        path="/",
    )
```

在 `backend/main.py` 中，把：

```python
from backend.frontend import FRONTEND_DIST, mount_frontend
from common.db import create_pool
```

改为：

```python
from backend.frontend import FRONTEND_DIST, mount_frontend
from backend.security import SecurityMiddleware, SecurityPolicy, auth_router
from common.db import create_pool
```

在 `backend/main.py` 中，把：

```python
    settings = get_settings()
    pool = create_pool(settings.database_url)
```

改为：

```python
    settings = get_settings()
    app.state.security = SecurityPolicy.from_settings(settings)
    pool = create_pool(settings.database_url)
```

在 `backend/main.py` 中，把：

```python
    app = FastAPI(title="open-personal-agent", lifespan=lifespan_handler)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    mount_frontend(app, frontend_dist)  # 必须在接口路由之后挂载，否则会遮住 /api
```

改为：

```python
    app = FastAPI(title="open-personal-agent", lifespan=lifespan_handler)
    app.add_middleware(SecurityMiddleware)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    mount_frontend(app, frontend_dist)  # 必须在接口路由之后挂载，否则会遮住 /api
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_security.py backend/tests/test_frontend.py -q`

预期：全部通过（31 个）。

- [ ] **步骤 5：写失败的前端测试**

在 `frontend/src/api/client.test.ts` 中，把：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, errorMessage, readableError } from "./client";

```

改为：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, needsAccessToken, readableError } from "./client";

```

在 `frontend/src/api/client.test.ts` 末尾追加：

```ts

describe("访问令牌", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("出错时抛出 ApiError，带上状态码，便于区分需要令牌的情况", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ detail: "需要访问令牌" }, { status: 401 })),
    );
    const error: unknown = await api.listThreads().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect(readableError(error)).toBe("需要访问令牌");
    expect(needsAccessToken(error)).toBe(true);
  });

  it("其他错误不算需要令牌", () => {
    expect(needsAccessToken(new ApiError(409, "该会话已有进行中的运行"))).toBe(false);
    expect(needsAccessToken(new Error("无法连接到后端，请确认服务已启动"))).toBe(false);
  });

  it("提交令牌", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.login("s3cret")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/token",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ token: "s3cret" }) }),
    );
  });
});
```

在 `frontend/src/api/queries.test.ts` 中，把：

```ts
import { describe, expect, it, vi } from "vitest";
import { historyQuery, modelsQuery, retryWhileFailing, threadsQuery } from "./queries";
```

改为：

```ts
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { historyQuery, modelsQuery, retryWhileFailing, threadsQuery } from "./queries";
```

在 `frontend/src/api/queries.test.ts` 中，把：

```ts
    expect(retryWhileFailing({ state: { status: "success" } } as never)).toBe(false);
  });
});

```

改为：

```ts
    expect(retryWhileFailing({ state: { status: "success" } } as never)).toBe(false);
  });

  it("需要访问令牌时不重试，等用户输入令牌", () => {
    const state = { status: "error", error: new ApiError(401, "需要访问令牌") };
    expect(retryWhileFailing({ state } as never)).toBe(false);
  });
});

```

在 `frontend/src/api/queries.test.ts` 中，把：

```ts
    expect(modelsQuery.refetchInterval).toBe(retryWhileFailing);
  });
```

改为：

```ts
    expect(modelsQuery.refetchInterval).toBe(retryWhileFailing);
    // 不叠加 TanStack Query 默认的 3 次退避重试：失败立即显示（令牌页、"正在重试"），之后每 5 秒一次
    expect(threadsQuery.retry).toBe(0);
    expect(modelsQuery.retry).toBe(0);
  });
```

- [ ] **步骤 6：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/api`（预期失败）

预期：`ApiError is not a constructor`、`api.login is not a function`、`retry` 为 `undefined` 等 5 个失败。

- [ ] **步骤 7：实现前端**

在 `frontend/src/api/client.ts` 中，把：

```ts
  return `请求失败：${status}`;
}
```

改为：

```ts
  return `请求失败：${status}`;
}

/** 后端返回的错误：带上状态码，便于区分"需要访问令牌"等情况。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** 后端配置了访问令牌（.env 的 ACCESS_TOKEN），而浏览器还没有提交过。 */
export function needsAccessToken(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
```

在 `frontend/src/api/client.ts` 中，把：

```ts
  if (!resp.ok) {
    throw new Error(errorMessage(resp.status, await resp.json().catch(() => null)));
  }
```

改为：

```ts
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    throw new ApiError(resp.status, errorMessage(resp.status, body));
  }
```

在 `frontend/src/api/client.ts` 中，把：

```ts
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
};
```

改为：

```ts
  threadUsage: (threadId: string) => request<ThreadUsage>(`/threads/${threadId}/usage`),
  // 令牌正确时服务器写入 Cookie，之后的请求（含推送）由浏览器自动带上
  login: (token: string) =>
    request<undefined>("/auth/token", { method: "POST", body: JSON.stringify({ token }) }),
};
```

在 `frontend/src/api/queries.ts` 中，把：

```ts
import type { Query } from "@tanstack/react-query";
import { api } from "./client";

```

改为：

```ts
import type { Query } from "@tanstack/react-query";
import { api, needsAccessToken } from "./client";

```

在 `frontend/src/api/queries.ts` 中，把：

```ts

/** 失败后每 5 秒重试一次，直到成功（例如后端重启期间列表加载失败）。 */
export function retryWhileFailing(query: Pick<Query, "state">): number | false {
  return query.state.status === "error" ? 5000 : false;
}

export const threadsQuery = {
  queryKey: ["threads"],
  queryFn: api.listThreads,
  refetchInterval: retryWhileFailing,
```

改为：

```ts

/**
 * 失败后每 5 秒重试一次，直到成功（例如后端重启期间列表加载失败）。
 * 需要访问令牌时不重试：重试也不会成功，等用户在令牌页提交后再统一刷新。
 */
export function retryWhileFailing(query: Pick<Query, "state">): number | false {
  const { status, error } = query.state;
  return status === "error" && !needsAccessToken(error) ? 5000 : false;
}

// retry: 0 —— 不叠加默认的 3 次退避重试，失败立即显示，之后由 retryWhileFailing 每 5 秒重试
export const threadsQuery = {
  queryKey: ["threads"],
  queryFn: api.listThreads,
  retry: 0,
  refetchInterval: retryWhileFailing,
```

在 `frontend/src/api/queries.ts` 中，把：

```ts
  queryFn: api.listModels,
  refetchInterval: retryWhileFailing,
```

改为：

```ts
  queryFn: api.listModels,
  retry: 0,
  refetchInterval: retryWhileFailing,
```

新建 `frontend/src/features/auth/AccessTokenGate.tsx`：

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { api, readableError } from "../../api/client";

/**
 * 访问令牌页：后端配置了访问令牌（.env 的 ACCESS_TOKEN）而浏览器还没提交过时显示。
 * 提交正确后服务器写入 Cookie，刷新全部数据即回到正常界面。
 */
export function AccessTokenGate() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <div className="app-glow flex h-screen items-center justify-center bg-background p-4 text-foreground">
      <form
        className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-lg"
        onSubmit={(event) => {
          event.preventDefault();
          if (token.trim()) login.mutate(token.trim());
        }}
      >
        <h1 className="flex items-center gap-2 font-medium">
          <KeyRound className="size-4 text-warning" />
          需要访问令牌
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          服务已开启访问令牌保护。请输入 .env 中 ACCESS_TOKEN 的值，本浏览器之后会记住它。
        </p>
        <input
          autoFocus
          type="password"
          aria-label="访问令牌"
          autoComplete="current-password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          className="mt-4 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-ring"
        />
        {login.isError && <p className="mt-3 text-sm text-danger">{readableError(login.error)}</p>}
        <button
          type="submit"
          className="mt-4 w-full rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={login.isPending || !token.trim()}
        >
          {login.isPending ? "正在验证…" : "进入"}
        </button>
      </form>
    </div>
  );
}
```

在 `frontend/src/layout/AppShell.tsx` 中，把：

```tsx
import { useState } from "react";
import { threadsQuery } from "../api/queries";
import { ChatView } from "../features/chat/ChatView";
```

改为：

```tsx
import { useState } from "react";
import { needsAccessToken } from "../api/client";
import { threadsQuery } from "../api/queries";
import { AccessTokenGate } from "../features/auth/AccessTokenGate";
import { ChatView } from "../features/chat/ChatView";
```

在 `frontend/src/layout/AppShell.tsx` 中，把：

```tsx
  const thread = threads.data?.find((item) => item.id === selectedId) ?? null;

```

改为：

```tsx
  const thread = threads.data?.find((item) => item.id === selectedId) ?? null;

  if (needsAccessToken(threads.error)) return <AccessTokenGate />;

```

- [ ] **步骤 8：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/api`

预期：全部通过（15 个）。

- [ ] **步骤 9：严格反序列化与环境变量**

对话存档只反序列化登记过的类型（`langgraph-checkpoint-postgres` 的建议）：Makefile、镜像、compose、测试夹具四处一致。可选令牌经 compose 传给后端，`.env` 没设置时为空，表示不需要令牌。后端端口按 `.env` 的 `LISTEN_ADDRESS` 绑定（默认 `127.0.0.1`），同一个值也传给后端，用来检查"对局域网开放时必须有令牌"。

在 `conftest.py` 中，把：

```python
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

```

改为：

```python
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    # 与正式运行一致：对话存档只反序列化登记过的类型（须在导入 langgraph 之前设置）
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

```

在 `Makefile` 中，把：

```makefile
export LITELLM_LOCAL_MODEL_COST_MAP := True
# 前端命令使用 frontend/.nvmrc 指定的 Node 版本（nvm 安装的那一份），不改动全局默认版本
```

改为：

```makefile
export LITELLM_LOCAL_MODEL_COST_MAP := True
# 对话存档只反序列化登记过的类型（langgraph-checkpoint-postgres 的建议，设计文档 12.2）
export LANGGRAPH_STRICT_MSGPACK := true
# 前端命令使用 frontend/.nvmrc 指定的 Node 版本（nvm 安装的那一份），不改动全局默认版本
```

在 `deploy/backend.Dockerfile` 中，把：

```dockerfile
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LITELLM_LOCAL_MODEL_COST_MAP=True

```

改为：

```dockerfile
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    LANGGRAPH_STRICT_MSGPACK=true

```

在 `deploy/docker-compose.yml` 中，把：

```yaml
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
      WORKDATA_DIR: /app/workdata
```

改为：

```yaml
      LITELLM_LOCAL_MODEL_COST_MAP: "True"
      LANGGRAPH_STRICT_MSGPACK: "true"
      # 可选访问令牌：.env 里设置了 ACCESS_TOKEN 才生效（不设置则为空，表示不需要令牌）
      ACCESS_TOKEN: ${ACCESS_TOKEN:-}
      # 后端端口对外开放的地址：默认只有本机；.env 设为 0.0.0.0 时局域网也能访问（此时必须设置 ACCESS_TOKEN）
      LISTEN_ADDRESS: ${LISTEN_ADDRESS:-127.0.0.1}
      WORKDATA_DIR: /app/workdata
```

在 `deploy/docker-compose.yml` 中，把：

```yaml
      - ../workdata:/app/workdata
    ports: ["127.0.0.1:8000:8000"]
    depends_on:
```

改为：

```yaml
      - ../workdata:/app/workdata
    ports: ["${LISTEN_ADDRESS:-127.0.0.1}:8000:8000"]
    depends_on:
```

在 `.env.example` 中，把：

```text
LITELLM_LOCAL_MODEL_COST_MAP=True

```

改为：

```text
LITELLM_LOCAL_MODEL_COST_MAP=True

# ---- 可选：访问令牌。设置后浏览器首次打开需输入它（防止本机其他网页或程序调用接口）----
ACCESS_TOKEN=

# ---- 可选：局域网访问。默认 127.0.0.1 只有本机能访问；设为 0.0.0.0 时局域网里的设备也能访问（必须同时设置 ACCESS_TOKEN）----
LISTEN_ADDRESS=127.0.0.1

```

- [ ] **步骤 10：文档**

在 `docs/development/architecture.md` 末尾追加：

```markdown

## 10. 本机安全防护（设计文档 12.2）

只监听本机地址不等于安全：浏览器里打开的任何网页都能向 `127.0.0.1:8000` 发请求。`backend/security.py` 的中间件对每个请求检查：

| 检查 | 范围 | 不通过 |
|---|---|---|
| Host 请求头只接受 `config/app.yaml` 的 `security.allowed_hosts` 里的主机名，或其中网段（带"/"）里的 IP（防 DNS 重绑定：这类攻击的请求头里是域名） | 全部请求（含前端页面） | 400 |
| 写操作（POST / PUT / PATCH / DELETE）带 Origin 时，必须与请求的地址同源，或是 `security.allowed_origins` 之一 | `/api` | 403 |
| POST 必须是 JSON（表单、纯文本是跨站网页不经预检就能发出的请求） | `/api` | 415 |
| 设置了 `.env` 的 `ACCESS_TOKEN` 时需要令牌（Cookie `opa_token` 或 `Authorization: Bearer`） | `/api`，健康检查与 `/api/auth/token` 除外 | 401 |

约定：
1. 不开启跨域（CORS）：前端与接口同源（开发时经 Vite 转发），跨站网页读不到任何接口结果。
2. 新增接口无需额外处理；新增**文件上传**接口（M2）时，额外要求一个自定义请求头（表单上传是"简单请求"，不受第 3 条约束）。
3. 前端遇到 401 显示令牌页（`features/auth/AccessTokenGate.tsx`），提交后服务器写入只供服务器读取的 Cookie，推送连接（EventSource）也自动带上。
4. 对话存档只反序列化登记过的类型：`LANGGRAPH_STRICT_MSGPACK=true`（Makefile、镜像、compose、测试夹具四处一致）。
5. **局域网访问**：compose 按 `.env` 的 `LISTEN_ADDRESS` 绑定后端端口（默认 `127.0.0.1`，只有本机）。设为本机以外的地址时必须设置 `ACCESS_TOKEN`，否则启动时 `SecurityPolicy.from_settings` 报错、服务不启动——局域网里的程序可以伪造 Host，挡得住它们的只有令牌。
```

在 `README.md` 中，把：

```markdown

开发前端时可另开终端运行 `make web`，打开 http://127.0.0.1:5173（改代码即时生效，接口转发到 8000）。
```

改为：

```markdown

**访问令牌（可选）**：在 `.env` 里填写 `ACCESS_TOKEN=<随机串>` 后运行 `make up`，浏览器首次打开会要求输入它，防止本机其他网页或程序调用接口。

**局域网访问（可选）**：在 `.env` 里设置 `LISTEN_ADDRESS=0.0.0.0` 并填写 `ACCESS_TOKEN`，运行 `make up`。之后同一局域网的设备打开 `http://<这台电脑的局域网 IP>:8000`（Mac 上用 `ipconfig getifaddr en0` 查看），输入令牌即可使用。局域网访问必须设置令牌，否则后端拒绝启动。允许的局域网网段在 `config/app.yaml` 的 `security.allowed_hosts`（默认三个私有网段）；用其他主机名访问时也在这里补上。

开发前端时可另开终端运行 `make web`，打开 http://127.0.0.1:5173（改代码即时生效，接口转发到 8000）。
```

- [ ] **步骤 11：检查点**

运行：`make check`

写计划时演练用过测试数据库（它已升级到本计划任务 5 的迁移 0004），先重建，`make test-int` 会自动重新启动它（测试库的数据本来就是测完即弃）：

运行：`make test-down`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 87 个、前端 54 个）；`make test-int` 全部通过（集成测试 44 个）。

---

### 任务 2：前端类型自动生成

**文件：**
- 新建：`backend/openapi.py`、`backend/tests/test_openapi.py`；`frontend/src/api/generated/openapi.json`、`schema.d.ts`（由命令生成）
- 修改：
  - 后端：`agents/main_agent/runtime/events.py`、`agents/main_agent/models/base.py`、`backend/runtime/envelope.py`、`backend/runs/schemas.py`；
  - 前端：`frontend/package.json`、`pnpm-lock.yaml`、`.prettierignore`、`eslint.config.js`、`frontend/src/api/types.ts`、`frontend/src/features/chat/reducer.test.ts`；
  - 工具与文档：`Makefile`、`docs/development/architecture.md`、`docs/development/coding-standards.md`、`README.md`、`CLAUDE.md`。

**接口：**
- 产出（backend）：
  - `build_openapi(app) -> dict`：FastAPI 接口文档的副本，`components.schemas` 并入事件定义，事件联合类型名为 `AgentEvent`；同名而内容不同（忽略默认值）时抛 `ValueError`；
  - `GENERATED_OPENAPI`：生成文件路径；`python -m backend.openapi [输出路径]`；
  - `RunStatus = Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]`（导出为同名类型）。
- 产出（命令）：
  - `make types`：生成 openapi.json，再生成 schema.d.ts；
  - `pnpm types` / `pnpm types:check`；`make check-web` 跑 `types:check`。
- 产出（前端 `src/api/types.ts`，供后续任务使用）：
  - `Thread`、`ModelInfo`、`RunStatus`、`RunRecord`、`UsageTotals`、`InterruptedUsage`、`ModelUsage`、`ThreadUsage`、`TodoItem`、`AgentEvent`、`UsageData`、`RunHistory`；
  - `EventEnvelope`：按 `type` 区分的 `data` 联合；`message.delta` / `thinking.delta` 另有可选的 `full_text`。
- 约定：输出模型（事件、用量合计、模型信息、信封）有默认值的字段一律必有。所以 `run.finished` 的 `usage`、`interrupted` 在类型上必有，测试样例要写全。

- [ ] **步骤 1：写失败的测试**

新建 `backend/tests/test_openapi.py`：

```python
import json
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from backend.main import create_app
from backend.openapi import GENERATED_OPENAPI, build_openapi


def _doc() -> dict[str, Any]:
    return build_openapi(create_app(lifespan_handler=None))


def test_agent_events_are_included() -> None:
    """接口文档里只有信封（data 是任意字典），事件本身的定义要另外并进去，前端才能按类型区分。"""
    schemas = _doc()["components"]["schemas"]
    mapping = schemas["AgentEvent"]["discriminator"]["mapping"]
    assert set(mapping) == {
        "run.started",
        "message.delta",
        "thinking.delta",
        "tool.started",
        "tool.finished",
        "subagent.started",
        "subagent.finished",
        "todos.updated",
        "usage",
        "run.finished",
    }
    assert mapping["usage"] == "#/components/schemas/UsageReported"
    assert "UsageReported" in schemas


def test_fields_always_present_in_responses_are_required() -> None:
    """有默认值的字段在响应里总会出现：标为必有，前端类型才不会多出"可能没有"。"""
    schemas = _doc()["components"]["schemas"]
    assert "ts" in schemas["EventEnvelope"]["required"]
    assert "agent_path" in schemas["RunStarted"]["required"]
    assert "cost" in schemas["UsageTotals"]["required"]
    assert "max_input_tokens" in schemas["ModelInfo"]["required"]
    assert schemas["RunStatus"]["enum"] == [
        "queued",
        "running",
        "interrupted",
        "completed",
        "failed",
        "cancelled",
    ]


def test_rejects_same_name_with_different_shape() -> None:
    """事件里的类型与接口里的同名却不同时报错，而不是悄悄用其中一个（前端类型会错）。"""

    class UsageTotals(BaseModel):
        something_else: str

    app = FastAPI()

    @app.get("/x")
    async def x() -> UsageTotals:
        return UsageTotals(something_else="")

    with pytest.raises(ValueError, match="UsageTotals"):
        build_openapi(app)


def test_does_not_change_served_openapi() -> None:
    app = create_app(lifespan_handler=None)
    build_openapi(app)
    assert "AgentEvent" not in app.openapi()["components"]["schemas"]


def test_generated_file_is_up_to_date() -> None:
    """前端类型由 generated/openapi.json 生成：接口或事件改了却没重新生成时失败。"""
    committed = json.loads(GENERATED_OPENAPI.read_text(encoding="utf-8"))
    assert committed == _doc(), "接口或事件定义变了：运行 make types 重新生成前端类型"
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_openapi.py -q`（预期失败）

预期：收集阶段报错 `ModuleNotFoundError: No module named 'backend.openapi'`。

- [ ] **步骤 3：实现导出**

输出模型的默认值字段标为必有：

在 `agents/main_agent/runtime/events.py` 中，把：

```python

from pydantic import BaseModel, Field, TypeAdapter

```

改为：

```python

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

```

在 `agents/main_agent/runtime/events.py` 中，把：

```python

class _BaseEvent(BaseModel):
    agent_path: list[str] = Field(default_factory=lambda: [MAIN])
```

改为：

```python

# 导出的类型定义里，有默认值的字段也标为必有：输出的数据总带着它们，前端类型不必处理"可能没有"
_OUTPUT = ConfigDict(json_schema_serialization_defaults_required=True)


class _BaseEvent(BaseModel):
    model_config = _OUTPUT

    agent_path: list[str] = Field(default_factory=lambda: [MAIN])
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python

    calls: int = 0
```

改为：

```python

    model_config = _OUTPUT

    calls: int = 0
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python
    """被中断的模型调用的估算用量（中断后网关不返回用量）：只用于显示，不计入用量表与合计。"""

```

改为：

```python
    """被中断的模型调用的估算用量（中断后网关不返回用量）：只用于显示，不计入用量表与合计。"""

    model_config = _OUTPUT

```

在 `agents/main_agent/models/base.py` 中，把：

```python
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

```

改为：

```python
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict

```

在 `agents/main_agent/models/base.py` 中，把：

```python
    """网关里登记的一个具体模型版本。"""

```

改为：

```python
    """网关里登记的一个具体模型版本。"""

    # 导出的类型定义里，有默认值的字段也标为必有（接口返回时总带着它们）
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

```

在 `backend/runtime/envelope.py` 中，把：

```python

from pydantic import BaseModel, Field

```

改为：

```python

from pydantic import BaseModel, ConfigDict, Field

```

在 `backend/runtime/envelope.py` 中，把：

```python
    """推给浏览器、存入 run_events 表的统一格式。"""

```

改为：

```python
    """推给浏览器、存入 run_events 表的统一格式。"""

    # 导出的类型定义里 ts 标为必有：推送与历史里的信封总带着时间
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

```

在 `backend/runs/schemas.py` 中，把：

```python
from datetime import datetime
from typing import Annotated
from uuid import UUID
```

改为：

```python
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
```

在 `backend/runs/schemas.py` 中，把：

```python

class RunCreate(BaseModel):
```

改为：

```python

# 与 runs 表的 CHECK 约束一致（0001 迁移）
type RunStatus = Literal["queued", "running", "interrupted", "completed", "failed", "cancelled"]


class RunCreate(BaseModel):
```

在 `backend/runs/schemas.py` 中，把：

```python
    thread_id: UUID
    status: str
    model: str
```

改为：

```python
    thread_id: UUID
    status: RunStatus
    model: str
```

新建 `backend/openapi.py`：

```python
"""导出接口文档，供前端生成类型（make types）。

FastAPI 自动生成的接口文档里，推送事件只是信封（data 是任意字典）；这里把智能体的事件定义
（agents 的 EVENT_ADAPTER）以 AgentEvent 的名字并进去，前端才能按事件类型区分 data 的内容。
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from agents.main_agent.runtime import EVENT_ADAPTER

_ROOT = Path(__file__).resolve().parent.parent
GENERATED_OPENAPI = _ROOT / "frontend" / "src" / "api" / "generated" / "openapi.json"


def build_openapi(app: FastAPI) -> dict[str, Any]:
    # 复制一份再改：app.openapi() 的结果被缓存，也是 /openapi.json 返回的内容
    doc = copy.deepcopy(app.openapi())
    events = EVENT_ADAPTER.json_schema(
        ref_template="#/components/schemas/{model}", mode="serialization"
    )
    schemas = doc["components"]["schemas"]
    for name, schema in events.pop("$defs", {}).items():
        # 同一个模型两边都有时（如 UsageTotals）保留接口里的；同名却不同则是两个模型撞了名
        existing = schemas.setdefault(name, schema)
        if _without_defaults(existing) != _without_defaults(schema):
            raise ValueError(f"事件定义与接口里有同名但不同的类型：{name}")
    schemas["AgentEvent"] = events
    return doc


def _without_defaults(schema: Any) -> Any:
    """比较时忽略默认值：FastAPI 导出接口文档时会去掉 null 默认值，事件定义里则保留。"""
    if isinstance(schema, dict):
        return {key: _without_defaults(value) for key, value in schema.items() if key != "default"}
    if isinstance(schema, list):
        return [_without_defaults(item) for item in schema]
    return schema


def main() -> None:
    from backend.main import create_app

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else GENERATED_OPENAPI
    doc = build_openapi(create_app(lifespan_handler=None))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 4：生成接口文档，运行测试，确认通过**

运行：`uv run python -m backend.openapi`

运行：`uv run pytest backend/tests/test_openapi.py -q`

预期：生成 `frontend/src/api/generated/openapi.json`；5 个测试通过。

- [ ] **步骤 5：前端生成工具**

运行：`cd frontend && pnpm add -D -E openapi-typescript@7.13.0`

`pnpm add` 已在 `package.json` 里加上依赖，再加两个脚本：

在 `frontend/package.json` 中，把：

```json
    "lint": "eslint .",
    "format": "prettier --check ."
  },
```

改为：

```json
    "lint": "eslint .",
    "format": "prettier --check .",
    "types": "openapi-typescript src/api/generated/openapi.json -o src/api/generated/schema.d.ts",
    "types:check": "openapi-typescript src/api/generated/openapi.json -o src/api/generated/schema.d.ts --check"
  },
```

生成的文件不参与格式与代码规范检查：

在 `frontend/.prettierignore` 末尾追加：

```text
# make types 自动生成，不手改
src/api/generated
```

在 `frontend/eslint.config.js` 中，把：

```js
export default defineConfig(
  { ignores: ["dist"] },
  js.configs.recommended,
```

改为：

```js
export default defineConfig(
  { ignores: ["dist", "src/api/generated"] },
  js.configs.recommended,
```

在 `Makefile` 中，把：

```makefile

.PHONY: install fmt check check-py check-web test test-int smoke \
	infra-up up build restart down logs restart-gateway test-up test-down web migrate
```

改为：

```makefile

.PHONY: install fmt check check-py check-web types test test-int smoke \
	infra-up up build restart down logs restart-gateway test-up test-down web migrate
```

在 `Makefile` 中，把：

```makefile
check-web:
	cd frontend && pnpm exec tsc --noEmit && pnpm lint && pnpm format && pnpm test

```

改为：

```makefile
check-web:
	cd frontend && pnpm exec tsc --noEmit && pnpm types:check && pnpm lint && pnpm format && pnpm test

types: ## 改了接口或事件定义后运行：重新生成前端类型（frontend/src/api/generated/）
	uv run python -m backend.openapi
	cd frontend && pnpm types

```

运行：`make types`

预期：生成 `frontend/src/api/generated/schema.d.ts`。

- [ ] **步骤 6：类型改为别名，确认更严格的类型能发现问题**

`frontend/src/api/types.ts`（整个替换）：

```ts
// 与 backend 接口对应的类型：由 make types 从接口文档与事件定义自动生成（generated/，不要手改），
// 这里只起简短的别名，并补上接口文档表达不了的部分（信封里按事件类型区分的 data）
import type { components } from "./generated/schema";

type Schemas = components["schemas"];

export type Thread = Schemas["Thread"];
export type ModelInfo = Schemas["ModelInfo"];
export type RunStatus = Schemas["RunStatus"];
export type RunRecord = Schemas["RunRecord"];
export type UsageTotals = Schemas["UsageTotals"];
export type InterruptedUsage = Schemas["InterruptedUsage"];
export type ModelUsage = Schemas["ModelUsage"];
export type ThreadUsage = Schemas["ThreadUsage"];
export type TodoItem = Schemas["TodoItem"];

/** 智能体事件（agents 的事件协议）。 */
export type AgentEvent = Schemas["AgentEvent"];
type EventType = AgentEvent["type"];
type EventData<T extends EventType> = Omit<Extract<AgentEvent, { type: T }>, "type" | "agent_path">;

/** 一次模型调用的用量（推送事件 usage 的内容）。 */
export type UsageData = EventData<"usage">;

// 界面历史里合并过的逐字片段带 full_text: true，表示 text 是这段内容到此为止的全文，应整体替换
type DeltaExtra<T extends EventType> = T extends "message.delta" | "thinking.delta"
  ? { full_text?: boolean }
  : unknown;

/** 推送与界面历史里的事件：信封字段 + 按 type 区分的 data（backend 把事件除 type、agent_path 外的字段放进 data）。 */
export type EventEnvelope = {
  [T in EventType]: Omit<Schemas["EventEnvelope"], "type" | "data"> & {
    type: T;
    data: EventData<T> & DeltaExtra<T>;
  };
}[EventType];

export type RunHistory = Omit<Schemas["RunHistory"], "events"> & { events: EventEnvelope[] };
```

运行：`cd frontend && pnpm exec tsc --noEmit`（预期失败）

预期：`src/features/chat/reducer.test.ts` 报 5 处错误，内容是"`run.finished` 的 `data` 缺少 `usage`、`interrupted`"。生成的类型把它们标为必有，样例要写全：

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
  { ...base, seq: 5, type: "message.delta", data: { message_id: "m1", text: "好" } },
  { ...base, seq: 6, type: "run.finished", data: { status: "completed", error: null } },
];
```

改为：

```ts
  { ...base, seq: 5, type: "message.delta", data: { message_id: "m1", text: "好" } },
  {
    ...base,
    seq: 6,
    type: "run.finished",
    data: { status: "completed", error: null, usage: null, interrupted: null },
  },
];
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用" },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用", usage: null, interrupted: null },
    };
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用" },
    });
```

改为：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用", usage: null, interrupted: null },
    });
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null, interrupted: null },
    };
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "completed", error: null },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "completed", error: null, usage: null, interrupted: null },
    };
```

运行：`cd frontend && pnpm exec tsc --noEmit`

运行：`cd frontend && pnpm types:check`

预期：类型检查通过；`types:check` 通过（生成文件是最新的）。

- [ ] **步骤 7：文档**

在 `docs/development/architecture.md` 中，把：

```markdown

**新增前端功能**：在 `frontend/src/features/<功能>/` 下建组件，只用语义样式类；涉及对话展示的改动放在 `src/components/chat/`；接口调用加到 `src/api/client.ts`；类型加到 `src/api/types.ts`；纯逻辑（如事件处理器、转换函数）必须有单元测试。

```

改为：

```markdown

**新增前端功能**：在 `frontend/src/features/<功能>/` 下建组件，只用语义样式类；涉及对话展示的改动放在 `src/components/chat/`；接口调用加到 `src/api/client.ts`；后端接口或事件有改动时运行 `make types` 重新生成类型，再在 `src/api/types.ts` 起别名；纯逻辑（如事件处理器、转换函数）必须有单元测试。

```

在 `docs/development/architecture.md` 中，把：

```markdown
|---|---|
| `agents/main_agent/runtime/events.py` | 事件协议（pydantic）。新增事件在这里定义，前端 `src/api/types.ts` 同步（M1c 起自动生成） |
| `agents/main_agent/runtime/translator.py` | 输出流片段 → 事件。回答与思考取自 `messages` 模式，工具 / 子智能体 / 待办取自 `updates` 模式 |
```

改为：

```markdown
|---|---|
| `agents/main_agent/runtime/events.py` | 事件协议（pydantic）。新增事件在这里定义，然后 `make types` 生成前端类型 |
| `backend/openapi.py` | 导出接口文档并把事件定义并入（`AgentEvent`），供 `make types` 生成前端类型；`make check` 核对生成结果是否最新 |
| `agents/main_agent/runtime/translator.py` | 输出流片段 → 事件。回答与思考取自 `messages` 模式，工具 / 子智能体 / 待办取自 `updates` 模式 |
```

在 `docs/development/coding-standards.md` 中，把：

```markdown
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型集中在 `src/api/types.ts`（M1c 起改为自动生成）。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
```

改为：

```markdown
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型从 `src/api/types.ts` 引入。它只给自动生成的类型（`src/api/generated/`，由 `make types` 从接口文档与事件定义生成，不手改）起别名；改了后端接口或事件定义后运行 `make types`，忘了会被 `make check` 发现。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
```

在 `README.md` 中，把：

```markdown
| Python 代码（agents / backend / common / config） | `make restart`（源码已挂载进容器，几秒生效） |
| 依赖（`pyproject.toml`、`uv.lock`、`frontend/package.json`、`pnpm-lock.yaml`）、前端界面、`deploy/backend.Dockerfile` | `make build`（重新构建镜像；依赖从本机构建缓存安装，不重新下载） |
```

改为：

```markdown
| Python 代码（agents / backend / common / config） | `make restart`（源码已挂载进容器，几秒生效） |
| 后端接口或事件定义 | `make types`（重新生成前端类型；忘了运行，`make check` 会提示） |
| 依赖（`pyproject.toml`、`uv.lock`、`frontend/package.json`、`pnpm-lock.yaml`）、前端界面、`deploy/backend.Dockerfile` | `make build`（重新构建镜像；依赖从本机构建缓存安装，不重新下载） |
```

在 `CLAUDE.md` 中，把：

```markdown
| `make web` | 前端开发服务器 http://127.0.0.1:5173（改代码即时生效） |
| `make check` | 格式、类型、依赖方向、前后端单元测试 |
| `make test-int` | 集成测试（自动启动测试数据库） |
```

改为：

```markdown
| `make web` | 前端开发服务器 http://127.0.0.1:5173（改代码即时生效） |
| `make types` | 改了后端接口或事件定义后，重新生成前端类型 |
| `make check` | 格式、类型（含生成的前端类型是否最新）、依赖方向、前后端单元测试 |
| `make test-int` | 集成测试（自动启动测试数据库） |
```

- [ ] **步骤 8：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 92 个、前端 54 个，含 `types:check`）；`make test-int` 全部通过（44 个）。

---

### 任务 3：后端停止、合并与续传的健壮性

**文件：**
- 修改：`backend/runtime/run_control.py`、`backend/runs/compaction.py`、`backend/runs/manager.py`、`backend/api/router.py`、`docs/development/architecture.md`
- 测试：`backend/tests/test_run_control.py`、`test_compaction.py`、`test_manager.py`、`test_api.py`
- 生成：`frontend/src/api/generated/*`（推送接口多了参数）

**接口：**
- 修改：
  - `InProcessRunControl.cancel_all()`：已在取消中的任务不再取消（与 `cancel` 共用 `_cancel_once`）；
  - `compact(events)`：按 `agent_path` 分别合并，`full_text` 的 `text` 是这段内容到此为止的全文，结果按 `seq` 排序；
  - `GET /api/runs/{id}/events?after=<序号>`：从 `max(after, Last-Event-ID)` 之后推送。
- `RunManager` 内部改动：
  - 用量写入改为后台任务，同一运行按调用顺序依次写（`_record_usage(run, usage, *, after)`）；`_finalize` 先等它们写完；
  - `cancel` 遇到没有后台任务的运行时调用 `_finish_idle`：存下结束事件、推送并关闭推送。
- 测试辅助（`test_manager.py`）：`_manager(..., usage=..., bus=...)`；`_SlowUsageRepo`、`_SlowFirstUsageRepo`。

- [ ] **步骤 1：写失败的测试**

在 `backend/tests/test_run_control.py` 末尾追加：

```python


async def test_cancel_all_does_not_interrupt_a_run_already_stopping(control: RunControl) -> None:
    """用户刚点了停止、运行正在收尾（把已输出的部分写进对话存档）时服务停止：不能再打断收尾。"""
    cleaned: list[str] = []

    async def run() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)  # 收尾：写对话存档
            cleaned.append("done")
            raise

    task = asyncio.create_task(run())
    control.track("r1", task)
    await asyncio.sleep(0)
    control.cancel("r1")
    await asyncio.sleep(0)  # 让它进入收尾

    await control.cancel_all()

    assert cleaned == ["done"]
    assert task.cancelling() == 1
```

在 `backend/tests/test_compaction.py` 中，把：

```python
from agents.main_agent.runtime import MessageDelta, RunFinished, ThinkingDelta, ToolStarted
from backend.runs.compaction import compact
```

改为：

```python
from agents.main_agent.runtime import (
    MessageDelta,
    RunFinished,
    ThinkingDelta,
    ToolStarted,
    UsageReported,
)
from backend.runs.compaction import compact
```

在 `backend/tests/test_compaction.py` 中，把：

```python
def _wrap(
    seq: int, event: MessageDelta | ThinkingDelta | ToolStarted | RunFinished
) -> EventEnvelope:
```

改为：

```python
def _wrap(
    seq: int, event: MessageDelta | ThinkingDelta | ToolStarted | RunFinished | UsageReported
) -> EventEnvelope:
```

在 `backend/tests/test_compaction.py` 末尾追加：

```python


def test_parallel_subagents_each_keep_their_full_text() -> None:
    """两个子智能体同时输出时片段交错：各自合并成全文，不能被对方切成几段（否则重放时只剩最后一段）。"""
    a, b = ["main", "ca"], ["main", "cb"]
    events = [
        _wrap(1, MessageDelta(agent_path=a, message_id="ma", text="子")),
        _wrap(2, MessageDelta(agent_path=b, message_id="mb", text="孙")),
        _wrap(3, MessageDelta(agent_path=a, message_id="ma", text="一")),
        _wrap(4, MessageDelta(agent_path=b, message_id="mb", text="二")),
    ]
    result = compact(events)
    assert [(e.seq, e.agent_path, e.data["text"]) for e in result] == [
        (3, a, "子一"),
        (4, b, "孙二"),
    ]


def test_text_split_by_another_event_carries_everything_so_far() -> None:
    """同一段回答中间夹了别的事件（如用量）：后一组的 full_text 仍是到此为止的全文。"""
    usage = UsageReported(
        caller="main", requested_model="m", actual_model="m", input_tokens=1, output_tokens=1
    )
    events = [
        _wrap(1, MessageDelta(message_id="m1", text="你")),
        _wrap(2, usage),
        _wrap(3, MessageDelta(message_id="m1", text="好")),
    ]
    result = compact(events)
    assert [(e.seq, e.type, e.data.get("text")) for e in result] == [
        (1, "message.delta", "你"),
        (2, "usage", None),
        (3, "message.delta", "你好"),
    ]
```

在 `backend/tests/test_manager.py` 中，把：

```python

from agents.main_agent.runtime import MainAgent
from agents.main_agent.usage import UsageRepo
```

改为：

```python

from agents.main_agent.runtime import MainAgent, UsageReported
from agents.main_agent.usage import UsageRepo
```

在 `backend/tests/test_manager.py` 中，把：

```python

def _manager(db: Pool, runs: RunRepo, model: ScriptedChatModel | None = None) -> RunManager:
    """flush_interval 调小，测试里不必等 200 毫秒。"""
```

改为：

```python

class _SlowUsageRepo(UsageRepo):
    """写用量时停住（模拟数据库慢），便于在"一次模型调用刚结束、正在写用量"的瞬间点停止。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.writing = asyncio.Event()

    async def add(self, *, thread_id: UUID, run_id: UUID, usage: UsageReported) -> None:
        self.writing.set()
        await asyncio.sleep(0.2)
        await super().add(thread_id=thread_id, run_id=run_id, usage=usage)


class _SlowFirstUsageRepo(UsageRepo):
    """第一条用量写得慢：后台写入若不按顺序，第二条会先落库。"""

    def __init__(self, db: Pool) -> None:
        super().__init__(db)
        self.first = True

    async def add(self, *, thread_id: UUID, run_id: UUID, usage: UsageReported) -> None:
        if self.first:
            self.first = False
            await asyncio.sleep(0.2)
        await super().add(thread_id=thread_id, run_id=run_id, usage=usage)


def _manager(
    db: Pool,
    runs: RunRepo,
    model: ScriptedChatModel | None = None,
    usage: UsageRepo | None = None,
    bus: InMemoryEventBus | None = None,
) -> RunManager:
    """flush_interval 调小，测试里不必等 200 毫秒。"""
```

在 `backend/tests/test_manager.py` 中，把：

```python
        threads=ThreadRepo(db),
        usage=UsageRepo(db),
        agent=agent,
        bus=InMemoryEventBus(),
        control=InProcessRunControl(),
```

改为：

```python
        threads=ThreadRepo(db),
        usage=usage or UsageRepo(db),
        agent=agent,
        bus=bus or InMemoryEventBus(),
        control=InProcessRunControl(),
```

在 `backend/tests/test_manager.py` 末尾追加：

```python


async def test_cancel_while_recording_usage_keeps_the_answer(db: Pool) -> None:
    """一次模型调用刚结束、正在写用量时点停止：已输出的回答仍要留在对话存档里，
    否则界面上看得到完整回答，模型下一轮却看不到，用户说"继续"时会从头重做。"""
    runs, usage = RunRepo(db), _SlowUsageRepo(db)
    meta = {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13}
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="完整的回答", usage_metadata=meta),
            AIMessage(content="二", usage_metadata=meta),
        ]
    )
    manager = _manager(db, runs, model, usage=usage)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="写一段话"))
    events = manager.stream(run.id)
    await asyncio.wait_for(usage.writing.wait(), timeout=5)

    await manager.cancel(run.id)
    _ = [event async for event in events]
    second = await manager.start(thread.id, RunCreate(message="继续"))
    _ = await asyncio.wait_for(_drain(manager, second.id), timeout=5)

    seen = [m.content for m in model.received[-1] if m.type == "ai"]
    assert any("完整的回答" in str(content) for content in seen)
    assert len(await usage.for_run(run.id)) == 1  # 已结束的那次调用的用量照常写入


async def test_cancel_run_that_is_not_executing_ends_its_stream(db: Pool) -> None:
    """没有后台任务的运行（如 M4 等待审批时）被停止：也要存下并推送结束事件，
    否则正在看它的页面一直停在"运行中"，刷新后又显示成"运行未正常结束"。"""
    runs, bus = RunRepo(db), InMemoryEventBus()
    manager = _manager(db, runs, bus=bus)
    thread = await ThreadRepo(db).create(model="m")
    run = await runs.create(
        thread_id=thread.id, model="m", message="hi"
    )  # 不经 start：没有后台任务
    bus.open(str(run.id))
    watching = asyncio.create_task(_drain(manager, run.id))
    await asyncio.sleep(0)

    await manager.cancel(run.id)

    live = await asyncio.wait_for(watching, timeout=5)
    assert [(e.type, e.data["status"]) for e in live] == [("run.finished", "cancelled")]
    assert (await runs.get(run.id)).status == "cancelled"
    replayed = await _drain(_manager(db, runs), run.id)  # 新进程：从界面历史补发
    assert [(e.type, e.data["status"]) for e in replayed] == [("run.finished", "cancelled")]


async def test_usage_is_recorded_in_call_order(db: Pool) -> None:
    """用量在后台写入，也要按调用顺序落库：每轮的调用明细按写入时间排列。"""
    runs, usage = RunRepo(db), _SlowFirstUsageRepo(db)
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "c1"}],
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            ),
            AIMessage(
                content="好",
                usage_metadata={"input_tokens": 2, "output_tokens": 2, "total_tokens": 4},
            ),
        ]
    )
    manager = _manager(db, runs, model, usage=usage)
    thread = await ThreadRepo(db).create(model="m")
    run = await manager.start(thread.id, RunCreate(message="hi"))
    _ = await asyncio.wait_for(_drain(manager, run.id), timeout=5)

    assert [r.input_tokens for r in await usage.for_run(run.id)] == [1, 2]
```

在 `backend/tests/test_api.py` 中，把：

```python
        assert next(e["seq"] for e in _sse_events(resp.text)) == 2

```

改为：

```python
        assert next(e["seq"] for e in _sse_events(resp.text)) == 2


async def test_subscribe_after_events_already_shown(make_client: ClientFactory) -> None:
    """刷新页面时，进行中运行已存的事件已由历史重建：从 after 之后接着推送，避免文字重复；
    之后断线重连带的 Last-Event-ID 更靠后，以它为准。"""
    async with make_client(ScriptedChatModel(responses=[AIMessage(content="好")])) as client:
        thread = (await client.post("/api/threads", json={})).json()
        run = (
            await client.post(f"/api/threads/{thread['id']}/runs", json={"message": "hi"})
        ).json()
        await _wait_finished(client, thread["id"])
        url = f"/api/runs/{run['id']}/events"

        resp = await client.get(url, params={"after": 1})
        assert next(e["seq"] for e in _sse_events(resp.text)) == 2
        resp = await client.get(url, params={"after": 1}, headers={"Last-Event-ID": "2"})
        assert next(e["seq"] for e in _sse_events(resp.text)) == 3

```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_run_control.py backend/tests/test_compaction.py -q`（预期失败）

预期：3 个失败——
- `test_cancel_all_does_not_interrupt_a_run_already_stopping`（`[] == ['done']`）；
- `test_parallel_subagents_each_keep_their_full_text`；
- `test_text_split_by_another_event_carries_everything_so_far`。

运行：`make test-up`

运行：`uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`（预期失败）

预期：3 个失败——
- `test_cancel_while_recording_usage_keeps_the_answer`（下一轮的模型看不到"完整的回答"）；
- `test_cancel_run_that_is_not_executing_ends_its_stream`（推送不结束，`TimeoutError`）；
- `test_subscribe_after_events_already_shown`（`1 == 2`）。

`test_usage_is_recorded_in_call_order` 现在就通过：改动前用量是同步写入的，本来就按顺序。它防的是"改成后台写入却没有依次写"——写计划时实测，那样写会让它失败（`[2, 1] == [1, 2]`）。

- [ ] **步骤 3：实现**

在 `backend/runtime/run_control.py` 中，把：

```python
            return False
        if not task.cancelling():  # 已在取消中（如连点停止）：不再重复打断，让它安心收尾
            task.cancel()
        return True
```

改为：

```python
            return False
        _cancel_once(task)
        return True
```

在 `backend/runtime/run_control.py` 中，把：

```python
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
```

改为：

```python
        for task in tasks:
            _cancel_once(task)
        await asyncio.gather(*tasks, return_exceptions=True)


def _cancel_once(task: asyncio.Task[None]) -> None:
    """已在取消中（连点停止、停止后紧接着服务停止）就不再打断：第二次取消会打断它的收尾，
    例如把已输出的回答写进对话存档。"""
    if not task.cancelling():
        task.cancel()
```

`backend/runs/compaction.py`（整个替换）：

```python
"""存入界面历史前合并同一段回答（或思考过程）的连续逐字片段，减少存储量。"""

from backend.runtime import EventEnvelope

_DELTAS = ("message.delta", "thinking.delta")

type _ContentKey = tuple[str, tuple[str, ...], str]  # (类型, agent_path, message_id)


def compact(events: list[EventEnvelope]) -> list[EventEnvelope]:
    """按智能体合并同一段内容的连续逐字片段。

    每个智能体（agent_path）单独看：并行的子智能体片段交错到达，也各自合并。
    合并后的事件带 full_text=True，text 是这段内容到此为止的全文——即使中间夹了同一智能体的
    其他事件（如用量）而分成几组，后一组也带着前面的文字；序号取该组最后一个：
    断线续传时，只要客户端还没收到这组的最后一个片段，就会收到全文并整体替换，既不丢字也不重复。
    结果按序号排列（与从数据库读回的顺序一致）。
    """
    result: list[EventEnvelope] = []
    texts: dict[_ContentKey, str] = {}
    open_groups: dict[tuple[str, ...], tuple[_ContentKey, int]] = {}  # 智能体 → 正在合并的组
    for event in events:
        path = tuple(event.agent_path)
        if event.type not in _DELTAS:
            open_groups.pop(path, None)  # 同一智能体的其他事件结束当前这组
            result.append(event)
            continue
        key: _ContentKey = (event.type, path, event.data["message_id"])
        texts[key] = texts.get(key, "") + event.data["text"]
        merged = event.model_copy(
            update={"data": {**event.data, "text": texts[key], "full_text": True}}
        )
        group = open_groups.get(path)
        if group is not None and group[0] == key:
            result[group[1]] = merged
        else:
            open_groups[path] = (key, len(result))
            result.append(merged)
    return sorted(result, key=lambda event: event.seq)
```

在 `backend/runs/manager.py` 中，把：

```python
            # 不在执行中（如等待审批的运行，M4）：没有后台任务可取消，直接记为已取消
            await self._runs.finish(run_id, status="cancelled", error=None)
        return run
```

改为：

```python
            # 不在执行中（如等待审批的运行，M4）：没有后台任务可取消，直接记为已取消
            await self._finish_idle(run)
        return run
```

在 `backend/runs/manager.py` 中，把：

```python
        published: list[EventEnvelope] = []
        totals = UsageTotals()
```

改为：

```python
        published: list[EventEnvelope] = []
        usage_writes: list[asyncio.Task[None]] = []
        totals = UsageTotals()
```

在 `backend/runs/manager.py` 中，把：

```python
                    totals = totals.add(event)
                    await self._record_usage(run, event)
                envelope = await self._publish(run_id, event, seq=len(published) + 1)
```

改为：

```python
                    totals = totals.add(event)
                    # 用量在后台写：这个循环里不能有真正的等待，停止才总是落在智能体内部，
                    # 由它把已输出的回答存进对话存档（落在这里则存档会丢掉刚完成的那次回答）
                    previous = usage_writes[-1] if usage_writes else None
                    usage_writes.append(
                        asyncio.create_task(self._record_usage(run, event, after=previous))
                    )
                envelope = await self._publish(run_id, event, seq=len(published) + 1)
```

在 `backend/runs/manager.py` 中，把：

```python
            finalizing = asyncio.create_task(
                self._finalize(run, writer, [*published, tail], finished, totals)
            )
```

改为：

```python
            finalizing = asyncio.create_task(
                self._finalize(run, writer, usage_writes, [*published, tail], finished, totals)
            )
```

在 `backend/runs/manager.py` 中，把：

```python
        writer: EventWriter,
        events: list[EventEnvelope],
```

改为：

```python
        writer: EventWriter,
        usage_writes: list[asyncio.Task[None]],
        events: list[EventEnvelope],
```

在 `backend/runs/manager.py` 中，把：

```python
        try:
            await writer.finish(events)
```

改为：

```python
        try:
            await asyncio.gather(*usage_writes)  # 前端收到结束事件后会查用量，此时须已写完
            await writer.finish(events)
```

在 `backend/runs/manager.py` 中，把：

```python

    async def _record_usage(self, run: RunRecord, usage: UsageReported) -> None:
        """用量写库失败不影响运行本身，只留下日志。"""
        try:
```

改为：

```python

    async def _finish_idle(self, run: RunRecord) -> None:
        """结束一个没有后台任务的运行：结束事件存进界面历史并推送，关闭推送。"""
        run_id = str(run.id)
        stored = await self._runs.events(run.id)
        finished = RunFinished(status="cancelled")
        tail = EventEnvelope.wrap(
            finished, seq=(stored[-1].seq if stored else 0) + 1, run_id=run_id
        )
        await self._runs.add_events(run.id, [tail])
        await self._runs.finish(run.id, status="cancelled", error=None)
        if self._bus.has(run_id):
            await self._bus.publish(run_id, tail)
            await self._bus.close(run_id)

    async def _record_usage(
        self, run: RunRecord, usage: UsageReported, *, after: asyncio.Task[None] | None
    ) -> None:
        """等上一条写完再写（明细按写入时间排列，须与调用顺序一致）。写库失败不影响运行，只留日志。"""
        if after is not None:
            await asyncio.wait({after})
        try:
```

在 `backend/api/router.py` 中，把：

```python

from fastapi import APIRouter, Depends, Header, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

改为：

```python

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

在 `backend/api/router.py` 中，把：

```python
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """推送运行事件。浏览器断线重连时会带上 Last-Event-ID，从该序号之后继续推送。"""
    async for event in services.manager.stream(run.id, after_seq=last_event_id or 0):
        yield ServerSentEvent(data=event.model_dump(mode="json"), id=str(event.seq))
```

改为：

```python
    last_event_id: Annotated[int | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
) -> AsyncIterator[ServerSentEvent]:
    """推送运行事件，从 after 之后开始（页面已从界面历史显示了前面的部分）。
    浏览器断线重连时会带上 Last-Event-ID（总在 after 之后），从该序号之后继续推送。"""
    after_seq = max(after, last_event_id or 0)
    async for event in services.manager.stream(run.id, after_seq=after_seq):
        yield ServerSentEvent(data=event.model_dump(mode="json"), id=str(event.seq))
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_run_control.py backend/tests/test_compaction.py -q`

运行：`uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：全部通过。

- [ ] **步骤 5：重新生成前端类型，更新架构规范**

运行：`make types`

在 `docs/development/architecture.md` 中，把：

```markdown
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即写入 `llm_usage`（写库失败只记日志、不影响对话）；`run.finished` 带本次合计并写入 `runs.usage`。费用取网关算好的 `response_cost`，未知为空。被停止的那次模型调用拿不到用量：运行跟踪器按发送的内容（含工具定义）与已输出的文字估算，并用该模型最近一次"实际 / 估算"的比例校准，随 `run.finished` 的 `interrupted` 字段显示在"已停止"旁——只用于显示，不写用量表、不计入合计。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。收尾（写库、推送结束事件）单独成任务并挡住取消，重复的停止请求只生效一次——否则连点停止或回答刚结束时点停止，运行会一直停在"运行中"、会话被卡住。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
4. **被打断的一轮**：停止或服务停止时，主智能体已输出的部分连同一段中断说明写进对话存档（说明的意思是"任务在此中断；用户要继续就接着已完成的部分往下做，提了别的要求就按新要求处理"），是否继续由用户的下一句话决定。没有输出文字或崩溃等来不及写入时，由中断标记中间件在下一次运行开始前补上同样的说明（被打断的工具调用由 deepagents 的 `PatchToolCallsMiddleware` 补结果）。
5. **界面历史**：运行中写入的是原始事件（进程中途退出也不丢已推送内容）；结束时替换为合并版本（同一段回答 / 思考的逐字片段合并，带 `full_text`）。补发时若历史里没有结束事件，补一个失败的结束事件，前端才会停止重连。

```

改为：

```markdown
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即在后台写入 `llm_usage`（写库失败只记日志、不影响对话；收尾时等它们写完再推送结束事件）。处理事件的循环里不能有真正的等待（写库等放后台）：停止信号要落在智能体内部，才能把已输出的部分存进对话存档；`run.finished` 带本次合计并写入 `runs.usage`。费用取网关算好的 `response_cost`，未知为空。被停止的那次模型调用拿不到用量：运行跟踪器按发送的内容（含工具定义）与已输出的文字估算，并用该模型最近一次"实际 / 估算"的比例校准，随 `run.finished` 的 `interrupted` 字段显示在"已停止"旁——只用于显示，不写用量表、不计入合计。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。收尾（写库、推送结束事件）单独成任务并挡住取消，重复的停止请求（含停止后紧接着服务停止）只生效一次——否则连点停止或回答刚结束时点停止，运行会一直停在"运行中"、会话被卡住。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
4. **被打断的一轮**：停止或服务停止时，主智能体已输出的部分连同一段中断说明写进对话存档（说明的意思是"任务在此中断；用户要继续就接着已完成的部分往下做，提了别的要求就按新要求处理"），是否继续由用户的下一句话决定。没有输出文字或崩溃等来不及写入时，由中断标记中间件在下一次运行开始前补上同样的说明（被打断的工具调用由 deepagents 的 `PatchToolCallsMiddleware` 补结果）。
5. **界面历史**：运行中写入的是原始事件（进程中途退出也不丢已推送内容）；结束时替换为合并版本（每个智能体分别合并同一段回答 / 思考的逐字片段，带 `full_text`，text 是这段内容到此为止的全文；并行子智能体的片段交错也各自合并）。补发时若历史里没有结束事件，补一个失败的结束事件，前端才会停止重连。没有后台任务的运行被停止时，也存下并推送结束事件。
6. **续传**：页面打开时进行中的运行，已存的事件由界面历史重建，推送从最后一个已存事件之后订阅（`/api/runs/{id}/events?after=<序号>`），否则文字会重复；断线重连时浏览器带的 `Last-Event-ID` 优先。前端按消息 ID 合并逐字片段（中间夹了用量等事件也不拆开）。

```

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 95 个、前端 54 个）；`make test-int` 全部通过（48 个）。

---

### 任务 4：前端发送、停止与续传

**文件：**
- 修改：`frontend/src/features/chat/reducer.ts`、`frontend/src/api/events.ts`、`frontend/src/features/chat/ChatView.tsx`、`frontend/src/components/chat/ChatThread.tsx`
- 测试：`frontend/src/features/chat/reducer.test.ts`、`frontend/src/api/events.test.ts`（新）

**接口：**
- 消费：任务 3 的 `?after=`。
- 产出：
  - `activeRun(runs: RunHistory[]) -> { id, afterSeq } | null`：界面历史里进行中的运行，以及它最后一个已存事件的序号；
  - `subscribeRun(runId, afterSeq, onEvent)`。
- 移除：`addSendError` 与错误项的 `transient`。发送、停止失败不再进对话，改由 `ChatThread` 的 `notice` / `onDismissNotice` 显示在输入框上方。
- 规则：
  - 逐字片段按消息 ID 找到原来的项再追加或替换，中间夹了别的项也不拆开；
  - 发送请求还没返回就点停止：记下，拿到运行 ID 后立即停止；
  - 发送遇到 409：以服务器为准重建对话并接上进行中的运行；
  - 发送失败恢复原文时，只在输入框为空时恢复。

- [ ] **步骤 1：写失败的测试**

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
import {
  addSendError,
  addUserMessage,
```

改为：

```ts
import {
  activeRun,
  addUserMessage,
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts

describe("发送失败的提示", () => {
  it("再次发送时清除上一次发送失败的提示，之前的回答不再显示为失败", () => {
    const answered = events.reduce(applyEvent, addUserMessage(emptyChat, "u1", "hi"));
    const failed = addSendError(answered, "send-err", "无法连接到后端，请确认服务已启动");
    expect(failed.items.at(-1)).toMatchObject({ kind: "error", id: "send-err" });

    const retried = addUserMessage(failed, "u2", "再试一次");
    expect(retried.items.map((item) => item.id)).toEqual([
      ...answered.items.map((item) => item.id),
      "u2",
    ]);
  });

  it("运行本身的失败记录不会被清除", () => {
    const failedRun = applyEvent(addUserMessage(emptyChat, "u1", "hi"), {
      ...base,
      seq: 1,
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用", usage: null, interrupted: null },
    });
    const next = addUserMessage(failedRun, "u2", "再问一次");
    expect(next.items.some((item) => item.kind === "error")).toBe(true);
  });
```

改为：

```ts

describe("页面打开时进行中的运行", () => {
  const run = (status: RunHistory["status"], events: EventEnvelope[]): RunHistory => ({
    id: "r1",
    thread_id: "t1",
    status,
    model: "claude-opus-4-6",
    message: "hi",
    error: null,
    created_at: "2026-10-12T00:00:00Z",
    events,
  });

  it("没有进行中的运行时不订阅", () => {
    expect(activeRun([run("completed", events)])).toBeNull();
  });

  it("从最后一个已存事件之后接着订阅：已存的部分由历史重建，重放会让文字重复", () => {
    const stored = events.slice(0, 4); // 运行到「你」
    const history = [run("running", stored)];
    expect(activeRun(history)).toEqual({ id: "r1", afterSeq: 4 });

    const later: EventEnvelope = {
      ...base,
      seq: 5,
      type: "message.delta",
      data: { message_id: "m1", text: "好" },
    };
    const state = applyEvent(chatFromHistory(history), later);
    expect(state.items.filter((item) => item.kind === "assistant")).toEqual([
      { kind: "assistant", id: "msg-m1", text: "你好" },
    ]);
    expect(state.running).toBe(true);
  });

  it("还没存下任何事件时从头订阅", () => {
    expect(activeRun([run("queued", [])])).toEqual({ id: "r1", afterSeq: 0 });
  });
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
    expect(state.items).toEqual([{ kind: "usage", id: "usage-r1-7", usage }]);
  });
});

```

改为：

```ts
    expect(state.items).toEqual([{ kind: "usage", id: "usage-r1-7", usage }]);
  });

  it("同一段回答中间夹了用量事件：仍接在原来的气泡里，不拆成两个", () => {
    const sequence: EventEnvelope[] = [
      { ...base, seq: 1, type: "message.delta", data: { message_id: "m1", text: "你" } },
      { ...base, seq: 2, type: "usage", data: usage },
      { ...base, seq: 3, type: "message.delta", data: { message_id: "m1", text: "好" } },
    ];
    const { items } = sequence.reduce(applyEvent, emptyChat);
    expect(items.map((item) => [item.kind, item.kind === "assistant" ? item.text : ""])).toEqual([
      ["assistant", "你好"],
      ["usage", ""],
    ]);
  });

  it("界面历史里被分成几组的同一段回答（后一组带到此为止的全文）：整体替换，不重复", () => {
    const sequence: EventEnvelope[] = [
      {
        ...base,
        seq: 1,
        type: "message.delta",
        data: { message_id: "m1", text: "你", full_text: true },
      },
      { ...base, seq: 2, type: "usage", data: usage },
      {
        ...base,
        seq: 3,
        type: "message.delta",
        data: { message_id: "m1", text: "你好", full_text: true },
      },
    ];
    const [answer] = sequence.reduce(applyEvent, emptyChat).items;
    expect(answer).toEqual({ kind: "assistant", id: "msg-m1", text: "你好" });
  });
});

```

新建 `frontend/src/api/events.test.ts`：

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { subscribeRun } from "./events";

describe("subscribeRun", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("从已显示的最后一个事件之后订阅", () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "EventSource",
      class {
        onmessage: unknown = null;
        constructor(url: string) {
          urls.push(url);
        }
        close() {}
      },
    );
    const stop = subscribeRun("r1", 4, () => undefined);
    expect(urls).toEqual(["/api/runs/r1/events?after=4"]);
    stop();
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/chat src/api/events.test.ts`（预期失败）

预期：
- `activeRun is not a function`（3 个）；
- 两个"同一段回答中间夹了用量事件"的测试失败（拆成了两个气泡 / 重复）；
- 订阅地址缺少 `?after=4`。

- [ ] **步骤 3：实现**

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  RunHistory,
  TodoItem,
```

改为：

```ts
  RunHistory,
  RunStatus,
  TodoItem,
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  | { kind: "stopped"; id: string; interrupted?: InterruptedUsage }
  // transient：发送请求本身失败（不是运行失败），下次发送时清除
  | {
      kind: "error";
      id: string;
      text: string;
      transient?: boolean;
      interrupted?: InterruptedUsage;
    };

```

改为：

```ts
  | { kind: "stopped"; id: string; interrupted?: InterruptedUsage }
  // 运行失败（发送、停止请求本身失败不算：它们显示在输入框上方，不进对话）
  | { kind: "error"; id: string; text: string; interrupted?: InterruptedUsage };

```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts

/** 追加用户消息；同时清除上一次发送失败的提示，免得它一直挂在之前的回答下面。 */
export function addUserMessage(state: ChatState, id: string, text: string): ChatState {
  const items = state.items.filter((item) => !(item.kind === "error" && item.transient));
  return { ...state, items: [...items, { kind: "user", id, text }] };
}
```

改为：

```ts

export function addUserMessage(state: ChatState, id: string, text: string): ChatState {
  return { ...state, items: [...state.items, { kind: "user", id, text }] };
}
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  return { items: [...state.items, { kind: "error", id, text }], running: false };
}

/** 发送请求失败（后端连不上、会话已有运行等）的提示；下次发送时自动清除。 */
export function addSendError(state: ChatState, id: string, text: string): ChatState {
  return { items: [...state.items, { kind: "error", id, text, transient: true }], running: false };
}
```

改为：

```ts
  return { items: [...state.items, { kind: "error", id, text }], running: false };
}
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts

/** 逐字片段：接在同一段内容后面；full_text 为 true 时（界面历史里合并过的片段）整体替换。 */
function appendDelta(
```

改为：

```ts

/**
 * 逐字片段：按 ID 接在同一段内容后面（中间夹了用量等事件也不拆开）；
 * full_text 为 true 时（界面历史里合并过的片段，text 是到此为止的全文）整体替换。
 */
function appendDelta(
```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
): ChatItem[] {
  const last = items.at(-1);
  if (last?.kind === kind && last.id === id) {
    const text = data.full_text ? data.text : last.text + data.text;
    return [...items.slice(0, -1), { ...last, text }];
  }
  return [...items, { kind, id, text: data.text }];
}
```

改为：

```ts
): ChatItem[] {
  const index = items.findLastIndex((item) => item.id === id);
  const existing = items[index];
  if (existing?.kind !== kind) return [...items, { kind, id, text: data.text }];
  const text = data.full_text ? data.text : existing.text + data.text;
  return items.with(index, { ...existing, text });
}

const ACTIVE_STATUSES = new Set<RunStatus>(["queued", "running", "interrupted"]);

/**
 * 界面历史里进行中的运行（页面打开时它还在跑）：推送从最后一个已存事件之后接着订阅，
 * 已存的部分已由界面历史重建，从头订阅会让文字重复。
 */
export function activeRun(runs: RunHistory[]): { id: string; afterSeq: number } | null {
  const run = runs.find((item) => ACTIVE_STATUSES.has(item.status));
  return run ? { id: run.id, afterSeq: run.events.at(-1)?.seq ?? 0 } : null;
}
```

`frontend/src/api/events.ts`（整个替换）：

```ts
import type { EventEnvelope } from "./types";

/**
 * 订阅一次运行的推送，从第 afterSeq 个事件之后开始（之前的已从界面历史显示）；
 * 收到 run.finished 后主动关闭，避免浏览器自动重连。
 */
export function subscribeRun(
  runId: string,
  afterSeq: number,
  onEvent: (event: EventEnvelope) => void,
): () => void {
  const source = new EventSource(`/api/runs/${runId}/events?after=${afterSeq}`);
  source.onmessage = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as EventEnvelope;
    onEvent(event);
    if (event.type === "run.finished") source.close();
  };
  return () => source.close();
}
```

`frontend/src/features/chat/ChatView.tsx`（整个替换）：

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, readableError } from "../../api/client";
import { subscribeRun } from "../../api/events";
import { historyQuery, threadUsageQuery } from "../../api/queries";
import type { RunHistory, Thread } from "../../api/types";
import { ChatThread } from "../../components/chat";
import { ModelSelect } from "../models/ModelSelect";
import { ThreadUsageBadge } from "../usage/ThreadUsageBadge";
import {
  activeRun,
  addUserMessage,
  applyEvent,
  chatFromHistory,
  removeItem,
  type ChatState,
} from "./reducer";

function ChatSession({ thread, history }: { thread: Thread; history: RunHistory[] }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ChatState>(() => chatFromHistory(history));
  const [model, setModel] = useState(thread.model);
  // 正在订阅的运行；afterSeq 之前的事件已经显示（来自界面历史）
  const [active, setActive] = useState(() => activeRun(history));
  // 发送、停止请求本身的失败（不是运行失败）：显示在输入框上方，不进对话
  const [notice, setNotice] = useState<string | null>(null);
  // 发送请求还没返回运行 ID 时就点了停止：拿到 ID 后立即停止
  const stopWhenStarted = useRef(false);

  useEffect(() => {
    if (!active) return;
    return subscribeRun(active.id, active.afterSeq, (event) => {
      setState((current) => applyEvent(current, event));
      if (event.type === "run.finished") {
        setActive(null);
        void queryClient.invalidateQueries({ queryKey: threadUsageQuery(thread.id).queryKey });
      }
    });
  }, [active, queryClient, thread.id]);

  /** 以服务器为准重建对话，并接上进行中的运行（例如在另一个标签页发起的）。 */
  const resync = async (): Promise<void> => {
    const latest = await api.history(thread.id).catch(() => null);
    if (!latest) return;
    setState(chatFromHistory(latest));
    setActive(activeRun(latest));
  };

  const stop = async (runId: string): Promise<void> => {
    try {
      await api.cancelRun(runId);
    } catch (error) {
      setNotice(`停止失败：${readableError(error)}`);
    }
  };

  /** 发送成功返回 true；失败时撤回乐观显示的消息并提示原因，返回 false 让输入框恢复原文。 */
  const send = async (text: string): Promise<boolean> => {
    const userId = `user-${Date.now()}`;
    setNotice(null);
    stopWhenStarted.current = false;
    setState((current) => ({ ...addUserMessage(current, userId, text), running: true }));
    try {
      const run = await api.startRun(thread.id, text, model);
      setActive({ id: run.id, afterSeq: 0 });
      if (stopWhenStarted.current) void stop(run.id);
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
      return true;
    } catch (error) {
      setNotice(`发送失败：${readableError(error)}`);
      setState((current) => ({ ...removeItem(current, userId), running: false }));
      if (error instanceof ApiError && error.status === 409) void resync(); // 会话已有进行中的运行
      return false;
    } finally {
      stopWhenStarted.current = false;
    }
  };

  /** 停止当前运行；结果（已停止）随推送到达。 */
  const cancel = async (): Promise<void> => {
    if (active) await stop(active.id);
    else stopWhenStarted.current = true; // 发送请求还没返回
  };

  return (
    <>
      <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
        <h1 className="truncate font-medium">{thread.title || "新会话"}</h1>
        <div className="flex shrink-0 items-center gap-4">
          <ThreadUsageBadge threadId={thread.id} />
          <ModelSelect value={model} onChange={setModel} />
        </div>
      </header>
      <ChatThread
        state={state}
        notice={notice}
        onDismissNotice={() => setNotice(null)}
        onSend={send}
        onCancel={cancel}
      />
    </>
  );
}

export function ChatView({ thread }: { thread: Thread }) {
  const history = useQuery(historyQuery(thread.id));
  if (history.isError) {
    return <p className="p-6 text-sm text-danger">历史加载失败：{readableError(history.error)}</p>;
  }
  if (!history.data) {
    return (
      <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        加载中…
      </p>
    );
  }
  return <ChatSession key={thread.id} thread={thread} history={history.data} />;
}
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
} from "@assistant-ui/react";
import { ArrowUp, Sparkles, Square } from "lucide-react";
import type { ChatState } from "../../features/chat/reducer";
```

改为：

```tsx
} from "@assistant-ui/react";
import { ArrowUp, Sparkles, Square, X } from "lucide-react";
import type { ChatState } from "../../features/chat/reducer";
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
  state: ChatState;
  /** 发送成功返回 true；失败返回 false 时输入框恢复原文，方便直接重试。 */
  onSend: (text: string) => Promise<boolean>;
```

改为：

```tsx
  state: ChatState;
  /** 输入框上方的提示（如发送失败的原因），可关闭。 */
  notice: string | null;
  onDismissNotice: () => void;
  /** 发送成功返回 true；失败返回 false 时输入框恢复原文（用户已在输入新内容时不覆盖）。 */
  onSend: (text: string) => Promise<boolean>;
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({ state, onSend, onCancel }: ChatThreadProps) {
  const runtime = useExternalStoreRuntime({
```

改为：

```tsx
/** 对话区：消息列表 + 输入框。assistant-ui 只在 components/chat/ 这一层使用（设计文档 13.1）。 */
export function ChatThread({ state, notice, onDismissNotice, onSend, onCancel }: ChatThreadProps) {
  const runtime = useExternalStoreRuntime({
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
      const text = message.content.map((part) => (part.type === "text" ? part.text : "")).join("");
      if (!(await onSend(text))) runtime.thread.composer.setText(text);
    },
```

改为：

```tsx
      const text = message.content.map((part) => (part.type === "text" ? part.text : "")).join("");
      const composer = runtime.thread.composer;
      if (!(await onSend(text)) && !composer.getState().text) composer.setText(text);
    },
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
```

改为：

```tsx
        <div className="mx-auto w-full max-w-3xl px-6 pb-6">
          {notice && (
            <div
              role="alert"
              className="mb-2 flex items-center gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
            >
              <span className="flex-1">{notice}</span>
              <button
                aria-label="关闭提示"
                className="rounded-md p-0.5 hover:bg-danger/10"
                onClick={onDismissNotice}
              >
                <X className="size-3.5" />
              </button>
            </div>
          )}
          <ComposerPrimitive.Root className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg focus-within:border-ring">
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/features/chat src/api/events.test.ts`

预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`

预期：全部通过（Python 单元测试 95 个、前端 58 个）。对话区的交互在任务 9 的浏览器验证里检查。

---

### 任务 5：用量细节

**文件：**
- 新建：`backend/migrations/versions/0004_backend_interrupted_usage.py`
- 修改：
  - agents：`agents/main_agent/runtime/tracker.py`、`agent.py`、`events.py`；
  - backend：`backend/runs/manager.py`、`conftest.py`；
  - 前端：`frontend/src/features/chat/reducer.ts`、`frontend/src/components/chat/adapter.ts`、`parts.tsx`；
  - 文档：`docs/development/architecture.md`。
- 测试：`agents/tests/test_tracker.py`、`backend/tests/test_migrations.py`、`test_manager.py`、`test_api.py`、`test_event_bus.py`；`frontend/src/features/chat/reducer.test.ts`、`frontend/src/components/chat/adapter.test.ts`
- 生成：`frontend/src/api/generated/*`

**接口：**
- 产出：
  - `Calibration(token_ratio: float = 1.0, input_price: float | None = None)`（`agents/main_agent/runtime/tracker.py`）；
  - `RunTracker(calibration: dict[str, Calibration] | None, model_info)`；
  - 根目录夹具 `alembic_config`（指向测试库的迁移配置，会话级）。
- 改名：
  - `RunFinished.interrupted` → `interrupted_usage`（迁移 0004 改写已存的结束事件，并给缺 `usage` / `interrupted_usage` 的补上 `null`）；
  - 前端事件处理器里的项字段 `interrupted` → `interruptedUsage`；消息自定义信息 `custom.interrupted` → `custom.interruptedUsage`。
- 规则：
  - 每次调用结束时，由实际费用反推平均输入价格：`(cost − output_tokens × 输出单价) / input_tokens`，不小于 0。估算时优先用它，没有再用登记价格。
  - 估算输入 token 失败时，一次运行只记一条警告。

- [ ] **步骤 1：写失败的测试**

在 `agents/tests/test_tracker.py` 中，把：

```python
from agents.main_agent.runtime import UsageReported
from agents.main_agent.runtime.tracker import RunTracker

```

改为：

```python
from agents.main_agent.runtime import UsageReported
from agents.main_agent.runtime.tracker import Calibration, RunTracker

```

在 `agents/tests/test_tracker.py` 中，把：

```python
async def test_interrupted_call_is_estimated_with_calibration_and_price() -> None:
    calibration: dict[str, float] = {}
    prices = ModelInfo(name="m", input_cost_per_token=1e-6, output_cost_per_token=2e-6)
```

改为：

```python
async def test_interrupted_call_is_estimated_with_calibration_and_price() -> None:
    calibration: dict[str, Calibration] = {}
    prices = ModelInfo(name="m", input_cost_per_token=1e-6, output_cost_per_token=2e-6)
```

在 `agents/tests/test_tracker.py` 中，把：

```python
    await tracker.on_llm_end(_result({**USAGE, "input_tokens": raw_input * 2}, {}), run_id=first)
    assert calibration == {"m": 2.0}
    assert tracker.interrupted_usage() is None  # 已结束的调用不算被中断
```

改为：

```python
    await tracker.on_llm_end(_result({**USAGE, "input_tokens": raw_input * 2}, {}), run_id=first)
    assert calibration["m"].token_ratio == 2.0
    assert tracker.interrupted_usage() is None  # 已结束的调用不算被中断
```

在 `agents/tests/test_tracker.py` 末尾追加：

```python


async def test_interrupted_cost_reflects_prompt_cache_discount() -> None:
    """开启提示缓存时大部分输入按缓存价计费：估算按上一次调用实际的平均输入价格，而不是登记价格，
    否则显示的"约 $"会比实际高好几倍。"""
    prices = ModelInfo(name="m", input_cost_per_token=3e-6, output_cost_per_token=15e-6)
    tracker = RunTracker(calibration={}, model_info=lambda name: prices)
    metadata = {"ls_model_name": "litellm_proxy/m"}
    messages: list[BaseMessage] = [HumanMessage("写一篇长文")]
    # 上一次调用：1000 个输入里 900 个读缓存（按登记价格的十分之一计费），网关报的实际费用
    cost = 100 * 3e-6 + 900 * 0.3e-6 + 10 * 15e-6
    usage = {
        "input_tokens": 1000,
        "output_tokens": 10,
        "total_tokens": 1010,
        "input_token_details": {"cache_read": 900},
    }
    first = uuid4()
    await tracker.on_chat_model_start({}, [messages], run_id=first, metadata=metadata)
    await tracker.on_llm_end(_result(usage, {"response_cost": cost}), run_id=first)

    second = uuid4()
    await tracker.on_chat_model_start({}, [messages], run_id=second, metadata=metadata)
    estimate = tracker.interrupted_usage()

    assert estimate is not None
    assert estimate.output_tokens == 0
    average_input_price = (cost - 10 * 15e-6) / 1000  # 去掉输出部分，摊到每个输入 token
    assert estimate.cost == pytest.approx(estimate.input_tokens * average_input_price)


async def test_estimate_failure_is_logged_once_per_run(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """估算失败（如遇到不认识的消息格式）只提示一次，不在每次模型调用时都刷一遍错误堆栈。"""

    def broken(*args: object) -> int:
        raise ValueError("不认识的内容")

    monkeypatch.setattr("agents.main_agent.runtime.tracker.estimate_input_tokens", broken)
    tracker = RunTracker()
    for _ in range(3):
        await tracker.on_chat_model_start({}, [[HumanMessage("hi")]], run_id=uuid4(), metadata={})

    assert [r.levelname for r in caplog.records] == ["WARNING"]
```

迁移测试需要退回到旧版本再升级：根目录夹具拆出 `alembic_config`：

在 `conftest.py` 中，把：

```python
@pytest.fixture(scope="session")
async def pg_pool() -> AsyncIterator[Pool]:
    alembic_config = Config(toml_file="pyproject.toml")
    alembic_config.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(alembic_config, "head")
```

改为：

```python
@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """指向测试库的迁移配置；迁移测试用它退回到旧版本、写入旧数据再升级。"""
    config = Config(toml_file="pyproject.toml")
    config.attributes["database_url"] = TEST_DATABASE_URL
    return config


@pytest.fixture(scope="session")
async def pg_pool(alembic_config: Config) -> AsyncIterator[Pool]:
    command.upgrade(alembic_config, "head")
```

在 `backend/tests/test_migrations.py` 中，把：

```python
import pytest

from common.db import Pool
```

改为：

```python
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from backend.runs import RunRepo
from backend.threads import ThreadRepo
from common.db import Pool
```

在 `backend/tests/test_migrations.py` 末尾追加：

```python


async def test_finished_events_use_interrupted_usage(db: Pool, alembic_config: Config) -> None:
    """0004：已存结束事件的 interrupted 改名为 interrupted_usage（与运行状态 interrupted 区分）；
    M1b 之前存下的结束事件补齐 usage / interrupted_usage（前端类型把它们标为必有）。"""
    estimate = {"input_tokens": 5, "output_tokens": 1, "cost": None}
    old_data = [
        {"status": "completed", "error": None},  # M1b 之前
        {"status": "cancelled", "error": None, "usage": None, "interrupted": estimate},
    ]
    command.downgrade(alembic_config, "0003")
    try:
        thread = await ThreadRepo(db).create(model="m")
        run = await RunRepo(db).create(thread_id=thread.id, model="m", message="hi")
        async with db.connection() as conn:
            for seq, data in enumerate(old_data, start=1):
                payload = {
                    "seq": seq,
                    "run_id": str(run.id),
                    "ts": "2026-10-12T00:00:00Z",
                    "type": "run.finished",
                    "agent_path": ["main"],
                    "data": data,
                }
                await conn.execute(
                    "INSERT INTO run_events (run_id, seq, type, payload) VALUES (%s, %s, %s, %s)",
                    (run.id, seq, "run.finished", Jsonb(payload)),
                )
        command.upgrade(alembic_config, "0004")
    finally:
        command.upgrade(alembic_config, "head")

    assert [e.data for e in await RunRepo(db).events(run.id)] == [
        {"status": "completed", "error": None, "usage": None, "interrupted_usage": None},
        {"status": "cancelled", "error": None, "usage": None, "interrupted_usage": estimate},
    ]
```

在 `backend/tests/test_manager.py` 中，把：

```python
    # 被中断那次调用的估算随结束事件推送（刷新后从界面历史重现），但不写用量表、不计入合计
    assert tail.data["interrupted"]["output_tokens"] > 0
    assert tail.data["usage"]["calls"] == 0
    assert await usage.for_run(run.id) == []
    assert (await runs.events(run.id))[-1].data["interrupted"] == tail.data["interrupted"]

```

改为：

```python
    # 被中断那次调用的估算随结束事件推送（刷新后从界面历史重现），但不写用量表、不计入合计
    assert tail.data["interrupted_usage"]["output_tokens"] > 0
    assert tail.data["usage"]["calls"] == 0
    assert await usage.for_run(run.id) == []
    stored = (await runs.events(run.id))[-1]
    assert stored.data["interrupted_usage"] == tail.data["interrupted_usage"]

```

在 `backend/tests/test_api.py` 中，把：

```python
            "usage": None,
            "interrupted": None,
        }
```

改为：

```python
            "usage": None,
            "interrupted_usage": None,
        }
```

在 `backend/tests/test_event_bus.py` 中，把：

```python
        "usage": None,
        "interrupted": None,
    }
```

改为：

```python
        "usage": None,
        "interrupted_usage": None,
    }
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
    type: "run.finished",
    data: { status: "completed", error: null, usage: null, interrupted: null },
  },
```

改为：

```ts
    type: "run.finished",
    data: { status: "completed", error: null, usage: null, interrupted_usage: null },
  },
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用", usage: null, interrupted: null },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "failed", error: "模型网关不可用", usage: null, interrupted_usage: null },
    };
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null, interrupted: null },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null, interrupted_usage: null },
    };
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
describe("被中断调用的估算用量", () => {
  const interrupted = { input_tokens: 4600, output_tokens: 320, cost: 0.03 };

```

改为：

```ts
describe("被中断调用的估算用量", () => {
  const estimate = { input_tokens: 4600, output_tokens: 320, cost: 0.03 };

```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null, interrupted },
    };
    expect(applyEvent(emptyChat, cancelled).items).toEqual([
      { kind: "stopped", id: "stopped-r1", interrupted },
    ]);
```

改为：

```ts
      type: "run.finished",
      data: { status: "cancelled", error: null, usage: null, interrupted_usage: estimate },
    };
    expect(applyEvent(emptyChat, cancelled).items).toEqual([
      { kind: "stopped", id: "stopped-r1", interruptedUsage: estimate },
    ]);
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "failed", error: "服务停止，运行被中断", usage: null, interrupted },
    };
    expect(applyEvent(emptyChat, failed).items).toEqual([
      { kind: "error", id: "err-r1", text: "服务停止，运行被中断", interrupted },
    ]);
```

改为：

```ts
      type: "run.finished",
      data: {
        status: "failed",
        error: "服务停止，运行被中断",
        usage: null,
        interrupted_usage: estimate,
      },
    };
    expect(applyEvent(emptyChat, failed).items).toEqual([
      { kind: "error", id: "err-r1", text: "服务停止，运行被中断", interruptedUsage: estimate },
    ]);
```

在 `frontend/src/features/chat/reducer.test.ts` 中，把：

```ts
      type: "run.finished",
      data: { status: "completed", error: null, usage: null, interrupted: null },
    };
```

改为：

```ts
      type: "run.finished",
      data: { status: "completed", error: null, usage: null, interrupted_usage: null },
    };
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
  it("放进消息的自定义信息，与本轮实际用量分开", () => {
    const interrupted = { input_tokens: 4600, output_tokens: 320, cost: null };
    const state: ChatState = {
```

改为：

```ts
  it("放进消息的自定义信息，与本轮实际用量分开", () => {
    const interruptedUsage = { input_tokens: 4600, output_tokens: 320, cost: null };
    const state: ChatState = {
```

在 `frontend/src/components/chat/adapter.test.ts` 中，把：

```ts
        { kind: "assistant", id: "msg-m1", text: "写到一半" },
        { kind: "stopped", id: "stopped-r1", interrupted },
      ],
    };
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.metadata?.custom).toEqual({ usage: undefined, stopped: true, interrupted });
  });
```

改为：

```ts
        { kind: "assistant", id: "msg-m1", text: "写到一半" },
        { kind: "stopped", id: "stopped-r1", interruptedUsage },
      ],
    };
    const [, assistant] = toThreadMessages(state);
    expect(assistant?.metadata?.custom).toEqual({
      usage: undefined,
      stopped: true,
      interruptedUsage,
    });
  });
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_tracker.py backend/tests/test_event_bus.py -q`（预期失败）

预期：`ImportError: cannot import name 'Calibration'`；`test_event_bus` 的结束事件字段不符。

运行：`uv run pytest -m integration backend/tests/test_migrations.py -q`（预期失败）

预期：`No such revision or branch '0004'`。

运行：`cd frontend && pnpm exec vitest run src/features/chat src/components/chat`（预期失败）

预期：停止 / 失败项上没有 `interruptedUsage`、自定义信息没有 `interruptedUsage`。

- [ ] **步骤 3：实现**

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
3. 运行被中断时，估算尚未结束的调用的用量：中断后网关不返回用量，按发送的内容与已输出的文字
   粗略估算，再用该模型最近一次"实际 / 估算"的比例校准，价格取网关登记的价格。
"""
```

改为：

```python
3. 运行被中断时，估算尚未结束的调用的用量：中断后网关不返回用量，按发送的内容与已输出的文字
   粗略估算，再用该模型最近一次完成的调用校准：token 数按"实际 / 估算"的比例，输入价格按实际的
   平均输入价格（开启提示缓存时远低于登记价格）；没有校准值时用网关登记的价格。
"""
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
@dataclass
class _Call:
```

改为：

```python
@dataclass
class Calibration:
    """某个模型版本最近一次完成的调用留下的校准值，由同一个主智能体的各次运行共享。"""

    token_ratio: float = 1.0  # 实际输入 / 粗略估算的输入
    input_price: float | None = None  # 实际的平均每输入 token 价格（含缓存读写的折扣与加价）


@dataclass
class _Call:
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
        *,
        calibration: dict[str, float] | None = None,
        model_info: Callable[[str], ModelInfo | None] | None = None,
```

改为：

```python
        *,
        calibration: dict[str, Calibration] | None = None,
        model_info: Callable[[str], ModelInfo | None] | None = None,
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
        self._usage: list[UsageReported] = []
        # 模型版本 → "实际输入 / 估算输入"，由同一个主智能体的各次运行共享
        self._calibration = calibration if calibration is not None else {}
        self._model_info = model_info

```

改为：

```python
        self._usage: list[UsageReported] = []
        self._calibration = calibration if calibration is not None else {}  # 模型版本 → 校准值
        self._model_info = model_info
        self._estimate_failed = False

```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
        except Exception:  # 估算只用于中断时显示，失败不能影响调用本身
            logger.exception("估算输入 token 失败")
            estimated = 0
```

改为：

```python
        except Exception:  # 估算只用于中断时显示，失败不能影响调用本身
            if not self._estimate_failed:  # 每次调用都会遇到同样的内容：一次运行只提示一次
                self._estimate_failed = True
                logger.warning("估算输入 token 失败，本次运行不再提示", exc_info=True)
            estimated = 0
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
            model = version_name(call.metadata.get("ls_model_name") or "")
            ratio = self._calibration.get(model, 1.0)
            call_input = round(call.estimated_input * ratio)
            call_output = round(estimate_text_tokens("".join(call.output)) * ratio)
            input_tokens += call_input
            output_tokens += call_output
            info = self._model_info(model) if self._model_info else None
            if (
                cost is None
                or info is None
                or None
                in (
                    info.input_cost_per_token,
                    info.output_cost_per_token,
                )
            ):
                cost = None
            else:
                assert info.input_cost_per_token is not None
                assert info.output_cost_per_token is not None
                cost += (
                    call_input * info.input_cost_per_token
                    + call_output * info.output_cost_per_token
                )
        return InterruptedUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost=cost)
```

改为：

```python
            model = version_name(call.metadata.get("ls_model_name") or "")
            calibration = self._calibration.get(model, Calibration())
            call_input = round(call.estimated_input * calibration.token_ratio)
            call_output = round(
                estimate_text_tokens("".join(call.output)) * calibration.token_ratio
            )
            input_tokens += call_input
            output_tokens += call_output
            info = self._model_info(model) if self._model_info else None
            input_price = calibration.input_price
            if input_price is None and info is not None:
                input_price = info.input_cost_per_token
            output_price = info.output_cost_per_token if info is not None else None
            if cost is None or input_price is None or output_price is None:
                cost = None
            else:
                cost += call_input * input_price + call_output * output_price
        return InterruptedUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost=cost)
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
        requested = version_name(metadata.get("ls_model_name") or "")
        if call and call.estimated_input:
            self._calibration[requested] = usage["input_tokens"] / call.estimated_input
        # 命名空间形如 "tools:<子智能体>|model:<本次调用>"，去掉最后一段即调用方所在的智能体
```

改为：

```python
        requested = version_name(metadata.get("ls_model_name") or "")
        cost = message.response_metadata.get("response_cost")
        self._calibrate(requested, call, usage["input_tokens"], usage["output_tokens"], cost)
        # 命名空间形如 "tools:<子智能体>|model:<本次调用>"，去掉最后一段即调用方所在的智能体
```

在 `agents/main_agent/runtime/tracker.py` 中，把：

```python
                reasoning_tokens=output_details.get("reasoning", 0),
                cost=message.response_metadata.get("response_cost"),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )

```

改为：

```python
                reasoning_tokens=output_details.get("reasoning", 0),
                cost=cost,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )

    def _calibrate(
        self,
        model: str,
        call: _Call | None,
        input_tokens: int,
        output_tokens: int,
        cost: float | None,
    ) -> None:
        calibration = self._calibration.setdefault(model, Calibration())
        if call and call.estimated_input:
            calibration.token_ratio = input_tokens / call.estimated_input
        info = self._model_info(model) if self._model_info else None
        output_price = info.output_cost_per_token if info is not None else None
        if cost is not None and output_price is not None and input_tokens > 0:
            # 实际费用去掉输出部分，摊到每个输入 token 上
            calibration.input_price = max(cost - output_tokens * output_price, 0.0) / input_tokens

```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
)
from agents.main_agent.runtime.tracker import RunTracker
from agents.main_agent.runtime.translator import Translator
```

改为：

```python
)
from agents.main_agent.runtime.tracker import Calibration, RunTracker
from agents.main_agent.runtime.translator import Translator
```

在 `agents/main_agent/runtime/agent.py` 中，把：

```python
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
        self._calibration: dict[str, float] = {}  # 模型版本 → 实际 / 估算的输入 token 比例
        self._interrupted: dict[str, InterruptedUsage] = {}
```

改为：

```python
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
        self._calibration: dict[str, Calibration] = {}  # 模型版本 → 估算用量的校准值
        self._interrupted: dict[str, InterruptedUsage] = {}
```

在 `agents/main_agent/runtime/events.py` 中，把：

```python
    usage: UsageTotals | None = None
    interrupted: InterruptedUsage | None = None

```

改为：

```python
    usage: UsageTotals | None = None
    interrupted_usage: InterruptedUsage | None = None  # 被中断那次调用的估算（不计入 usage）

```

在 `backend/runs/manager.py` 中，把：

```python
            # 被中断那次模型调用的估算用量：随结束事件显示，不写用量表、不计入合计
            interrupted = self._agent.take_interrupted_usage(run_id)
            if self._stopping:
                finished = RunFinished(
                    status="failed", error=STOPPED_BY_SHUTDOWN, interrupted=interrupted
                )
            else:
                finished = RunFinished(status="cancelled", interrupted=interrupted)
            raise
```

改为：

```python
            # 被中断那次模型调用的估算用量：随结束事件显示，不写用量表、不计入合计
            estimate = self._agent.take_interrupted_usage(run_id)
            if self._stopping:
                finished = RunFinished(
                    status="failed", error=STOPPED_BY_SHUTDOWN, interrupted_usage=estimate
                )
            else:
                finished = RunFinished(status="cancelled", interrupted_usage=estimate)
            raise
```

新建 `backend/migrations/versions/0004_backend_interrupted_usage.py`：

```python
"""backend：结束事件（run.finished）的 interrupted 改名为 interrupted_usage，避免与运行状态
interrupted（等待审批，M4）混淆；M1b 之前存下的结束事件补齐 usage / interrupted_usage（值为空）。

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE run_events SET payload = jsonb_set(
            payload,
            '{data}',
            ((payload -> 'data') - 'interrupted') || jsonb_build_object(
                'usage', coalesce(payload -> 'data' -> 'usage', 'null'::jsonb),
                'interrupted_usage', coalesce(payload -> 'data' -> 'interrupted', 'null'::jsonb)
            )
        )
        WHERE type = 'run.finished'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE run_events SET payload = jsonb_set(
            payload,
            '{data}',
            ((payload -> 'data') - 'interrupted_usage') || jsonb_build_object(
                'interrupted', coalesce(payload -> 'data' -> 'interrupted_usage', 'null'::jsonb)
            )
        )
        WHERE type = 'run.finished'
        """
    )
```

运行：`make types`

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
  | { kind: "timing"; id: string; startedAt: string; finishedAt?: string }
  // interrupted：被中断那次模型调用的估算用量（只显示，不计入合计）
  | { kind: "stopped"; id: string; interrupted?: InterruptedUsage }
  // 运行失败（发送、停止请求本身失败不算：它们显示在输入框上方，不进对话）
  | { kind: "error"; id: string; text: string; interrupted?: InterruptedUsage };

```

改为：

```ts
  | { kind: "timing"; id: string; startedAt: string; finishedAt?: string }
  // interruptedUsage：被中断那次模型调用的估算用量（只显示，不计入合计）
  | { kind: "stopped"; id: string; interruptedUsage?: InterruptedUsage }
  // 运行失败（发送、停止请求本身失败不算：它们显示在输入框上方，不进对话）
  | { kind: "error"; id: string; text: string; interruptedUsage?: InterruptedUsage };

```

在 `frontend/src/features/chat/reducer.ts` 中，把：

```ts
      );
      const interrupted = event.data.interrupted ? { interrupted: event.data.interrupted } : {};
      if (event.data.status === "failed") {
```

改为：

```ts
      );
      const estimate = event.data.interrupted_usage;
      const interrupted = estimate ? { interruptedUsage: estimate } : {};
      if (event.data.status === "failed") {
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
        : undefined;
    const interrupted = group.flatMap((item) =>
      (item.kind === "stopped" || item.kind === "error") && item.interrupted
        ? [item.interrupted]
        : [],
```

改为：

```ts
        : undefined;
    const interruptedUsage = group.flatMap((item) =>
      (item.kind === "stopped" || item.kind === "error") && item.interruptedUsage
        ? [item.interruptedUsage]
        : [],
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
            : { type: "complete", reason: "stop" },
      ...(usage || stopped || interrupted || timing
        ? {
```

改为：

```ts
            : { type: "complete", reason: "stop" },
      ...(usage || stopped || interruptedUsage || timing
        ? {
```

在 `frontend/src/components/chat/adapter.ts` 中，把：

```ts
                stopped,
                ...(interrupted ? { interrupted } : {}),
                ...(timing ? { timing } : {}),
```

改为：

```ts
                stopped,
                ...(interruptedUsage ? { interruptedUsage } : {}),
                ...(timing ? { timing } : {}),
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
  const stopped = custom.stopped === true;
  const interrupted = custom.interrupted as InterruptedUsage | undefined;
  const timing = custom.timing as TurnTiming | undefined;
```

改为：

```tsx
  const stopped = custom.stopped === true;
  const interrupted = custom.interruptedUsage as InterruptedUsage | undefined;
  const timing = custom.timing as TurnTiming | undefined;
```

在 `docs/development/architecture.md` 中，把：

```markdown
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即在后台写入 `llm_usage`（写库失败只记日志、不影响对话；收尾时等它们写完再推送结束事件）。处理事件的循环里不能有真正的等待（写库等放后台）：停止信号要落在智能体内部，才能把已输出的部分存进对话存档；`run.finished` 带本次合计并写入 `runs.usage`。费用取网关算好的 `response_cost`，未知为空。被停止的那次模型调用拿不到用量：运行跟踪器按发送的内容（含工具定义）与已输出的文字估算，并用该模型最近一次"实际 / 估算"的比例校准，随 `run.finished` 的 `interrupted` 字段显示在"已停止"旁——只用于显示，不写用量表、不计入合计。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。收尾（写库、推送结束事件）单独成任务并挡住取消，重复的停止请求（含停止后紧接着服务停止）只生效一次——否则连点停止或回答刚结束时点停止，运行会一直停在"运行中"、会话被卡住。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
```

改为：

```markdown
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即在后台写入 `llm_usage`（写库失败只记日志、不影响对话；收尾时等它们写完再推送结束事件）。处理事件的循环里不能有真正的等待（写库等放后台）：停止信号要落在智能体内部，才能把已输出的部分存进对话存档；`run.finished` 带本次合计并写入 `runs.usage`。费用取网关算好的 `response_cost`，未知为空。被停止的那次模型调用拿不到用量：运行跟踪器按发送的内容（含工具定义）与已输出的文字估算，并用该模型最近一次完成的调用校准（token 数按"实际 / 估算"的比例，输入价格按实际的平均输入价格，含提示缓存的折扣），随 `run.finished` 的 `interrupted_usage` 字段显示在"已停止"旁——只用于显示，不写用量表、不计入合计。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。收尾（写库、推送结束事件）单独成任务并挡住取消，重复的停止请求（含停止后紧接着服务停止）只生效一次——否则连点停止或回答刚结束时点停止，运行会一直停在"运行中"、会话被卡住。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents/tests/test_tracker.py backend/tests/test_event_bus.py -q`

运行：`uv run pytest -m integration backend/tests/test_migrations.py backend/tests/test_manager.py backend/tests/test_api.py -q`

运行：`cd frontend && pnpm exec vitest run src/features/chat src/components/chat`

预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 97 个、前端 58 个）；`make test-int` 全部通过（49 个）。

---

### 任务 6：前端打磨

**文件：**
- 新建：`frontend/src/features/threads/menu.ts`、`menu.test.ts`
- 修改：`frontend/src/features/threads/order.ts`、`ThreadMenu.tsx`、`ThreadList.tsx`、`frontend/src/components/chat/parts.tsx`、`ChatThread.tsx`、`frontend/src/index.css`
- 测试：`frontend/src/features/threads/order.test.ts`、`frontend/src/styles/no-raw-colors.test.ts`、`frontend/src/themes/mode.test.ts`

**接口：**
- 产出：
  - `sameOrder(a, b) -> boolean`；
  - `clampToViewport(point, menuSize, viewport, margin = 8) -> point`；
  - `MenuPosition` 增加 `trigger: HTMLElement | null`（Esc 关闭后焦点回到它）。
- 规则：
  - 会话列表：
    - 拖完顺序没变时不保存；保存前取消正在进行的列表刷新；最后一次保存结束后再以服务器为准刷新；
    - 重命名时右键不打开菜单；
    - 菜单打开时再点"⋯"是收起；
    - 侧栏的新建 / 重命名 / 排序失败提示 5 秒后自动消失。
  - 操作菜单：打开后焦点在第一项，上下方向键循环切换；Esc 关闭；Tab 移出时关闭；靠近窗口边缘时收回窗口内。
  - 对话区：消息转换用 `useMemo`；复制按钮在 `focus-within` 时显示。
  - 样式：Tailwind 不扫描 `*.test.ts`；写死颜色检查增加任意值写法；新增守护测试，核对 `index.html` 的内联脚本与 `MODE_STORAGE_KEY` 一致。

- [ ] **步骤 1：写失败的测试**

在 `frontend/src/features/threads/order.test.ts` 中，把：

```ts
import { describe, expect, it } from "vitest";
import { moveItem } from "./order";

```

改为：

```ts
import { describe, expect, it } from "vitest";
import { moveItem, sameOrder } from "./order";

```

在 `frontend/src/features/threads/order.test.ts` 末尾追加：

```ts

describe("sameOrder", () => {
  it("拖完顺序没变（放回原处、拖到相邻位置的同一侧）时不需要保存", () => {
    const ids = ["a", "b", "c"];
    expect(sameOrder(ids, moveItem(ids, "a", "b", "before"))).toBe(true);
    expect(sameOrder(ids, moveItem(ids, "a", "b", "after"))).toBe(false);
  });
});
```

新建 `frontend/src/features/threads/menu.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { clampToViewport } from "./menu";

describe("菜单位置", () => {
  const menu = { width: 128, height: 80 };
  const viewport = { width: 1000, height: 600 };

  it("有空间时放在点击处", () => {
    expect(clampToViewport({ x: 100, y: 100 }, menu, viewport)).toEqual({ x: 100, y: 100 });
  });

  it("靠近右边或底边时收回窗口内，留出边距", () => {
    expect(clampToViewport({ x: 990, y: 590 }, menu, viewport)).toEqual({ x: 864, y: 512 });
  });
});
```

在 `frontend/src/styles/no-raw-colors.test.ts` 中，把：

```ts
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

```

改为：

```ts
const LITERAL = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;
// 任意值写法：新式颜色函数，或颜色类后面方括号里的颜色名（如 bg-[red]）
const ARBITRARY =
  /\b(?:oklch|oklab|lab|lch|hwb)\(|\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide|placeholder|shadow|decoration|caret|accent)-\[[a-z]+\]/;

```

在 `frontend/src/styles/no-raw-colors.test.ts` 中，把：

```ts

describe("写死颜色检查", () => {
  it("组件代码中没有具体颜色", () => {
```

改为：

```ts

function hasRawColor(line: string): boolean {
  return PALETTE.test(line) || LITERAL.test(line) || ARBITRARY.test(line);
}

describe("写死颜色检查", () => {
  it("规则本身：认得出各种写死颜色的写法，不误伤非颜色的任意值", () => {
    const raw = [
      "bg-red-500",
      "text-[#fff]",
      "bg-[red]",
      "text-[oklch(0.6_0.2_30)]",
      "border-[rgb(1,2,3)]",
      'style={{ color: "rgba(0,0,0,.5)" }}',
    ];
    const fine = ["w-[3px]", "grid-cols-[1fr_auto]", "bg-[var(--surface)]", "text-[0.7rem]"];
    expect(raw.filter((line) => !hasRawColor(line))).toEqual([]);
    expect(fine.filter(hasRawColor)).toEqual([]);
  });

  it("组件代码中没有具体颜色", () => {
```

在 `frontend/src/styles/no-raw-colors.test.ts` 中，把：

```ts
          .map((line, index) => ({ line, at: `${relative(SRC, path)}:${index + 1}` }))
          .filter(({ line }) => PALETTE.test(line) || LITERAL.test(line))
          .map(({ at, line }) => `${at}  ${line.trim()}`),
```

改为：

```ts
          .map((line, index) => ({ line, at: `${relative(SRC, path)}:${index + 1}` }))
          .filter(({ line }) => hasRawColor(line))
          .map(({ at, line }) => `${at}  ${line.trim()}`),
```

存储键守护测试（两处现在一致，这条测试会直接通过；它防的是以后只改一处）：

在 `frontend/src/themes/mode.test.ts` 中，把：

```ts
import { describe, expect, it } from "vitest";
```

改为：

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
```

在 `frontend/src/themes/mode.test.ts` 末尾追加：

```ts

describe("首屏不闪烁", () => {
  it("index.html 的内联脚本读取同一个存储键（改名时两处要一起改）", () => {
    const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
    expect(html).toContain(`localStorage.getItem("${MODE_STORAGE_KEY}")`);
  });
});
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm exec vitest run src/features/threads src/themes src/styles`（预期失败）

预期：`sameOrder is not a function`；`Cannot find module './menu'`。

- [ ] **步骤 3：实现纯逻辑**

在 `frontend/src/features/threads/order.ts` 末尾追加：

```ts

/** 两个顺序是否相同（拖完放回原处时不必保存）。 */
export function sameOrder(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}
```

新建 `frontend/src/features/threads/menu.ts`：

```ts
interface Point {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

/** 菜单放在点击处；靠近窗口右边或底边时收回窗口内（留 8 像素边距），不被截掉。 */
export function clampToViewport(point: Point, menu: Size, viewport: Size, margin = 8): Point {
  return {
    x: Math.max(margin, Math.min(point.x, viewport.width - menu.width - margin)),
    y: Math.max(margin, Math.min(point.y, viewport.height - menu.height - margin)),
  };
}
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm exec vitest run src/features/threads src/themes src/styles`

预期：全部通过。

- [ ] **步骤 5：组件**

`frontend/src/features/threads/ThreadMenu.tsx`（整个替换）：

```tsx
import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { clampToViewport } from "./menu";

export interface MenuPosition {
  threadId: string;
  x: number;
  y: number;
  /** 打开菜单的元素（"⋯"按钮或会话行）：按 Esc 关闭后焦点回到它。 */
  trigger: HTMLElement | null;
}

/**
 * 会话的操作菜单（悬停"⋯"或右键打开）：点菜单外、按 Esc、滚动时关闭。
 * 打开后焦点在第一项，上下方向键切换；靠近窗口边缘时收回窗口内。
 */
export function ThreadMenu({
  position,
  onRename,
  onDelete,
  onClose,
}: {
  position: MenuPosition;
  onRename: (threadId: string) => void;
  onDelete: (threadId: string) => void;
  onClose: () => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  const [placed, setPlaced] = useState({ x: position.x, y: position.y });

  useLayoutEffect(() => {
    const rect = menu.current?.getBoundingClientRect();
    const size = { width: rect?.width ?? 0, height: rect?.height ?? 0 };
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    setPlaced(clampToViewport(position, size, viewport));
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [position]);

  useEffect(() => {
    const closeOutside = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", closeOutside);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      onClose();
      position.trigger?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    const current = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    items.at((current + step) % items.length)?.focus();
  };

  return (
    <div
      ref={menu}
      role="menu"
      aria-label="会话操作"
      className="fixed z-50 min-w-32 rounded-lg border border-border bg-card p-1 text-sm shadow-lg"
      style={{ left: placed.x, top: placed.y }}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        // 用 Tab 把焦点移出菜单时关闭；移到"⋯"按钮上不算（那是在点它收起菜单，由按钮处理）
        const next = event.relatedTarget as Node | null;
        if (next !== position.trigger && !event.currentTarget.contains(next)) onClose();
      }}
    >
      <button
        role="menuitem"
        tabIndex={-1}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:bg-muted"
        onClick={() => onRename(position.threadId)}
      >
        <Pencil className="size-3.5" />
        重命名
      </button>
      <button
        role="menuitem"
        tabIndex={-1}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-danger outline-none hover:bg-danger/10 focus-visible:bg-danger/10"
        onClick={() => onDelete(position.threadId)}
      >
        <Trash2 className="size-3.5" />
        删除
      </button>
    </div>
  );
}
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
import { MessageSquare, MoreHorizontal, Plus } from "lucide-react";
import { useCallback, useState, type DragEvent } from "react";
import { api, readableError } from "../../api/client";
```

改为：

```tsx
import { MessageSquare, MoreHorizontal, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type DragEvent } from "react";
import { api, readableError } from "../../api/client";
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
import { isImeComposing } from "./ime";
import { moveItem } from "./order";
import { ThreadMenu, type MenuPosition } from "./ThreadMenu";
```

改为：

```tsx
import { isImeComposing } from "./ime";
import { moveItem, sameOrder } from "./order";
import { ThreadMenu, type MenuPosition } from "./ThreadMenu";
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
  place: "before" | "after";
}
```

改为：

```tsx
  place: "before" | "after";
}

const REORDER = ["reorder-threads"];

/** 侧栏的操作失败提示几秒后自动消失，不一直挂着（之后的操作成功与否与它无关）。 */
function useAutoReset(mutation: { isError: boolean; reset: () => void }, delay = 5000) {
  const { isError, reset } = mutation;
  useEffect(() => {
    if (!isError) return;
    const timer = setTimeout(reset, delay);
    return () => clearTimeout(timer);
  }, [isError, reset, delay]);
}
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
  const reorder = useMutation({
    mutationFn: api.reorderThreads,
    // 保存失败时以服务器为准，恢复原来的顺序
    onError: () => queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey }),
  });

```

改为：

```tsx
  const reorder = useMutation({
    mutationKey: REORDER,
    mutationFn: api.reorderThreads,
    // 正在进行的列表刷新可能带回旧顺序，覆盖刚排好的界面：先取消它
    onMutate: () => queryClient.cancelQueries({ queryKey: threadsQuery.queryKey }),
    // 最后一次保存结束后以服务器为准（失败时即恢复原来的顺序）；连续拖动时中途不刷新，免得来回跳
    onSettled: () => {
      if (queryClient.isMutating({ mutationKey: REORDER }) === 1) {
        void queryClient.invalidateQueries({ queryKey: threadsQuery.queryKey });
      }
    },
  });
  useAutoReset(create);
  useAutoReset(rename);
  useAutoReset(reorder);

```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
  const finishDrag = () => {
    if (draggingId && drop) {
      const ids = moveItem(
        list.map((thread) => thread.id),
        draggingId,
        drop.threadId,
        drop.place,
      );
      const byId = new Map(list.map((thread) => [thread.id, thread]));
```

改为：

```tsx
  const finishDrag = () => {
    const current = list.map((thread) => thread.id);
    const ids = draggingId && drop ? moveItem(current, draggingId, drop.threadId, drop.place) : [];
    if (ids.length > 0 && !sameOrder(ids, current)) {
      const byId = new Map(list.map((thread) => [thread.id, thread]));
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
              onContextMenu={(event) => {
                event.preventDefault();
                setMenu({ threadId: thread.id, x: event.clientX, y: event.clientY });
              }}
```

改为：

```tsx
              onContextMenu={(event) => {
                if (renamingId === thread.id) return; // 正在重命名：保留输入框自己的右键菜单（粘贴等）
                event.preventDefault();
                setMenu({
                  threadId: thread.id,
                  x: event.clientX,
                  y: event.clientY,
                  trigger: event.currentTarget.querySelector<HTMLElement>('[role="button"]'),
                });
              }}
```

在 `frontend/src/features/threads/ThreadList.tsx` 中，把：

```tsx
                  aria-label="更多操作"
                  className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-1 text-muted-foreground opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground focus:opacity-100"
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    setMenu({ threadId: thread.id, x: rect.left, y: rect.bottom + 4 });
                  }}
```

改为：

```tsx
                  aria-label="更多操作"
                  aria-haspopup="menu"
                  aria-expanded={menu?.threadId === thread.id}
                  className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-1 text-muted-foreground opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground focus:opacity-100"
                  // 菜单打开时再点"⋯"是收起：不让菜单的"点外面关闭"先关掉、点击又重新打开
                  onMouseDown={(event) => {
                    if (menu?.threadId === thread.id) event.stopPropagation();
                  }}
                  onClick={(event) => {
                    if (menu?.threadId === thread.id) return setMenu(null);
                    const rect = event.currentTarget.getBoundingClientRect();
                    setMenu({
                      threadId: thread.id,
                      x: rect.left,
                      y: rect.bottom + 4,
                      trigger: event.currentTarget,
                    });
                  }}
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
    </div>
    <ActionBarPrimitive.Root className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
      <ActionBarPrimitive.Copy
```

改为：

```tsx
    </div>
    <ActionBarPrimitive.Root className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      <ActionBarPrimitive.Copy
```

在 `frontend/src/components/chat/parts.tsx` 中，把：

```tsx
      autohide="not-last"
      className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
    >
```

改为：

```tsx
      autohide="not-last"
      className="mt-1 flex gap-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
    >
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
import { ArrowUp, Sparkles, Square, X } from "lucide-react";
import type { ChatState } from "../../features/chat/reducer";
```

改为：

```tsx
import { ArrowUp, Sparkles, Square, X } from "lucide-react";
import { useMemo } from "react";
import type { ChatState } from "../../features/chat/reducer";
```

在 `frontend/src/components/chat/ChatThread.tsx` 中，把：

```tsx
export function ChatThread({ state, notice, onDismissNotice, onSend, onCancel }: ChatThreadProps) {
  const runtime = useExternalStoreRuntime({
    messages: toThreadMessages(state),
    isRunning: state.running,
```

改为：

```tsx
export function ChatThread({ state, notice, onDismissNotice, onSend, onCancel }: ChatThreadProps) {
  // 只在状态变化时重新转换：assistant-ui 按消息对象是否相同决定是否重新处理
  const messages = useMemo(() => toThreadMessages(state), [state]);
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: state.running,
```

在 `frontend/src/index.css` 中，把：

```css
@import "tailwindcss";
@import "./styles/tokens.css";
```

改为：

```css
@import "tailwindcss";
/* 测试文件里的类名只是测试数据（如写死颜色检查的反例），不生成样式 */
@source not "./**/*.test.ts";
@import "./styles/tokens.css";
```

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`cd frontend && pnpm build`

运行：`! grep -lF 'bg-\[red\]' frontend/dist/assets/*.css`

预期：
- `make check` 全部通过（Python 单元测试 97 个、前端 63 个）；
- 打包成功（体积超过 500KB 的提示是 M1a 已接受的代价）；
- 打包出的 CSS 里没有测试反例 `bg-[red]`。

---

### 任务 7：后端与工具小问题

**文件：**
- 修改：`backend/frontend.py`、`backend/threads/schemas.py`、`Makefile`
- 测试：`backend/tests/test_frontend.py`、`test_api.py`、`test_repos.py`、`test_migrations.py`

**接口：**
- 规则：
  - `/api` 下不存在的路径，任何请求方法都返回 404；
  - `PUT /api/threads/order` 的 `thread_ids` 有重复时返回 422；未知 ID 忽略；
  - 用到 compose 的 make 命令先检查 `.env`，缺少时提示 `cp .env.example .env`。
- 新增两条守护测试（现在就会通过，防以后回退）：
  - 路径穿越拿不到打包目录以外的文件；
  - 迁移 0003 按最近使用初始化会话顺序。

- [ ] **步骤 1：写失败的测试**

在 `backend/tests/test_frontend.py` 中，把：

```python
        assert "首页" in client.get("/threads/abc").text
        # 接口路径不兜底：仍然是 JSON 404
        missing = client.get("/api/not-exist")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found"}
        assert client.get("/api/health").json() == {"status": "ok"}
```

改为：

```python
        assert "首页" in client.get("/threads/abc").text
        # 接口路径不兜底：仍然是 JSON 404（写操作也一样，不是 405）
        missing = client.get("/api/not-exist")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found"}
        assert client.post("/api/not-exist", json={}).status_code == 404
        assert client.get("/api/health").json() == {"status": "ok"}
```

在 `backend/tests/test_frontend.py` 末尾追加：

```python


def test_cannot_read_files_outside_the_build(tmp_path: Path) -> None:
    """路径穿越（../）拿不到打包目录以外的文件。"""
    (tmp_path / "dist").mkdir()
    dist = _dist(tmp_path / "dist")
    (tmp_path / "secret.txt").write_text("机密", encoding="utf-8")
    app = create_app(lifespan_handler=None, frontend_dist=dist)
    with TestClient(app, base_url="http://localhost") as client:
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
            response = client.get(path)
            assert "机密" not in response.text, path
```

在 `backend/tests/test_api.py` 中，把：

```python
        assert [t["id"] for t in (await client.get("/api/threads")).json()] == order

```

改为：

```python
        assert [t["id"] for t in (await client.get("/api/threads")).json()] == order
        repeated = {"thread_ids": [first["id"], first["id"]]}
        assert (await client.put("/api/threads/order", json=repeated)).status_code == 422

```

在 `backend/tests/test_repos.py` 中，把：

```python

async def test_rename_thread(db: Pool) -> None:
```

改为：

```python

async def test_reorder_ignores_unknown_ids(db: Pool) -> None:
    """排序里有不存在的会话（如另一个标签页刚删掉的）：忽略它，其余照常排序。"""
    threads = ThreadRepo(db)
    first = await threads.create(model="m")
    second = await threads.create(model="m")

    await threads.reorder([uuid.uuid4(), first.id, second.id])

    assert [t.id for t in await threads.list_active()] == [first.id, second.id]


async def test_rename_thread(db: Pool) -> None:
```

在 `backend/tests/test_migrations.py` 中，把：

```python

async def test_finished_events_use_interrupted_usage(db: Pool, alembic_config: Config) -> None:
```

改为：

```python

async def test_existing_threads_get_positions_by_recent_use(
    db: Pool, alembic_config: Config
) -> None:
    """0003：已有会话按最近使用的顺序排好（最近用过的在上面），升级后列表顺序不变。"""
    command.downgrade(alembic_config, "0002")
    try:
        async with db.connection() as conn:
            for short_id, hours_ago in (("c_old", 3), ("c_new", 1), ("c_mid", 2)):
                await conn.execute(
                    "INSERT INTO threads (id, short_id, model, updated_at) "
                    "VALUES (gen_random_uuid(), %s, 'm', now() - make_interval(hours => %s))",
                    (short_id, hours_ago),
                )
        command.upgrade(alembic_config, "0003")
    finally:
        command.upgrade(alembic_config, "head")

    assert [t.short_id for t in await ThreadRepo(db).list_active()] == ["c_new", "c_mid", "c_old"]


async def test_finished_events_use_interrupted_usage(db: Pool, alembic_config: Config) -> None:
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_frontend.py -q`（预期失败）

预期：`assert 405 == 404`。

运行：`uv run pytest -m integration backend/tests/test_api.py -q -k reorder`（预期失败）

预期：`assert 204 == 422`。

- [ ] **步骤 3：实现**

在 `backend/frontend.py` 中，把：

```python
def _is_page_path(path: str) -> bool:
    """前端页面路径才兜底：/api 下的路径和带扩展名的文件（如重新打包后已不存在的旧脚本）保持 404，
    否则浏览器会把首页当成脚本加载，页面白屏。"""
    return path.split("/", 1)[0] != "api" and "." not in PurePosixPath(path).name

```

改为：

```python
def _is_page_path(path: str) -> bool:
    """前端页面路径才兜底：带扩展名的文件（如重新打包后已不存在的旧脚本）保持 404，
    否则浏览器会把首页当成脚本加载，页面白屏。"""
    return "." not in PurePosixPath(path).name

```

在 `backend/frontend.py` 中，把：

```python
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
```

改为：

```python
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.split("/", 1)[0] == "api":
            # 不存在的接口：任何请求方法都是 404（交给静态文件处理会对写操作返回 405）
            raise HTTPException(status_code=404)
        try:
```

在 `backend/threads/schemas.py` 中，把：

```python

from pydantic import BaseModel, Field, StringConstraints

```

改为：

```python

from pydantic import BaseModel, Field, StringConstraints, field_validator

```

在 `backend/threads/schemas.py` 末尾追加：

```python

    @field_validator("thread_ids")
    @classmethod
    def _no_repeats(cls, thread_ids: list[UUID]) -> list[UUID]:
        if len(set(thread_ids)) != len(thread_ids):
            raise ValueError("会话 ID 重复")
        return thread_ids
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest backend/tests/test_frontend.py -q`

运行：`uv run pytest -m integration backend/tests/test_api.py backend/tests/test_repos.py backend/tests/test_migrations.py -q`

预期：全部通过。

- [ ] **步骤 5：Makefile 检查 `.env`**

在 `Makefile` 中，把：

```makefile
DC := $(COMPOSE) --env-file .env -f deploy/docker-compose.yml
# 使用项目内的空 Docker 配置：本机全局配置残留了 Docker Desktop 的凭据程序（credsStore=desktop），会导致构建失败
```

改为：

```makefile
DC := $(COMPOSE) --env-file .env -f deploy/docker-compose.yml
# 用到 compose 的命令先检查 .env：缺少时 compose 只给出难懂的报错
NEED_ENV = @test -f .env || { echo "缺少 .env：先运行 cp .env.example .env（见 README 的首次准备）"; exit 1; }
# 使用项目内的空 Docker 配置：本机全局配置残留了 Docker Desktop 的凭据程序（credsStore=desktop），会导致构建失败
```

在 `Makefile` 中，把：

```makefile
test-up: ## 启动测试专用数据库
	$(DC) --profile test up -d --wait postgres-test

test-down:
	$(DC) --profile test rm -sf postgres-test
```

改为：

```makefile
test-up: ## 启动测试专用数据库
	$(NEED_ENV)
	$(DC) --profile test up -d --wait postgres-test

test-down:
	$(NEED_ENV)
	$(DC) --profile test rm -sf postgres-test
```

在 `Makefile` 中，把：

```makefile
infra-up: ## 启动数据库、网关、Ollama；向量模型不存在时才下载
	$(DC) up -d --wait postgres litellm ollama
```

改为：

```makefile
infra-up: ## 启动数据库、网关、Ollama；向量模型不存在时才下载
	$(NEED_ENV)
	$(DC) up -d --wait postgres litellm ollama
```

在 `Makefile` 中，把：

```makefile
build: ## 重新构建 backend 镜像并启动：依赖文件或前端界面改了以后运行（依赖从本机构建缓存安装，不重新下载）
	$(DC) build backend
```

改为：

```makefile
build: ## 重新构建 backend 镜像并启动：依赖文件或前端界面改了以后运行（依赖从本机构建缓存安装，不重新下载）
	$(NEED_ENV)
	$(DC) build backend
```

在 `Makefile` 中，把：

```makefile
restart: ## 改了 Python 代码后让后端加载新代码（源码已挂载进容器，无需重新构建）
	$(DC) restart backend
```

改为：

```makefile
restart: ## 改了 Python 代码后让后端加载新代码（源码已挂载进容器，无需重新构建）
	$(NEED_ENV)
	$(DC) restart backend
```

在 `Makefile` 中，把：

```makefile
restart-gateway: ## 修改 config/models.yaml 后让网关重新加载
	$(DC) restart litellm

logs:
	$(DC) logs -f --tail=100

down: ## 停止所有服务（数据保留在数据卷中）
	$(DC) down
```

改为：

```makefile
restart-gateway: ## 修改 config/models.yaml 后让网关重新加载
	$(NEED_ENV)
	$(DC) restart litellm

logs:
	$(NEED_ENV)
	$(DC) logs -f --tail=100

down: ## 停止所有服务（数据保留在数据卷中）
	$(NEED_ENV)
	$(DC) down
```

在一个没有 `.env` 的临时目录里试运行（不碰项目的 `.env`）：

运行：`d=$(mktemp -d) && cp Makefile $d/ && make -C $d test-up 2>&1 | tee $d/out.txt; grep -q '缺少 .env' $d/out.txt; s=$?; rm -rf $d; exit $s`

预期：输出"缺少 .env：先运行 cp .env.example .env（见 README 的首次准备）"。

- [ ] **步骤 6：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 98 个、前端 63 个）；`make test-int` 全部通过（51 个）。

---

### 任务 8：决策记录 D01～D15

**文件：**
- 新建：`docs/decisions/D01-*.md` ～ `D15-*.md`（15 份）
- 修改：`docs/decisions/D16-前端采用assistant-ui与主题系统.md`、`docs/decisions/README.md`

**说明：** 设计文档第 3 节的 D1～D15 逐条补成独立记录（背景、备选方案、结论与落地位置、原因与代价），内容只取自设计文档与已落地的代码。D16 补一条代价：`useExternalStoreRuntime` 在 assistant-ui 0.15.28 里位于 `legacy-runtime/` 目录（尚未标记弃用，升级时留意）。

- [ ] **步骤 1：新建决策记录**

新建 `docs/decisions/D01-模型调用统一走LiteLLM网关.md`：

```markdown
# D01：模型调用全部走 LiteLLM 网关（独立容器）

- 状态：已采纳
- 日期：2026-10-12

## 背景

要同时支持 Claude、OpenAI / Gemini、国产模型（DeepSeek / Qwen / Kimi / GLM 等），能按会话切换具体版本；知识库的向量化同样要调用模型（D15）。成功标准要求"加模型版本只改配置，业务代码不动"。LiteLLM 是一个用同一种写法调用各家大模型的开源工具，可以作为库嵌进代码，也可以部署成独立的"模型网关"服务。

## 备选方案

1. 在代码里直接调用 LiteLLM 库，不单独部署网关。
2. 直连各厂商的官方接口。
3. 经 OpenRouter 等第三方模型聚合服务调用。
4. 部署 LiteLLM 网关作为独立容器，所有调用都经过它。

设计文档把 1～3 列为"模型网关"接口以后可替换成的实现（4.1 节），没有展开逐项比较。

## 结论

- 所有模型调用（对话与向量化）都经 compose 中的 `litellm` 服务；`config/models.yaml` 直接挂载为网关的模型清单（见 D03）。
- 网关藏在"模型网关"可替换接口后面（`config/app.yaml` 的 `adapters.model_gateway` 选择实现），业务代码不直接引用 litellm。
- 智能体一侧用 langchain-litellm（LangChain 与 LiteLLM 的对接包）的 `ChatLiteLLM` 连接网关，不用通用的 `ChatOpenAI`——后者会丢弃思考内容，Claude 深度思考加工具调用会报错。
- 模型调用失败时由网关先自动重试、切换备用模型，仍失败才结束运行。

落地：M0：`agents/main_agent/models/base.py`（接口）、`agents/main_agent/models/litellm_proxy.py`（实现）、`agents/main_agent/bootstrap.py`（登记）、`config/models.yaml`、`deploy/docker-compose.yml` 的 `litellm` 服务；契约测试 `agents/tests/contracts/test_model_gateway_contract.py`。目前模型来源是公司的 LiteLLM 网关，本地网关以 `litellm_proxy/` 方式转发。

## 原因与代价

- 所有模型调用收拢到一个入口，密钥、重试、备用切换集中管理，本机其他工具也能共用这个网关。
- M0 先行验证 V1、V2 通过：经"本地网关 → 公司网关"两级转发，Claude 深度思考 + 多轮工具调用 + 逐字输出正常，思考块与签名得以保留；流式输出时每次调用都带输入、输出 token 及缓存、思考明细。
- 代价：多一个要运行的服务（网关在 PostgreSQL 里另占一个 `litellm` 库）；deepagents 自带的 Anthropic 提示缓存中间件只对官方 `ChatAnthropic` 生效，走网关用不上，要改在网关配置中为 Claude 开启缓存注入点（M0 时尚未配置）；LiteLLM 模型对象不带上下文长度，需由模型网关接口把读到的长度填进去，deepagents 才知道何时压缩上下文。
- 风险：litellm 曾出现投毒版本（1.82.7 / 1.82.8），靠精确版本、锁文件哈希和固定网关镜像规避（见 D12）；LiteLLM 导入时会联网拉价格表，统一设置 `LITELLM_LOCAL_MODEL_COST_MAP=True` 关闭。
```

新建 `docs/decisions/D02-前后端通信采用自定义SSE推送协议.md`：

```markdown
# D02：前后端通信用自定义推送协议（SSE），不用 AG-UI

- 状态：已采纳
- 日期：2026-10-12

## 背景

一次运行可能持续很久，过程中要把回答逐字、思考过程、工具调用、子智能体嵌套、待办、审批、产物等实时推给浏览器；关掉浏览器再打开，正在跑的任务和已推送的内容都不能丢。SSE（服务器单向推送）是浏览器自带的一种长连接：服务器持续往下推事件，浏览器用 `EventSource` 接收，断线会自动重连。AG-UI 是一个开源的"智能体与前端界面之间"的事件协议。

## 备选方案

1. 采用 AG-UI 协议。
2. 自己定义事件协议，经 SSE 推送。

## 结论

- 自定义事件协议，所有事件共用一个信封：`seq`（递增序号）、`run_id`、`type`、`agent_path`（事件属于哪个智能体，子智能体据此嵌套显示）、`ts`、`data`。
- 事件类型：`run.started`、`message.delta`、`thinking.delta`、`tool.started` / `tool.finished`、`subagent.started` / `subagent.finished`、`todos.updated`、`usage`、`run.finished`；`file.created`、`memory.saved`、`approval.required` 随 M2～M4 的功能加入。
- 事件定义（pydantic 数据模型）放在 `agents/main_agent/runtime/`，backend 原样转发、只加序号，前端类型由脚本自动生成；只有这个目录知道 deepagents，其他模块只认我们自己的事件。
- 发消息、审批、取消走普通接口；运行过程走 `GET /api/runs/{id}/events` 推送，断线重连带上最后收到的序号（`Last-Event-ID`），backend 先补发再接着推。空闲时每 15 秒发一次心跳，防止连接被中间环节掐断（FastAPI 自带的推送响应会自动发送）。
- 以后需要时再加一层 AG-UI 转换（扩展路线阶段 4）。

落地：M0：`agents/main_agent/runtime/events.py`（事件定义）、`agents/main_agent/runtime/translator.py`（把 deepagents 输出翻译成事件）、`backend/api/router.py`（推送接口）、`frontend/src/api/events.ts`（订阅）、`frontend/src/features/chat/reducer.ts`（事件处理器）；M1b 补齐思考、子智能体、待办、用量事件；M1c：前端类型自动生成（`backend/openapi.py`、`frontend/src/api/generated/`，`make types`）。

## 原因与代价

- 子智能体嵌套、待办、审批、产物都要定制界面，自己定义事件最直接；AG-UI 仍是 0.0.x 早期版本，接口不稳定。
- 推送只需要"服务器 → 浏览器"一个方向，SSE 由浏览器原生支持并自动重连；续传靠序号，不依赖连接粘在某个进程上（也为 D09 的多进程预留了条件）。
- 前端只有一套事件处理逻辑：实时显示是边收边处理，打开历史是把存好的事件重放（配合 D07）。
- 代价：协议、翻译器、前端事件处理器都要自己写、自己维护和测试；不能直接复用支持 AG-UI 的现成界面和工具，以后要接需另写转换层。
- 代价：推送是长连接，服务停止时 uvicorn 默认会一直等浏览器断开，必须配 `--timeout-graceful-shutdown` 才能及时收尾（见 `docs/development/architecture.md` 第 9 节）。
```

新建 `docs/decisions/D03-模型按具体版本登记.md`：

```markdown
# D03：模型按具体版本登记

- 状态：已采纳
- 日期：2026-10-12

## 背景

同一系列的模型会不断出新版本（如 `claude-opus-4-8`、`claude-opus-4-6`），能力和价格各不相同。成功标准要求：同一会话中途换模型版本，上下文不丢；每个模型版本的输入、输出 token 和费用都能统计到。所以必须明确"这次用的是哪个版本"。

## 备选方案

设计文档没有列出其他认真比较的方案。与之相对的做法是只登记"最新版"之类的别名（如 `claude-opus-latest`），设计中把它保留为可选的快捷名，而不是登记和统计的单位。

## 结论

- `config/models.yaml` 就是网关的模型清单（见 D01），一个具体版本一条记录，`model_name` 就是版本名，智能体和前端看到的都是这个名字。
- 可以加"最新版"快捷名指向某个具体版本，但统计里永远记录实际服务的具体版本。
- "请求的版本"和"实际回答的版本"分开记：网关因故障自动切到备用模型时，用量表两个都记（见 D04）。
- 启动时由模型网关接口向网关查询每个版本的上下文长度、价格、是否支持深度思考、能否看图；前端模型下拉框、上下文压缩阈值、费用计算都用这份信息。
- 会话可以中途换版本；Claude 的思考内容不能交给别家模型，由"换模型清理"中间件在模型变化时剥除（对话存档保持原样）。

落地：M0：`config/models.yaml`（目前登记 `claude-opus-4-6`、`gemini-3.5-flash`、`gpt-5.5-pro` 与向量模型 `embed-qwen3-0.6b`）、`agents/main_agent/models/base.py`（`ModelInfo`）、`frontend/src/features/models/ModelSelect.tsx`、接口 `GET /api/models`；M1b：用量表的 `requested_model` / `actual_model` 字段（`backend/migrations/versions/0002_agents_usage.py`）、换模型清理 `agents/main_agent/models/cleanup.py`。修改清单后执行 `make restart-gateway` 生效；设计中的 `POST /api/settings/reload`（重新读取配置）尚未实现。

## 原因与代价

- 按版本登记，才能明确用的是哪个、统计到哪个；网关切换备用模型时，也能看出实际是谁回答的。
- M0 先行验证 V3 通过：同一会话 `claude-opus-4-6` → `gemini-3.5-flash` → `claude-opus-4-6` 三轮均正常完成。
- 代价：每出一个新版本都要手动在清单里加一条；新模型网关可能还没有内置价格，要在 `model_info` 里手动补（未知的先不填，此时费用记为空）。
- 代价：清单改动后要重启网关；模型信息在启动时读取，网关当时不可用则稍后访问 `/api/models` 时重试。
```

新建 `docs/decisions/D04-用量用自建表按次记录.md`：

```markdown
# D04：用量用自建表按次记录，网关后台统计只作核对

- 状态：已采纳
- 日期：2026-10-12

## 背景

成功标准要求每个模型版本的输入、输出 token 和费用都能统计到，还要能按会话、按运行、按子智能体看。花钱的地方不止主对话：子智能体、上下文自动压缩（最容易漏）、记忆提取、知识向量化、标题生成都会调用模型。LiteLLM 网关自带一个管理后台，也能做花费统计。

## 备选方案

1. 直接使用网关后台的统计。
2. 自建用量表，每次模型调用记一行；网关后台统计只用来核对。

## 结论

- 自建 `llm_usage` 表，每次模型调用一行：会话、运行、调用方（主智能体 / 子智能体名 / 自动压缩 / 记忆提取 / 知识向量化 / 标题生成）、请求的版本、实际的版本、输入 / 输出 / 缓存读取 / 缓存写入 / 思考 token、费用、耗时、时间。
- 记录方式："用量记录器"挂在每次运行的全局回调上，自动覆盖主对话、子智能体和自动压缩；向量化不经过聊天回调，由向量化实现每次调用后直接记录。
- 费用按记录当时的价格算好存入（取网关返回的费用），以后调价不影响历史；用量表不设会话外键，删除会话后用量记录仍保留。
- 每次调用把会话 ID、运行 ID 作为网关元数据带上，方便在网关后台核对。
- 展示：每条回答下方显示本轮用量（可展开每次调用明细）；会话顶栏显示本会话累计；统计页按天、按模型版本看趋势。

落地：M1b：`agents/main_agent/runtime/tracker.py`（回调）、`agents/main_agent/usage/`（表的读写与查询）、`backend/migrations/versions/0002_agents_usage.py`、`backend/runs/manager.py`（收到用量事件后写库）、`frontend/src/features/usage/`，接口 `GET /api/threads/{id}/usage`、`GET /api/runs/{id}/usage`。统计页、`GET /api/usage/summary` 和网关元数据在 M5 实施；向量化的用量记录随 M3 实施。

## 原因与代价

- 自建表能与会话、运行、子智能体直接关联，也不受网关内部表结构变化的影响。
- M0 先行验证 V2 通过：流式输出时每次调用都有输入、输出 token，另含缓存读写与思考 token 明细，可以直接入库。
- 代价：要自己维护一张表、一个回调和一组查询；两边的数字可能有出入，以自建表为准。
- 代价：被停止的那次模型调用拿不到用量，只能估算后显示在"已停止"旁，不写入用量表、不计入合计；写库失败只记日志、不影响对话，此时这一次调用会漏记。
```

新建 `docs/decisions/D05-架构总纲底层解耦功能内聚.md`：

```markdown
# D05：架构总纲——底层解耦，功能内聚；所有基础设施走可替换接口

- 状态：已采纳
- 日期：2026-10-12

## 背景

沙箱、模型网关、向量检索、运行时队列等基础设施以后都可能更换（云沙箱、外部向量库、多进程……）。成功标准要求"加模型版本、加工具、换基础设施实现，只改配置或只加一个实现类，业务代码不动"。同时 deepagents（LangChain 出品的智能体框架）迭代快，0.7 版就有破坏性变更，升级影响面要可控。

## 备选方案

1. 业务代码直接引用第三方库（如 `litellm`、`docker`），不设接口。
2. 处处预设抽象，连 LangChain 聊天模型、LangGraph 对话存档、deepagents 后端协议这类本身已是标准接口的东西也再包一层。
3. 只为基础设施建可替换接口，用配置选择实现；功能模块内部内聚。

设计文档明确否定了 1 和 2（4 节"不过度包装""只为基础设施建接口"）。

## 结论

- 一句话：横向靠接口隔离，纵向靠模块内聚。
- **底层解耦**：外部依赖藏在我们自己定义的接口后面，清单见设计文档 4.1：模型网关、向量化、工作区（文件 + 执行）、原文件存储、知识检索、文档解析、MCP 客户端、运行时 4 个替换点、智能体运行器。用哪个实现由 `config/app.yaml` 的 `adapters` 决定，只在组装根 `agents/main_agent/bootstrap.py` 装配。新增实现 = 写实现类 + 登记 + 配置选中。
- **功能内聚**：每个能力模块把接口、实现、数据访问、中间件、给智能体的工具放在一起；模块之间只调用对方公开的服务，不跨模块读写对方的表。
- **不过度包装**：本身已是标准接口的东西直接用；deepagents 只出现在 `agents/main_agent/runtime/`。
- 防止解耦被慢慢破坏的三个机制：每个接口一套契约测试（所有实现跑同一套）；import-linter 自动检查依赖方向（见 D06）；"用哪个实现"只在组装根决定。

落地：M0：`agents/main_agent/bootstrap.py`、`config/app.yaml`（目前只有 `model_gateway: litellm_proxy` 一项）、契约测试 `agents/tests/contracts/`；运行时替换点在 `backend/runtime/`（事件总线 M0、运行控制 M1b）；写法模板见 `docs/development/architecture.md` 第 4 节。其余接口随 M2～M4 各自的功能加入。

## 原因与代价

- 基础设施都要能快速替换；deepagents 被限制在一个目录里，升级时只需改这一处。
- 只为基础设施建接口，其他地方不为"以后可能"预设抽象，避免过度设计。
- 代价：每个接口都要多写接口定义、登记代码和一套契约测试。
- 代价：模块之间不能直接读写对方的表，要经公开服务多走一层；"只为基础设施建接口"的边界要靠规范和自动检查长期维护（见 D14）。
```

新建 `docs/decisions/D06-三大块单向依赖的单一Python项目.md`：

```markdown
# D06：agents / backend / frontend 三大块同级、单向依赖；单一 Python 项目

- 状态：已采纳
- 日期：2026-10-12

## 背景

项目由三部分组成：智能体能力（agents）、对外提供接口与运行调度的服务（backend）、浏览器界面（frontend）。希望结构简洁，并且 agents 能脱离 HTTP 独立运行；以后还可能在 agents 下新增其他专职 agent。依赖方向如果只靠自觉，时间一长就会被破坏。

## 备选方案

设计文档没有展开比较其他整体结构。明确否定的细节做法有：给包加统一前缀或套一层 `src/` 目录（6.1 补充说明）；用 `import ... as ...` 改名来避开与 OpenAI Agents SDK 的同名冲突（6.3，做不到）。

## 结论

- 顶层 `agents/`、`backend/`、`frontend/` 同级；`common/`（与业务无关的基础设施）和 `config/`（配置读取与配置文件）是公共基础。
- 依赖只能单向：`frontend ──(HTTP 接口 + 推送协议)──→ backend ──→ agents ──→ config ──→ common`。agents 不得引用 backend；backend 只能用 agents 对外公开的内容（`build_agent` 总入口、事件定义、各模块 `__init__.py` 导出的服务与数据结构），不得深入内部子模块；agents 内各能力模块之间也只走公开服务。
- 以后在 agents 下新增的 agent 可以依赖 `main_agent`，`main_agent` 不得反向依赖它们。
- 只有一个 Python 项目：唯一的 `pyproject.toml` 与 `uv.lock`；顶层目录本身就是可直接导入的包（如 `from config import settings`）。
- 用 import-linter（检查模块之间引用关系的工具）把规则写死，违反即 `make check` 失败。
- agents 只提供能力、不管调度：记忆提取、文档处理、标题生成何时执行由 backend 决定。

落地：M0：`pyproject.toml` 的 `[tool.importlinter]`（两条规则："单向依赖"分层规则、"backend 只使用 agents 的公开入口"禁止规则），`make check` 中的 `lint-imports`；说明见 `docs/development/architecture.md` 第 2 节。

## 原因与代价

- 结构简洁，一份依赖清单、一个锁文件（配合 D12）；agents 不依赖 HTTP，可以单独运行和测试。
- 依赖方向由工具自动检查，不靠人记。
- 代价：backend 不得引用的 agents 内部模块目前在 `pyproject.toml` 里逐个列出，新增内部模块时要记得补进清单，否则检查发现不了越界。
- 代价：顶层包名 `agents` 与 OpenAI Agents SDK 的导入名相同，同一进程只能有一个。本项目不使用该 SDK；确需使用时，要么重命名本项目目录，要么（推荐）把基于该 SDK 的 agent 作为独立进程经 HTTP 或 MCP（让智能体接入外部工具的开放协议）接入。
```

新建 `docs/decisions/D07-界面历史与模型上下文分开存.md`：

```markdown
# D07：界面历史与模型上下文分开存

- 状态：已采纳
- 日期：2026-10-12

## 背景

deepagents（本项目使用的智能体框架）把发给模型的对话保存在"对话存档"里，对话快满时会自动压缩：用摘要替换旧消息。如果界面也直接读这份存档来显示历史，压缩后旧内容就会从界面上"消失"。成功标准还要求关掉浏览器再打开，会话和正在跑的任务都还在，界面不漏内容。

## 备选方案

1. 界面直接读 deepagents 对话存档来显示历史。
2. 界面历史单独存一份（推送过的事件），模型上下文仍由对话存档负责。

## 结论

- 界面历史读 `run_events` 表（运行 ID、序号、事件类型、内容、时间；主键为运行 ID + 序号）；模型上下文读 deepagents 对话存档（LangGraph 的 PostgreSQL 存档，表由它自己的 `setup()` 创建）。
- 前端只有一套渲染逻辑：实时显示是边收事件边处理，打开历史会话是把存好的事件按顺序重放。
- 运行中把原始事件每 200 毫秒分批写库，进程中途退出也不丢已推送的内容；运行结束时整体替换为合并版本（同一段回答或思考的逐字片段合并成全文），减少存储量。
- 断线续传时先查内存缓冲，没有再查 `run_events`。

落地：M0：`backend/migrations/versions/0001_backend_core.py`（`runs`、`run_events` 表）、`backend/runs/repo.py`、`backend/runs/compaction.py`（合并逐字片段）、接口 `GET /api/threads/{id}/history`、前端事件处理器 `frontend/src/features/chat/reducer.ts`；M1b：分批写库 `backend/runs/writer.py`。

## 原因与代价

- 上下文压缩只影响模型看到的内容，界面历史完整保留；实时显示与历史重放共用一套逻辑，测试一套即可。
- 代价：同一段对话存两份，多占存储（靠合并逐字片段缓解）。
- 代价：两份内容要靠代码保持一致。例如用户点"停止"时，界面上已显示的回答不会自动进入对话存档，需要另外把已输出的部分连同一段中断说明写进存档，否则模型下一轮不知道刚才说过什么（M1b 之后的"体验优化"已处理）；删除会话时也要把运行、界面历史和对话存档都删掉。
```

新建 `docs/decisions/D08-沙箱采用常驻容器与内部专用网络.md`：

```markdown
# D08：沙箱用常驻容器 + 共享工作区 + 内部专用网络，backend 不持有 Docker 控制权

- 状态：已采纳
- 日期：2026-10-12

## 背景

智能体要能在隔离环境（沙箱：与本机隔开、专门用来跑代码的容器）里执行代码、处理用户上传的 Excel / PDF 等文件，并产出图表等产物。所有服务都用 docker compose（按一份配置文件启动一组容器的工具）管理。本服务只监听本机，但能执行代码，必须防止代码越界、联网乱来或拖垮本机。使用者只有本人一个。

## 备选方案

1. 每个会话一个独立容器：需要 backend 能按需创建、销毁容器，也就是持有 Docker 的控制权。
2. E2B、Daytona、Modal 等云沙箱（deepagents 有官方适配包）：v1 范围明确不做云沙箱。
3. 一个常驻的沙箱容器，按会话划分工作目录。

1、2 在设计文档里列为"工作区"接口以后可替换成的实现。

## 结论

- compose 中的 `sandbox` 服务（本项目自建镜像）常驻运行，只接入内部专用网络（`internal: true`），只能与 backend 通信、不对外；可在配置中开启联网以便 `pip install`。
- backend 与沙箱挂载同一个工作区数据卷：读写文件由 backend 直接做，只有执行命令交给沙箱里的执行服务；每个会话一个目录 `/workspace/<会话短ID>/`，智能体看到的路径就是沙箱里的真实路径。
- 安全边界：非 root 用户；除 `/workspace` 与 `/tmp` 外文件系统只读；默认 2 核 CPU、2GB 内存并限制最大进程数；命令默认 120 秒超时，超时杀掉整个进程组；超过 30KB 的输出写入文件；backend 调用执行服务时带共享密钥。
- 实现方式：在 deepagents 的本地文件后端上显式继承 `SandboxBackendProtocol` 增加"执行命令"能力，作为文件路由（`CompositeBackend`）的默认后端，deepagents 随即为智能体提供 `execute` 工具（M0 先行验证 V4 已离线确认可行）。

落地：M2 实施（计划位置：`deploy/sandbox/`、`agents/main_agent/workspace/`，compose 新增 `sandbox` 与测试用 `sandbox-test`）；目前只有离线验证 `agents/tests/spikes/test_v4_workspace_backend.py`。

## 原因与代价

- 隔离足够、实现简单；backend 不直接操作 Docker，不把相当于宿主机最高权限的 Docker 控制权交给 backend。
- 单人使用，按目录隔离会话已经够用。
- 代价：所有会话共用一个容器和同一份资源上限，会话之间只有目录级隔离，不适合多人使用。
- 代价：默认断网，需要装包时要手动开启联网；预装库要提前写进镜像（含中文字体，否则图中中文显示为方框），LibreOffice 体积大，只作为可选镜像变体。
- 代价：以后换云沙箱或每会话独立容器，要整体替换"工作区"接口的实现（文件与执行必须一起换）；跨多台机器运行时还要把工作区换成共享存储。
```

新建 `docs/decisions/D09-单进程运行并预留运行时替换点.md`：

```markdown
# D09：v1 单进程运行，预留运行时替换点，真实数据以数据库为准

- 状态：已采纳
- 日期：2026-10-12

## 背景

只有本人使用，v1 范围明确不做多进程。但以后可能需要多个工作进程、甚至多台机器，希望到时只改配置、加几个实现类，而不是重写运行管理。妨碍多进程的有 5 样东西：同会话互斥、事件推送、取消信号、运行在哪执行、后台任务。

## 备选方案

1. 一开始就做多进程：独立工作进程从 `runs` 表抢任务，事件经 PostgreSQL 消息通知或 Redis 消息流推送。
2. 单进程运行，但把上面 5 样东西做成可替换的点。

## 结论

- backend 以单进程运行，运行在 backend 进程内的后台任务中执行。
- 5 个替换点（设计文档 10.9）：
  - ① 同会话互斥：数据库部分唯一索引（同一会话只能有一条排队 / 运行中 / 等待审批的运行），天然支持多进程，不用改。
  - ② 事件推送："事件总线"接口，v1 为内存缓冲 + `run_events` 表；多进程时换 PostgreSQL 消息通知（推荐）或 Redis。
  - ③ 取消信号："运行控制"接口，v1 直接取消本进程任务；多进程时经事件总线广播。
  - ④ 运行在哪执行："运行执行器"接口；⑤ 后台任务："任务队列"接口（配合 `jobs` 表）。多进程时都由工作进程抢任务。
- 真实数据以数据库为准，内存只做加速；前端续传靠序号，不依赖连接粘在某个进程上；每个接口各有契约测试。
- 服务重启时把排队 / 运行中的运行标记为失败（"服务重启中断"），前端提供重试；等待审批的运行不受影响。

落地：M0：替换点①（`backend/migrations/versions/0001_backend_core.py` 的唯一索引）、替换点②（`backend/runtime/event_bus.py`）、启动时标记未完成运行（`backend/main.py`）；M1b：替换点③（`backend/runtime/run_control.py`）。替换点⑤随 M3 后台任务实施；替换点④目前尚未单独成接口，由 `backend/runs/manager.py` 直接在本进程启动后台任务。设计中由 `config/app.yaml` 的 `adapters.runtime` 选择实现，该配置项尚未加入。

## 原因与代价

- 单人使用，单进程足够，实现最简单。
- 以后切换的工作量：2～3 个新实现类（约 300 行）+ 一个 `python -m backend.worker` 启动命令（作为 compose 新服务）+ 配置 `runtime: postgres`。
- 代价：只能开一个 backend 进程，不能横向扩展；运行与接口服务在同一进程，服务重启时正在跑的运行会中断（记为失败，需手动重试）；停止服务时要先等运行收尾，为此容器必须用 `exec` 启动 uvicorn 并设置 `--timeout-graceful-shutdown`。
- 代价：内存里的事件缓冲随进程消失，运行结束后只保留一段时间，之后的补发要查数据库。
- 代价：现在就要为替换点多写接口和契约测试；以后真切到多进程，各进程的智能体缓存与 MCP 连接各存一份，MCP 配置变更时要经事件总线通知刷新；跨多台机器还要把工作区换成共享存储。
```

新建 `docs/decisions/D10-统一知识库.md`：

```markdown
# D10：统一知识库——一套知识存储、一套检索

- 状态：已采纳
- 日期：2026-10-12

## 背景

助理既要能检索用户上传的文档并带出处回答，又要跨会话记住偏好和事实（长期记忆），还要有一份每次都带上的个人画像。设计初稿按"四层记忆"分开处理（对话记忆、个人画像、事实记忆、知识库文档），第 2 版改为并入统一知识库。

## 备选方案

1. 原"四层记忆"：记忆、画像、文档各自存储、各自检索。
2. 用 deepagents 自带的文件式记忆（`memory=` 参数）和长期存储（`store=` 参数）。
3. 引入独立的向量数据库（Qdrant、Milvus、Elasticsearch 等）。
4. 只维护一个知识库，存在 PostgreSQL 里，用 pgvector（PostgreSQL 的向量检索扩展）和 jieba（Python 中文分词库）做检索。

设计文档明确不用 2，不引入 3（3 保留为"知识检索"接口以后可替换的实现）。

## 结论

- 知识库的最小单位是"知识条目"（`knowledge_items` 表），每条带标记：种类 `kind`（`document_chunk` 文档片段、`memory` 记忆，以后可扩展）、自由标签 `tags`、常驻 `pinned`、来源 `source`（对话 / 文档 / 手动）。文档本身（文件名、处理状态等）记在 `knowledge_documents` 表，原文件存在 `workdata/knowledge/`。
- 一套向量化、一套混合检索、一套管理界面：向量检索（找意思相近）与关键词检索（找人名、型号、报错码等精确词）两路结果按"倒数排名融合"合并排序。
- 中文关键词检索：在 Python 里先用 jieba 分词再存入全文检索字段，不必自建带中文分词插件的数据库镜像。
- 文档入库：markitdown（微软开源的格式转换工具）解析为 Markdown → 按标题结构切块（约 600 token，重叠约 80）→ 向量化 → 分词 → 写入条目。
- 智能体工具：`search_knowledge`（统一检索，可按种类、标签过滤）、`read_document`（读片段前后原文）、`remember`（记住一条）。
- 对话记忆不属于知识库，仍是 deepagents 的对话存档。记忆与个人画像的具体规则见 D11。

落地：M3 实施（计划位置：`agents/main_agent/knowledge/`、前端知识库页）。目前已就绪：数据库镜像自带 pgvector，`deploy/postgres/init.sql` 在主库启用了 `vector` 扩展。

## 原因与代价

- 一套存储、一套检索、一套管理界面，概念最少；不引入独立向量库，少运行一个服务。
- 记忆和文档用同样的方式查看、修改、删除，用户完全可控。
- 代价：文档片段与记忆共用一张表，数量级差异大。应对：检索按 `kind` 过滤并建过滤索引；记忆自动召回只查 `kind=memory`；文档片段不自动召回，由智能体按需检索。
- 代价：中文分词要在应用里先做一遍再入库；以后若改用外部向量库，要替换"知识检索"接口的实现并迁移数据。
```

新建 `docs/decisions/D11-记忆与个人画像都是知识条目.md`：

```markdown
# D11：记忆是知识条目，个人画像是常驻条目；会话后自动提取记忆

- 状态：已采纳
- 日期：2026-10-12

## 背景

成功标准之一是"越用越懂你"：跨会话记得用户的偏好和事实。同时记忆可能记错或过时，用户必须能看到、能改、能删。知识库已经统一（D10），记忆和个人画像需要在其中找到位置。

## 备选方案

1. 用 deepagents 自带的文件式记忆（`memory=`）与长期存储（`store=`）。
2. 记忆、画像各自单独存储（初稿"四层记忆"中的"事实记忆""个人画像"）。
3. 都作为知识库里带标记的条目，并在会话后自动提取记忆。

设计文档明确不用 1；2 在第 2 版并入知识库（见 D10）。

## 结论

- 记忆 = `kind=memory` 的知识条目；个人画像 = 打了"常驻"（`pinned`）标记的条目，如"我在 某公司 做后端""回答简洁点"。
- 常驻条目由 `KnowledgeContextMiddleware`（知识上下文中间件）在每次调用模型前拼入系统提示词；总量设上限（默认约 2000 token），超出时前端提示精简。
- 相关记忆自动召回：每条新用户消息先向量化，在 `kind=memory` 中查相似度超过阈值（初始 0.75）的前 5 条注入上下文。
- 知识怎么进来：对话中由智能体调用 `remember` 工具主动记（前端提示"已记住"）；每次运行结束后 backend 创建"记忆提取"任务，用便宜的模型读刚结束的对话，对每条信息判断"新增 / 更新已有 / 删除过时 / 忽略"；用户也可在知识库界面手动添加。
- 自动提取可在 `config/app.yaml` 关闭或更换模型；费用计入用量表（调用方"记忆提取"）。"记住一条记忆"默认无需审批。

落地：M3 实施（计划位置：`agents/main_agent/knowledge/`、后台任务 `backend/jobs/`、前端知识库页的"常驻"视图）。

## 原因与代价

- 实现"越用越懂你"，同时所有记忆都能在知识库界面统一查看、修改、删除，个人画像就是"常驻"视图。
- 代价：自动提取可能写入错误或过时的信息。应对：提取时先做"新增 / 更新 / 删除 / 忽略"判断；界面可改可删；可整体关闭。
- 代价：每次运行结束都多一次模型调用，产生少量费用；常驻条目每次都占用上下文，所以必须设总量上限。
- 代价：召回阈值 0.75 是初始值，效果要在实际使用中调整；每条新消息都要先向量化，受向量化速度影响（单条查询中位约 30 毫秒，见 D15）。
```

新建 `docs/decisions/D12-依赖版本精确锁定.md`：

```markdown
# D12：依赖版本确定——Python 用 uv、前端用 pnpm，直接依赖写精确版本，锁文件锁定全部间接依赖

- 状态：已采纳
- 日期：2026-10-12

## 背景

deepagents 等核心依赖迭代很快，0.7 版就有破坏性变更（默认不再带待办清单、基础提示词为空等）；litellm 曾出现被投毒的恶意版本（1.82.7 / 1.82.8）。环境必须可复现，依赖只能显式升级。uv 是 Python 的包与环境管理工具（管 Python 版本、虚拟环境、依赖安装与锁定）；pnpm 是前端包管理工具，作用同 npm，安装更快、锁定更严格。

## 备选方案

1. 直接依赖写版本范围（如 `^`、`~`），只靠锁文件固定间接依赖。
2. 前端用 npm 管理依赖。
3. Python 用 uv、前端用 pnpm，直接依赖一律精确版本，锁文件锁定全部间接依赖。

设计文档明确否定了 1（"不带 `^`、`~`"）；选 pnpm 而不是 npm 的理由是安装更快、锁定更严格。

## 结论

- **Python**：版本写在 `.python-version`（3.12）；`pyproject.toml` 所有直接依赖（含 `dev` 组的开发工具）写 `==` 精确版本；`uv.lock` 锁定全部间接依赖及哈希；安装一律 `uv sync --locked`，锁文件与 `pyproject.toml` 不一致时直接报错。
- **前端**：Node 版本写入 `.nvmrc` 与 `package.json` 的 `engines`；pnpm 版本写入 `packageManager` 字段；所有依赖写精确版本，`.npmrc` 设 `save-exact=true`；`pnpm-lock.yaml` 锁定间接依赖，安装一律 `pnpm install --frozen-lockfile`。
- **镜像**：compose 中第三方镜像写具体版本（见 D13），自建镜像的基础镜像同样固定；沙箱镜像的预装库也写精确版本。
- 新增或升级：`uv add 包名==版本`、`pnpm add -E 包名@版本`，并在 `docs/changelog.md` 记录原因。初始版本为 M0 时各依赖的最新稳定版（附录 A 为 2026-10-09 的调研基线）。

落地：M0：`pyproject.toml`、`uv.lock`、`.python-version`、`frontend/package.json`、`frontend/pnpm-lock.yaml`、`frontend/.nvmrc`、`frontend/.npmrc`，`make install`；规则见 `docs/development/coding-standards.md` 第 4 节。

## 原因与代价

- 任何时候重新安装都得到同一套依赖，可复现；破坏性变更只会在主动升级时出现。
- 精确版本 + 锁文件哈希 + 固定镜像，能避开已知的恶意版本。
- 代价：不会自动得到安全修复和新功能，每次升级都要手动做、跑完检查并记录原因。
- 代价：pnpm 11 会拒绝"发布时间太短"的版本，遇到时只能改选更早的稳定版本（规范要求不放宽这项策略）。
```

新建 `docs/decisions/D13-第三方服务一律由compose管理.md`：

```markdown
# D13：第三方服务一律由 docker-compose.yml 管理和构建

- 状态：已采纳
- 日期：2026-10-12

## 背景

项目依赖多个第三方服务：数据库、模型网关、向量模型服务、沙箱，以及自动化测试用的数据库和沙箱，以后还会增加（Redis、SearXNG、Langfuse、MinIO 等）。希望一条命令拉起完整环境，各服务版本统一固定。docker compose 是按一份配置文件启动一组容器的工具。

## 备选方案

1. 部分服务在宿主机上原生运行，例如 Ollama（本地运行开源模型的工具）原生运行可以用上苹果芯片的显卡加速。
2. 所有第三方服务都放进 `deploy/docker-compose.yml`。

设计文档 v1 选 2；1 留到以后需要本地对话模型时，作为本决策的例外另写决策记录（扩展路线阶段 1）。

## 结论

- 所有第三方服务一律在 `deploy/docker-compose.yml` 中定义、构建和启动，镜像写死具体版本标签和摘要；以后新增的服务同样加进这份文件。
- 服务清单：`postgres`（带 pgvector；两个库：业务用 `agent`、网关自用 `litellm`）、`litellm`（网关）、`ollama`（只做向量化，首次由一次性初始化服务拉取模型）、`sandbox`（只接内部网络）、`backend`（本项目镜像，正式使用时也托管打包好的前端）；`postgres-test`、`sandbox-test` 属于 `test` 配置组，数据放内存盘、测完即弃。
- 对外端口一律只绑定 `127.0.0.1`；`ollama`、`sandbox` 不对外。
- 需要自建的 MCP 服务也加进 compose；用 `npx` / `uvx` 启动的本地进程型 MCP 服务作为 backend 容器里的子进程运行。
- 常用操作统一走 `Makefile`：`make infra-up`、`make up`、`make test-int` 等。

落地：M0：`deploy/docker-compose.yml`（目前有 `postgres`、`litellm`、`ollama`、`ollama-init`、`backend`、`postgres-test`）、`deploy/backend.Dockerfile`、`deploy/postgres/init.sql`、`Makefile`；`sandbox`、`sandbox-test` 在 M2 加入。目前镜像只写了版本标签，尚未加摘要。

## 原因与代价

- 一条命令拉起完整环境，版本统一固定；测试用服务也由 compose 管理，集成测试自动启动、测完即弃。
- 代价：Mac 上的 Docker 用不了苹果芯片的显卡，容器里的 Ollama 只能用 CPU：本地对话模型 v1 因此不接，向量模型批量处理文档也偏慢（见 D15）。
- 代价：Mac 上容器收不到源码改动的通知，改了 Python 代码要 `make restart`；数据库数据放在 Docker 数据卷而不是 `workdata/`（Mac 上挂本地文件夹性能差、易出权限问题）。
- M0 遇到的环境问题：Docker Hub 不可达，镜像改经 `mirror.gcr.io` 与 `ghcr.io` 拉取；本机 Docker 配置残留凭据程序，Makefile 改用项目内的空配置；Ollama 镜像（arm64 约 2.7GB）与向量模型下载耗时较长。
```

新建 `docs/decisions/D14-开发规范与架构规范独立成文并做成技能.md`：

```markdown
# D14：开发规范与架构规范独立成文，并做成项目技能

- 状态：已采纳
- 日期：2026-10-12

## 背景

成功标准之一：任何人（或 AI 编程助手）开发新功能前读一份规范，就能写出与项目架构一致的代码。项目分 6 期开发，如果规范散落在设计文档各处或只靠口头约定，很难保证长期一致。项目技能是放在 `.claude/skills/` 下的说明文件，AI 编程助手在相关任务中会自动加载（注意与给智能体用的技能目录 `agents/skills/` 区分，后者 M2 加入）。

## 备选方案

设计文档没有列出其他认真比较的方案。明确否定的做法是在技能里再抄一份完整规范——"规范只维护一份，技能不重复抄写"。

## 结论

- 三份规范独立成文：`docs/development/architecture.md`（架构规范：三大块与依赖方向、模块模板、可替换接口写法、数据归属、各类新增步骤）、`docs/development/coding-standards.md`（编码规范）、`docs/development/testing.md`（测试规范）。
- 项目技能 `.claude/skills/dev-standards/SKILL.md`：在本项目开发、审查、重构代码时加载；正文只放核心要点和检查清单，细节指向三份规范。
- `CLAUDE.md` 声明"开发任何功能前先加载 dev-standards 技能"，并列出常用命令。
- 三条原则：官方规范优先（PEP 8 / PEP 257 / typing、FastAPI 与 LangChain 官方写法、TypeScript 严格模式与 React 官方规则）；代码精简（只为基础设施建接口，不为"以后可能"写代码）；与项目架构对齐。
- 标准流程：加载技能 → 在需求池登记 → 涉及架构取舍写决策记录 → 先写测试 → 实现 → `make check` 通过 → 同步 backlog、changelog（必要时 `architecture.md`）。

落地：M0（先写要点，后续各期逐步充实）：上述三份规范、`.claude/skills/dev-standards/SKILL.md`、`CLAUDE.md`；格式、类型、依赖方向和测试由 `make check` 一条命令检查。

## 原因与代价

- 开发新功能前先读规范，AI 编程助手每次开工自动加载同一份要点，保证长期一致；能自动检查的规则（格式、类型、依赖方向、写死颜色等）都交给 `make check`，不靠人记。
- 规范只维护一份，避免技能、文档两处内容不一致。
- 代价：规范要随代码同步更新，否则会误导后来的开发者和 AI 编程助手，所以"文档同步"被写进了完成定义，每个功能都多一步文档工作。
- 代价：设计文档、规范、技能三处都会提到同一批规则，修改规则时要确认三处的要点仍然一致。
```

新建 `docs/decisions/D15-向量化采用本地Ollama与Qwen3向量模型.md`：

```markdown
# D15：向量化用本地 Ollama + Qwen3 向量模型，经网关调用，统一 1024 维

- 状态：已采纳
- 日期：2026-10-12

## 背景

统一知识库（D10）和记忆召回（D11）都要把文字转成向量：向量模型把一段文字变成一串数字，意思相近的文字得到的数字也相近，靠它做"按意思检索"。知识库和记忆是个人数据，希望尽量不出本机；向量化调用频繁，希望没有边际费用；内容以中文为主。设计文档第 3 版确定了本方案，并新增先行验证 V6。Ollama 是在本机运行开源模型的工具。

## 备选方案

1. 更大的本地向量模型：`qwen3-embedding:4b`（更准、更慢）、`bge-m3`。
2. 云端向量模型：百炼 `text-embedding-v4`、OpenAI `text-embedding-3-small`（都可输出 1024 维）。
3. 本地 Ollama 运行千问 Qwen3 向量模型 0.6B（`qwen3-embedding:0.6b`）。

## 结论

- compose 中的 `ollama` 服务只做向量化，运行 `qwen3-embedding:0.6b`，不跑对话模型；首次启动由一次性初始化服务拉取模型。
- 在 `config/models.yaml` 中登记为 `embed-qwen3-0.6b`，与对话模型一样经 LiteLLM 网关调用（D01），价格记为 0。
- 所有向量统一 1024 维；每个知识条目记录所用的向量模型。
- 查询加一句任务说明前缀（官方称可提升约 1%～5%），文档片段不加；前缀写在知识模块的检索实现里。
- 换模型只需改 `config/models.yaml` 与 `config/app.yaml`，再运行"重建向量"脚本，表结构不变。
- 只有向量化在本机完成；记忆提取、标题生成等需要对话模型的任务用云端的便宜模型。

落地：M0：`deploy/docker-compose.yml` 的 `ollama`、`ollama-init` 服务，`config/models.yaml` 的 `embed-qwen3-0.6b`，先行验证结论见 `docs/decisions/M0-先行验证结论.md`（V6）；向量化接口、入库与检索在 M3 实施（计划位置：`agents/main_agent/models/`、`agents/main_agent/knowledge/`）。

## 原因与代价

- 知识与记忆不出本机、零边际费用、中文表现强、苹果芯片可直接运行。
- 1024 维低于 pgvector 向量索引的上限（2000 维），而且是各主流向量模型都能输出的尺寸，以后换模型只需重建向量、不改表结构。
- V6 结果（部分通过）：输出 1024 维，达标；单条查询向量化中位 30 毫秒，达标（目标 < 300 毫秒）；300 个约 600 token 的片段耗时 312 秒，未达标（目标 < 60 秒）。原因是 Mac 上容器内的 Ollama 只能用 CPU，约 1 秒处理一个片段。
- 代价：文档入库慢。原定退路"改用云端向量模型"当前不可用（公司网关没有向量模型、也没有直连厂商的密钥）；用户 2026-10-12 决定先接受当前速度——入库在后台进行，查询已经够快。以后改用云端向量模型（需求池 R11），届时改配置并重建向量，维度仍为 1024。
- 代价：0.6B 是该系列最小的版本，准确度不如更大的版本；Ollama 镜像（arm64 约 2.7GB）与模型首次下载耗时较长。
```

- [ ] **步骤 2：D16 补充与索引**

在 `docs/decisions/D16-前端采用assistant-ui与主题系统.md` 末尾追加：

```markdown
- 代价：本项目用的"外部数据源"接法（`useExternalStoreRuntime`）在 0.15.28 里位于 `legacy-runtime/` 目录。它尚未标记弃用，但说明官方主推的接法在变；升级 assistant-ui 时先确认它仍受支持（M1a 审查记录）。
```

在 `docs/decisions/README.md` 中，把：

```markdown
|---|---|---|
| D01～D15 | 见设计文档第 3 节（M1c 逐条补成独立记录） | 已采纳 |
| D16 | [前端采用 assistant-ui 与主题系统](D16-前端采用assistant-ui与主题系统.md) | 已采纳 |
```

改为：

```markdown
|---|---|---|
| D01 | [模型调用全部走 LiteLLM 网关（独立容器）](D01-模型调用统一走LiteLLM网关.md) | 已采纳 |
| D02 | [前后端通信用自定义推送协议（SSE），不用 AG-UI](D02-前后端通信采用自定义SSE推送协议.md) | 已采纳 |
| D03 | [模型按具体版本登记](D03-模型按具体版本登记.md) | 已采纳 |
| D04 | [用量用自建表按次记录，网关后台统计只作核对](D04-用量用自建表按次记录.md) | 已采纳 |
| D05 | [架构总纲——底层解耦，功能内聚；所有基础设施走可替换接口](D05-架构总纲底层解耦功能内聚.md) | 已采纳 |
| D06 | [agents / backend / frontend 三大块同级、单向依赖；单一 Python 项目](D06-三大块单向依赖的单一Python项目.md) | 已采纳 |
| D07 | [界面历史与模型上下文分开存](D07-界面历史与模型上下文分开存.md) | 已采纳 |
| D08 | [沙箱用常驻容器 + 共享工作区 + 内部专用网络，backend 不持有 Docker 控制权](D08-沙箱采用常驻容器与内部专用网络.md) | 已采纳 |
| D09 | [v1 单进程运行，预留运行时替换点，真实数据以数据库为准](D09-单进程运行并预留运行时替换点.md) | 已采纳 |
| D10 | [统一知识库——一套知识存储、一套检索](D10-统一知识库.md) | 已采纳 |
| D11 | [记忆是知识条目，个人画像是常驻条目；会话后自动提取记忆](D11-记忆与个人画像都是知识条目.md) | 已采纳 |
| D12 | [依赖版本确定——Python 用 uv、前端用 pnpm，直接依赖写精确版本，锁文件锁定全部间接依赖](D12-依赖版本精确锁定.md) | 已采纳 |
| D13 | [第三方服务一律由 docker-compose.yml 管理和构建](D13-第三方服务一律由compose管理.md) | 已采纳 |
| D14 | [开发规范与架构规范独立成文，并做成项目技能](D14-开发规范与架构规范独立成文并做成技能.md) | 已采纳 |
| D15 | [向量化用本地 Ollama + Qwen3 向量模型，经网关调用，统一 1024 维](D15-向量化采用本地Ollama与Qwen3向量模型.md) | 已采纳 |
| D16 | [前端采用 assistant-ui 与主题系统](D16-前端采用assistant-ui与主题系统.md) | 已采纳 |
```

- [ ] **步骤 3：检查点**

运行：`ls docs/decisions`

预期：列出 D01～D16 共 16 份记录、`M0-先行验证结论.md` 与 `README.md`；`README.md` 的索引每行都能点开对应文件。

---

### 任务 9：文档收尾与端到端验证

**文件：**
- 修改：`docs/development/testing.md`、`docs/requirements/backlog.md`、`docs/changelog.md`

- [ ] **步骤 1：测试规范、需求池、变更记录**

在 `docs/development/testing.md` 中，把：

```markdown
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`。
- **离线先行验证**放在 `agents/tests/spikes/`：用于固定"第三方库的关键行为"，库升级后它们会第一时间报警。
- 前端：纯逻辑（如 `features/chat/reducer.ts`、`components/chat/adapter.ts`）必须有 Vitest 单元测试；事件序列用接近真实的样例。
- 前端设计系统有两条自动检查：主题契约（`src/themes/themes.test.ts`）与写死颜色检查（`src/styles/no-raw-colors.test.ts`），改动主题或组件后它们必须通过。

```

改为：

```markdown
- **数据库测试**：使用根目录 `conftest.py` 的 `db` 夹具（每个测试前清空业务表）；不要连接开发库。
- **迁移测试**：改动已有数据的迁移要测"旧数据升级后的样子"：用 `alembic_config` 夹具退回到上一版（`command.downgrade`），写入旧格式的数据，再升级并核对；`finally` 里升回 `head`（见 `backend/tests/test_migrations.py`）。
- **接口测试**：使用 `backend/tests/conftest.py` 的 `make_client(模型)`，它直接装配服务对象，不走 `lifespan`。测试客户端的地址必须是 `http://localhost`（本机安全防护只接受本机主机名）；安全检查本身的测试在 `backend/tests/test_security.py`。
- **离线先行验证**放在 `agents/tests/spikes/`：用于固定"第三方库的关键行为"，库升级后它们会第一时间报警。
- 前端：纯逻辑（如 `features/chat/reducer.ts`、`components/chat/adapter.ts`）必须有 Vitest 单元测试；事件序列用接近真实的样例。
- 前端设计系统有两条自动检查：主题契约（`src/themes/themes.test.ts`）与写死颜色检查（`src/styles/no-raw-colors.test.ts`），改动主题或组件后它们必须通过。测试文件里的类名不会生成样式（`src/index.css` 的 `@source not`），可以放心写反例。
- **前端类型**：由 `make types` 生成（`src/api/generated/`）。`make check` 会核对两件事：`generated/openapi.json` 与后端当前的接口和事件定义一致（`backend/tests/test_openapi.py`），`schema.d.ts` 与 `openapi.json` 一致（`pnpm types:check`）。改了接口或事件却没重新生成时，按提示运行 `make types`。

```

需求池：R04c 完成；新增 R13（设计文档提到、目前还没做的代码高亮与数学公式）与 R14（写决策记录时核对出的、设计要求但尚未落地的三项基础设施细节）：

在 `docs/requirements/backlog.md` 中，把：

```markdown
| R12 | 体验优化：用户消息可选取复制、停止后由下一句话决定是否继续、中断处显示估算用量、左侧会话拖拽排序、重命名与删除、每轮耗时 | M1b 之后 | 高 | 完成 |
| R04c | 本机安全防护、前端类型自动生成、决策记录 D1～D15、M1a 遗留小问题 | M1c | 高 | 计划 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
```

改为：

```markdown
| R12 | 体验优化：用户消息可选取复制、停止后由下一句话决定是否继续、中断处显示估算用量、左侧会话拖拽排序、重命名与删除、每轮耗时 | M1b 之后 | 高 | 完成 |
| R04c | 本机安全防护（含可选访问令牌）、前端类型自动生成、决策记录 D1～D15、M1a / M1b / 体验优化遗留小问题、运行进行中刷新不重复显示 | M1c | 高 | 完成 |
| R05 | 沙箱执行代码、文件上传下载与产物预览、数据分析员子智能体 | M2 | 高 | 计划 |
```

在 `docs/requirements/backlog.md` 末尾追加：

```markdown
| R13 | 回答里的代码高亮与数学公式（设计文档 13.1 / 13.2；目前只支持表格等 GitHub 风格 Markdown） | 待定 | 中 | 待定 |
| R14 | 设计文档要求、尚未落地的基础设施细节（写决策记录时核对发现）：compose 镜像写摘要（digest，D13）；运行时替换点按 `config/app.yaml` 的 `adapters.runtime` 选择实现（D09）；替换点④"运行执行器"做成接口（D09） | 待定 | 低 | 待定 |
```

变更记录新增 M1c 小节，并更正 M1b 小节里"空串兜底"的旧说法：

在 `docs/changelog.md` 中，把：

```markdown
## 未发布

```

改为：

```markdown
## 未发布

### M1c 安全与稳固（完成）

- 新增：本机安全防护（设计文档 12.2）——只接受本机主机名与局域网 IP（防 DNS 重绑定）、写操作只接受同源或本项目前端的来源、POST 只接受 JSON；可选访问令牌（`.env` 的 `ACCESS_TOKEN`，设置后浏览器首次打开先输入令牌）；可选局域网访问（`.env` 的 `LISTEN_ADDRESS=0.0.0.0`，必须同时设置访问令牌，允许的网段在 `config/app.yaml`）；对话存档只反序列化登记过的类型（`LANGGRAPH_STRICT_MSGPACK=true`）。
- 新增：前端类型自动生成——`make types` 从后端接口文档与事件定义生成 `frontend/src/api/generated/`，`make check` 发现没重新生成时报错。
- 新增：决策记录 D01～D15 逐条成文（`docs/decisions/`）。
- 修复：运行进行中刷新页面，已输出的文字重复一遍（推送改为从最后一个已存事件之后接着订阅）。
- 修复：并行的子智能体刷新后回答只剩最后一段；同一段回答中间夹了用量事件会被拆成两个气泡。
- 修复：在"一次模型调用刚结束、正在写用量"时点停止，刚完成的回答没进对话存档（"继续"会重做）；停止后紧接着服务停止，收尾被打断；停止一个没有在执行的运行时推送不结束。用量改为在后台按调用顺序写入。
- 修复：发送请求还没返回时点停止不起作用（现在拿到运行 ID 后立即停止）；发送 / 停止失败的提示改为显示在输入框上方（不再把上一条回答标成出错）；会话已有进行中的运行（如另一个标签页发起的）时，发送失败后接上那次运行；发送失败恢复原文时不覆盖用户新输入的内容。
- 改进：被中断调用的估算费用按上一次调用实际的平均输入价格计算（含提示缓存折扣，不再高估好几倍）；估算失败一次运行只提示一次；结束事件的字段 `interrupted` 改名为 `interrupted_usage`（与运行状态"interrupted"区分，迁移 0004 同步改写已存历史）。
- 改进：左侧会话——拖完顺序没变时不保存、排序不再被同时进行的列表刷新覆盖；操作菜单支持键盘（方向键、Esc 回到"⋯"）、靠近窗口边缘时不被截掉、再点"⋯"收起；重命名时右键保留输入框自己的菜单；侧栏操作失败的提示几秒后自动消失。消息的复制按钮用键盘聚焦时也显示。
- 改进：不存在的接口用写操作访问时返回 404（原为 405）；排序请求里有重复会话 ID 时拒绝（422）；没有 `.env` 时 `make` 命令给出明确提示；列表加载失败立即显示并每 5 秒重试（不再先等约 7 秒）；写死颜色检查覆盖 `bg-[red]`、`oklch()` 等写法。

```

在 `docs/changelog.md` 中，把：

```markdown
- 改进：运行事件每 200 毫秒分批写库，进程中途退出也不丢已推送的内容；结束时整体替换为合并版本。
- 修复：服务停止时进行中的运行没有收尾（M0 遗留 M3；容器启动命令改为 `exec` 启动 uvicorn 并带 `--timeout-graceful-shutdown 3`）；回答片段 ID 缺失时用空串兜底（M0 遗留 M6）；只存了部分事件的运行补发时不结束、前端一直重连。
- 修复（独立审查）：收尾途中再次取消（连点停止、回答刚结束时点停止、停机时再取消）会让运行永久停在"运行中"、会话无法再发消息；停止或服务中断后再发消息，模型会把被打断的请求重做一遍（现在被打断的一轮会补上"已中断"说明）；分批写库收尾时可能吞掉自身的取消。
```

改为：

```markdown
- 改进：运行事件每 200 毫秒分批写库，进程中途退出也不丢已推送的内容；结束时整体替换为合并版本。
- 修复：服务停止时进行中的运行没有收尾（M0 遗留 M3；容器启动命令改为 `exec` 启动 uvicorn 并带 `--timeout-graceful-shutdown 3`）；回答片段 ID 缺失时改用该次模型调用的命名空间兜底（M0 遗留 M6）；只存了部分事件的运行补发时不结束、前端一直重连。
- 修复（独立审查）：收尾途中再次取消（连点停止、回答刚结束时点停止、停机时再取消）会让运行永久停在"运行中"、会话无法再发消息；停止或服务中断后再发消息，模型会把被打断的请求重做一遍（现在被打断的一轮会补上"已中断"说明）；分批写库收尾时可能吞掉自身的取消。
```

- [ ] **步骤 2：浏览器端到端验证**

先运行 `make build`（依赖与前端都改了，要重新构建镜像），再打开 http://127.0.0.1:8000。第 3、4 步会调用真实模型，费用约 0.1 美元。

1. **安全检查**（终端里运行）：
   - `curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.example' http://127.0.0.1:8000/api/health` 输出 `400`；
   - `curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/threads` 输出 `403`；
   - `curl -s -o /dev/null -w '%{http_code}' -X POST -d 'title=x' http://127.0.0.1:8000/api/threads` 输出 `415`；
   - 页面照常打开、能新建会话。
2. **访问令牌与局域网访问**（下面的环境变量只在本次启动生效，不改 `.env`）：
   - 运行 `LISTEN_ADDRESS=0.0.0.0 make up`（没有令牌）：后端启动失败，`make logs` 里能看到"必须同时在 .env 设置 ACCESS_TOKEN"。
   - 运行 `LISTEN_ADDRESS=0.0.0.0 ACCESS_TOKEN=local-test-token make up`，刷新页面，出现"需要访问令牌"页。
   - 输入错的令牌，显示"访问令牌不正确"；输入 `local-test-token`，进入正常界面，会话列表与推送都正常。
   - 用局域网地址打开 `http://<ipconfig getifaddr en0 的结果>:8000`：同样先出现令牌页，输入后能新建会话、发消息。
   - 再运行 `make up`，恢复为只有本机、不需要令牌。
3. **运行中刷新**：
   - 发送"请写一篇约 800 字的短文，介绍长城。"，输出到一半时刷新页面、重新打开该会话。
   - 已输出的部分只出现一次，后续文字接着出现，不重复；结束后再刷新一次，内容完整。
4. **停止与继续**：
   - 再发送一个长文请求，几秒后点停止，显示"已停止"和"被中断的调用：…约 $…"（估算费用与实际同量级，不再高出好几倍）；
   - 发送"继续"，模型接着已输出的部分往下写。
5. **以前的会话**：打开 M1b / 体验优化时期停止过的会话（如"西游记读后感"），"已停止"旁的"被中断的调用"估算仍在，每轮用量与耗时正常。
6. **会话列表**：
   - 点"⋯"打开菜单后按上下方向键切换、Esc 关闭（焦点回到"⋯"）；再点一次"⋯"收起菜单；
   - 在列表最下面的会话上右键，菜单完整显示在窗口内；
   - 重命名时在输入框里右键，出现浏览器自己的菜单（可粘贴）。

预期：以上全部符合描述。

- [ ] **步骤 3：检查点**

运行：`make check`

运行：`make test-int`

预期：`make check` 全部通过（Python 单元测试 98 个、前端 63 个）；`make test-int` 全部通过（集成测试 51 个）。

收尾：
- 全部通过后，`docs/changelog.md` 的 M1c 小节保持"（完成）"、`docs/requirements/backlog.md` 的 R04c 保持"完成"；
- 若浏览器验证有未通过项，两处改回"进行中"并记录原因。

---

## 自查记录（写计划时完成）

- **设计覆盖：**
  - 第 21 节 M1 行剩余部分：
    - 本机安全防护（12.2 的四条 + `LANGGRAPH_STRICT_MSGPACK`）→ 任务 1；
    - 前端类型自动生成（10.3 / 12.2 节末：普通接口从 OpenAPI、推送事件从 agents 的事件定义）→ 任务 2；
    - 补齐决策记录 D1～D16 → 任务 8（D16 已有，补一条代价）。
  - 10.4 续传的完善（运行中刷新不重复）→ 任务 3、4。
  - M1a / M1b / 体验优化三次审查延后的小问题：任务 1（重试时机）、3、4、5、6、7、9（文档）。逐条对照：
    - M1a：
      - 405 → 任务 7；每 5 秒重试 → 任务 1；`.env` 必需 → 任务 7；`useMemo` → 任务 6；
      - 颜色检查 → 任务 6；存储键 → 任务 6；409 发送 → 任务 4；恢复原文 → 任务 4；
      - 代码高亮与数学公式 → 任务 9 的 R13；D16 legacy-runtime → 任务 8；路径穿越 → 任务 7；
      - 发送失败提示位置 → 任务 4；侧栏提示常驻 → 任务 6。
    - M1b：
      - 发送未返回时停止 → 任务 4；用量拆开气泡 → 任务 3、4；停止失败标错 → 任务 4；
      - "空串"措辞 → 任务 9；明细顺序 → 任务 3；空闲运行停止不结束推送 → 任务 3。
    - 体验优化：
      - 写用量时停止 → 任务 3；`cancel_all` → 任务 3；排序竞争与无变化仍保存 → 任务 6；
      - 缓存折扣 → 任务 5；日志刷屏 → 任务 5；重命名时右键 → 任务 6；
      - 菜单键盘、贴边、收起 → 任务 6；复制按钮聚焦 → 任务 6；
      - 迁移回填与未知 ID 测试 → 任务 7；`interrupted` 命名 → 任务 5。
- **与设计文档的差异：**
  1. 12.2 第 3 条"文件上传接口额外要求自定义请求头"本期没有上传接口，已写进架构规范第 10 节，由 M2 新增上传接口时落实。
  2. 12.2 第 2 条"跨域只放行自己的前端来源"的做法是：不开启跨域（CORS），写操作再核对 Origin。前端与接口同源，开发时经 Vite 转发，所以不需要开启跨域。
  3. 令牌通过只供服务器读取的 Cookie 携带，而不是让前端在每个请求里带上。这样推送（EventSource 无法自定义请求头）也能带上令牌，令牌也不会暴露给页面脚本。
  4. 设计文档 12.2 第 1 条只说"接受 localhost / 127.0.0.1"；按用户要求（2026-10-14）增加局域网访问：允许私有网段的 IP，端口对局域网开放时必须设置令牌（局域网里的程序能伪造 Host，主机名检查挡不住它们）。
- **占位扫描：** 无"待定 / 以后实现"类步骤。
- **类型与命名一致性：**
  - 已用严格类型检查、mypy 与重放验证：
    - 事件字段（`interrupted_usage`）在 `events.py`、生成的类型、事件处理器、转换函数、迁移中一致；
    - `subscribeRun` 的新参数与 `activeRun` 的返回值一致；
    - `Calibration` 在跟踪器与主智能体中一致。
  - `RunManager._record_usage` 的 `after` 参数只在 manager 内部使用。
