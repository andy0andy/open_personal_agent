# 管理页面接上后端（交付方式 C）实施计划

> **给执行者：** 必须使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐个任务执行本计划（用户已选方式二：本会话内执行 + 最后一次整体审查）。步骤用复选框（`- [ ]`）跟踪。开始任何任务前先读 `.claude/skills/dev-standards/SKILL.md`、设计文档与 D21。
>
> 本计划只写定下来的决定：文件、名称与签名、取值、每个任务用哪些测试证明。函数体由执行者按签名与测试写出。

**目标：** 模型、技能、MCP 三页从预览改成真实读写：改动存进 `workdata/` 与网关数据库，改完立即生效。

**本轮范围**（2026-10-18 与用户确认，见 D21）：
- 只读目录不动：`config/`、`agents/skills/`。用户的改动写进 `workdata/config/`（`mcp_servers.yaml`、`approval_rules.yaml`、`app.yaml`、`skills.yaml`）与 `workdata/skills/`。
- 加载：先 `workdata/` 后 `config/`，`config/` 兜底；同名的以 `workdata/` 为准：
  - MCP 服务：同名的**按字段覆盖**。所以停用一个自带服务，只要写 `{enabled: false}`。
  - 审批规则：按工具名覆盖。
  - `app.yaml`：逐层按设置项覆盖。
- 模型：页面新增、修改、删除的模型经**网关的模型管理接口**存进网关数据库。自带模型（`config/models.yaml`）在页面上只读。
- 技能：上传的不许与已有技能同名（含自带的，不分大小写）。自带的只能停用，不能删。
- 密钥不经页面：
  - 新模型只引用 `.env` 已有的密钥；
  - 需要密钥的 MCP 服务，页面只提示要在 `.env` 设置哪个变量。
- 向量模型只读：换了要重新向量化知识库（R31）。
- 不做：
  - 系统页、日志页（R28）；
  - 在对话里添加技能（R29）；
  - 页面填写密钥（R32）；
  - 限制命令的写入范围（R33）；
  - 技能编辑、从官方技能库导入；
  - 模型信息自动查询（本轮手填）。

**架构：**
- `config/integrations.py` 增加"基础 + 用户"两份数据的合并函数（纯函数）。读文件的函数在它外面再包一层。
- 写入集中在 `backend/settings/`：
  - 先在内存里合并、校验，不合规就拒绝，不写文件；
  - 合规才原子写入 `workdata/config/` 的文件；
  - 写完再让智能体生效：重连 MCP，或只换审批规则。
- 技能：
  - `agents/main_agent/runtime/skills.py` 的 `SkillCatalog` 管两个目录与停用清单；
  - 智能体的文件树挂两个只读目录（`/skills/builtin/`、`/skills/user/`），停用的技能在里面看不见；
  - 上传包的检查放在 `backend/settings/skill_upload.py`。
- 模型：
  - 可替换接口 `ModelGateway` 增加新增、修改、删除、测试四个方法；
  - LiteLLM 实现调网关的 `/model/new`、`PATCH /model/{id}/update`、`/model/delete`；
  - 业务规则放在新模块 `backend/models/`：重名、默认模型、自带只读、删除后改会话的模型。
- 前端：三页去掉示例数据与提示条，改用 TanStack Query 读写。原来的纯函数（校验、格式、识别）留着并按真实类型调整。

**技术栈：** 后端 Python 3.12、FastAPI、pydantic 2、PyYAML、标准库 `zipfile`。前端 React 19、TanStack Query 5、Vitest、Playwright。网关 LiteLLM v1.105.0（打开 `STORE_MODEL_IN_DB`）。**不新增任何依赖**。

**设计文档：** `docs/specs/2026-10-18-frontend-admin-ui-design.md`（第 5～7 节）；决策 `docs/decisions/D21-管理页面改配置走workdata叠加与网关模型接口.md`；纯界面计划 `docs/plans/2026-10-18-frontend-admin-ui.md`（页面结构不变）。

## 全局约束

- 依赖方向 `backend → agents → config → common`；deepagents 只在 `agents/main_agent/runtime/`。
- 页面只写 `workdata/`（`Settings.user_config_dir`、`Settings.user_skills_dir`）与网关数据库，绝不写 `config/`、`agents/skills/`。
- 写 `workdata/config/` 的文件一律原子写：同目录临时文件 + `os.replace`。目录不存在时创建。每份文件开头一行注释：`# 由管理页面写入，也可以手改；同名的条目覆盖 config/ 里的（D21）`。
- 用户文件写坏时（手改出错），页面上的修改一律拒绝，不覆盖用户的文件；设置页照常显示原因。
- 内置工具 `execute`（执行命令）**永远先问**，任何规则都放宽不了（D21 第 7 条）。
- 错误用 `common.errors`：
  - 重名、自带的不能删、有对话正在进行：`ConflictError`；
  - 内容不合规：`InvalidRequestError`；
  - 配置文件写错：`InvalidConfigError`；
  - 超过大小上限：`TooLargeError`；
  - 网关出错：`UpstreamError`。
  - 消息都是给用户看的一句中文。
- 改了接口要运行 `make types`；`make check` 会核对生成的类型。
- 自动化测试不连真实网关、不花钱。只有页面上点"测试"会真的调一次模型（几个 token）。
- 价格：页面上填"美元 / 每百万 token"，存进网关时除以 1,000,000，存成"美元 / token"。页面新增的模型必须填价格或选"免费"（两项都存 0）。任何统计都不用价格。
- 界面文案中文、标识符英文、注释只写"为什么"。

## 重点检查（没有现成测试覆盖、最容易让使用者踩坑的五类情况）

