# M4 MCP 与审批 实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务执行本计划。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`。
>
> 本计划只写定下来的决定：文件、名称与签名、取值、每个任务用哪些测试证明。函数体由执行者按签名与测试写出；只有签名和测试决定不了的规则才在计划里写明。

**目标：** 智能体能接入 MCP 服务；有副作用的操作先停下来问你，你在审批卡片上决定后它接着做；一次运行调用模型太多或花费太高时也停下来问你。

- 在 `config/mcp_servers.yaml` 登记 MCP 服务，后端启动时连上，服务提供的工具交给智能体用。首个接入的是官方的"文件夹读写"服务（`@modelcontextprotocol/server-filesystem`），读写一个共享文件夹（默认是本机 `workdata/shared/`）。它不需要任何账号。
- 审批规则（`config/approval_rules.yaml`）给每个工具标"自动执行"或"先问你"。智能体调用"先问你"的工具时运行暂停，对话里出现审批卡片，有四种选择：同意、修改参数后执行、拒绝、回复一句话。几小时后再审批、服务重启后再审批都可以。
- 预算刹车：一次运行默认最多调用模型 100 次、花费 2 美元。到了上限就暂停，由你选"继续"（再给一份同样的额度）或"停止"。
- 设置页：模型列表、MCP 服务（连接状态、提供的工具）、审批规则与预算、智能体技能（只读），以及"重新加载"按钮。
- 技能的两处小改进（2026-10-16 与用户确认并入 M4）：
  - 新加的技能在老会话里也能用上：deepagents 原本每个会话只在第一次运行时读一遍技能清单；
  - 设置页列出有哪些技能。

**完成标准（设计文档第 21 节 M4 行）：** 接入一个 MCP 服务，有副作用的操作会先请你审批。

**架构：**

- **新的可替换接口 `McpClient`**（设计文档 4.2 的 `mcp_client`，在 `agents/main_agent/integrations/`）。实现 `McpAdaptersClient`，基于 langchain-mcp-adapters。
  - 每个服务一个专属后台任务，长期保持一个连接。这个库默认每调用一次工具就新起一个进程，又慢又会丢掉服务的状态。
  - 接口只给出 `McpTool`：服务名、工具名、说明、是否声明只读、LangChain 工具对象。连接细节不外露。
- **审批规则判定**（`ApprovalPolicy`，同目录），按顺序：
  1. 规则文件里第一条匹配的为准（支持 `*` 通配）；
  2. 没写到的内置工具自动执行；
  3. 没写到的 MCP 工具：服务声明只读的自动执行，其余按 `mcp_default`（默认"先问你"）。
- **暂停与恢复走 deepagents 自带的 `interrupt_on`**，主智能体和子智能体都生效。
  - 智能体层：把输出流里的 `__interrupt__` 翻译成一个 `approval.required` 事件，带上全部待审批请求和当时的预算状态，然后结束这一段，不发 `run.finished`。
  - 恢复：`MainAgent.resume` 用 `Command(resume={中断 ID: 决定})` 接着跑；第一个事件是 `approval.resolved`。
- **预算刹车** `BudgetBrakeMiddleware`：每次调用模型前检查本次运行已用的次数和费用，到上限就 `interrupt`。
  - 恢复时按暂停那一刻的状态重建预算，节点重新执行时会走到同一个 `interrupt`，拿到"继续"后加一份额度（先行探测已验证）。
  - "停止"等同于停止运行（`POST /runs/{id}/cancel`）。
- **后端**：
  - 运行遇到 `approval.required` 时：状态改为 `interrupted`，用量合计写入数据库，后台任务结束，推送关闭；
  - `POST /runs/{id}/resume`：校验决定、把状态原子地改回 `running`，再开一个后台任务，事件序号接着往下编；
  - 等待审批时点停止，记为"已停止"，用量保留。
- **设置**：
  - `GET /settings/mcp-servers`、`GET /settings/approval-rules`；
  - `POST /settings/reload`：重新读两个配置文件、重连 MCP 服务、刷新模型信息，组装好的智能体随之失效重建。有运行正在进行时拒绝。
- **工具出错不算运行失败**（设计文档 10.7）：MCP 工具抛出的异常（超时、服务断开）由中间件转成"调用失败"的工具结果，交给智能体自行调整。LangGraph 默认只转换参数错误，其余异常会让整次运行失败。

**技术栈：**

- 新增 Python 依赖：`langchain-mcp-adapters==0.3.2`（设计文档第 16 节的版本）、`mcp==1.30.0`（0.3.2 要求 mcp 1.x，这是最新的 1.x）。
- 后端镜像加 Node.js 24（从已有的前端构建阶段复制），用来运行 `npx` 启动的 MCP 服务（设计文档 6 节"本地进程型 MCP 服务作为 backend 容器内的子进程运行"）。
- 前端沿用 assistant-ui 的数据片段（`data-*`）显示审批卡片，做法同"已记住"卡片。

**设计文档：** `docs/specs/2026-10-10-personal-agent-design.md`（第 5 版）：

- 4.2 节（`mcp_client` 替换点）、6 节（MCP 服务的运行位置）；
- 7.2 节（智能体组装、按"模型版本 + 工具配置版本"缓存）、7.5 节（审批规则与四种选择）；
- 10.1、10.3 节（运行状态、`approval.required`）；
- 10.5～10.8 节（暂停与恢复、取消、错误处理、预算刹车）；
- 12.1 节（运行与设置接口）、13.3 节（审批卡片、设置页）；
- 第 21 节 M4 行，需求池 R07。

## 全局约束

- 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容（import-linter 检查）。`agents.main_agent.integrations.mcp_adapters` 加进"backend 不得直接引用"的清单。
- deepagents 只能出现在 `agents/main_agent/runtime/`；langchain-mcp-adapters 只能出现在 `agents/main_agent/integrations/mcp_adapters.py`。
- 新增依赖只有 `langchain-mcp-adapters==0.3.2`、`mcp==1.30.0`，版本写死；`uv.lock` 由 `uv lock` 生成。MCP 服务的 npm 包在配置里写死版本（`@2026.8.31`）。
- 第三方服务与镜像一律由 `deploy/docker-compose.yml` 管理；只操作本项目的容器。
- 密钥只在 `.env`，**执行者不读取、不打印 `.env` 的内容**。MCP 服务需要的密钥用 `${变量名}` 引用环境变量。
- 只有 `frontend/src/components/chat/` 可以引用 `@assistant-ui/*`；组件只用语义样式类（两条自动检查）。
- 由命令生成的文件不手改：`frontend/src/api/generated/`（`make types`）、`uv.lock`。
- 前端命令一律通过 `make` 执行，或先把 `~/.nvm/versions/node/v24.21.0/bin` 加到 `PATH` 前面。
- 集成测试先 `make test-up`。
- 给用户看的报错一律是一句中文，原始异常只记进日志。
- 注释与文档用中文，代码标识符用英文；注释只写"为什么"。
- **当前不是 git 仓库：不执行任何 git 命令**；每个任务以"检查点"结束。

## 重点关注

1. **隔很久再审批、服务重启后再审批、重复提交**：
   - 等待审批的运行在重启后仍是"等待审批"，审批后从原处接着执行；
   - 同一个审批提交两次（连点、两个标签页）只执行一次，第二次得到 409；
   - 页面打开时有等待审批的运行，不反复重连推送。
   - 测试：任务 6 `test_resume_after_restart`、`test_second_resume_is_conflict`；任务 8 `activeRun` 跳过等待审批的运行。
2. **等待审批时点停止，或停止后直接发新消息**：
   - 运行记为"已停止"，用量保留；审批卡片显示"已停止，未执行"；
   - 新消息正常回答，没执行的操作不会被偷偷执行。
   - 测试：任务 4 `test_new_message_after_unanswered_approval`；任务 6 `test_cancel_while_waiting_keeps_usage`。
3. **MCP 服务起不来、中途卡住、调用出错**：
   - 其他功能照常；设置页写明原因（找不到命令、连接超时、缺少环境变量）；
   - 卡住的调用到时限就结束；出错作为工具结果交给智能体，不让整次运行失败。
   - 测试：任务 2 `test_broken_server_fails_with_reason`、`test_slow_call_times_out`；任务 3 `test_failing_mcp_tool_becomes_error_result`。
4. **修改参数时填错**：
   - 不是合法 JSON、不是对象：卡片里就地提示，不能提交；
   - 后端拒绝"修改"却没带参数、决定数量不对、对预算刹车给工具决定：422；
   - 改出了工具不接受的参数：工具报错作为结果。
   - 测试：任务 8 `parseEditedArgs`；任务 4 `test_answers_must_match_pending`。
5. **配置文件写错**（YAML 语法、未知字段、标准输入输出方式却没写 `command`、引用了没设置的环境变量）：
   - 重新加载返回中文原因，旧配置继续生效；
   - 启动时写错不影响启动，设置页显示原因；
   - 缺环境变量只影响那一个服务。
   - 测试：任务 1 各加载测试；任务 7 `test_reload_with_bad_file_keeps_old_config`。

## 先行探测结论（2026-10-16 写计划时实测，脚本在会话临时目录 `m4-probe/`）