1. **用户手改 `workdata/config/` 时写坏了文件**（YAML 不合法、字段写错）：服务照常启动；设置页、MCP 页显示"哪个文件哪一行"；页面上的修改返回 400，用户的文件原样保留。→ 任务 2 的接口测试。
2. **同名，以及大小写**：Mac 的文件系统不分大小写，上传 `Excel` 和自带的 `excel` 要算重名。页面新增的模型和自带的同名时必须拒绝，否则网关会把两份一起分摊调用。→ 任务 3、任务 4 的测试。
3. **上传的压缩包里有坏路径或太大**（`../`、绝对路径、软链接，总量超过 20MB 或超过 500 个文件）：拒绝，一个文件都不落盘。→ 任务 3 的测试。
4. **有对话正在进行时改 MCP 服务**：要重连的修改返回 409、文件不改（先检查再写）；只改某个工具"自动 / 先问"不用重连，照常生效。→ 任务 2 的接口测试。
5. **删除正在用的模型**：
   - 默认模型和自带模型都不能删；
   - 别的模型删掉以后，在用它的会话改用默认对话模型，历史与用量保留；
   - 网关出错时报中文原因，不留半条记录。

   → 任务 4 的测试。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `config/integrations.py` | 合并基础与用户两份 MCP 清单 / 审批规则；读目录清单 `mcp_catalog.yaml` |
| `config/settings.py` | `app.yaml` 两份逐层合并；`user_config_dir`、`user_skills_dir`；模型来源 `ModelsConfig.sources` |
| `config/mcp_catalog.yaml`（新） | 项目自带的 MCP 目录（只读） |
| `agents/main_agent/integrations/approval.py` | `execute` 固定先问 |
| `agents/main_agent/integrations/mcp.py`、`mcp_adapters.py` | `McpClient.probe`；状态里加启用、自带、命令、缺的环境变量 |
| `agents/main_agent/runtime/skills.py` | `SkillCatalog`、`SkillInfo`、`SkillDetail`、`SkillPackage` |
| `agents/main_agent/runtime/files.py` | `SkillsFilesystem`（隐藏停用的技能）与两个技能目录的挂载 |
| `agents/main_agent/models/base.py`、`litellm_proxy.py` | `ModelSpec`、`ModelTestResult`；网关的增、改、删、测 |
| `backend/settings/store.py`（新） | `UserConfigFiles`：读写 `workdata/config/` 的文件 |
| `backend/settings/service.py` | MCP 服务与审批规则的修改 |
| `backend/settings/skill_upload.py`（新） | 上传包的检查（zip / 文件夹 / 单个 SKILL.md） |
| `backend/models/`（新） | `ModelAdmin`：模型页的业务规则 |
| `backend/api/settings.py`、`backend/api/models.py`（新） | 接口 |
| `frontend/src/features/{models,skills,mcp}/` | 三页改用真实接口 |

---

### 任务 1：叠加配置的读取，以及"执行命令"固定先问

**文件：**
- 修改：`config/integrations.py`、`config/settings.py`、`config/__init__.py`、`config/approval_rules.yaml`、`agents/main_agent/integrations/approval.py`、`backend/settings/service.py`（`_read`）、`backend/tests/e2e_server.py`。
- 测试：`config/tests/test_integrations.py`、`config/tests/test_settings.py`、`agents/tests/test_approval.py`（文件名以现有的为准，没有就新建）。

**接口：**
- 产出：
  - `merge_mcp_servers(base: dict, user: dict, env: Mapping[str, str], *, labels: tuple[str, str]) -> list[McpServerConfig]`：`base` / `user` 是两份文件读出的内容；`labels` 是两份文件在报错里的显示名。
  - `load_mcp_servers(path: Path, env: Mapping[str, str], user_path: Path | None = None) -> list[McpServerConfig]`。
  - `merge_approval_rules(base: dict, user: dict, *, labels: tuple[str, str]) -> ApprovalRulesConfig`。
  - `load_approval_rules(path: Path, user_path: Path | None = None) -> ApprovalRulesConfig`。
  - `McpServerConfig.builtin: bool`：由加载函数填写，加进 `_LOADER_FIELDS`，文件里写了就报错。
  - `Settings.user_config_dir -> Path`（`workdata_dir / "config"`）、`Settings.user_skills_dir -> Path`（`workdata_dir / "skills"`），都是属性。

- [ ] **步骤 1：写失败的测试**
  - `test_user_server_overrides_builtin_fields`：
    - 基础 `{servers: {files: {command: npx, args: [a]}}}`，用户 `{servers: {files: {enabled: false}}}`；
    - 结果只有一个 `files`：`enabled is False`、`command == "npx"`、`args == ["a"]`、`builtin is True`。
  - `test_user_only_server_comes_after_builtin`：
    - 基础有 `files`，用户有 `memo`（command `echo`）；
    - 结果的名字依次为 `["files", "memo"]`；`memo.builtin is False`。
  - `test_error_names_the_user_file`：
    - 用户文件里 `memo` 少了 `command`；
    - 抛 `InvalidConfigError`，消息含用户文件的显示名与 `memo`。
  - `test_builtin_field_in_file_is_rejected`：用户文件里写 `builtin: true`，消息含"不认识的字段"。
  - `test_user_rules_come_first`：
    - 基础 `tools: {"*_write*": ask, files_read: auto}`，用户 `tools: {files_read: ask, files_write_file: auto}, mcp_default: auto`；
    - 结果 `tools` 的键依次为 `["files_read", "files_write_file", "*_write*"]`，`files_read == "ask"`，`mcp_default == "auto"`。
  - `test_user_app_yaml_overrides_one_setting`：
    - 用 `monkeypatch` 把 `WORKDATA_DIR` 指到临时目录，写入 `config/app.yaml`，内容 `agent: {default_model: other}`；
    - `get_settings.cache_clear()` 后 `Settings(...)` 的 `agent.default_model == "other"`；
    - 基础 `app.yaml` 里的其他设置不变（断言 `knowledge.embedding_model` 等于基础文件里的值）。
  - `test_execute_always_asks`：
    - 规则 `{"*": "auto", "execute": "auto"}`；
    - `ApprovalPolicy(rules).decide("execute", server=None, read_only=None).action == "ask"`，`reason == "执行命令每次先问（固定，D21）"`。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest config/tests agents/tests/test_approval.py -q`。
  - 预期：新用例失败（参数不存在或断言不符），原有用例通过。

- [ ] **步骤 3：实现**
  - 两份 MCP 清单的合并：
    - 用户条目先与同名的基础条目合并原始字段（`{**base_raw, **user_raw}`），再做 `${变量}` 替换与校验；
    - 顺序：基础条目在前（按基础文件的顺序），用户新加的在后（按用户文件的顺序）。
  - 两份审批规则的合并：
    - 用户的规则在前，同名的以用户的为准，再接上基础规则里剩下的；
    - `mcp_default` 用户写了就用用户的。
  - `app.yaml` 的两份文件：
    - `settings_customise_sources` 里的 yaml 来源同时读基础文件和用户文件；
    - 用户文件的位置：环境变量 `WORKDATA_DIR`（没有时用 `ROOT_DIR / "workdata"`）下的 `config/app.yaml`；
    - 要逐层合并。pydantic-settings 对多个 yaml 文件不逐层合并时，自己写一个来源，先读两份再逐层合并。
  - `ApprovalPolicy.decide`：在匹配规则之前，内置工具 `execute`（`server is None`）直接返回 ask。
  - `config/approval_rules.yaml`：删掉 `execute: ask` 这一行，改成一句注释，说明执行命令固定先问。
  - `IntegrationSettings._read` 传入用户文件 `settings.user_config_dir / "mcp_servers.yaml"`、`/ "approval_rules.yaml"`。
  - `e2e_server.py` 不变：基础文件仍在临时目录的根上，用户目录是它下面的 `config/`。

- [ ] **步骤 4：确认测试通过**
  - 运行：`uv run pytest -q`。预期：全部通过。

---

### 任务 2：MCP 页接上后端

**文件：**
- 新建：`config/mcp_catalog.yaml`、`backend/settings/store.py`。
- 修改：
  - `config/integrations.py`：目录清单；
  - `agents/main_agent/integrations/{mcp.py,mcp_adapters.py,__init__.py}`；
  - `agents/main_agent/runtime/agent.py`：`update_rules`、`probe_mcp`；
  - `agents/tests/fakes.py`：`FakeMcpClient.probe`；
  - `backend/settings/service.py`、`backend/api/settings.py`、`backend/tests/e2e_server.py`；
  - 前端 `src/api/*`、`src/features/mcp/*`、`e2e/mcp.spec.ts`。
- 测试：`agents/tests/contracts/test_mcp_client_contract.py`、`backend/tests/test_settings_api.py`（已有就加在里面）、`src/features/mcp/mcp.test.ts`、`e2e/mcp.spec.ts`。

**接口：**
- 消费：任务 1 的 `merge_mcp_servers`、`merge_approval_rules`、`Settings.user_config_dir`。
- 产出（后端）：
  - `UserConfigFiles(directory: Path)`：
    - `read(name: str) -> dict[str, Any]`：文件不存在时是 `{}`；写坏时抛 `InvalidConfigError`；
    - `write(name: str, data: dict[str, Any]) -> None`。
    - 任务 4 也用它写 `app.yaml`。
  - `McpProbeResult(ok: bool, tools: list[str], error: str | None)`。
  - `McpClient.probe(server: McpServerConfig) -> McpProbeResult`：单独连一次、列出工具后断开，不动现有连接。
  - `McpServerStatus` 新增字段：
    - `enabled: bool`、`builtin: bool`；
    - `target: str`：本地进程是命令加参数，网络服务是地址；
    - `missing_env: list[str]`。
  - `MainAgent.update_rules(rules: ApprovalRulesConfig) -> None`：只换审批规则，不重连。
  - `MainAgent.probe_mcp(server: McpServerConfig) -> McpProbeResult`。
  - `McpCatalogItem`：`id`、`name`、`description`、`transport`、`command`、`args`、`url`、`env`、`headers`、`needs: list[str]`。
  - `load_mcp_catalog(path: Path) -> list[McpCatalogItem]`。
  - `McpServerInput`：`name`、`description`、`transport`、`command`、`args`、`env`、`url`、`headers`。
- 接口（都在 `/api/settings` 下）：

| 方法与路径 | 请求体 | 返回 |
|---|---|---|
| `GET /mcp-catalog` | — | `list[McpCatalogView]`（目录项加 `missing_env`：本机没设置的变量） |
| `POST /mcp-servers` | `{servers: McpServerInput[]}` | 201，`McpServersView`；全部成功或全部不加 |
| `PUT /mcp-servers/{name}` | `McpServerInput` | `McpServersView`；`name` 不能改 |
| `PATCH /mcp-servers/{name}` | `{enabled: bool}` | `McpServersView` |
| `DELETE /mcp-servers/{name}` | — | 204 |
| `POST /mcp-servers/test` | `McpServerInput` | `McpProbeResult` |
| `PUT /approval-rules/tools/{tool}` | `{action: "auto" \| "ask"}` | `ApprovalSettingsView` |

- [ ] **步骤 1：写失败的测试**
  - MCP 客户端的契约测试（用现有的测试服务）：
    - `test_probe_lists_tools_without_touching_connections`：已连上服务 A 时探测服务 B，结果 `ok`、带 B 的工具；`statuses()` 仍只有 A，且仍是已连接。
    - `test_probe_reports_failure`：命令不存在时 `ok is False`，`error` 是中文。
  - 接口测试（`make_client`，用 `FakeMcpClient`）：
    - `test_add_server_writes_user_file_only`：
      - 加一个 `memo`（command `echo`）后，`workdata/config/mcp_servers.yaml` 里有 `memo`，基础文件内容不变；
      - `GET /api/settings/mcp-servers` 里 `memo.builtin is False`。
    - `test_add_duplicate_name_conflicts`：加名为 `demo` 的服务（基础里已有），返回 409，消息"已有同名服务：demo"。
    - `test_add_batch_is_all_or_nothing`：一次加 `memo` 和 `bad-name`，返回 400；用户文件不存在或内容不变。
    - `test_disable_builtin_writes_only_enabled`：`PATCH demo {enabled: false}` 后，用户文件的 `servers` 等于 `{"demo": {"enabled": False}}`。
    - `test_delete_builtin_conflicts`：返回 409，消息"自带的服务不能删除，可以停用"。
    - `test_delete_user_server_removes_its_rules`：先给 `memo_add` 设成 auto，再删 `memo`；用户规则里不再有 `memo_` 开头的键。
    - `test_changes_wait_for_running_conversation`：有运行在进行时（`HangingChatModel` 起一个运行），`POST /mcp-servers` 返回 409，消息"有对话正在进行，等它结束或停止后再改"；用户文件不变。
    - `test_tool_action_applies_without_reconnect`：
      - 有运行在进行时 `PUT /approval-rules/tools/demo_add_note {action: auto}` 返回 200；
      - 该工具的生效结果是 auto；
      - `FakeMcpClient` 的连接次数不变。
    - `test_broken_user_file_is_reported_and_kept`：
      - 用户文件写成 `servers: [`；
      - `GET /mcp-servers` 的 `config_error` 含 `mcp_servers.yaml`；
      - `POST /mcp-servers` 返回 400；文件内容一个字节都不变。
    - `test_probe_names_missing_env`：`env: {K: "${NOT_SET_X}"}` 时 `ok is False`，`error` 含 `NOT_SET_X` 与 `.env`。
    - `test_catalog_marks_missing_env`：目录里需要 `NOT_SET_X` 的条目，`missing_env == ["NOT_SET_X"]`。
    - `test_execute_rule_cannot_be_relaxed`：`PUT /approval-rules/tools/execute {action: auto}` 返回 400，消息"执行命令固定先问，不能改"。
  - 前端：
    - `mcp.test.ts` 去掉 `maskSecret` 的用例，其余保留；
    - 加 `statusLabel` 的新用例：缺环境变量时是"缺少环境变量：BRAVE_API_KEY"；正在连接时是"连接中"。
  - `e2e/mcp.spec.ts` 改成真实数据：
    - 不再出现示例提示条；
    - `demo` 显示"已连接"；停用后刷新页面仍是"已停用"；
    - 从目录安装 `time`，之后列表里有它；
    - 目录里 `brave_search` 的安装对话框显示"需要在 .env 里设置：BRAVE_API_KEY（未设置）"；
    - 粘贴 JSON 加两个服务；
    - 把 `demo_add_note` 改成"自动"，刷新后仍是"自动"。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/contracts/test_mcp_client_contract.py backend/tests/test_settings_api.py -q`。预期：新用例失败（接口返回 404 / 405，`probe` 不存在）。

- [ ] **步骤 3：实现后端**
  - `IntegrationSettings` 新增方法：`add_servers`、`update_server`、`set_server_enabled`、`remove_server`、`set_tool_action`、`probe`、`catalog`。修改的流程统一为：
    1. 要重连的修改，先查有没有运行在进行，有就抛 `ConflictError`；
    2. 读用户文件，在内存里改；
    3. 用 `merge_*` 校验合并结果，不合规就抛，文件不动；
    4. 写入文件；
    5. 让智能体生效：要重连的调 `reload_integrations`，审批规则调 `update_rules`。
  - 删除用户服务时，一起删掉用户规则里 `"{name}_"` 开头的键（不处理通配）。
  - `update_server` 用于自带服务时，把表单里的字段整份写进用户条目作为覆盖。
  - `probe`：先按 `os.environ` 替换 `${变量}`。有缺的就直接返回：`缺少环境变量 X：在 .env 里设置，并在 docker-compose.yml 的 backend.environment 传入后重启`。
  - `config/mcp_catalog.yaml` 初始四项：`fetch`（`uvx mcp-server-fetch`）、`time`（`uvx mcp-server-time`）、`brave_search`（`npx -y @modelcontextprotocol/server-brave-search`，`env: {BRAVE_API_KEY: "${BRAVE_API_KEY}"}`，`needs: [BRAVE_API_KEY]`）、`github`（网络地址 `https://api.githubcopilot.com/mcp/`，请求头 `Authorization: "Bearer ${GITHUB_TOKEN}"`，`needs: [GITHUB_TOKEN]`）。
  - 执行时，在后端容器里对 `fetch`、`time` 各探测一次，确认能启动（`uvx` 在镜像里不存在时，去掉这两项并记一条裁决）。
  - `e2e_server.py`：在临时目录放一份目录清单，含 `time`（无需密钥）与 `brave_search`。
  - 运行 `make types`。

- [ ] **步骤 4：实现前端**
  - 删掉 `sample.ts`、`catalog.ts`，以及 `mcp.ts` 里的 `maskSecret`、`maskedEnv`、`formToServer`、`parsedToServer`、`serversReducer`；
  - 保留 `parseMcpJson`、`serverNameError`、`validateServerForm`、`filterCatalog`、`statusLabel`，改用生成的类型。
  - 新增查询 `mcpServersQuery`、`mcpCatalogQuery`。修改后让 `mcpServersQuery` 与审批规则的查询失效（设置页也用后者）。
  - 页面结构不变，只改这几处：
    - 去掉示例提示条；
    - "重新加载"调 `POST /settings/reload`；
    - 自带的服务没有"删除"；用户加的服务，编辑抽屉左下有"删除"（先确认）；
    - 编辑时服务名不能改；
    - 安装对话框只问服务名。需要密钥的条目列出要在 `.env` 里设置的变量，以及"已设置 / 未设置"；
    - 环境变量和请求头原样显示，旁边写一句提示"密钥写成 ${变量名}，在 .env 里设置"；
    - 状态文字：已连接 / 连接中 / 出错：原因 / 已停用 / 缺少环境变量：X。
  - 后端返回的错误消息显示在对应的对话框或抽屉里。

- [ ] **步骤 5：确认测试通过**
  - 运行：`uv run pytest -q && cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test e2e/mcp.spec.ts`。预期：全部通过。

---

### 任务 3：技能页接上后端

**文件：**
- 新建：`backend/settings/skill_upload.py`。
- 修改：
  - `agents/main_agent/runtime/{skills.py,files.py,agent.py,__init__.py}`；
  - `agents/main_agent/bootstrap.py`；
  - `agents/prompts/system.md` 第 14 行；
  - `backend/api/settings.py`、`backend/tests/e2e_server.py`；
  - 前端 `src/api/*`、`src/features/skills/*`、`src/features/settings/` 里用到技能类型的地方、`e2e/skills.spec.ts`。
- 测试：`agents/tests/test_skills.py`、`backend/tests/test_skill_upload.py`、`backend/tests/test_settings_api.py`、`src/features/skills/skills.test.ts`、`e2e/skills.spec.ts`。

**接口：**
- 产出（`agents/main_agent/runtime/skills.py`，由 `runtime/__init__.py` 导出）：
  - `SkillInfo`：`name`、`description`、`error`、`origin: Literal["builtin", "upload"]`、`enabled: bool`、`location: str`（如 `agents/skills/excel/`、`workdata/skills/周报写作/`）、`added_at: date | None`（上传的取文件夹的修改日期；自带的为 None）。
  - `SkillDetail(SkillInfo)`：`body: str`（去掉开头说明后的正文）、`files: list[str]`（相对路径，排好序）。
  - `SkillPackage`：`name: str`、`description: str`、`files: dict[str, bytes]`（相对路径 → 内容）。
  - `read_front_matter(text: str) -> tuple[str, str] | str`：成功时返回 (name, description)，失败时返回中文原因。
  - `SkillCatalog(builtin_dir: Path | None, user_dir: Path, state_file: Path)`，方法：
    - `list() -> list[SkillInfo]`；
    - `detail(name) -> SkillDetail`；
    - `hidden() -> frozenset[str]`；
    - `set_enabled(name, enabled) -> SkillInfo`；
    - `install(package) -> SkillInfo`；
    - `remove(name) -> None`。
    - `state_file` 是 `workdata/config/skills.yaml`，内容 `disabled: [名字…]`。
  - `MainAgent(..., skills: SkillCatalog | None = None)`：代替 `skills_dir`。
- 产出（backend）：
  - `parse_skill_upload(files: list[tuple[str, bytes]]) -> SkillPackage`；
  - 上限 `MAX_SKILL_BYTES = 20 * 1024 * 1024`、`MAX_SKILL_FILES = 500`；
  - 技能名规则：`^[\w][\w-]{0,63}$`（`\w` 含中文）。
- 接口（都在 `/api/settings` 下）：

| 方法与路径 | 请求体 | 返回 |
|---|---|---|
| `GET /skills` | — | `list[SkillInfo]` |
| `GET /skills/{name}` | — | `SkillDetail` |
| `POST /skills` | multipart：`files`，每个文件的文件名是相对路径（如 `周报写作/SKILL.md`） | 201，`SkillInfo` |
| `PATCH /skills/{name}` | `{enabled: bool}` | `SkillInfo` |
| `DELETE /skills/{name}` | — | 204 |

- [ ] **步骤 1：写失败的测试**
  - `test_skills.py`：
    - `test_catalog_lists_builtin_then_upload`：自带 `excel`、上传 `memo`。结果的 `origin` 依次为 `["builtin", "upload"]`；`location` 分别以 `agents/skills/excel/` 和 `workdata/skills/memo/` 结尾。
    - `test_disabled_skill_is_hidden_from_the_agent_files`：停用 `excel` 后，`SkillsFilesystem` 列 `/` 时不含 `excel`，读 `/excel/SKILL.md` 返回错误；启用后又能看到。
    - `test_disabled_skill_is_not_listed_for_the_agent`：用 `ScriptedChatModel` 跑一轮，第一次调用收到的系统消息里有启用的技能名，没有停用的。
    - `test_install_rejects_same_name_ignoring_case`：自带 `excel` 时安装 `Excel`，抛 `ConflictError`，消息"已有同名技能：Excel"；`workdata/skills/` 下没有新文件夹。
    - `test_remove_builtin_conflicts`：消息"自带的技能不能删除，可以停用"。
    - `test_remove_upload_deletes_folder_and_state`：删掉一个已停用的上传技能后，文件夹不在了，`disabled` 里也没有它。
  - `test_skill_upload.py`：
    - `test_zip_with_one_top_folder`：`周报写作/SKILL.md` 加 `周报写作/scripts/a.py`，得到 `name == "周报写作"`、`files` 的键为 `["SKILL.md", "scripts/a.py"]`。
    - `test_single_skill_md`、`test_folder_upload_paths`。
    - `test_rejects_path_escape`：zip 条目 `../evil`、`/abs`、软链接，各自抛 `InvalidRequestError`。
    - `test_rejects_too_big`：超过 20MB 或 500 个文件时抛 `TooLargeError`。
    - `test_requires_skill_md_at_root`：没有 SKILL.md 时报"文件夹或压缩包里要有 SKILL.md"。
    - `test_bad_name`：说明头 `name: ../x` 时报"技能名只能用文字、数字、- 和 _"。
    - `test_ignores_mac_metadata`：`__MACOSX/` 与 `.DS_Store` 被跳过。
  - 接口：
    - `test_upload_then_list_and_detail`；
    - `test_toggle_persists_in_user_state`：`workdata/config/skills.yaml` 里有 `disabled`。
  - 前端 `skills.test.ts`：
    - `inspectUpload` 遇到同名（不分大小写）时返回 `{kind: "error", message: "已有同名技能「excel」，换个名字再上传"}`；
    - 删掉 `replaces` 字段和 `skillsReducer`。
  - `e2e/skills.spec.ts` 改成真实数据：
    - 列表里有自带的 `excel`；
    - 上传一个 SKILL.md 后它出现在列表里；停用后刷新仍是停用；
    - 查看能看到正文；
    - 删除上传的技能（先确认）；
    - 上传与 `excel` 同名的会报错；`.pdf` 不支持。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/test_skills.py backend/tests/test_skill_upload.py -q`。预期：失败（模块或名字不存在）。

- [ ] **步骤 3：实现后端**
  - `SkillsFilesystem(root: Path, hidden: Callable[[], AbstractSet[str]])`，继承 `ReadOnlyFilesystem`：
    - 第一层文件夹名在 `hidden()` 里的，在这几处都看不见：`ls`、`read`、`glob`、`grep`、`download_files`，以及它们的异步版本；
    - deepagents 读技能用 `ls` 与 `download_files`，以它当前版本的方法为准。
  - 文件树挂两处：`/skills/builtin/` 与 `/skills/user/`。deepagents 的技能来源写成 `[("/skills/builtin/", "自带技能"), ("/skills/user/", "上传的技能")]`。按 `deepagents.middleware.skills` 的来源写法，不支持元组时只写路径。
  - `system.md` 第 14 行改为：`- 处理特定类型的任务前，先看下方列出的可用技能，有对应的就按它的 SKILL.md 做。`
  - 停用状态每次现读 `skills.yaml`：停用、启用都不用重新加载。
  - `bootstrap.py`：`SkillCatalog(settings.agent.skills_dir, settings.user_skills_dir, settings.user_config_dir / "skills.yaml")`。
  - `parse_skill_upload`：
    - 只有一个 `.zip` 时在内存里解压；
    - 只有一个 `SKILL.md` 时就是它；
    - 否则按文件夹处理，去掉共同的第一层文件夹名；
    - 以上之外的情况报"只能上传技能文件夹、.zip 或 SKILL.md"；
    - zip 里的软链接用 `external_attr >> 16` 的文件类型判断。
  - 安装时，先写到 `workdata/skills/.installing-<随机>/`，写完再改名成技能名，免得留下半个技能。
  - 运行 `make types`。

- [ ] **步骤 4：实现前端**
  - 删掉 `sample.ts`；新增查询 `skillsQuery`、`skillDetailQuery(name)`。
  - 上传对话框：
    - 先在本地识别（保留 `inspectUpload` 与拖入文件夹的读取）；
    - 点"安装"后用 `FormData.append("files", file, 相对路径)` 发给后端；
    - 压缩包在本地不识别，显示"压缩包会在安装时检查"，"安装"按钮可点；
    - 后端返回的错误显示在对话框里。
  - 自带的技能没有"删除"，抽屉里写"项目自带，可以停用"；
  - 去掉示例提示条。
  - 设置页的技能列表按新类型显示，内容不变。

- [ ] **步骤 5：确认测试通过**
  - 运行：`uv run pytest -q && cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test e2e/skills.spec.ts`。预期：全部通过。

---

### 任务 4：模型页接上后端（网关的模型管理接口）

**文件：**
- 新建：`backend/models/{__init__.py,service.py,schemas.py}`、`backend/api/models.py`。
- 修改：
  - `deploy/docker-compose.yml`（litellm 的环境变量）、`.env.example`、`.env`（只追加一行，见步骤 3）；
  - `config/settings.py`（`ModelsConfig`）；
  - `agents/main_agent/models/{base.py,litellm_proxy.py,__init__.py}`、`agents/tests/fakes.py`（`FakeGateway`）；
  - `backend/threads/repo.py`、`backend/api/{router.py,deps.py}`、`backend/tests/e2e_server.py`；
  - 前端 `src/api/*`、`src/features/models/*`、`e2e/models.spec.ts`。
- 测试：`agents/tests/contracts/test_model_gateway_contract.py`、`backend/tests/test_models_api.py`（集成，要数据库）、`backend/tests/test_threads_repo.py`（集成，已有就加在里面）、`src/features/models/models.test.ts`、`e2e/models.spec.ts`。

**接口：**
- 消费：任务 2 的 `UserConfigFiles`（写 `app.yaml`）。
- 产出（`agents/main_agent/models/base.py`）：
  - `ModelInfo` 新增字段：
    - `id: str | None = None`（网关里的部署编号，页面加的才有）；
    - `builtin: bool = True`（网关返回 `db_model: true` 时为 False）；
    - `upstream: str | None = None`（`litellm_params.model`）；
    - `max_output_tokens: int | None = None`；
    - `supports_function_calling: bool = False`。
  - `ModelSpec`：
    - `name`、`upstream`、`api_base`、`api_key: str | None`；
    - `mode: Literal["chat", "embedding"]`；
    - `max_input_tokens`、`max_output_tokens`；
    - `input_cost_per_token: float`、`output_cost_per_token: float`；
    - `supports_reasoning`、`supports_vision`、`supports_function_calling`；
    - `extra_params: dict[str, Any] = {}`。
  - `ModelTestResult(ok: bool, latency_ms: int, error: str | None)`。
  - `ModelGateway` 新增四个方法，前三个改完都会重新拉一次模型清单：
    - `add_model(spec) -> ModelInfo`；
    - `update_model(model_id, spec) -> ModelInfo`；
    - `delete_model(model_id) -> None`；
    - `test_model(name) -> ModelTestResult`。
- 产出（config）：
  - `ModelSource`：`id`、`label`、`mode`、`prefix`、`api_base`、`api_key: str | None`；
  - `ModelsConfig.sources` 的默认值有两项：
    - `upstream`：公司 LiteLLM 网关，chat，`litellm_proxy/`，`os.environ/UPSTREAM_GATEWAY_URL`，`os.environ/UPSTREAM_GATEWAY_KEY`；
    - `ollama`：本机 Ollama，embedding，前缀与地址照抄 `config/models.yaml` 里的向量模型条目。
  - `Settings.models: ModelsConfig`。
- 产出（backend）：
  - `ThreadRepo.count_by_model(model: str) -> int`；
  - `ThreadRepo.reassign_model(old: str, new: str) -> int`；
  - `ModelInput`：
    - `name`、`source`、`upstream_id`；
    - `mode: Literal["chat", "embedding"]`；
    - `max_input_tokens`、`max_output_tokens`；
    - `price_input`、`price_output`（美元 / 每百万，≥ 0 的有限数）；
    - `supports_reasoning`、`supports_vision`、`supports_function_calling`；
  - `ModelView(ModelInfo)`：`source_label`、`sessions: int`、`is_default_chat`、`is_default_embedding`；
  - `ModelsView`：`models`、`default_chat`、`default_embedding`、`sources`；
  - `ModelAdmin(settings, gateway, threads, user_files)`：`list`、`add`、`update`、`delete`、`test`、`set_default_chat`。
- 接口（都在 `/api/settings/models` 下；`GET /api/models` 不变，对话页的下拉框还用它）：

| 方法与路径 | 请求体 | 返回 |
|---|---|---|
| `GET /` | — | `ModelsView` |
| `POST /` | `ModelInput` | 201，`ModelView` |
| `PUT /{model_id}` | `ModelInput` | `ModelView`；名字不能改 |
| `DELETE /{model_id}` | — | `{reassigned: int}` |
| `POST /{name}/test` | — | `ModelTestResult` |
| `PUT /default` | `{name}` | `ModelsView` |

- [ ] **步骤 1：写失败的测试**
  - 契约测试（`httpx.MockTransport` 记下请求）：
    - `test_add_model_puts_price_in_litellm_params`：
      - 发到 `POST /model/new`；
      - 请求体 `litellm_params` 含 `input_cost_per_token`、`output_cost_per_token`、`api_key == "os.environ/UPSTREAM_GATEWAY_KEY"`；
      - `model_info` 不含价格。
    - `test_update_uses_patch`：发到 `PATCH /model/{id}/update`，同时带 `litellm_params` 与 `model_info`。
    - `test_delete_model`：`POST /model/delete`，`{"id": …}`。
    - `test_listing_marks_db_models`：`db_model: true` 的条目 `builtin is False`、`id` 有值。
    - `test_gateway_rejection_becomes_upstream_error`：网关返回 400 时抛 `UpstreamError`，消息带网关的原因。
    - `test_test_model_reports_latency_or_reason`：
      - 对话模型发 `POST /chat/completions`，`max_tokens: 1`；向量模型发 `POST /embeddings`；
      - 成功时 `ok` 且 `latency_ms >= 0`；失败时 `ok is False`，`error` 是中文。
  - 接口测试（集成，`FakeGateway`）：
    - `test_add_model_with_existing_name_conflicts`：用自带模型的名字新增，返回 409，消息"已有同名模型：fake-model"。
    - `test_price_is_required_and_finite`：`price_input` 为负数或无穷大时返回 422 / 400。
    - `test_builtin_model_is_read_only`：`PUT` 或 `DELETE` 自带模型，返回 409，消息含"config/models.yaml"。
    - `test_cannot_delete_default`：返回 409，消息"先换掉默认再删"。
    - `test_delete_reassigns_threads_to_default`：两个会话用模型 X，删掉 X 后它们的 `model` 都是默认对话模型；`reassigned == 2`；用量记录条数不变。
    - `test_gateway_failure_leaves_nothing`：`FakeGateway` 新增时抛 `UpstreamError`，接口返回 502，列表里没有它。
    - `test_set_default_chat_persists_and_applies`：
      - `PUT /default {name: X}` 后，`workdata/config/app.yaml` 的 `agent.default_model == "X"`；
      - 之后新建的会话用 X；
      - 向量模型或不存在的名字返回 400。
  - 前端 `models.test.ts`：
    - `formatPrice`：价格为 null 时显示"价格未填"，两项都是 0 时显示"免费"，其余显示 `$5 / $25 每百万`；
    - 表单转请求体时，价格单位仍是每百万（由后端换算）；
    - 删掉 `modelsReducer`、`canDelete` 等示例状态的用例。
  - `e2e/models.spec.ts` 改成真实数据：
    - 自带模型标"自带"，没有"编辑""删除"；
    - 新增模型时不填价格会提示，选"免费"后能保存；保存后它出现在列表里；
    - "测试"显示"✓ 可用"；
    - 删除先确认，确认后它就不在列表里了；
    - 把它设成默认对话模型后，刷新仍是它。

- [ ] **步骤 2：确认测试失败**
  - 运行：`uv run pytest agents/tests/contracts/test_model_gateway_contract.py -q`。预期：新用例失败（方法不存在）。

- [ ] **步骤 3：实现**
  - 网关：
    - `docker-compose.yml` 里 litellm 的 `STORE_MODEL_IN_DB` 改成 `"True"`，并加 `LITELLM_SALT_KEY: ${LITELLM_SALT_KEY:?请在 .env 中设置 LITELLM_SALT_KEY（D21：设了以后不能改）}`；
    - `.env.example` 加这一行和说明；
    - `.env` 只在没有这一行时追加，**不读出、不打印 `.env` 的内容**。命令：`grep -q '^LITELLM_SALT_KEY=' .env || printf 'LITELLM_SALT_KEY=salt-%s\n' "$(openssl rand -hex 24)" >> .env`。
  - LiteLLM 实现：
    - `litellm_params` 写：
      - 上游模型、`api_base`、`api_key`（环境变量引用）与两项价格；
      - Claude 系列（上游 ID 含 `claude`）且勾了"思考"时，再加 `thinking: {type: adaptive}` 与 `max_tokens: min(64000, max_output_tokens)`，与 `config/models.yaml` 的 Claude 条目一致；
    - `model_info` 写：`mode`、上下文 / 输出上限、能力。
  - `ModelAdmin`：
    - 名字与网关里已有的任何模型都不能相同；
    - 来源必须在 `settings.models.sources` 里，而且来源的 `mode` 要和模型类型一致；
    - 删除时先调网关，成功后再 `reassign_model`；
    - `set_default_chat` 写用户的 `app.yaml`（`agent.default_model`），同时把 `settings.agent.default_model` 改成新值。
  - `FakeGateway` 改成内存里的登记表：
    - 初始两个自带模型：`fake-model`（chat）、`embed-fake`（embedding）；
    - 名字含 `broken` 的模型测试失败；
    - `fail_next_add` 开关用来模拟网关出错。
  - `e2e_server` 的 `knowledge.embedding_model` 设为 `embed-fake`。
  - 运行 `make types`。
  - 前端：
    - 删掉 `sample.ts` 与示例 reducer；新增查询 `modelsAdminQuery`；
    - 标题栏的"重载网关"改为"刷新"（重新拉清单；自带模型改了要在终端执行 `make restart-gateway`，旁边写这句提示）；
    - 默认模型卡：对话模型是下拉框，选了就生效；向量模型只读，旁边写"换向量模型要重新向量化整个知识库，暂不支持在页面上改"；
    - 删除确认框的文案：`将从网关移除 {name}。有 {n} 个会话正在用它，之后会改用默认模型 {default}；历史消息和用量保留。`；
    - 自带的行标"自带"，没有"编辑""删除"；
    - 去掉示例提示条。

- [ ] **步骤 4：先行验证网关的修改接口**
  - 照 2026-10-18 的做法：临时网关容器 + 测试库 + 本机模拟上游，完后删干净。
  - 确认 `PATCH /model/{id}/update` 同时带 `litellm_params` 与 `model_info` 时，两边都改了。
  - 确认模型价格改动后，再调用一次，返回的 `x-litellm-response-cost` 按新价格算。
  - 不符合时改实现（例如先 `POST /model/update` 再 `PATCH`），并记一条裁决。

- [ ] **步骤 5：确认测试通过**
  - 运行：`uv run pytest -q && make test-int && cd frontend && pnpm exec vitest run && pnpm build && pnpm exec playwright test e2e/models.spec.ts`。预期：全部通过。

---

### 任务 5：备份、文档与收尾

**文件：** 修改 `Makefile`（`BACKUP_ENV` 的 `FILE_DIRS`）、`deploy/tests/test_backup_scripts.py`、`frontend/src/components/ui/PreviewBanner.tsx`（删除）与 `ui.test.tsx`，以及以下文档：
- `docs/usage.md` 第 3、4 节；
- `docs/development/architecture.md` 第 5、13 节；
- `docs/decisions/D21-…`（"同名按字段覆盖"的说法）；
- `docs/changelog.md`、`docs/requirements/backlog.md`；
- `README.md`（`.env` 里新的一行）。

- [ ] **步骤 1：写失败的测试**
  - `test_backup_includes_user_config_and_skills`（集成）：临时 workdata 里放 `config/mcp_servers.yaml` 与 `skills/memo/SKILL.md`，备份后的压缩包里有这两个文件。

- [ ] **步骤 2：确认测试失败**
  - 运行：`make test-int`。预期：这一条失败（压缩包里没有）。

- [ ] **步骤 3：实现**
  - `FILE_DIRS="workspace knowledge shared config skills"`。
  - 删掉不再使用的 `PreviewBanner` 和它的测试用例。
  - 文档：
    - 使用指南写清：
      - 三页的改动存在哪里；
      - 自带的只读或只能停用；
      - 改自带模型照旧改 `config/models.yaml` 再 `make restart-gateway`；
      - 需要密钥的 MCP 服务怎么设置；
      - `LITELLM_SALT_KEY` 不能改、恢复备份要用同一个值。
    - 架构规范写叠加加载、网关数据库、两个技能目录。
    - changelog 加一节"管理页面接上后端（D21）"。
    - 需求池：
      - R27 → 完成；
      - R22 备注"界面上传已做（2026-10-18），从官方技能库导入仍待定"；
      - R30 里"上传同名覆盖自带"那条划掉，注明改为不许同名。

- [ ] **步骤 4：全部检查**
  - 运行：`make check`、`make test-int`、`make e2e`。预期：全部通过。
  - 运行：`make build`（网关会按新的环境变量重建），然后：
    - `curl http://127.0.0.1:8000/api/models`：自带模型都在；
    - 打开 http://127.0.0.1:8000 ，在深色、浅色两版下各看一遍模型、技能、MCP 三页；
    - 不点"测试"（会真的调用模型）；
    - 在 MCP 页停用再启用 `files`，确认 `workdata/config/mcp_servers.yaml` 先写入、后恢复为启用。