| 问题 | 结论 |
|---|---|
| 审批中断在输出流里的样子 | `updates` 里出现 `{"__interrupt__": (Interrupt(value, id),)}`：子智能体里的中断先在子智能体的命名空间出现一次，再在顶层（`ns == ()`）出现一次。`value` 是 `{"action_requests": [{name, args, description}], "review_configs": [{action_name, allowed_decisions}]}`，**不带工具调用 ID** |
| 恢复 | `Command(resume={中断 ID: {"decisions": [...]}})`，并行的两个子智能体各有一个中断时一起恢复也正确。`edit` 用新参数执行，结果前面加一段英文说明；`reject` 写入一条状态为 error 的工具结果（带 message 时内容为 "User rejected the tool call for `X` with reason: …"）；`respond` 是"人替工具回答"：工具不执行，结果却显示成功 |
| 拒绝的结果从哪来 | 由 `HumanInTheLoopMiddleware.after_model` 节点直接写入，不经过 `tools` 节点：翻译器目前只看 `model`、`tools` 两个节点，会漏掉 |
| 有待审批的中断时直接发新消息 | 正常运行：`PatchToolCallsMiddleware` 给没执行的调用补上 "did not complete" 结果，模型照常回答 |
| 子智能体与 `interrupt_on` | 声明式子智能体（含通用子智能体）都继承顶层的 `interrupt_on`。deepagents 自动加的通用子智能体**不带我们的中间件**；自己提供一份名为 `general-purpose` 的定义（`{**GENERAL_PURPOSE_SUBAGENT, "middleware": [...]}`）就能带上 |
| 预算刹车用 `interrupt` | 在中间件的 `abefore_model` 里调用 `interrupt` 可行，主智能体、子智能体都可以。恢复时节点从头重新执行：按暂停时的状态重建预算，就会走到同一个 `interrupt`，它返回恢复值；拿到"继续"后加额度，之后再到上限还会再停 |
| 工具抛异常 | LangGraph 的 ToolNode 默认只把参数错误转成结果，其余异常（如 MCP 调用超时的 `McpError`）会让整次运行失败 |
| langchain-mcp-adapters 0.3.2 | `MultiServerMCPClient(connections, tool_name_prefix=True)` 给工具名加上服务名前缀（`demo_add_note`）；`tool.metadata` 带服务声明的标注（`readOnlyHint` 等，没声明时为 None）。默认每次调用新起一个进程（两次调用进程号不同）；`async with client.session(name)` 加 `load_mcp_tools(session, server_name=, tool_name_prefix=True)` 保持一个进程。会话必须在同一个任务里进入和退出（anyio），所以每个服务放一个专属任务；别的任务里并发调用没问题，取消一次调用后会话照常可用 |
| 出错与超时 | 工具本身报错：返回内容为 "Error executing tool …" 的结果（作为工具调用时是 status=error 的 ToolMessage）。连接参数 `session_kwargs={"read_timeout_seconds": timedelta(seconds=N)}` 让卡住的调用 N 秒后抛 `McpError`。命令不存在时立即抛 `FileNotFoundError` |
| 文件夹读写服务 `@modelcontextprotocol/server-filesystem@2026.8.31` | 14 个工具都带标注：读文件、列目录、搜索、查信息等声明只读；`write_file`、`edit_file`、`create_directory`、`move_file` 声明有副作用。包里没有写 Node 版本要求，镜像用 Node 24。1.0.0 版发布还不满两周，不用 |
| 技能清单何时读取 | deepagents 的 `SkillsMiddleware` 在 `before_agent` 里读技能清单，存进会话状态（`skills_metadata`）；状态里已有清单就不再读，所以新加的技能只有新会话看得到。官方给的办法是运行输入里带 `"skills_metadata": None`，请它重新读 |
| 后端容器 | 基础镜像 `ghcr.io/astral-sh/uv:0.11.7-python3.12-trixie-slim` 自带 uv（可用 `uvx`），没有 Node；前端构建阶段是 `node:24.21.0-trixie-slim`，同为 Debian trixie，可以直接复制 node 与 npm |

## 文件结构（本计划涉及）

```
config/
├── integrations.py          # 新：McpServerConfig、ApprovalRulesConfig、两个加载函数
├── mcp_servers.yaml         # 新：MCP 服务清单（files 服务）
├── approval_rules.yaml      # 新：审批规则
├── settings.py、app.yaml    # 改：adapters.mcp_client、integrations 文件路径、budget
agents/main_agent/integrations/
├── __init__.py              # 新：公开 McpClient、McpTool、McpServerStatus、ApprovalPolicy、ToolApproval
├── mcp.py                   # 新：MCP 客户端接口与数据结构
├── mcp_adapters.py          # 新：langchain-mcp-adapters 实现
└── approval.py              # 新：审批规则判定
agents/main_agent/runtime/
├── approvals.py             # 新：interrupt_on 组装、恢复决定的转换与校验、工具出错转结果的中间件
├── budget.py                # 新：RunBudget、BudgetBrakeMiddleware
├── skills.py                # 新：列出技能（名字、说明、出错原因）
├── events.py、translator.py、tracker.py、agent.py、__init__.py  # 改
agents/main_agent/context.py、bootstrap.py
agents/tests/fixtures/mcp/demo_server.py  # 新：测试用 MCP 服务
backend/
├── runs/manager.py、repo.py、writer.py、schemas.py  # 改：暂停、恢复、续接序号
├── runtime/event_bus.py     # 改：同一运行可以重新打开
├── settings/                # 新：IntegrationSettings（读配置文件、重新加载、出错原因）
├── api/settings.py          # 新：设置接口
├── api/router.py、deps.py、errors.py、main.py
common/errors.py             # 改：InvalidConfigError、InvalidRequestError → 422
deploy/backend.Dockerfile、docker-compose.yml、Makefile、.env.example
frontend/src/
├── features/chat/           # 改：reducer（审批条目、等待状态）、ChatView（提交审批）
├── components/chat/         # 改：审批卡片、预算卡片、工具卡片"等待审批"、输入框等待状态
├── features/settings/SettingsPage.tsx 等  # 新：设置页
├── api/                     # 改：resumeRun、设置接口、事件订阅在 approval.required 时关闭
└── layout/AppShell.tsx      # 改：侧栏"设置"入口
docs/                        # 改：架构规范、README、需求池、变更记录；新增 D18
```

---

### 任务 1：配置文件与加载

**文件：**
- 新建：`config/integrations.py`、`config/mcp_servers.yaml`、`config/approval_rules.yaml`、`config/tests/test_integrations.py`
- 修改：`config/settings.py`、`config/app.yaml`、`config/__init__.py`、`common/errors.py`、`backend/api/errors.py`、`config/tests/test_settings.py`

**接口：**
- 产出（`config` 公开）：
  - `McpServerConfig(BaseModel, extra="forbid")`：
    - 标识与开关：`name: str`（`^[a-z][a-z0-9_]{0,31}$`，做工具名前缀）、`description: str = ""`、`enabled: bool = True`；
    - 连接方式：`transport: Literal["stdio", "streamable_http", "sse"] = "stdio"`；
    - 标准输入输出方式：`command: str | None = None`、`args: list[str] = []`、`env: dict[str, str] = {}`；
    - 网络方式：`url: str | None = None`、`headers: dict[str, str] = {}`；
    - 时限：`connect_timeout: float = 60`（首次 `npx` 下载较慢）、`call_timeout: float = 60`；
    - `missing_env: list[str] = []`：加载时填入，配置里不能写。
  - `ApprovalRulesConfig(BaseModel, extra="forbid")`：`tools: dict[str, Literal["auto", "ask"]] = {}`（保持文件里的顺序）、`mcp_default: Literal["auto", "ask"] = "ask"`。
  - `load_mcp_servers(path: Path, env: Mapping[str, str]) -> list[McpServerConfig]`。
  - `load_approval_rules(path: Path) -> ApprovalRulesConfig`。
  - `BudgetConfig(BaseModel)`：`max_model_calls: int = 100`、`max_cost_usd: float = 2.0`（都要 > 0）。
  - `IntegrationsConfig(BaseModel)`：`mcp_servers_file: Path = CONFIG_DIR / "mcp_servers.yaml"`、`approval_rules_file: Path = CONFIG_DIR / "approval_rules.yaml"`。
  - `Settings` 新字段：`integrations: IntegrationsConfig`、`budget: BudgetConfig`；`AdaptersConfig.mcp_client: str = "mcp_adapters"`。
- 产出（`common.errors`）：`InvalidConfigError(AppError)`、`InvalidRequestError(AppError)`，在 `backend/api/errors.py` 都映射为 422。

**加载规则：**
- 文件格式：`servers:` 下每个键是服务名，值是其余字段。
- 文件不存在时当作没有服务或没有规则。这不是错误：用户可能删了文件。
- YAML 语法错误、未知字段、校验失败：抛 `InvalidConfigError`。消息一句中文，带文件名和出错位置，如 "config/mcp_servers.yaml 有误：files.command 必填（标准输入输出方式要写启动命令）"。
- 网络方式要写 `url`。
- `${名字}` 替换：在 `command`、`args`、`env` 的值、`url`、`headers` 的值里按 `env` 替换。没有的名字记进 `missing_env`（去重、按出现顺序），原文不替换。这不是加载错误：只影响这一个服务。

- [ ] **步骤 1：写失败的测试**

`config/tests/test_integrations.py`：

```python
def test_loads_servers_and_substitutes_env(tmp_path):
    # files: command npx, args 含 "${SHARED}"；env={"SHARED": "/shared"}
    [server] = load_mcp_servers(path, {"SHARED": "/shared"})
    assert (server.name, server.transport, server.args[-1], server.missing_env) == ("files", "stdio", "/shared", [])
def test_missing_env_is_recorded_not_raised(tmp_path):
    # github: url ..., headers {Authorization: "Bearer ${GITHUB_TOKEN}"}；env={}
    assert server.missing_env == ["GITHUB_TOKEN"]
def test_stdio_without_command_is_an_error(tmp_path):
    with pytest.raises(InvalidConfigError, match="command"): ...
def test_unknown_field_and_bad_yaml_are_errors(tmp_path):   # 拼错的 "comand" 与 "servers: [" 两种，消息都含文件名
def test_bad_server_name_is_an_error(tmp_path):              # "My Server" → InvalidConfigError
def test_missing_files_mean_nothing_configured(tmp_path):
    assert load_mcp_servers(tmp_path / "none.yaml", {}) == []
    assert load_approval_rules(tmp_path / "none.yaml") == ApprovalRulesConfig()
def test_rules_keep_file_order(tmp_path):                    # "files_*": auto 在前、"files_write_file": ask 在后 → list(rules.tools) 顺序不变
def test_rule_values_are_auto_or_ask(tmp_path):              # "yes" → InvalidConfigError
def test_shipped_config_files_load():                        # 仓库里的两个文件：files 服务、mcp_default == "ask"
```

`config/tests/test_settings.py` 加：`test_budget_defaults`（100、2.0、`adapters.mcp_client == "mcp_adapters"`）。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest config/tests -q`

预期：`ImportError: cannot import name 'load_mcp_servers'`。

- [ ] **步骤 3：实现**

写 `config/integrations.py` 与两个错误类。

`config/mcp_servers.yaml`：

```yaml
# MCP 服务清单（设计文档 7.2、7.5）。改完后在设置页点"重新加载"。
# 每个键是服务名（小写字母、数字、下划线），也是它的工具名前缀：files 服务的 write_file 工具叫 files_write_file。
# 本地进程型（npx / uvx 启动）在 backend 容器里运行；网络型直接连接 url。
# 需要密钥时写 ${变量名}：在 .env 里设置，并在 deploy/docker-compose.yml 的 backend.environment 里传进去。
servers:
  files:
    description: 共享文件夹（本机 workdata/shared/，.env 的 SHARED_DIR 可改成别的文件夹）
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem@2026.8.31", "/shared"]
  # github:
  #   description: GitHub
  #   transport: streamable_http
  #   url: https://api.githubcopilot.com/mcp/
  #   headers: { Authorization: "Bearer ${GITHUB_TOKEN}" }
```

`config/approval_rules.yaml`：

```yaml
# 工具审批规则（设计文档 7.5）：auto 自动执行，ask 先问你。改完后在设置页点"重新加载"。
# 名字可以用 * 通配，从上往下第一条匹配的为准。
# 没写到的工具：
# - 内置工具（读写会话文件、在沙箱里执行代码、检索知识库、记住一条记忆等）自动执行：
#   代码在断网的沙箱里执行；记忆可以随时在知识库页修改或删除。
# - MCP 工具：服务声明为只读的（查询类）自动执行，其余按 mcp_default。
mcp_default: ask
tools: {}
#  files_write_file: auto   # 例：写共享文件夹不用问我
#  execute: ask             # 例：执行代码前先问我
```

`config/app.yaml` 加：

```yaml
# 预算刹车（设计文档 10.8）：一次运行到了上限就暂停，由你选"继续"（再给一份同样的额度）或"停止"
budget:
  max_model_calls: 100 # 最多调用模型几次（含子智能体与上下文压缩）
  max_cost_usd: 2.0 # 最多花多少美元（网关算出的费用；没有价格的模型只按次数）
```

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest config/tests -q`

预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 2：MCP 客户端接口与实现

**文件：**
- 新建：`agents/main_agent/integrations/__init__.py`、`mcp.py`、`mcp_adapters.py`；`agents/tests/fixtures/mcp/demo_server.py`；`agents/tests/contracts/test_mcp_client_contract.py`
- 修改：`pyproject.toml`（依赖与 import-linter 清单）、`uv.lock`（命令生成）、`agents/tests/fakes.py`（`FakeMcpClient`）

**接口：**
- 消费：`McpServerConfig`（任务 1）。
- 产出（`agents.main_agent.integrations` 公开）：
  - `McpTool`（dataclass，frozen）：`server: str`、`name: str`（带前缀的工具名）、`description: str`、`read_only: bool | None`、`tool: BaseTool`；
  - `McpServerStatus(BaseModel)`：
    - `name: str`、`description: str`、`transport: str`；
    - `state: Literal["disabled", "connecting", "connected", "failed"]`、`error: str | None = None`；
    - `tools: list[str] = []`；
  - `McpClient`（接口）：
    - `async connect(servers: Sequence[McpServerConfig]) -> None`：先关掉现有连接，再并行连接这些服务；每个服务连上、失败或超时（`connect_timeout`）后才返回；
    - `tools() -> list[McpTool]`：已连接服务的工具，按服务在清单里的顺序；
    - `statuses() -> list[McpServerStatus]`：与清单同序，没连接过时为空；
    - `async close() -> None`。
- 产出（实现，不公开）：`McpAdaptersClient`。
- 产出（测试替身）：`FakeMcpClient(tools: list[McpTool], statuses: list[McpServerStatus] | None = None)`。它记下 `connected: list[list[McpServerConfig]]`；`connect` 之后 `tools()` 返回 `next_tools`（测试可设置）。

**规则：**
- 每个服务一个专属任务：进入 `client.session(name)`，用 `load_mcp_tools(session, server_name=name, tool_name_prefix=True)` 取工具，标记已连接，然后等待停止信号。`close` 与再次 `connect` 时通知停止并等任务退出。
- 连接参数：
  - 标准输入输出方式：`command`、`args`、`env`。`env` 要并上当前进程的 `PATH`，否则 `npx` 找不到 node；
  - 网络方式：`url`、`headers`；
  - 两种方式都带 `session_kwargs={"read_timeout_seconds": timedelta(seconds=call_timeout)}`。
- `read_only` 取 `tool.metadata["readOnlyHint"]`；没有标注时为 None。
- 不连接的情况：
  - `enabled: false`：状态 `disabled`；
  - 有 `missing_env`：状态 `failed`，原因 "缺少环境变量 GITHUB_TOKEN：在 .env 里设置，并在 docker-compose.yml 里传给 backend"。
- 失败原因（一句中文，原始异常记进日志）：
  - `FileNotFoundError` → "找不到命令 npx"；
  - 超时 → "连接超时（60 秒）"；
  - 其他 → "连接失败：<异常的第一行，最多 200 字>"。
- 一个服务失败不影响其他服务。

**测试用服务** `agents/tests/fixtures/mcp/demo_server.py`（FastMCP，名为 demo），四个工具：
- `list_notes`：声明只读，返回 `pid=<进程号> notes=[…]`；
- `add_note(text)`：返回 `pid=<进程号> added <text>`；
- `fail`：抛 `ValueError("坏了")`；
- `hang`：睡 3600 秒。

契约测试用 `sys.executable` 启动它。

- [ ] **步骤 1：新增依赖**

`pyproject.toml` 加 `"langchain-mcp-adapters==0.3.2"`、`"mcp==1.30.0"`；import-linter 的禁止清单加 `agents.main_agent.integrations.mcp_adapters`；运行 `uv lock` 与 `uv sync`。

预期：`uv.lock` 新增这两个包。如果 `mcp` 要求的 `httpx`、`pydantic` 版本与已锁定的冲突，就停下来报告。

- [ ] **步骤 2：写失败的测试**

`agents/tests/contracts/test_mcp_client_contract.py`。参数化实现（目前只有 `McpAdaptersClient`）；同一模块共用一个已连接 demo 的客户端，减少启动进程的次数：

```python
async def test_tools_carry_prefix_and_read_only(client):
    tools = {t.name: t for t in client.tools()}
    assert set(tools) == {"demo_list_notes", "demo_add_note", "demo_fail", "demo_hang"}
    assert (tools["demo_list_notes"].read_only, tools["demo_add_note"].read_only) == (True, None)
    assert tools["demo_add_note"].server == "demo"
    assert [s.state for s in client.statuses()] == ["connected"]
async def test_one_process_serves_all_calls(client):      # add_note 后 list_notes 能看到，两次返回的进程号相同
async def test_tool_failure_is_reported(client):          # 作为工具调用执行 demo_fail：结果 status == "error"，内容含 "坏了"
async def test_slow_call_times_out():                     # call_timeout=1 的新客户端：demo_hang 在 5 秒内抛出异常
async def test_broken_server_fails_with_reason():         # [demo, 命令为 "no-such-command-xyz" 的 broken]
    assert [s.state for s in statuses] == ["connected", "failed"]
    assert "找不到命令 no-such-command-xyz" in statuses[1].error
async def test_missing_env_and_disabled_are_not_started():  # missing_env=["TOKEN"] → failed 且原因含 "TOKEN"；enabled=False → disabled；tools() 为空
async def test_connect_again_replaces_servers():          # connect([demo]) 后 connect([]) → tools() == []、statuses() == []，原进程已退出
async def test_close_stops_servers():                     # close 后进程已退出（用 list_notes 返回的进程号检查 os.kill(pid, 0) 抛 ProcessLookupError）
```

- [ ] **步骤 3：运行测试，确认失败**

运行：`uv run pytest agents/tests/contracts/test_mcp_client_contract.py -q`

预期：`ImportError: cannot import name 'McpAdaptersClient'`。

- [ ] **步骤 4：实现**

按上面的规则写接口、实现、测试用服务与 `FakeMcpClient`。mypy 若报 langchain_mcp_adapters 缺类型，在 `pyproject.toml` 加 override，并在注释里写明原因。

- [ ] **步骤 5：运行测试，确认通过**

运行：`uv run pytest agents/tests/contracts/test_mcp_client_contract.py -q`

预期：8 个通过，总时长 20 秒以内。

- [ ] **步骤 6：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 3：审批规则判定、MCP 工具接入智能体、重新加载

**文件：**
- 新建：`agents/main_agent/integrations/approval.py`、`agents/main_agent/runtime/approvals.py`、`agents/main_agent/runtime/skills.py`、`agents/tests/test_approval.py`、`agents/tests/test_skills.py`
- 修改：`agents/main_agent/runtime/agent.py`、`agents/main_agent/runtime/__init__.py`、`agents/main_agent/integrations/__init__.py`、`agents/tests/test_main_agent.py`

**接口：**
- 消费：`McpClient`、`McpTool`（任务 2）；`ApprovalRulesConfig`、`McpServerConfig`（任务 1）。
- 产出（`agents.main_agent.integrations` 公开）：
  - `ToolApproval(BaseModel)`：`name: str`、`server: str | None`（内置工具为 None）、`action: Literal["auto", "ask"]`、`reason: str`；
  - `ApprovalPolicy(rules: ApprovalRulesConfig)`：
    - `decide(name: str, *, server: str | None, read_only: bool | None) -> ToolApproval`；
    - `table(builtin: Sequence[str], mcp_tools: Sequence[McpTool]) -> list[ToolApproval]`：先 MCP 工具，再内置工具。
- 产出（`agents.main_agent.runtime`）：
  - `BUILTIN_TOOLS: tuple[str, ...]`：智能体自带的工具名（deepagents 的文件、执行、待办、子智能体工具，加上 `search_knowledge`、`read_document`、`remember`）；
  - `MainAgent` 新增：
    - 构造参数 `mcp: McpClient | None = None`、`approval: ApprovalRulesConfig | None = None`；
    - `async reload_integrations(servers: Sequence[McpServerConfig], rules: ApprovalRulesConfig) -> None`：重连 MCP，换规则，清空组装缓存；
    - `mcp_servers() -> list[McpServerStatus]`；
    - `tool_approvals() -> list[ToolApproval]`；
    - `async close() -> None`：关闭 MCP 连接；
    - `skills() -> list[SkillInfo]`：列出技能目录里的技能。
  - `SkillInfo(BaseModel)`：`name: str`、`description: str`、`error: str | None = None`（`runtime/skills.py` 的 `list_skills(skills_dir: Path | None) -> list[SkillInfo]`）。
- 产出（`runtime/approvals.py`，内部）：
  - `interrupt_on(asks: Sequence[ToolApproval], descriptions: Mapping[str, str]) -> dict[str, InterruptOnConfig]`：每个"先问你"的工具 `allowed_decisions=["approve", "edit", "reject"]`，`description` 为工具说明（MCP 工具前面加 "<服务名> · "）；
  - `ToolErrorMiddleware(names: frozenset[str])`：只管这些工具。`awrap_tool_call` 捕获 `Exception`（`CancelledError` 照常抛出），返回 `ToolMessage(status="error", content="工具 <名> 调用失败：<一句原因>", tool_call_id=…, name=…)`，并记日志。

**判定规则（`decide` 的 `reason`，中文原样写死）：**

| 情况 | action | reason |
|---|---|---|
| 规则里的确切名字或通配匹配（第一条为准） | 规则的值 | `规则 <规则写法>` |
| 内置工具 | auto | `内置工具默认自动执行` |
| MCP 工具，`read_only is True` | auto | `服务声明为只读` |
| 其他 MCP 工具 | `mcp_default` | `MCP 工具默认（mcp_default）` |

**组装：**
- `_graph_for(model)` 把 MCP 工具（`[t.tool for t in mcp.tools()]`）加在知识库工具后面。
- `interrupt_on`：对内置工具与 MCP 工具逐个判定，只放"先问你"的。
- `ToolErrorMiddleware` 管全部 MCP 工具名，放在中间件列表最后。
- 组装缓存仍按模型版本；`reload_integrations` 清空缓存。正在跑的运行继续用它手里那份。

**技能：**
- `run` 的输入加 `"skills_metadata": None`：每次运行都重新读技能清单（只读几个本地文件的开头），新加的技能在老会话里也能用上。恢复（`Command`）不带输入，不受影响。
- `list_skills`：技能目录下每个子文件夹里的 `SKILL.md`，按文件夹名排序。读说明头的做法同 `subagents.py`。
  - 说明头缺 `name` 或 `description`、YAML 写错：照样列出，`name` 用文件夹名，`error` 为 "说明头不完整（需要 name 与 description）"；
  - 没有技能目录：空列表。

- [ ] **步骤 1：写失败的测试**

`agents/tests/test_approval.py`：

```python
def test_first_matching_rule_wins():
    policy = ApprovalPolicy(ApprovalRulesConfig(tools={"files_*": "auto", "files_write_file": "ask"}))
    assert policy.decide("files_write_file", server="files", read_only=False).action == "auto"
    assert policy.decide("files_write_file", server="files", read_only=False).reason == "规则 files_*"
def test_builtin_tools_default_to_auto():          # execute → auto，reason "内置工具默认自动执行"；规则 execute: ask → ask
def test_mcp_tools_follow_read_only_then_default(): # read_only True → auto；None / False → ask；mcp_default auto 时 → auto
def test_table_lists_mcp_then_builtin():           # table(["execute"], [只读工具, 写工具]) 的 name 顺序与 action
```

`agents/tests/test_main_agent.py` 加（`FakeMcpClient` 提供一个只读工具 `demo_list_notes`、一个会抛 `RuntimeError("断开")` 的工具 `demo_flaky`）：

```python
async def test_mcp_tools_are_available_to_the_agent():
    # 剧本：调用 demo_list_notes → 回答。事件里 tool.finished(name="demo_list_notes", status="success")，最后 run.finished(completed)
async def test_failing_mcp_tool_becomes_error_result():
    # 剧本：调用 demo_flaky → 回答。tool.finished status=="error"，output 含 "调用失败"；run.finished(completed)
async def test_reload_rebuilds_agent_with_new_tools():
    # 先跑一次（建立缓存）；reload_integrations([...], rules) 后 FakeMcpClient.next_tools 里的新工具在下一次运行中可被调用
def test_builtin_tool_names_match_the_agent():
    # 组装一个智能体，读出它绑定给模型的工具名（ScriptedChatModel 记下 bind_tools 收到的工具），
    # 与 BUILTIN_TOOLS 完全一致（没有 MCP、没有知识库时去掉对应的三个）
```

`ScriptedChatModel.bind_tools` 改为记下工具名（`bound: list[str]`），仍返回自身。

`agents/tests/test_skills.py`（技能目录用临时目录）：

```python
def test_lists_skills_with_name_and_description(tmp_path):   # a/SKILL.md、b/SKILL.md → 按文件夹名排序，name 与 description 取自说明头
def test_broken_skill_is_listed_with_reason(tmp_path):       # 说明头缺 description → name 为文件夹名，error 含 "说明头不完整"
def test_no_skills_dir_means_no_skills():                    # list_skills(None) == []
async def test_new_skill_is_seen_by_existing_thread(tmp_path):
    # 同一会话先跑一次；再往技能目录加一个技能；第二次运行时模型收到的系统提示里有新技能的名字
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_approval.py agents/tests/test_skills.py agents/tests/test_main_agent.py -q`

预期：`ImportError: cannot import name 'ApprovalPolicy'`（或 `'list_skills'`）。

- [ ] **步骤 3：实现**

按上面的接口与规则写。通配用 `fnmatch.fnmatchcase`。

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 4：审批暂停与恢复（智能体层）

**文件：**
- 修改：`agents/main_agent/runtime/events.py`、`translator.py`、`approvals.py`、`agent.py`、`__init__.py`
- 测试：`agents/tests/test_approvals_runtime.py`（新建）、`agents/tests/test_translator.py`

**接口：**
- 消费：任务 3 的 `interrupt_on`、`ApprovalPolicy`。
- 产出（`agents.main_agent.runtime` 公开，事件进前端类型）：
  - `DecisionType = Literal["approve", "edit", "reject"]`；
  - `ApprovalAction(BaseModel)`：`call_id: str`、`name: str`、`args: dict[str, Any]`、`server: str | None`、`description: str`、`allowed: list[DecisionType]`；
  - `BudgetStatus(BaseModel)`：`calls: int`、`cost: float`、`max_calls: int`、`max_cost: float`、`step_calls: int`、`step_cost: float`（"继续"时追加的那一份）；
  - `ApprovalRequest(BaseModel)`：`interrupt_id: str`、`agent_path: list[str]`、`kind: Literal["tool", "budget"]`、`actions: list[ApprovalAction] = []`；
  - 事件 `ApprovalRequired(_BaseEvent)`：`type: "approval.required"`、`requests: list[ApprovalRequest]`、`budget: BudgetStatus`；
  - 输入 `ToolDecision(BaseModel)`：
    - `type: DecisionType`；
    - `args: dict[str, Any] | None = None`：只用于 edit，且必须有；
    - `message: str | None = None`：只用于 reject，1～2000 字，表示"回复一句话"；
  - 输入 `ApprovalAnswer(BaseModel)`：`interrupt_id: str`、`decisions: list[ToolDecision] = []`。预算刹车的"继续"不带决定；
  - 事件 `ApprovalResolved(_BaseEvent)`：`type: "approval.resolved"`、`answers: list[ApprovalAnswer]`；
  - `MainAgent.check_answers(*, thread_id: str, model: str, answers: Sequence[ApprovalAnswer]) -> Awaitable[None]`；
  - `MainAgent.resume(*, thread_id, thread_short_id, run_id, model, message: str, answers: Sequence[ApprovalAnswer], budget: BudgetStatus) -> AsyncIterator[Event]`。
- 任务 5 会把 `budget` 用起来。本任务里 `ApprovalRequired.budget` 先按 `BudgetConfig()` 的默认值填（已用 0），`resume` 的 `budget` 参数先不使用。

**翻译规则（`Translator`）：**
- 记下每个 `tool.started` 的 `(agent_path, name, args) → call_id`，`tool.finished` 时去掉。
- `updates` 里有 `__interrupt__`：
  - 子智能体命名空间里的：只记下"中断 ID → agent_path"；
  - 顶层（`ns == ()`）的：生成请求，存进 `translator.approvals`，不立即输出。
- 生成请求的方法：
  - 工具审批：`value` 里有 `action_requests`，`kind="tool"`。每个动作按名字和参数，在同一 `agent_path` 还没配对的已开始调用里找第一个，取它的 `call_id`；找不到时为空字符串。`allowed` 取 `review_configs` 里同名的那条。
  - 预算刹车：`value["kind"] == "budget"`，`kind="budget"`，没有动作。
  - MCP 工具的 `server` 由工具名前缀判断：`MainAgent` 把 MCP 工具名到服务名的对照传给翻译器。
- `model`、`tools` 以外的节点（审批中间件 `HumanInTheLoopMiddleware.after_model`）：只翻译其中的 `ToolMessage`，输出 `tool.finished`。被拒绝的调用由它写入结果。
- 流结束后，`translator.approvals` 不为空：输出一个 `ApprovalRequired`，不输出 `RunFinished(completed)`；用量照常先输出。

**恢复规则：**
- `check_answers` 读 `graph.aget_state(...)` 的 `interrupts`：
  - 中断 ID 集合与答复的不一致：抛 `ConflictError("这次审批已失效：请刷新页面后再看")`；
  - 工具审批的决定数量与动作数量不等、决定类型不在 `allowed` 里、预算刹车的答复带了决定：抛 `InvalidRequestError`（一句中文）。
- 转换（`approvals.py` 的 `resume_command(answers, pending) -> Command`）：
  - approve → `{"type": "approve"}`；
  - edit → `{"type": "edit", "edited_action": {"name": <原名>, "args": args}}`；
  - reject → `{"type": "reject"}`；带 message 时为 `{"type": "reject", "message": "用户回复：<message>"}`；
  - 预算刹车 → `"continue"`；
  - 合成 `Command(resume={中断 ID: {"decisions": [...]} 或 "continue"})`。
- `resume` 先输出 `ApprovalResolved(answers)`，再像 `run` 一样驱动流。`run` 与 `resume` 共用一个内部驱动方法：输入、运行上下文、预算是参数。
- 恢复时的 `AgentContext.knowledge` 用 `message` 重新计算（常驻条目与相关记忆）。

"回复一句话"用 reject 带 message 实现，而不是设计文档第 20 节写的 respond：在 langchain 1.4 里 respond 是"人替工具回答"，工具没执行，卡片却显示成功。这一点写进决策记录 D18（任务 10）。

- [ ] **步骤 1：写失败的测试**

`agents/tests/test_approvals_runtime.py`。`MainAgent` + `ScriptedChatModel` + `InMemorySaver`；`FakeMcpClient` 提供 `demo_add_note`：read_only=None，所以先问你；它会记下收到的参数。

```python
async def test_ask_tool_pauses_with_approval_required():
    events = [e async for e in agent.run(...)]           # 剧本：调用 demo_add_note(text="买牛奶")
    assert events[-1].type == "approval.required"
    assert not any(e.type == "run.finished" for e in events)
    [request] = events[-1].requests
    started = next(e for e in events if e.type == "tool.started")
    assert request.kind == "tool" and request.actions[0].call_id == started.call_id
    assert (request.actions[0].name, request.actions[0].args, request.actions[0].server) == ("demo_add_note", {"text": "买牛奶"}, "demo")
    assert request.actions[0].allowed == ["approve", "edit", "reject"]
async def test_approve_runs_the_tool_and_continues():     # resume(approve)：第一个事件 approval.resolved；tool.finished success；run.finished completed；工具收到 {"text": "买牛奶"}
async def test_edit_runs_with_new_args():                 # edit args={"text": "买豆浆"} → 工具收到 {"text": "买豆浆"}
async def test_reject_with_message_tells_the_model():     # reject message="先别记" → tool.finished status=="error"；下一次模型调用收到的工具结果含 "用户回复：先别记"；工具没被调用
async def test_answers_must_match_pending():              # 错的中断 ID → ConflictError；两个决定对一个动作 → InvalidRequestError；edit 不带 args → pydantic ValidationError
async def test_approval_inside_subagent_has_its_path():   # 主智能体派 general-purpose，子智能体调用 demo_add_note → request.agent_path == ["main", <task 调用 ID>]，call_id 与子智能体里的 tool.started 一致
async def test_two_parallel_approvals_resume_together():  # 并行两个子智能体各调用一次 → 一个 approval.required 带两个请求；两份答复一起恢复后 run.finished completed
async def test_new_message_after_unanswered_approval():   # 暂停后不恢复，直接 run 新消息 → completed；工具没被调用；模型收到的消息里有那次调用 "did not complete" 的结果
```

`agents/tests/test_translator.py` 加：`test_rejected_call_from_approval_node_finishes_the_tool`（`HumanInTheLoopMiddleware.after_model` 节点更新里的 ToolMessage → `tool.finished` error；同一更新里的 AIMessage 不重复输出 `tool.started`）。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_approvals_runtime.py agents/tests/test_translator.py -q`

预期：`ImportError: cannot import name 'ApprovalAnswer'`。

- [ ] **步骤 3：实现**

按上面的接口与规则写。`events.py` 的 `Event` 联合类型加入两个新事件。

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2，再跑 `uv run pytest agents -q`。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make types`、`make check`。预期：全部通过（前端类型新增两个事件）。

---

### 任务 5：预算刹车

**文件：**
- 新建：`agents/main_agent/runtime/budget.py`、`agents/tests/test_budget.py`
- 修改：`agents/main_agent/context.py`、`runtime/tracker.py`、`runtime/translator.py`、`runtime/agent.py`、`runtime/subagents.py`（或 `agent.py` 里组装子智能体处）、`bootstrap.py`、`agents/main_agent/runtime/__init__.py`

**接口：**
- 消费：`BudgetConfig`（任务 1）；`BudgetStatus`、`ApprovalRequired`（任务 4）。
- 产出：
  - `RunBudget`（dataclass，可变）：
    - 字段 `calls: int`、`cost: float`、`max_calls: int`、`max_cost: float`、`step_calls: int`、`step_cost: float`；
    - `@classmethod start(config: BudgetConfig) -> RunBudget`、`@classmethod restore(status: BudgetStatus) -> RunBudget`；
    - `record(cost: float | None) -> None`：次数加一，费用已知时累加；
    - `exhausted() -> bool`：`calls >= max_calls or cost >= max_cost`；
    - `grant() -> None`：两个上限各加一份 step；
    - `status() -> BudgetStatus`。
  - `BudgetBrakeMiddleware`：`abefore_model` 里，`runtime.context.budget` 用完时 `interrupt({"kind": "budget", **status})`。返回 `"continue"` 时 `grant()`。
  - `AgentContext` 新字段 `budget: RunBudget | None = None`。
  - `RunTracker(..., budget: RunBudget | None = None)`：`on_llm_end` 里 `budget.record(cost)`。用量为空的调用也算一次。
  - `MainAgent` 构造参数 `budget: BudgetConfig | None = None`。`run` 用 `RunBudget.start`；`resume` 用 `RunBudget.restore(budget)`，即按暂停时的状态重建（先行探测：节点重新执行，会走到同一个 interrupt）。`ApprovalRequired.budget = budget.status()`。

**组装：**
- 主智能体中间件加 `BudgetBrakeMiddleware()`。
- 自定义子智能体的 `middleware` 也加它。
- 提供自己的通用子智能体 `{**GENERAL_PURPOSE_SUBAGENT, "middleware": [WorkDirectoryMiddleware(), BudgetBrakeMiddleware()]}`。这样通用子智能体也受预算约束，顺带补上它缺的工作目录说明。

- [ ] **步骤 1：写失败的测试**

`agents/tests/test_budget.py`：

```python
def test_budget_grants_another_step():
    budget = RunBudget.start(BudgetConfig(max_model_calls=2, max_cost_usd=1.0))
    budget.record(0.3); budget.record(None)
    assert budget.exhausted() and (budget.calls, budget.cost) == (2, 0.3)
    budget.grant()
    assert not budget.exhausted() and (budget.max_calls, budget.max_cost) == (4, 2.0)
    assert RunBudget.restore(budget.status()) == budget
async def test_brake_pauses_before_the_call_over_the_limit():  # max_model_calls=2，剧本 4 步：第 3 次调用前暂停
    # 最后一个事件 approval.required，requests[0].kind == "budget"，budget.calls == 2，模型只被调用了 2 次
async def test_continue_gives_another_quota():               # resume(continue, budget=暂停时的状态) → 再调用 2 次后又暂停，budget.max_calls == 4
async def test_cost_limit_also_pauses():                     # 每次 cost 0.6、上限 1.0 → 第 3 次前暂停（calls == 2，cost == 1.2）
async def test_subagent_calls_count_and_can_pause():         # 主 1 次 + general-purpose 子智能体里 2 次、上限 2 → 暂停请求的 agent_path 是子智能体
```

用量与费用来自 `ScriptedChatModel` 回复里的 `usage_metadata`、`response_metadata["response_cost"]`。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest agents/tests/test_budget.py -q`

预期：`ImportError: cannot import name 'RunBudget'`。

- [ ] **步骤 3：实现**

按上面的接口写。bootstrap 把 `settings.budget` 传给 `MainAgent`。

- [ ] **步骤 4：运行测试，确认通过**

运行：`uv run pytest agents -q`。预期：全部通过（已有测试不受预算影响：默认 100 次）。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 6：后端——等待审批的运行与恢复

**文件：**
- 修改：
  - `backend/runs/manager.py`、`repo.py`、`writer.py`、`schemas.py`、`__init__.py`；
  - `backend/runtime/event_bus.py`、`backend/api/router.py`；
  - `backend/tests/conftest.py`（组装智能体时可传入 `FakeMcpClient` 与审批规则）。
- 测试：
  - `backend/tests/test_manager.py`、`test_event_bus.py`、`test_writer.py`（单元）；
  - `backend/tests/test_api.py`（集成）。

**接口：**
- 消费：`MainAgent.check_answers`、`MainAgent.resume`、`ApprovalRequired`、`ApprovalAnswer`、`BudgetStatus`（任务 4、5）。
- 产出：
  - `ResumeRequest(BaseModel)`：`answers: list[ApprovalAnswer]`（1～10 条）；
  - `RunManager.resume(run_id: UUID, body: ResumeRequest) -> RunRecord`；
  - `RunRepo` 新增：
    - `pause(run_id, *, usage: UsageTotals) -> None`：状态 interrupted，写入用量；
    - `mark_resumed(run_id) -> bool`：`UPDATE … SET status = 'running' WHERE id = %s AND status = 'interrupted'`，改到返回 True；
    - `usage_totals(run_id) -> UsageTotals`：没有时为空合计；
  - `EventWriter(runs, run_id, *, interval=0.2, prior: Sequence[EventEnvelope] = ())`：`finish(events)` 用 `[*prior, *compact(events)]` 替换。已合并过的事件不能再合并：带 `full_text` 的片段会重复；
  - `InMemoryEventBus.open` 可以重新打开已关闭的运行：清除关闭标记，取消已安排的"过一段时间忘掉"；
  - 接口 `POST /api/runs/{run_id}/resume`（202，返回 `RunRecord`）。

**规则：**
- `_execute` 增加参数：`answers`（有则调用 `agent.resume`）、`prior`（已存事件）、`totals`（已有合计）、`budget`。
- 新事件序号从 `prior[-1].seq + 1` 起。已存事件合并过，序号不连续，不能用条数。
- 收到 `ApprovalRequired`：照常推送，记下"已暂停"。智能体随后结束，不发 `run.finished`。收尾时：
  - 等用量、文件写完；
  - `writer.finish`；
  - `runs.pause(usage=合计)`；
  - 关闭推送；
  - 不登记后续任务（标题、记忆提取）。
- `resume` 依次：
  1. 运行状态不是 interrupted：`ConflictError("这次运行没有在等待审批")`；
  2. 已存事件的最后一个不是 `approval.required`：`ConflictError`；
  3. `agent.check_answers`；
  4. `mark_resumed` 为 False：`ConflictError("这次审批已经提交过了")`；
  5. 读会话短 ID、已有合计；预算取最后那个 `approval.required` 的 `budget`；
  6. `bus.open`，登记后台任务；返回最新的运行记录。
- `cancel` 等待审批的运行（没有后台任务）：沿用 `_finish_idle`，但用量保留——`runs.finish` 与结束事件的 `usage` 都用 `usage_totals`。
- `stream`：等待审批、没有推送的运行，从界面历史补发到 `approval.required` 为止，然后结束，不补结束事件（现有逻辑已是如此，用测试固定下来）。
- 运行顺利结束后的 `_answer`（后续任务取回答全文）跨段拼接，现有逻辑即可，加测试固定。

- [ ] **步骤 1：写失败的测试**

`backend/tests/test_event_bus.py` 加：`test_reopened_run_streams_new_events_and_is_kept`（关闭后重新打开、发布 seq 5，订阅 after=4 收到；超过保留时间后 `has()` 仍为 True）。

`backend/tests/test_writer.py` 加：`test_finish_keeps_prior_events_as_they_are`（prior 里带 full_text 的片段原样保留，新片段单独合并）。

`backend/tests/test_manager.py`（集成）。用 `conftest` 的真实 `MainAgent` + `ScriptedChatModel` + `FakeMcpClient` 的先问你工具：

```python
async def test_run_pauses_for_approval(db):
    # 事件以 approval.required 结束、没有 run.finished；runs.status == "interrupted"；usage_totals.calls == 1
    # 同一会话再发消息 → ConflictError
async def test_resume_continues_with_following_seq(db):
    # resume(approve) → 新事件第一个是 approval.resolved，seq == 暂停时最后序号 + 1；
    # 最终 completed；界面历史里两段事件都在、序号递增；usage_totals.calls == 2；后续任务已登记
async def test_second_resume_is_conflict(db):         # 第二次 resume → ConflictError("这次审批已经提交过了")
async def test_resume_rejects_stale_answers(db):      # 错的中断 ID → ConflictError；状态仍是 interrupted
async def test_cancel_while_waiting_keeps_usage(db):  # cancel → status cancelled，run.finished(cancelled).usage.calls == 1，runs 表 usage 未被清空
async def test_resume_after_restart(db):              # 暂停后用新的 RunManager（同一数据库、同一 checkpointer）恢复 → completed
async def test_stream_of_paused_run_ends_at_approval(db):  # 推送关闭后再订阅：补发到 approval.required 就结束
```

`backend/tests/test_api.py`（集成）加：`test_resume_endpoint`（202；body 不合法 422；未暂停的运行 409）。

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest backend/tests/test_event_bus.py backend/tests/test_writer.py -q` 与 `uv run pytest -m integration backend/tests/test_manager.py backend/tests/test_api.py -q`

预期：新测试失败（`AttributeError: 'RunManager' object has no attribute 'resume'` 等）。

- [ ] **步骤 3：实现**

按上面的接口与规则写。

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make types`、`make check`、`make test-int`。预期：全部通过。

---

### 任务 7：设置接口、启动时连接、后端镜像带 Node

**文件：**
- 新建：`backend/settings/__init__.py`、`backend/settings/service.py`、`backend/api/settings.py`、`backend/tests/test_settings_api.py`
- 修改：
  - `agents/main_agent/bootstrap.py`（`_MCP_CLIENTS`）；
  - `backend/api/deps.py`、`backend/api/__init__.py` 或 `router.py`（挂上设置路由）、`backend/main.py`；
  - `backend/runs/repo.py`（`count_running`）；
  - `deploy/backend.Dockerfile`、`deploy/docker-compose.yml`、`Makefile`、`.env.example`。

**接口：**
- 消费：`load_mcp_servers`、`load_approval_rules`、`InvalidConfigError`（任务 1）；`MainAgent.reload_integrations`、`mcp_servers`、`tool_approvals`、`close`（任务 3）；`ModelGateway.list_models`。
- 产出：
  - `IntegrationSettings(settings: Settings, agent: MainAgent, runs: RunRepo)`：
    - `async load() -> None`：读两个文件并重连。读文件出错时记下原因，智能体用空配置，不抛出；
    - `async reload() -> None`：
      - 有 running 的运行：`ConflictError("有对话正在进行，等它结束或停止后再重新加载")`；
      - 读文件出错：抛 `InvalidConfigError`，旧配置不动；
      - 成功：重连、换规则，并调用 `agent.models.list_models()` 刷新模型信息（网关不可用只记日志），清除记下的原因；
    - `config_error: str | None`；
    - `rules: ApprovalRulesConfig`。
  - 接口：
    - `GET /api/settings/mcp-servers` → `McpServersView`：`servers: list[McpServerStatus]`、`config_error: str | None`；
    - `GET /api/settings/approval-rules` → `ApprovalSettingsView`：`mcp_default`、`rules: list[ApprovalRuleView(tool: str, action)]`（文件顺序）、`tools: list[ToolApproval]`、`budget: BudgetConfig`；
    - `GET /api/settings/skills` → `list[SkillInfo]`（每次请求现读，加了技能不用重新加载）；
    - `POST /api/settings/reload`（body `{}`）→ `ReloadResult`：`servers: McpServersView`、`approvals: ApprovalSettingsView`。
  - `Services.integrations: IntegrationSettings`。
  - lifespan：
    - 启动：`fail_unfinished` 之后用 `asyncio.create_task(services.integrations.load())` 在后台连接，不挡启动（首次 `npx` 下载可能要几十秒）；
    - 停止：先取消还没完成的连接任务，再 `await agent.close()`。

**镜像与 compose：**
- `deploy/backend.Dockerfile` 第二阶段从 `frontend` 阶段复制：
  - `/usr/local/bin/node`；
  - `/usr/local/lib/node_modules/npm`；
  - 建 `npm`、`npx` 两个链接：`../lib/node_modules/npm/bin/npm-cli.js`、`npx-cli.js`。
- `docker-compose.yml` 的 backend：
  - environment 加 `npm_config_cache: /app/workdata/cache/npm`（下载的 MCP 服务包随数据卷保留，重建容器不用重下）、`npm_config_update_notifier: "false"`；
  - volumes 加 `${SHARED_DIR:-../workdata/shared}:/shared`。
- `Makefile`：`up` 与 `build` 启动前 `mkdir -p workdata/shared`。podman 不会替你创建挂载的目录。
- `.env.example` 加注释说明 `SHARED_DIR`：可改成本机任意文件夹的绝对路径，智能体可以读写它；写入前会先问你。

- [ ] **步骤 1：写失败的测试**

`backend/tests/test_settings_api.py`（集成，用 `FakeMcpClient` 与临时目录里的配置文件）：

```python
async def test_lists_servers_and_effective_approvals(client):
    # GET mcp-servers：servers[0].state == "connected"、tools 含 "demo_add_note"
    # GET approval-rules：tools 里 demo_add_note → ask（"MCP 工具默认（mcp_default）"），demo_list_notes → auto（"服务声明为只读"），execute → auto；budget.max_model_calls == 100
async def test_reload_reads_files_again(client):        # 改规则文件 demo_add_note: auto 后 POST reload → 返回的 approvals 里变成 auto（"规则 demo_add_note"）；FakeMcpClient.connected 多一次
async def test_reload_with_bad_file_keeps_old_config(client):  # 写坏的 YAML → 422，detail 含文件名；GET approval-rules 仍是旧规则
async def test_reload_while_running_is_conflict(client):       # 有 running 的运行 → 409
async def test_startup_config_error_is_shown(client_with_bad_files):  # GET mcp-servers 的 config_error 含原因，接口 200
async def test_lists_skills(client):                     # GET skills 含仓库里的 excel 技能（name == "excel"，error 为 None）
```

- [ ] **步骤 2：运行测试，确认失败**

运行：`uv run pytest -m integration backend/tests/test_settings_api.py -q`

预期：404（路由还不存在）或 `ImportError`。

- [ ] **步骤 3：实现**

按上面的接口写。bootstrap 里：

```python
_MCP_CLIENTS: dict[str, Callable[[Settings], McpClient]] = {"mcp_adapters": lambda s: McpAdaptersClient()}
```

把它连同 `approval`、`budget` 一起传给 `MainAgent`。

- [ ] **步骤 4：运行测试，确认通过**

运行：同步骤 2。预期：全部通过。

- [ ] **步骤 5：镜像验证**

运行：`make build`，然后 `podman exec deploy-backend-1 sh -c 'node --version && npx --version'`（容器名以 `podman ps` 为准）。

预期：
- 打印 `v24.21.0` 与 npm 版本；
- `curl -s http://127.0.0.1:8000/api/settings/mcp-servers` 在一分钟内显示 files 服务 `connected`，有 14 个工具；
- `workdata/shared/` 已创建。

- [ ] **步骤 6：检查点**

运行：`make types`、`make check`、`make test-int`。预期：全部通过。

---

### 任务 8：前端——审批卡片与预算卡片

**文件：**
- 修改：
  - `frontend/src/features/chat/reducer.ts`、`reducer.test.ts`、`ChatView.tsx`；
  - `frontend/src/api/events.ts`、`events.test.ts`、`client.ts`；
  - `frontend/src/components/chat/adapter.ts`、`adapter.test.ts`、`parts.tsx`、`ChatThread.tsx`、`index.ts`。
- 新建：
  - `frontend/src/components/chat/approvalActions.ts`（React 上下文，做法同 `citationActions.ts`）；
  - `frontend/src/features/chat/approvals.ts`、`approvals.test.ts`。

**接口：**
- 消费：生成的类型 `ApprovalRequired`、`ApprovalResolved`、`ApprovalAnswer`、`ToolDecision`、`BudgetStatus`（任务 4、6）；接口 `POST /runs/{id}/resume`。
- 产出：
  - `ChatItem` 新成员 `{ kind: "approval"; id: \`approval-${run_id}-${seq}\`; runId; seq; requests: ApprovalRequest[]; budget: BudgetStatus; status: "pending" | "submitting" | "resolved" | "stopped"; answers?: ApprovalAnswer[] }`；
  - 工具条目 `status` 加 `"waiting"`；
  - `timing` 条目加 `pausedMs?: number`、`pausedAt?: string`；
  - `pendingApproval(state: ChatState): ApprovalItem | null`；
  - `approvals.ts`：
    - `type Choice = { type: "approve" } | { type: "edit"; text: string } | { type: "reject" } | { type: "reply"; message: string }`；
    - `parseEditedArgs(text: string): { ok: true; args: Record<string, unknown> } | { ok: false; error: string }`；
    - `toAnswers(item: ApprovalItem, choices: Record<string, Choice>): ApprovalAnswer[] | null`：键为 `${interrupt_id}/${动作序号}`，有动作没选或修改的 JSON 不合法时为 null；
    - `choiceLabel(decision: ToolDecision): string`；
  - `api.resumeRun(runId: string, answers: ApprovalAnswer[]): Promise<RunRecord>`。

**规则：**
- 事件处理器：
  - `approval.required`：
    - 加审批条目（pending），`running: false`；
    - 请求里各动作的 `call_id` 对应的工具卡片改为 `waiting`。子智能体内部的按 `agent_path` 找到嵌套位置；
    - timing 记 `pausedAt`。
  - `approval.resolved`：最近的 pending 或 submitting 条目改为 resolved 并记下 answers；`running: true`；timing 的 `pausedMs` 加上这段等待。
  - `run.finished` 时还有 pending 或 submitting 的审批条目：改为 stopped。
- 耗时显示扣掉 `pausedMs`。
- `activeRun` 跳过状态为 interrupted 且最后一个事件是 `approval.required` 的运行：它在等你，没有推送可接。
- `subscribeRun` 收到 `approval.required` 也主动关闭，避免浏览器自动重连。
- `ChatView`：
  - 提交审批：条目改为 submitting，调 `resumeRun`；成功后 `setActive({ id: runId, afterSeq: item.seq })`；
  - 失败时提示"提交审批失败：…"，条目回到 pending；409 时 `resync()`；
  - 停止：没有正在订阅的运行、但有等待中的审批时，停止那次运行。
- 卡片（`parts.tsx` 的 `ApprovalPart`，数据片段 `data-approval`）：
  - **工具审批**：每个动作显示工具名、服务名、说明、参数（格式化 JSON），四个按钮"同意""修改后执行""拒绝""回复"：
    - "修改后执行"：展开参数编辑框，内容不合法时就地显示原因；
    - "回复"：展开一行输入，提示"告诉智能体该怎么做"；
    - 每个动作都选好后提交；只有一个动作时选完即提交（"修改""回复"在点确定时提交）。
  - **预算刹车**：
    - 文字："本次运行已调用模型 {calls} 次、花费约 ${cost}，到了上限（{max_calls} 次 / ${max_cost}）。"；
    - 按钮："继续（再给 {step_calls} 次 / ${step_cost}）""停止"。"停止"调停止运行。
  - **已处理**：显示每个动作的选择（`choiceLabel`："已同意""已修改参数后执行""已拒绝""已回复：…"），预算的显示"已继续"；stopped 显示"已停止，未执行"。
  - 工具卡片 waiting 状态显示"等待审批"：adapter 用 `artifact` 带出 `waiting: true`。
- 输入框：有等待中的审批时不能发送。占位文字"请先处理上面的审批，或点停止"，发送按钮换成停止按钮（设计文档 10.1"有待审批时须先处理审批"）。

- [ ] **步骤 1：写失败的测试**

`reducer.test.ts`：
- `approval.required adds a pending approval and marks tool cards waiting`：含子智能体内的工具卡片；
- `approval.resolved resolves it and resumes running`；
- `run.finished while waiting marks the approval stopped`；
- `paused time is not counted in the duration`；
- `activeRun skips a run waiting for approval`。

`approvals.test.ts`：
- `parseEditedArgs`：`'{"a":1}'` 成功；`'[1]'` 与 `'{'` 失败，原因分别含"对象"与"JSON"；
- `toAnswers`：缺选择时为 null；approve / edit / reject / reply 分别变成 `{type:"approve"}`、`{type:"edit",args}`、`{type:"reject"}`、`{type:"reject",message}`；预算请求变成 `{interrupt_id, decisions: []}`；
- `choiceLabel` 四种文字。

`adapter.test.ts`：审批条目变成 `data-approval` 片段；waiting 工具的 artifact 带 `waiting: true`。

`events.test.ts`：收到 `approval.required` 后关闭。

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm test`（`PATH` 先加 Node 24）

预期：新测试失败。

- [ ] **步骤 3：实现**

按上面的接口与规则写。

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm test`。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 9：前端——设置页

**文件：**
- 新建：`frontend/src/features/settings/SettingsPage.tsx`、`labels.ts`、`labels.test.ts`
- 修改：`frontend/src/layout/AppShell.tsx`、`frontend/src/api/queries.ts`、`client.ts`

**接口：**
- 消费：任务 7 的三个设置接口、已有的 `GET /models`（`modelsQuery`）。
- 产出：
  - `mcpServersQuery`、`approvalSettingsQuery`、`skillsQuery`；`api.reloadSettings(): Promise<ReloadResult>`；
  - `labels.ts`：
    - `serverStateLabel(state)`："未启用""连接中""已连接""连接失败"；
    - `actionLabel(action)`："自动执行""先问你"；
    - `formatPerMillion(costPerToken: number | null): string`：每百万 token 的美元价格，没有时"—"。

**页面：**
- 侧栏"知识库"下面加"设置"（齿轮图标），做法同知识库入口。
- 设置页五个区块：
  - **外观**：已有的深浅色切换。
  - **模型**：版本名、上下文长度、输入 / 输出价格（每百万 token）、能否看图、能否深度思考。
  - **MCP 服务**：每个服务显示名字、说明、状态、失败原因、工具清单（工具名与"自动执行 / 先问你"）。`config_error` 不为空时在顶上显示。
  - **审批规则与预算**：
    - 规则文件里的规则（按顺序）、`mcp_default`；
    - 全部工具的生效结果和原因（可折叠）；
    - 预算两个数，旁注"改 config/app.yaml 后需要 make restart"。
  - **技能**：每个技能的名字、说明；出错的显示原因。旁注"在 agents/skills/ 下加一个带 SKILL.md 的文件夹即可新增，新老会话都能用上"。
- 页面右上角"重新加载"按钮：
  - 加载中按钮禁用；
  - 成功后刷新三个设置查询和模型列表，显示"已重新加载"；
  - 失败显示原因（409 / 422 的 detail）。
- 页首一句说明："MCP 服务与审批规则在 config/mcp_servers.yaml、config/approval_rules.yaml 里修改，改完点重新加载。"

- [ ] **步骤 1：写失败的测试**

`labels.test.ts`：三个函数的全部取值；`formatPerMillion(0.000003) === "$3.00"`，`formatPerMillion(null) === "—"`。

- [ ] **步骤 2：运行测试，确认失败**

运行：`cd frontend && pnpm test`。预期：`labels.test.ts` 失败（模块不存在）。

- [ ] **步骤 3：实现**

按上面的规则写。

- [ ] **步骤 4：运行测试，确认通过**

运行：`cd frontend && pnpm test`。预期：全部通过。

- [ ] **步骤 5：检查点**

运行：`make check`。预期：全部通过。

---

### 任务 10：真实模型验证、端到端验收、文档

**文件：**
- 修改：
  - `agents/tests/live/test_smoke.py`；
  - `docs/development/architecture.md`、`README.md`、`docs/requirements/backlog.md`、`docs/changelog.md`、`docs/decisions/README.md`。
- 新建：`docs/decisions/D18-审批与预算刹车的实现方式.md`。

- [ ] **步骤 1：真实模型验证（会产生少量费用）**

`test_smoke.py` 加 `test_mcp_side_effect_needs_approval`：
- 真实网关 + 默认模型 + 测试用 demo 服务（`McpAdaptersClient`）；
- 消息"用 demo 的工具记一条笔记：买牛奶，然后告诉我现在有哪些笔记"。

断言：
- 第一段以 `approval.required` 结束，动作是 `demo_add_note`，参数含"买牛奶"；
- 期间 `demo_list_notes` 若被调用，是自动执行的；
- 同意后 `run.finished(completed)`，回答里有"买牛奶"。

运行：`make smoke`。预期：全部通过。

- [ ] **步骤 2：端到端验收（浏览器，`make build` 之后）**

在内置浏览器里依次验证：
1. 设置页：files 服务"已连接"，`files_write_file` 显示"先问你"，`files_list_directory` 显示"自动执行"；技能区块列出 excel。
2. 新会话发"列出共享文件夹里的文件"：没有审批卡片，直接回答。
3. 发"在共享文件夹里新建 hello.txt，内容写：你好"：出现审批卡片；工具卡片显示"等待审批"；输入框不能发送。
4. 点"修改后执行"，把内容改成"你好，世界"，提交：运行接着跑完，`workdata/shared/hello.txt` 的内容是"你好，世界"。
5. 再让它写一个文件，这次"回复"："先别写，把内容发给我看"：回答里给出内容，文件没有生成。
6. 再让它写一个文件，出现审批卡片后执行 `make restart`；刷新页面，卡片还在；点"同意"后完成。
7. 再让它写一个文件，出现审批卡片后点"停止"：卡片显示"已停止，未执行"；接着发一句"你好"，正常回答，文件没有生成。

验收结束后删掉 `workdata/shared/` 里这次生成的文件，删掉验收用的会话。

- [ ] **步骤 3：文档**

- **architecture.md**：
  - 目录结构加 `agents/main_agent/integrations/`、`backend/settings/`；
  - 可替换接口表加 `McpClient`；
  - 新增"审批与恢复"一节，约定三条：
    1. 只有 `ApprovalRequired` 能让一段运行不带 `run.finished` 结束；
    2. 恢复时的事件序号从已存最后一个起算；
    3. 中间件里的 `interrupt` 必须在节点重新执行时走到同样的位置（预算按暂停时的状态重建）。
- **README**：
  - MCP 服务怎么加，含需要密钥的写法；
  - 审批规则；
  - 预算；
  - 共享文件夹与 `SHARED_DIR`；
  - 怎么新增技能（新老会话都能用上）；
  - 设置页与"重新加载"。
- **需求池**：R07 改为完成；登记 R22"技能管理：在界面上传技能、从官方技能库导入"（待定）；登记任务中延后的小问题（如有）。
- **变更记录**：加 M4 一节。
- **D18**，写四个决定的来由与代价：
  1. "回复"用 reject 带 message（不用 respond）；
  2. MCP 工具默认看服务的只读声明；
  3. 预算刹车用 interrupt，"停止"即停止运行；
  4. 重新加载时有运行在进行就拒绝。

- [ ] **步骤 4：检查点**

运行：`make check`、`make test-int`。预期：全部通过。

---

## 自查记录（写计划时完成）

- **设计文档覆盖**：
  - 4.2 `mcp_client` → 任务 2；
  - 7.2 MCP 工具与缓存失效 → 任务 3；
  - 7.5 规则与四种选择 → 任务 1、3、4、8；
  - 10.1 等待审批时须先处理 → 任务 8；
  - 10.3 `approval.required` → 任务 4；
  - 10.5 暂停与恢复、重启后再审批 → 任务 4、6；
  - 10.6 取消 → 任务 6；
  - 10.7 工具出错不算失败 → 任务 3；
  - 10.8 预算刹车 → 任务 5、8；
  - 12.1 resume 与设置接口 → 任务 6、7；
  - 13.3 审批卡片、设置页 → 任务 8、9；
  - 6 节 backend 镜像带 Node → 任务 7；
  - 7.4 技能（每次运行重新读清单、设置页列出）→ 任务 3、7、9；
  - 第 21 节完成标准 → 任务 10。
- **名称一致**：
  - `ApprovalAnswer`、`ToolDecision`、`BudgetStatus`、`ApprovalRequired.requests`：在任务 4 定义，任务 5、6、8 引用；
  - `MainAgent.reload_integrations`、`mcp_servers`、`tool_approvals`、`close`：在任务 3 定义，任务 7 引用；
  - `RunBudget.restore`：在任务 5 定义，由任务 6 通过 `MainAgent.resume(budget=…)` 间接使用。
- **偏离设计文档的地方**：
  - "回复一句话"用 reject 带 message，没用第 20 节写的 respond（理由见任务 4，记入 D18）；
  - 预算改了 `config/app.yaml` 要重启才生效：设计文档的"重新加载"只说配置，本计划只重新加载两个规则文件和模型信息。
