# 架构规范

> 适用于本项目全部代码。设计依据：`docs/specs/2026-10-10-personal-agent-design.md`。规范只在这里维护一份，`dev-standards` 技能只放要点并指向本文。

## 1. 总纲：底层解耦，功能内聚

- **底层解耦**：外部依赖（模型网关、沙箱、向量检索、文档解析、MCP、运行时队列等）都藏在我们自己定义的可替换接口后面；业务代码只认接口；"用哪个实现"只在组装根决定。
- **功能内聚**：一个能力模块把自己的接口、实现、数据访问、中间件、提供给智能体的工具放在一起；模块之间只调用对方公开的内容。
- **不过度包装**：LangChain 聊天模型、LangGraph 对话存档、deepagents 后端协议本身就是标准接口，直接使用。
- **只为基础设施建接口**：只有设计文档 4.1 所列的外部依赖才定义可替换接口，其他地方不预设抽象。

## 2. 三大块与依赖方向

```
frontend ──(HTTP 接口 + 推送协议)──→ backend ──→ agents ──→ config ──→ common
```

| 目录 | 职责 | 允许依赖 |
|---|---|---|
| `agents/` | 智能体能力；可脱离 HTTP 独立运行 | `config`、`common` |
| `backend/` | 把 agents 的能力通过 HTTP 与推送提供出去；运行调度 | `agents` 的公开内容、`config`、`common` |
| `frontend/` | 浏览器界面 | 只通过 `/api` 与推送协议访问 backend |
| `config/` | 读取配置的代码 + 所有可编辑的配置文件 | `common` |
| `common/` | 与业务无关的基础设施：数据库连接池、错误类型、ID | 无 |

依赖方向由 import-linter 强制（`pyproject.toml` 的 `[tool.importlinter]`），`make check` 会检查：
1. 分层：`backend → agents → config → common`，不得反向。
2. `backend` 不得引用 agents 的内部实现模块（如 `agents.main_agent.runtime.translator`），只用各模块 `__init__.py` 导出的内容。

## 3. 模块结构模板

### agents 能力模块（`agents/main_agent/<能力>/`）

| 文件 | 内容 |
|---|---|
| `__init__.py` | 对外公开的内容（其他模块与 backend 只能从这里导入） |
| `base.py` | 可替换接口（`typing.Protocol`）与数据结构（仅基础设施类能力需要） |
| `<实现名>.py` | 接口的具体实现，如 `litellm_proxy.py` |
| `tools.py` | 提供给智能体的工具 |
| `repo.py` | 本模块拥有的表的数据访问 |

`agents/main_agent/bootstrap.py` 是组装根：按设置里的 `adapters`（代码默认值，可用环境变量覆盖，D22）选择实现并装配，产出 `MainAgent`。

### backend 功能模块（`backend/<功能>/`）

| 文件 | 内容 |
|---|---|
| `schemas.py` | 接口与数据库之间的数据结构（pydantic） |
| `repo.py` | 数据访问（psycopg + 原生 SQL） |
| `manager.py` 等 | 业务流程 |
| `__init__.py` | 对外公开的内容 |

路由统一放在 `backend/api/`；服务对象在启动时装配到 `app.state.services`（见 `backend/api/deps.py`）。

## 4. 可替换接口的写法

```python
# agents/main_agent/<能力>/base.py —— 接口
class XxxGateway(Protocol):
    async def do(self, ...) -> Result: ...

# agents/main_agent/<能力>/<实现名>.py —— 实现（不继承接口，按结构匹配）
class FooXxxGateway:
    async def do(self, ...) -> Result: ...

# agents/main_agent/bootstrap.py —— 登记
_XXX: dict[str, Callable[[Settings], XxxGateway]] = {"foo": lambda s: FooXxxGateway(...)}

# agents/tests/contracts/test_xxx_contract.py —— 契约测试
IMPLEMENTATIONS = [make_foo]          # 新实现加进这个列表，必须跑通同一套测试
```

新增实现 = 写实现类 + 在组装根登记 + 加进契约测试 + 改 `AdaptersConfig` 的默认值（或用环境变量如 `ADAPTERS__WORKSPACE` 选中）。

## 5. 前端结构与设计系统（设计文档 13 节）

| 目录 | 职责 |
|---|---|
| `src/themes/` | 主题即数据：`types.ts`（主题结构）、`default.ts`（默认主题深浅两版）、`registry.ts`（登记表）、`apply.ts`（写到根节点的 CSS 变量）、`mode.ts`（深浅色偏好）、`ThemeProvider.tsx` |
| `src/styles/` | `tokens.css`：主题变量 → 派生色（color-mix）→ Tailwind 语义样式类，以及代码高亮的颜色 `--syntax-*`；`markdown.css`：回答排版（含代码块、高亮类名、公式） |
| `src/components/chat/` | **唯一**使用 assistant-ui 的地方：转换函数 `adapter.ts`（处理完的审批并入对应的工具行）、消息各片段 `parts.tsx`（相邻工具调用用 `MessagePrimitive.GroupedParts` 合成一组）、工具行与工具组 `toolLine.tsx`（中文名、合组摘要、执行命令的输出与退出码由 `tools.ts` 算出）、审批卡片 `approval.tsx`、报错卡片 `errorCard.tsx`（重试、换个模型再试，动作由页面经 `retryActions.ts` 提供）、输入框上方的待办进度 `TodoBar.tsx`、对话区 `ChatThread.tsx`（草稿、粘贴截图）；回答里的代码块 `code.tsx`（着色 `highlight.ts`，回答还在输出时不着色、超过 16 行先折叠，靠 `messageContext.ts`）、公式 `math.ts`（以 assistant-ui 自带的公式与金额处理为主，D19）；对外只导出 `ChatThread` |
| `src/components/ui/` | 页面骨架共用的组件：按钮 `Button`、标题栏 `PageHeader`、卡片 `Panel`、开关 `Switch`、标签 `Tag`、状态点 `StatusDot`、表单项 `Field`、右侧抽屉 `Drawer`、居中对话框 `Modal`、删除确认 `ConfirmDialog`、标签页 `Tabs`、示例提示条 `PreviewBanner`；`escape.ts` 让 Esc 只关最上面一层弹层；对话框、抽屉的键盘操作 `dialogFocus.ts`（`useDialog`：打开时聚焦、Tab 循环、Esc 关闭，只管最上面一层，关闭后焦点回到原处；层栈在 `escape.ts`） |
| `src/components/ime.ts` | 判断输入法是否正在选字（回车只是确认候选词、Esc 只是取消候选词），会话列表、知识库、弹层共用 |
| `src/components/useCopy.ts` | 复制按钮共用的复制（剪贴板接口不可用时退回到隐藏文本框）与"已复制 / 复制失败"状态 |
| `src/components/format.ts` | 文件大小、文件名等显示格式（对话、文件面板、知识库共用；原在 `components/chat/` 里，功能页不再深引它的内部文件） |
| `src/features/<功能>/` | 业务功能：会话列表、对话页、模型选择、外观设置等，只用语义样式类和 `components/chat` 的导出 |
| `src/layout/` | 整体布局：`AppShell`（左侧栏 `Sidebar` + 按地址切换的内容区）；`routes.ts` 集中写所有页面地址与侧栏分组（每页一个地址，刷新、收藏能回到原页；路由用 react-router 7） |
| `src/features/chat/ChatPage.tsx` | 对话页：第二栏是会话列表（可收起，记在浏览器里），右边是对话区；地址 `/chat/<会话 ID>`，会话不存在时回到 `/chat`；没选会话时是新会话落地页 `NewChatLanding.tsx`（发送时才建会话，流程在 `newChat.ts`） |
| `src/features/chat/` 其余 | 顶栏 `ChatHeader.tsx`（标题、轮数、文件、更多）；上下文占比 `context.ts`；草稿 `drafts.ts`（按会话存在浏览器里）；待办进度 `todos.ts`；重试 `retry.ts` |
| `src/features/threads/` | 会话列表：状态点、相对时间、标题过滤 `activity.ts`（`GET /api/threads` 的每个会话带最近一次运行折算出的 `activity`；有会话在跑或在等审批时列表每 5 秒刷新） |
| `src/features/models/`、`skills/`、`mcp/` | 模型、技能、MCP 三个管理页（读写都接上，D21） |
| `src/api/` | 接口调用、推送订阅、查询配置、类型 |

示例数据页的写法：`sample.ts` 放示例数据，同目录一个纯函数模块（校验、筛选、`xxxReducer`）放全部逻辑并有单元测试，页面用 `useReducer` 持有临时状态、顶部放 `PreviewBanner`。接上后端时只把数据来源换成接口查询，纯函数与组件基本不动。

页面有两个入口，连的是同一个后端：8000 由 backend 托管打包好的 `frontend/dist`（`backend/frontend.py`，设计文档 13.5，日常使用走它；只绑本机）；5173 是 Vite 开发服务器（`make web`，热更新，`/api` 转发到 8000），只用于开发界面。改了界面要 `make build` 后 8000 才会更新。

规则（由检查自动保证）：
1. 组件只用语义样式类（`bg-background`、`bg-card`、`text-foreground`、`text-muted-foreground`、`border-border`、`bg-primary` 等），不写具体颜色——`src/styles/no-raw-colors.test.ts`。
2. 主题必须提供全部必需字段，且与 `tokens.css` 的首屏默认值一致——`src/themes/themes.test.ts`。
3. 只有 `src/components/chat/` 可以引用 `@assistant-ui/*`——ESLint `no-restricted-imports`。
4. 新增主题：在 `src/themes/` 加一个主题文件并在 `registry.ts` 登记，组件不改。

## 6. 数据归属与迁移

- 每张表归属一个模块，只有该模块的 `repo.py` 读写它。
- 表结构变更统一用 Alembic，脚本放 `backend/migrations/versions/`，**一律写原生 SQL**；文件名带归属模块前缀，如 `0002_agents_knowledge.py`。
- deepagents 的对话存档表由 `AsyncPostgresSaver.setup()` 自行创建，不写迁移。
- 所有表带 `user_id`（v1 固定 `'me'`）。

## 7. 配置、密钥与第三方服务

- **配置只有两处（D22）**：
  - 普通设置：`config/settings.py` 的代码默认值 → 数据库 `app_settings` 表（设置页上改）→ 同名环境变量（含 `.env`，名字是键把 `.` 换成 `__` 再大写）。启动分两步：`get_settings()` 只读环境变量、连上数据库，再 `load_settings(表里存的)`；存的某项不合规就去掉那一项并记日志。设置页的清单与"立即 / 重启后生效"在 `SETTING_SPECS`。
  - 技能、MCP 服务清单、审批规则：`.workdata/` 里的文件（见第 13 节）。
  - 首次启动从 `config/seed/` 写入 `.workdata` 缺的默认文件（只补缺的、从不覆盖，记在 `.workdata/.seeded`），并经网关接口导入网关里缺的模型（`config/seed/models.yaml`）。`config/models.yaml` 只剩网关自身的设置。
  - **配置文件的格式版本**（设计 2026-10-23 7.3）：当前版本在 `config/integrations.py` 的 `CONFIG_VERSIONS`，没写 `version` 的当作 0。每次启动先 `migrate_config_files`（`backend/settings/seed.py`）再写默认文件：按 `_STEPS` 一版一版改原文（保留注释），改完重新解析核对，核对不上、写坏的（含不是 UTF-8 的）、备份或写入失败的都不动、记警告，启动照常；改之前原文件复制到 `.workdata/config/history/<文件名>.<时间>.bak`。页面写入（`UserConfigFiles.write`、停用清单）没有版本号时补上当前版本，其余字段原样保留；读取时 `version` 不当作配置项。**改了某个文件的格式**：把它的版本加一，并在 `_STEPS` 里加一步。
- 密钥只放根目录 `.env`（不进版本库）；模板是 `.env.example`。后端容器整份读入 `.env`（`env_file`），但网关要用的密钥（上游网关、`LITELLM_SALT_KEY`、各厂商的 `*_API_KEY`）在 compose 里给后端置空（D22）：智能体执行的命令只拿白名单里的变量（D20），本地 MCP 服务却以 root 跑在后端容器里、能读到后端进程的全部环境变量。
- **第三方服务一律在 `deploy/docker-compose.yml` 中定义**，镜像写死版本；当前网络访问不了 Docker Hub，经 `mirror.gcr.io` 拉取。
- 个人数据放 `.workdata/`（不进版本库、需要备份）；数据库数据在 Docker 数据卷中。

## 8. 新增功能的步骤清单

**新增 agents 能力模块**：建 `agents/main_agent/<能力>/` → 需要外部依赖时先写 `base.py` 接口与契约测试 → 写实现 → 在 `bootstrap.py` 装配 → 只通过 `__init__.py` 对外公开 → 如需建表，按第 6 节写迁移。

**新增接口路由**：在对应 backend 功能模块写 `schemas.py` / `repo.py` / 业务 → 在 `backend/api/` 加路由 → 可预期错误抛 `common.errors` 中的类型（统一映射为 404 / 409 / 503）→ 流式接口的存在性检查放在依赖里（推送开始后无法再返回 404）。

**新增前端功能**：在 `frontend/src/features/<功能>/` 下建组件，只用语义样式类；涉及对话展示的改动放在 `src/components/chat/`；接口调用加到 `src/api/client.ts`；后端接口或事件有改动时运行 `make types` 重新生成类型，再在 `src/api/types.ts` 起别名；纯逻辑（如事件处理器、转换函数）必须有单元测试。

**新增第三方服务**：加进 `deploy/docker-compose.yml`（固定版本、只监听 `127.0.0.1`）→ 确认不经 make、直接 `podman compose up -d` 也能起来（启动顺序写成 `depends_on`）→ 需要时在 `Makefile` 补快捷命令 → 写决策记录。

**启动与镜像**（D27）：后端是镜像模式，代码与打包好的前端都在镜像里（`image: ${BACKEND_IMAGE:-open-personal-agent-backend:latest}`，保留 `build:` 给构建电脑），不挂源码、不自动重载；启动只靠 compose（`deploy/` 里 `podman compose up -d`），Makefile 只是快捷命令。`deploy/.env` 链接到根目录 `.env`，compose 替换 `${变量}` 时读得到；扫描类测试不读它。`deploy/bundle-images.sh`（`make bundle`）把 `compose config --images` 列出的镜像存成一个文件，换机器时加载。

## 9. 运行、事件与用量（设计文档第 10 节、7.7）

**一次运行的链路**：

```
POST /threads/{id}/runs → RunManager.start：建运行记录，交给运行控制登记后台任务
  └→ MainAgent.run（agents）：deepagents 输出流 → 翻译器 → 我们的事件；运行跟踪器挂在回调上
       └→ RunManager._execute（backend）：加序号 → 事件总线（实时推送）
                                          → 每 200 毫秒分批写入 run_events
                                          → 用量事件写入 llm_usage；tool.running 写入 tool_usage
          结束（完成 / 失败 / 停止 / 服务停止）：run_events 整体替换为合并后的版本 → 更新 runs → 推送 run.finished
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/runtime/events.py` | 事件协议（pydantic）。新增事件在这里定义，然后 `make types` 生成前端类型 |
| `backend/openapi.py` | 导出接口文档并把事件定义并入（`AgentEvent`），供 `make types` 生成前端类型；`make check` 核对生成结果是否最新 |
| `agents/main_agent/runtime/translator.py` | 输出流片段 → 事件。回答与思考取自 `messages` 模式，工具 / 子智能体 / 待办取自 `updates` 模式 |
| `agents/main_agent/runtime/tracker.py` | 运行跟踪器（回调）：子智能体命名空间 → task 调用 ID；每次模型调用的用量；主智能体每次调用的上下文分段（`context_usage.py`） |
| `agents/main_agent/runtime/compaction.py` | 自建的上下文压缩：同名替换 deepagents 默认的那个；摘要后附上用户原话与锚点索引（压缩前提取记忆已于 2026-10-24 去掉：每一轮结束时已经提取过） |
| `agents/main_agent/models/failures.py` | 运行失败的类型（`error_kind`）：额度、限流、卡住、网关、上下文超长、其他（"被打断"由后端标） |
| `agents/main_agent/runtime/interruption.py` | 中断标记中间件：被打断的一轮补上"已中断"回答，模型下一轮不会重做 |
| `agents/main_agent/models/cleanup.py` | 换模型清理中间件：发给模型的请求里去掉其他模型产生的思考内容 |
| `agents/main_agent/usage/` | `llm_usage`（每次调用明细、会话按模型汇总）与 `tool_usage`（工具、技能各用了几次，设计 2026-10-23 6.8）的数据访问与查询 |
| `agents/main_agent/interjections.py`、`runtime/interjection.py` | 运行中插话（设计 2026-10-23 6.3）：每个运行一个内存队列；主智能体调用模型前取出送达的中间件 |
| `backend/runs/manager.py` | 运行编排：执行、停止、服务停止时收尾、补发 |
| `backend/runs/writer.py` | 事件分批写库与结束时的整体替换 |
| `backend/runtime/` | 运行时替换点：事件总线（②）、运行控制（③）、后台任务队列（⑤，见第 12 节） |

约定：
1. **agent_path**：主智能体为 `["main"]`；子智能体内部事件为 `["main", "<task 调用 ID>"]`，多层嵌套依次追加。前端按它把事件嵌进对应的子智能体卡片。
2. **用量**：每次模型调用一条 `usage` 事件，backend 收到即在后台写入 `llm_usage`（写库失败只记日志、不影响对话；收尾时等它们写完再推送结束事件）。处理事件的循环里不能有真正的等待（写库等放后台）：停止信号要落在智能体内部，才能把已输出的部分存进对话存档；`run.finished` 带本次合计并写入 `runs.usage`。只算 token、不算费用（设计 2026-10-19 4.11）：输入是实际发给模型的全部输入（含命中缓存的部分），缓存读写与思考只在每次调用的明细里，汇总与界面不单列；网关算的费用不读。被停止的那次模型调用拿不到用量：运行跟踪器按发送的内容（含工具定义）与已输出的文字估算，并用该模型最近一次完成的调用校准（token 数按"实际 / 估算"的比例），随 `run.finished` 的 `interrupted_usage` 字段显示在"已停止"旁——只用于显示，不写用量表、不计入合计。
3. **停止与服务停止**：停止 = 运行控制取消后台任务，结果记为 `cancelled`。运行建好后立即登记后台任务（中间没有等待），没有后台任务的运行在停止前再读一次状态——停止请求可能恰好碰上收尾，已结束的就按"已结束"拒绝，不给完整的回答追加"已停止"；服务停止 = 取消全部运行并等它们写完结果，记为失败（"服务停止，运行被中断"）。收尾（写库、推送结束事件）单独成任务并挡住取消，重复的停止请求（含停止后紧接着服务停止）只生效一次——否则连点停止或回答刚结束时点停止，运行会一直停在"运行中"、会话被卡住。容器里的启动命令必须用 `exec` 启动 uvicorn（否则停止信号到不了它），并带 `--timeout-graceful-shutdown`（否则会一直等浏览器的推送连接断开），两者缺一，收尾逻辑都执行不到。
4. **被打断的一轮**：停止或服务停止时，主智能体已输出的部分连同一段中断说明写进对话存档（说明的意思是"任务在此中断；用户要继续就接着已完成的部分往下做，提了别的要求就按新要求处理"），是否继续由用户的下一句话决定。没有输出文字或崩溃等来不及写入时，由中断标记中间件在下一次运行开始前补上同样的说明（被打断的工具调用由 deepagents 的 `PatchToolCallsMiddleware` 补结果）。
4a. **模型中途不再发数据**（网络断了、上游卡住）：各层都不会很快超时，运行会一直挂着。所以网关客户端每等下一段内容最多 `agent.stream_idle_timeout` 秒（默认 120；网关记录里等第一个字最长约 35 秒），超过就关掉连接、抛出 `ModelStalledError`。运行按失败结束，原因是一句中文（不带异常类名）；已输出的部分与被打断时一样写进对话存档，被放弃的那次调用给出估算用量（用量记录器对这种错误不丢掉进行中的调用）。只盯模型的数据流，执行很久的命令不受影响。
5. **界面历史**：运行中写入的是原始事件（进程中途退出也不丢已推送内容）；结束时替换为合并版本（每个智能体分别合并同一段回答 / 思考的逐字片段，带 `full_text`，text 是这段内容到此为止的全文；并行子智能体的片段交错也各自合并）。补发时若历史里没有结束事件，补一个失败的结束事件，前端才会停止重连。没有后台任务的运行被停止时，也存下并推送结束事件。
4b. **只在还没输出时重试**（设计 2026-10-23 4.3）：重试只留网关一层（`config/models.yaml` 的 `router_settings.num_retries: 2`，只在建立连接前），后端客户端 `max_retries: 0`，不配备用模型。等第一个有内容的片段的时限 = 空闲时限 + 每 10 万输入 token 60 秒、最多 300 秒（空闲时限更长时以它为准）；还没有任何输出（文字、思考、工具调用）就卡住时，网关客户端（`_TaggedChatLiteLLM._astream`）把开头的空片段扣住、关掉连接、重发一次同样的请求；已有输出后卡住照旧按 4a 失败。
4b'. **压缩的附录**（设计 2026-10-23 4.6）：附录前有一行系统标记（`APPENDIX_MARK`），下次压缩从最后一个标记往后逐条取回上次附上的原话与锚点（模型写摘要时可能照抄"原话"标题再写一份改写过的，所以不按标题找），与这次的合并后超限只从最早的逐条丢。
4c. **失败的类型与"重试这一轮"**（D26）：`run.finished` 带 `error_kind`（`models/failures.py` 识别；服务停止与重启补发的为 `interrupted`）与 `retryable`（后端收尾时按这次运行全部 `tool.started` 判断有没有副作用，含审批暂停前那段与子智能体内部）。没有输出就失败时也写中断说明（写明真实原因），但还没进到这一轮（最新存档点不属于这次运行）时不写。`POST /api/runs/{id}/retry` 以收尾时记下的 `retryable` 为准（界面历史里没有结束事件的运行一律不能重试），从这次运行最早的存档点的上一个存档点分叉重跑（会话第一轮就失败时先清掉存档），新运行记 `runs.retry_of`（迁移 0013）；前端由界面历史把被重试的那一轮收成一行。
4e. **运行中插话**（设计 2026-10-23 6.3）：`RunManager` 在 `_launch` 给每个运行建一个 `Interjections` 队列（只在内存里；恢复审批沿用同一个），经 `AgentContext.interjections` 交给智能体；`POST /api/runs/{id}/interject` 往里放，等审批时、已结束（队列已关）时 409。`InterjectionMiddleware` 只装在主智能体上，`abefore_model` 取出全部插话，推 `user.interjected`（`runtime.stream_writer`），并作为带 `additional_kwargs.interjection` 的用户消息追加进对话存档（内容前加"（用户在你工作时插话）"）；中断说明、修改参数说明、上下文分段、前端"最近的待办"找"本轮第一条用户消息"时都跳过插话。收尾时关掉队列取出没送达的：顺利结束（且不是服务停止）就用它们（换行拼接）发起下一轮，结束事件带 `next_run_id`，前端据此重建并接上；失败、被停或接续失败时结束事件带 `undelivered`，前端只在实时推送时放回输入框。收尾写库途中停机或点了停止（`_stop_requested`）时也不再接续：插话退回，并用 `RunRepo.update_event` 补存进已存的结束事件（积压小问题 B9）。送达过插话的一轮不能"重试这一轮"（`_retryable`），标题、记忆提取、会话索引的"用户说的话"带上插话（`answers.user_text`）。
4f. **工具用量**（设计 2026-10-23 6.8）：`ToolRunningMiddleware` 排在 `McpCallMiddleware` 之后（暂停挡下的调用不推），`tool.running` 带工具名与技能名（`read_file` 读 `/skills/<技能>/SKILL.md`、没有 offset 时）；派出子智能体（`task`）不推。后端收到后在后台写 `tool_usage`（同用量，收尾前等写完）；表不设外键，删会话不影响统计。
4d. **上下文分段与思考起止**（设计 2026-10-23 4.7、4.8）：主智能体每次调用模型时，跟踪器在拿到最终请求时算出系统提示词、常驻记忆、工具定义、相关记忆、对话历史各多少 token（真实分词器 × 校准比例），推 `context.usage`（排在这次调用的回答之前）；翻译器按（智能体，消息）推 `thinking.started` / `thinking.finished`，时间戳在发布时加上。旧历史没有这些事件，前端退回原来的推算。
6. **续传**：页面打开时进行中的运行，已存的事件由界面历史重建，推送从最后一个已存事件之后订阅（`/api/runs/{id}/events?after=<序号>`），否则文字会重复；断线重连时浏览器带的 `Last-Event-ID` 优先。前端按消息 ID 合并逐字片段（中间夹了用量等事件也不拆开）。

## 10. 工作区、执行命令与产物（设计文档第 9 节；D20）

```
智能体读写文件 → 工作区（agents/main_agent/workspace/local.py）直接读写 .workdata/workspace/<会话短 ID>/
智能体执行命令 → 先请用户审批（approval_rules.yaml 的 execute: ask）→ LocalSandbox（workspace/local_sandbox.py）
                 → 在智能体所在环境（后端容器）的 .workdata/workspace/<会话短 ID>/ 下用 bash 运行
写文件或执行命令之后 → 检查 outputs/ 的新增或改动 → file.created 事件 → 产物卡片
用户上传 → POST /api/threads/{id}/files（请求体就是文件）→ uploads/ → 随下一条消息作为附件交给智能体
文件面板 → GET /api/threads/{id}/files（列表）→ 按类型预览（表格走 …/table，其余直接读 …/content）
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/workspace/base.py` | 替换点：`Workspace`（文件后端、列出产物、读文件、删除会话目录）与 `Sandbox`（执行命令）；契约测试在 `agents/tests/contracts/test_workspace_contract.py` |
| `agents/main_agent/workspace/local.py` | 本地实现：deepagents 本地文件后端加上"只能访问本会话目录"的限制与执行命令能力 |
| `agents/main_agent/workspace/local_sandbox.py` | 执行命令：会话目录里用 bash 运行，进程组、超时、停止、环境变量白名单、root 时改用 uid 1000 并加 Landlock 写入限制（D25，含跨目录改名、硬链接的 `refer`）；标准输出与错误输出分开收，太长时给模型开头 40% 与结尾 60%、完整输出写日志；真实退出码（超时 124） |
| `agents/main_agent/workspace/reaper.py` | 停止或超时时补杀脱离进程组的后代进程：运行中每 0.5 秒记下后代（进程号 + 启动时间），两次脱离的靠命令环境里的随机标记从 `/proc` 找（以 uid 1000 扫描） |
| `agents/main_agent/runtime/execute.py` | `ExecuteResultMiddleware`：经 `COMMAND_RESULTS` 上下文槽位把退出码、错误输出、是否超时并进工具结果的附加信息，翻译器写进 `tool.finished` |
| `agents/main_agent/runtime/tool_running.py` | `ToolRunningMiddleware`：工具真正开始执行（审批之后）时经自定义流推 `tool.running`（流模式含 `custom`），界面从这时算用时 |
| `agents/main_agent/workspace/files.py` | `workspace_files` 表：登记上传与产物；文件 ID 由会话 ID 与路径算出（同一文件始终同一个 ID） |
| `agents/main_agent/runtime/files.py` | 智能体看到的文件树：`/workspace/`（工作区）、`/skills/`（技能，只读）、`/.agent/`（大段工具输出的转存，存在对话存档里） |
| `agents/main_agent/workspace/media.py` | 按文件名判断类型：只用 Python 自带的表并补上 Office、Markdown 等常用格式，本机与容器里结果一致 |
| `agents/main_agent/runtime/attachments.py` | 消息附带的文件交给模型：注明文件位置；能看图的模型同时收到图片本身 |
| `backend/files/preview.py` | 表格预览：CSV / Excel 的前若干行，单元格一律转成文字 |
| `frontend/src/features/files/` | 右侧文件面板与各类预览（`kind.ts` 按类型选择预览方式） |
| `frontend/src/features/chat/uploads.ts` | 输入框上方待发送的文件（上传中、完成、失败） |
| `deploy/backend.Dockerfile`、`deploy/matplotlibrc` | 执行命令用到的环境：中文字体与 matplotlib 配置、uid 1000 的普通用户、`/workspace` 指向工作区；预装的数据处理库就是项目依赖（与智能体共用一个 Python 环境）；去掉了系统 Python 的 pip（命令里装不了包，D20 修订） |
| `agents/subagents/` | 子智能体定义（每个一个 `.md`，开头 YAML 写名称与说明，正文是提示词；不写 `model` 时跟随主对话所选模型） |

约定：
1. **会话隔离**：会话短 ID 从运行上下文（`AgentContext`）取得，子智能体继承同一上下文。文件工具越界时抛 `PermissionError`——deepagents 只把 `OSError` / `RuntimeError` 转成工具错误，抛别的异常会让整次运行失败。覆盖、修改已有文件前要读过最新版（按读时的修改时间与大小判断，记录在内存里，）。**执行的命令只限写入**（D25）：以 uid 1000 运行时 Landlock 只放行本会话目录、`cache/exec-home`、`/tmp`、`/dev` 的写入；读不限、能上网（D20 的代价），所以默认执行前先问用户。内核不支持 Landlock 时只记警告、不加限制。后端容器里 `.workdata/backups` 用空的只读目录 `deploy/empty-dir` 遮住（podman 的 tmpfs 默认会把底下的内容复制进去，不能用）。读过记录按调用方分开（主智能体为空串，子智能体为它的检查点命名空间去掉最后一段，`workspace/local.py` 的 `current_caller`），主智能体读过、子智能体改过之后要先重读（积压小问题 D16）。
2. **目录权限**：每次运行开始时由 backend 建好会话目录与 `outputs/`（`Workspace.prepare`），新建的目录权限放开为 0777——backend 在容器里是 root、执行命令用 uid 1000；Mac 上的 podman 共享目录不区分 uid，换到 Linux 原生 Docker 时命令改不了 backend 写的文件。
3. **后端容器的 1 号进程是 init**（compose 的 `init: true`）：负责回收停止或超时时被杀掉的孙进程，否则僵尸进程会一直累积。命令只拿到白名单里的环境变量（不含网关密钥、数据库地址），`HOME` 是 `.workdata/cache/exec-home`；PATH 最前面是智能体自己的 Python。智能体看到的路径是 `/workspace/<会话短 ID>/`：镜像里 `/workspace` 是指向工作区的链接，命令输出里的真实路径换回这个写法。
4. **停止**：运行被停止时，执行命令的协程被取消，随即杀掉整个进程组（`start_new_session`），再按 `reaper.py` 补杀脱离进程组的后代（命令正常结束时还有后代占着输出也补杀，积压小问题 D14）。超时同样处理；时限默认 `workspace.command_timeout`（120 秒），智能体最多能要 `max_command_timeout`（600 秒）。
5. **产物**：只看 `outputs/`。backend 收到 `file.created` 时直接算出文件 ID 填进事件再推送，登记在后台完成（处理事件的循环里不能有真正的等待，见第 9 节约定 2）；收尾时等登记写完再推送结束事件，前端收到后即可下载。停止、失败的运行收尾时再列一遍 `outputs/`，没登记的照常登记并在结束事件之前补推 `file.created`（命令写好文件后卡住被停时，智能体来不及发现它们，积压小问题 D1）。
6. **下载**：先核对文件属于该会话（不属于时返回 404），再按登记的路径边读边传（`Workspace.open_file`）；文件被删除、换成目录或换成指向会话目录外的链接时返回 404"文件已不存在"。响应带 `Content-Security-Policy: sandbox` 与 `X-Content-Type-Options: nosniff`，智能体生成的 HTML / SVG 直接打开时不执行脚本。
7. **给执行的代码加库**：直接加进项目依赖（`uv add 包==版本`），再 `make build`；改提示词里的已装库清单（`agents/prompts/system.md`、`agents/subagents/data_analyst.md`）。
8. **上传**：`POST /api/threads/{id}/files`，请求体就是文件本身，文件名按 UTF-8 百分号编码放在 `X-File-Name` 请求头（这个自定义请求头同时满足第 11 节约定 2）。单个文件上限是设置 `max_upload_mb`（默认 50MB，与知识库文档、技能包共用）：请求头声明的长度超限时立即拒绝，传输中超限时删掉已写的部分，都返回 413。只保留文件名本身（去掉目录部分、控制字符和开头的点；超过 200 字节的保留开头与后缀，文件系统限制文件名不超过 255 字节），同名时加序号，不覆盖已有文件；登记为来源 `upload`。
9. **附件**：发消息时 `attachments` 带上本会话已上传文件的 ID（最多 10 个，别的会话的文件返回 404），运行记录的 `input` 里存一份（`{"message", "attachments"}`），界面历史据此在用户消息下显示附件。交给模型时在消息末尾注明文件位置；当前模型能看图（网关的模型信息，每次调用时才判断，不知道时按不能处理）时，PNG / JPEG / GIF / WebP 且不超过 5MB 的图片同时作为图片内容发出；一条消息合计不超过 15MB（各家对整个请求有大小限制），超出的只注明位置并告诉模型可以用代码查看。图片存进对话存档后，之后每一轮都会随历史重发（计入输入用量）。同一会话换到不能看图的模型时，换模型清理中间件把历史里的图片换成一句说明（对话存档不变）。
10. **预览**：前端按类型选择预览方式（`features/files/kind.ts`）。表格走 `GET …/files/{fid}/table?sheet=`：只读不超过 20MB 的文件，取前 100 行、50 列，CSV 依次按 UTF-8（可带 BOM）、GB18030 解码。网页放在不允许脚本的内嵌框里（Claude 的内置浏览器会拦截这类内嵌框，要在普通浏览器里验证）；超过 1MB 的文字文件不在页面里显示。预览地址带 `?v=<更新时间>`，同一文件被改写后不会显示浏览器缓存的旧内容。
11. **后端的时区跟着本机**：Makefile 读 `/etc/localtime` 导出 `HOST_TZ`；不经 make 时用 `.env` 里的 `HOST_TZ`。compose 只给 backend 设 `TZ: ${HOST_TZ:-UTC}`（`.env` 里写的是 `HOST_TZ` 不是 `TZ`：网关也整份读 `.env`，不受影响）；都没有时是 UTC。数据库里的时间、运行事件的时间戳、用量按天统计都不受影响（都明确带时区）。（命令也拿到 TZ：白名单里本来就有它）

## 11. 本机安全防护（D23 删除，D25 加回令牌与 Host 校验）

2026-10-19 删除了访问令牌页、局域网访问、写操作来源检查、只收 JSON、启动时的配置自检（D23）；2026-10-23 加回一层轻防护（D25）。现在有：
1. **本机守卫**（`backend/api/local_guard.py`，纯 ASGI 中间件，`create_app` 里最后加、在最外层）：Host 只认 `127.0.0.1`、`localhost`（端口不限）；`/api/` 下除 `/api/health`、`/api/session` 外要令牌——请求头 `X-Session-Token`，GET / HEAD 也认 Cookie `opa_session`，写操作只认请求头。令牌每次启动生成、只在内存（`app.state.session_token`）。前端 `api/session.ts` 取令牌并缓存，`client.ts` 每个请求带上、401 重取一次；推送（`events.ts`）先取令牌再开，被关掉时重取并从断点重开一次。测试客户端（`make_client`）默认带令牌；端到端测试直接调接口用 `tokenHeaders`。防不住同一容器里的命令和 MCP 进程（D25）。
2. 后端端口在 compose 里写死只绑本机 `127.0.0.1:8000`。
3. 不开启跨域（CORS）：前端与接口同源（开发时经 Vite 转发，Host 仍是 localhost），跨站网页读不到接口的返回内容，也拿不到令牌。
4. 文件预览的响应带 `Content-Security-Policy: sandbox`，预览的网页里的脚本不能执行。
5. 对话存档只反序列化登记过的类型：`LANGGRAPH_STRICT_MSGPACK=true`（Makefile、镜像、compose、测试夹具四处一致）。
6. 文件上传接口的请求体是文件本身，文件名放在请求头 `X-File-Name`。
7. **日志**（`backend/logging_setup.py`，lifespan 最先调用）：根日志从 INFO 起，格式 `%(asctime)s %(levelname)s %(name)s: %(message)s`，全部经 `common/redact.py` 打码（环境变量里 `*_KEY`、`*_TOKEN`、`*_SECRET`、`*_PASSWORD` 的值，`sk-…`、`Bearer …`、`api_key=…`、网址口令）；警告以上另写 `.workdata/logs/backend-error.log`（5MB × 3，0600）；uvicorn 的处理器换成同一格式并挂上错误日志。运行失败写进数据库、界面的报错文字也过 `redact`。httpx、httpcore 只记警告以上。

## 12. 知识库、记忆、文档与后台任务（设计文档第 8 节）

```
每次运行开始 → MainAgent 查常驻条目 → 运行上下文 → 知识上下文中间件拼进系统提示词末尾
新的一轮开始 → 与这句话相关的记忆（向量召回）→ 放在本轮用户消息开头（"系统附加"，D24）；审批后继续不再召回
上下文快满 → 自建压缩中间件：先对要压掉的部分提取一次记忆（只主智能体、只送没提取过的消息）→ 摘要 → 附上用户原话与锚点索引
智能体 remember → 知识存储写入（向量化 + 分词）→ 工具结果附带条目 → 翻译器推送 memory.saved → 前端"已记住"
运行顺利结束 → RunFollowups 登记后台任务（第一次顺利结束：标题；开启自动提取：记忆提取）→ jobs 表
  └→ TableJobQueue 后台循环逐个处理 → 读运行的消息与回答 → MainAgent.generate_title / extract_memories
       → 改会话标题 / 改知识库；模型用量记在这次运行名下（调用方 title / memory_extraction）
知识库页 → /api/knowledge/*（列表、检索、增删改、常驻汇总）
上传文档 → POST /api/knowledge/documents → DocumentLibrary.add：原文件存 .workdata/knowledge/<文档 ID>/（边存边算 SHA-256），
  内容相同的已有一份就删掉刚存的并 409，否则登记 knowledge_documents（带 content_hash，迁移 0018；升级前的旧文档
  每次启动后台给还没有的补算，原文件读不出的记占位空字符串；空文件当场拒绝，不进查重）
  └→ 文档队列（单独一条）→ DocumentLibrary.ingest：解析为 Markdown（页码统一成标记）→ 按标题切块
       → 每次向量化 2 段写入 knowledge_items（kind=document_chunk）→ 更新进度 → 完成 / 失败（带原因）
智能体 search_knowledge → 文档片段带出处链接 [《文档名》位置](#kb-<条目 ID>) → 模型照抄进回答
  → 前端把 #kb- 链接显示成出处按钮 → GET /api/knowledge/items/{id}/context → 右侧"出处"面板（PDF 可打开到对应页）
会话文件 → POST /api/threads/{id}/files/{fid}/knowledge → 同上传文档
```

| 位置 | 职责 |
|---|---|
| `agents/main_agent/models/embedding.py` | 替换点：向量化（`Embedder`），经网关的实现；统一 1024 维；契约测试 `agents/tests/contracts/test_embedder_contract.py` |
| `agents/main_agent/knowledge/base.py` | 替换点：知识存储（`KnowledgeStore`：增删改查、常驻条目、检索、记忆召回）；契约测试 `test_knowledge_contract.py`（集成） |
| `agents/main_agent/knowledge/pgvector.py` | PostgreSQL 实现：`knowledge_items` 表；向量检索与关键词检索按倒数排名融合合并；查询加 Qwen 的任务说明前缀，条目本身不加 |
| `agents/main_agent/knowledge/tokens.py` | jieba 分词（搜索引擎模式），写入与查询用同一套切法 |
| `agents/main_agent/knowledge/extraction.py` | 会后提取记忆：对照相近的已有记忆，按模型回的 JSON 新增 / 更新 / 删除 |
| `agents/main_agent/runtime/knowledge.py` | `remember` / `update_memory` / `forget_memory` / `search_knowledge` / `read_document` 工具与知识上下文中间件 |
| `agents/main_agent/knowledge/pinned.py`、`suspicious.py` | 常驻上限的检查（`pinned_room`）与记忆的可疑检查（`suspicious_reason`，设计 2026-10-23 6.6） |
| `agents/main_agent/conversations/` | 替换点：会话索引（`ConversationIndex`，设计 2026-10-23 6.1）与 PostgreSQL 实现（`conversation_turns` 表，jieba 分词同知识库）；契约测试 `test_conversation_index_contract.py`（集成） |
| `agents/main_agent/runtime/conversations.py` | `search_conversations` 工具：搜、看某一轮、前后翻、最近几次，结果带 `#conv-<会话>-<运行>` 链接 |
| `agents/main_agent/runtime/titles.py` | 会话标题生成与清理 |
| `backend/runtime/jobs.py` | 后台任务队列：`jobs` 表 + 本进程一个后台循环，失败按次数延后重试，最多 3 次 |
| `backend/runs/followups.py` | 运行顺利结束后的后续任务：登记与处理程序 |
| `agents/main_agent/knowledge/parsing.py`、`markitdown_parser.py` | 替换点：文档解析（`DocumentParser`）与 markitdown 实现；契约测试 `test_document_parser_contract.py`，样例文件在 `agents/tests/fixtures/documents/` |
| `agents/main_agent/knowledge/chunking.py` | 按标题切块，每块记下章节路径与页码 |
| `agents/main_agent/knowledge/blobs.py`、`blobs_local.py` | 替换点：原文件存储（`BlobStore`）与本地磁盘实现；契约测试 `test_blob_store_contract.py` |
| `agents/main_agent/knowledge/documents.py` | `knowledge_documents` 表：文件名、状态、进度、失败原因 |
| `agents/main_agent/knowledge/library.py` | `DocumentLibrary`：登记、存原文件、处理流程、删除、重新处理 |
| `backend/knowledge/jobs.py` | 文档处理的后台任务（单独一条队列） |
| `backend/api/knowledge.py` | 知识库接口：条目、常驻汇总、文档、片段前后文 |
| `frontend/src/features/knowledge/` | 知识库页（记忆 / 常驻 / 文档）、文档列表、出处面板、出处链接的识别 |

约定：
0. **记忆放在哪**（D24，修订 D17 的放置位置）：常驻条目每次调用前拼在系统提示词末尾；相关记忆在新的一轮开始时召回一次，放在本轮用户消息开头（"系统附加"的说明 + `<related_memories>`，尖括号转全角，之后才是用户原话），审批后继续不再召回。系统提示词因此在一个会话里不变，提示缓存才能命中（Claude 的缓存断点写在网关的模型参数里，D24）。用到用户原话的地方（标题、记忆提取、压缩附录、端到端假模型）用 `user_words()` 去掉这段。
1. **召回失败不影响回答**：向量化服务不可用或召回超过 `knowledge.recall_timeout`（默认 5 秒）时，本次运行不带相关记忆（常驻条目不需要向量化，照常带上）；召回只拿消息开头 2000 字，只找非常驻的记忆（常驻条目本来就每次都带上，不占名额）；`remember` / `search_knowledge` 失败时工具结果标为出错并说明原因，运行继续。知识库页的添加、搜索返回 503 并说明原因，不带搜索词的列表照常可用。
2. **常驻条目**：每次调用模型都带上，总量上限是设置 `knowledge.pinned_token_limit`（默认 2000 token），2026-10-23 起是硬限制（设计 6.6）：`remember` 设常驻、知识库页新增或改成常驻、改了常驻条目的内容（`update_memory` 同样）时用 `pinned_room` 检查，放不下就拒绝（接口 409，工具结果出错），改的那条原来的大小不算；系统提示词写"常驻信息已用 X / 上限 token"（按全部常驻算，含可疑的）。文档片段不能设常驻（422）。自动提取不改常驻条目（只列给模型看，避免重复）。
2a. **可疑的记忆**（设计 2026-10-23 6.6）：存储实现在写入记忆（`add`、`update` 改了内容时）时调用 `suspicious_reason`，命中的记下类名（`suspicious`），改了内容重新检查并把 `trusted` 复位（迁移 0016）；文档片段不查。可疑且未确认（`KnowledgeItem.flagged`）的不拼进常驻提示词、不给提取模型看、不出现在 `search`（页面检索传 `include_suspicious=True`）与 `recall` 里；知识库页照常列出，另有"可疑"视图（`list_items(flagged=True)`），"确认无害"即 `PATCH {trusted: true}`。资料标记与尖括号转义照旧（两道防线）。规则只认针对智能体的说法（审查后收紧：误标的记忆会悄悄失效）：英文词边界用"前后不是英文字母数字"（汉字也算 `\w`），先去掉零宽字符；每段长度都有上限、邮箱用 ASCII 字符类，长文本也是线性时间；改规则时把误报、漏报的句子都加进 `test_suspicious.py`。
2b. **更正与忘掉**：`update_memory(old, new)`、`forget_memory(fragment)` 用 `KnowledgeStore.find_memories`（不分大小写的子串，只找记忆）定位，唯一命中才改 / 删，否则作为工具出错列出最多 5 条候选（包进 `<资料>`）；与其他知识库工具一样自动执行；子智能体不给（`MEMORY_WRITE_TOOLS`）。
2c. **会话索引**（设计 2026-10-23 6.1）：运行结束（含失败、被停）后后台任务 `conversation_index` 写一行"用户说的话 + 回答全文"（`answer_text` 从界面历史拼出，"重试这一轮"替换旧行）；改标题同步、删会话一并删（删会话最后再删一次索引，写索引的任务写完再查会话还在不在：两者撞上也不留下已删的内容）；搜索除分词全文检索外再按原文整段查（jieba 会把名字和旁边的字粘在一起），整段出现的排前面；启动时 `backfill_conversation_index_once` 把已有历史补建一次（`.workdata/.seeded` 记下）。服务中途退出的运行，下次启动标记失败时一并登记写索引（已分批写下的部分回答也搜得到）；已被"重试这一轮"替换的那一轮，写索引的任务晚到时不再写回（积压小问题 B6、B7）。
3. **后台任务**：只在运行顺利结束时登记，并且在推送结束事件之前登记（前端收到结束事件时任务已在队列里）；登记失败只记日志。任务逐个处理，标题排在记忆提取前面。处理程序抛异常时按次数延后重试（30 秒、60 秒），第 3 次失败记为失败并留下原因；服务停止时正在处理的任务保持"处理中"，下次启动时重做。会话被删除后，它的任务直接结束。
4. **标题**：会话的标题先是首条消息的前 30 个字（自动标题）；第一次顺利结束后由后台生成。只有标题仍是自动标题时才替换（带条件更新，生成期间用户改了名也不覆盖）。前端在运行结束后标题仍是自动标题时，隔 2、5、10、20 秒刷新会话列表。
5. **新增后台任务种类**：在 `RunFollowups.handlers()` 登记处理函数，在 `after_completed` 里决定何时登记。处理函数可能被重试或在重启后重做：写成重做也无妨的样子；做不到时写明后果（如记忆提取做到一半被打断、重做时，可能多出一条重复的记忆，用户可在知识库页删除）。
6. **报错原因**：向量化失败的原因只给一句中文（会显示在知识库页和工具卡片上），原始报错记进日志；后台循环里写任务结果失败只记日志、循环继续。
7. **文档处理**：单独一条任务队列（`TableJobQueue` 只领取、只在启动时放回自己有处理函数的种类），几分钟的大文档不挡住标题、记忆提取。每次只向量化 `knowledge.ingest_batch_size`（默认 2）段：本机向量模型一次只处理一个请求，批太大时对话里找相关记忆要等太久（每批 8 段时要等约 12 秒）。处理失败（解析不出文字、向量模型不可用、原文件不见了，以及意料之外的错误）只把文档状态改成"失败"并写明原因，不抛出、不自动重试，用户点"重新处理"；处理到一半服务停了（文档还是"处理中"），重启后接着做一次，连续中断两次就标为失败（文件可能大到把服务撑崩，不能在每次启动时重做）；处理开始时先删掉旧片段，重新处理、重启后重做都不会重复。处理途中文档被删，安静结束。
8. **切块与出处**：解析时页码统一成 `<!-- page: N -->` 标记（PDF 的页、PPT 的幻灯片）；切块按标题记下章节路径（`第一章 考勤 › 1.1 请假`）；新的一页、新的一节总是另起一块（不带上一块的结尾），一节太长时才在节内按大小切开并重叠——出处的页码、章节才准。代码块（``` 或 ~~~ 之间）里以 # 开头的注释不是标题。向量化与分词用的文字带上文档名与章节，存下的内容只是片段本身。出处链接 `#kb-<条目 ID>` 由 `runtime/knowledge.py` 的 `citation` 生成，前端 `features/knowledge/citations.ts` 识别；两边的位置写法（章节路径 · 第 N 页）要保持一致。
9. **格式与上限**：支持 PDF、Word、PowerPoint、Excel 的新格式与 CSV、Markdown、TXT、网页（`SUPPORTED_SUFFIXES`），其他格式上传时就拒绝（415，提示另存为新格式）；单个文档不超过 `max_upload_mb`（默认 50MB，与对话附件、技能包共用；解析在内存里进行）。扫描件解析不出文字，处理失败并说明原因。

## 13. 外部集成与审批（设计文档 7.2、7.5、10.5；D23：会话权限三档、预算刹车已去掉）

```
启动 → IntegrationSettings.load（后台，不挡启动）：读 config/mcp_servers.yaml、config/approval_rules.yaml
  └→ MainAgent.reload_integrations：McpClient.connect（每个服务一个专属任务保持一个会话）→ 换审批规则 → 清空组装缓存
组装智能体（按模型与会话的审批权限各一份）→ 知识库工具 + MCP 工具；ApprovalPolicy 按档位逐个判定
  → "先问你"的工具进 interrupt_on（主智能体与子智能体都生效）
运行中调用"先问你"的工具 → LangGraph 中断 → 翻译器收集请求 → 这一段以 approval.required 结束（不发 run.finished）
  └→ RunManager：事件、用量写完 → runs 记为 interrupted（带用量合计）→ 关闭推送；后台任务结束，不占资源
审批卡片 → POST /api/runs/{id}/resume → 校验答复 → 状态原子地改回 running → 重新打开推送 → MainAgent.resume
  └→ 第一个事件 approval.resolved，序号接着往下编 → 跑完照常 run.finished
MCP 页、技能页 → /api/settings/*（MCP 服务、审批规则、技能；重新加载）；设置页 → /api/settings/app、/api/settings/files
```

| 位置 | 职责 |
|---|---|
| `config/integrations.py` | 两个可重新加载的配置文件：`McpServerConfig`（`${变量名}` 替换，缺的记进 `missing_env`）、`ApprovalRulesConfig`；写错时抛 `InvalidConfigError`（一句中文，带文件与位置） |
| `agents/main_agent/integrations/mcp.py`、`mcp_adapters.py` | 替换点：MCP 客户端（`McpClient`）与 langchain-mcp-adapters 实现；契约测试 `test_mcp_client_contract.py`，测试用服务 `agents/tests/fixtures/mcp/demo_server.py`（环境变量开关：记启动、拒绝启动、多一个工具）。每个服务一个守护任务：每 30 秒 ping，断开后 `reconnecting` 按 1、2、4、8、16 秒重试，还不行 `failed`、之后每 5 分钟再试；交出的是稳定的代理工具（拦截器转给当前会话，断开时返回 `MCP_DISCONNECTED` 提示）；工具清单变了经 `on_tools_changed` 通知 |
| `agents/main_agent/integrations/approval.py` | `ApprovalPolicy`：在某个会话权限档位（`PermissionMode`：ask / ask_execute / skip）下，每个工具"自动执行"还是"先问你"，带原因 |
| `agents/main_agent/runtime/approvals.py` | `interrupt_on` 组装（硬底线：任何档位危险命令都问）、同名替换的审批中间件 `ApprovalMiddleware`（中文的拒绝说法，`edit_notice=None`）、恢复答复的校验与转换 |
| `agents/main_agent/runtime/danger.py` | 硬底线的判断 `danger_reason`：引号外换行当分隔，shlex 切词后逐段看命令名与参数（`cd` 进 .workdata 之后的写操作、`bash -c` 里的命令也算）；"下载后直接执行"看整条命令 |
| `agents/main_agent/runtime/mcp_calls.py` | `McpCallMiddleware`：MCP 工具出错转成工具结果、按（运行，服务）数连续失败（`McpBreaker`，3 次暂停 60 秒，主智能体一份）、服务返回的内容加"外部资料"前缀并转义尖括号 |
| `agents/main_agent/runtime/subagent_reports.py` | `SubagentReportMiddleware`：子智能体交回超过 4000 字时全文存进会话目录 `reports/`，只交回开头与路径 |
| `agents/main_agent/runtime/interruption.py` | 被打断的一轮补上中断说明；停止、卡住、额度用完、调用出错时已输出的部分连同原因写进存档（D23） |
| `agents/main_agent/models/quota.py` | 判断模型调用失败是不是"额度用完"（402、预算超限、余额不足一类的字样；频率限制不算） |
| `agents/main_agent/runtime/skills.py` | 列出技能（设置页）；技能的加载由 deepagents 负责 |
| `backend/settings/` | `IntegrationSettings`：读配置文件、交给智能体、记下启动时的出错原因；有运行进行时拒绝重新加载 |
| `backend/api/settings.py` | 设置接口 |
| `frontend/src/features/chat/approvals.ts`、`components/chat/approval.tsx` | 审批卡片的选择与答复组装、卡片界面 |
| `frontend/src/features/settings/` | 设置页 |

约定：
1. **只有 `approval.required` 能让一段运行不带 `run.finished` 结束**。前端收到它就关闭推送（否则浏览器会自动重连）；页面打开时停在审批处的运行不订阅推送，等用户在卡片上决定后，从 `approval.required` 的序号之后订阅。
2. **恢复前先核对**：`approval.required` 带着暂停时工具与审批规则的指纹（`tools_version`），恢复时对不上（重新加载改了规则、重启后 MCP 服务没连上）就拒绝（409，提示停止后重新发消息）——否则审批中间件按新规则重新判定，用户的"拒绝"可能被无视、或因决定数量对不上而报错。正在重连 MCP 服务时（如刚重启）先等连接完成（最多 75 秒）；lifespan 在开始后台连接后让出一次，保证之后到达的恢复请求能看到"连接中"。同一运行的恢复与停止在 RunManager 里排队进行（每个运行一把锁），停止请求落在暂停收尾期间时，收尾完成后按"等待审批时停止"结束。
3. **恢复时的序号从已存的最后一个事件起算**（合并过的事件序号不连续，不能按条数算）；已存的事件原样保留，只合并新的一段（再合并一次，带 `full_text` 的片段会重复）。同一运行会重新打开推送、登记新的后台任务：事件总线要清掉上一段的关闭状态，运行控制只注销"还是它自己"的任务登记。
4. **一次运行的审批权限不变**：运行开始时从会话上取档位、记进运行的 `input`（`RunRecord.permission`），恢复时用它组装同一份智能体、算同一个工具指纹；运行中改会话的档位从下一条消息起生效（D23）。
5. **审批规则**：规则文件里第一条匹配的为准（`*` 通配）→ 没写到的内置工具自动执行 → 没写到的 MCP 工具看服务声明，只读的自动执行，其余按 `mcp_default`（默认"先问你"）。工具名带服务名前缀（`files_write_file`）。"回复一句话"用带 message 的拒绝实现：调用不执行，这句话转给智能体（D18）。
6. **工具出错不算运行失败**：MCP 工具抛出的异常（如超时）由 `McpCallMiddleware` 转成"调用失败"的工具结果（主智能体与子智能体都加：子智能体继承了 MCP 工具，deepagents 的 task 工具也不捕获异常）；服务断开时客户端直接返回提示、不抛异常；每次调用最多等 `call_timeout`（默认 60 秒）。某个服务连不上只影响它自己，原因显示在 MCP 页。服务返回的内容按资料对待（设计 2026-10-23 5.9），系统自己的提示（断开、暂停、调用失败）不加前缀。
6b. **重连期间的新运行**：MCP 服务正在（重）连时（启动后的首次连接、MCP 页"重新加载"或改服务），新运行组装前最多等 20 秒（`_NEW_RUN_SETTLE_TIMEOUT`），等不到照常跑；MCP 页的修改在锁与 `MainAgent.reconnecting()` 里先查"有没有对话在进行"再重连，查完之后发起的运行等重连完（积压小问题 E10、E15）。系统提示词末尾按已交出工具的服务列出"服务名（工具名以 服务名_ 开头）：说明"（E13）。MCP 工具失败的文字分两段：系统的"工具 X 调用失败。"与外部的"服务给出的原因（只作参考…）：…"（打码）；我们自己的超时（`TimeoutError`"调用超时（N 秒）"）不加说明；断线提示不计入连续出错（E1、E2、E5、E8）。
7. **组装缓存**：按（模型版本，审批权限）缓存；重新加载（含启动时后台连接完成）、MCP 重连后工具变了（`on_tools_changed`）都清空缓存，正在跑的运行继续用它手里那份。内置工具名列在 `BUILTIN_TOOLS`，由测试与 deepagents 实际绑定的工具核对。
8. **修改参数后执行**（`EditNoticeMiddleware`）：对话存档里那次调用的记录换成实际执行的参数；"用户亲自改了参数"写进本轮的系统提示词，不写在工具结果里——工具结果只是资料（D17），模型会把写在那里的要求当成可疑的提示。凡是要让模型知道"用户做了什么决定"，都走系统提示词这类可信的渠道。
9. **通用子智能体用自己的定义**（`MainAgent._general_purpose`）：deepagents 自动加的那个不带我们的中间件。子智能体的中间件统一由 `_subagent_middleware` 给出（工作目录说明、修改参数后执行的处理、MCP 工具出错转结果）；自定义子智能体与通用子智能体一样拿到技能来源。子智能体的 `tools` 是主智能体的工具去掉 `remember`、`update_memory`、`forget_memory`（设计 2026-10-23 5.10、6.6），审批中间件放在它自己的 `middleware` 里、`interrupt_on` 设为空（否则 deepagents 再加一个同名的）。
10. **技能清单每次运行都重读**（运行输入带 `skills_metadata: None`）：deepagents 默认每个会话只读一次，新加的技能老会话看不到。
11. **MCP 服务的运行环境**：本地进程型在 backend 容器里运行（镜像带 Node 24 与 uv）；npm 缓存在 `.workdata/cache/npm`（重建容器不用重下）；共享文件夹 `/shared` 对应 `.env` 的 `SHARED_DIR`（默认 `.workdata/shared/`）。需要密钥的服务在配置里写 `${变量名}`，变量在 `.env` 里设置后 `make restart`（后端容器整份读入 `.env`）。


### 管理页面的修改（D22，取代 D21 的叠加）

- **只有一份**：MCP 服务清单与审批规则在 `.workdata/config/`（`Settings.mcp_servers_file`、`approval_rules_file`），`config/integrations.py` 的 `load_mcp_servers` / `load_approval_rules` 是纯函数（参数是文件内容）。没有"自带"：任何服务、技能、模型都能改、能删。
- **写入**：`backend/settings/service.py`（MCP 与审批规则）先在内存里改、校验，不合规就拒绝；合规才经 `backend/settings/store.py` 的 `UserConfigFiles` 原子写入，再让智能体生效（要重连的先看有没有对话在进行；只改审批规则用 `MainAgent.update_rules`，不重连，但同样拿锁——重连结束时不能用旧规则盖回去；锁里写完文件后重读一次规则再生效）。停用清单 `skills.yaml` 写坏时 `SkillCatalog.hidden()` 当作没有停用、记日志，不让对话失败。接口给编辑用的原文（未替换 `${变量}`），密钥不出现在页面上。
- **执行命令固定先问**：在"每次先问""只问执行命令"两档下，`ApprovalPolicy.decide` 对内置工具 `execute` 直接返回 ask，任何规则放宽不了它——被同意的命令改得动 `.workdata/`（D21 第 7 条，限制写入范围见 R33）；"跳过所有审批"档才放开（D23）。
- **技能**：`agents/main_agent/runtime/skills.py` 的 `SkillCatalog` 管一个目录 `.workdata/skills/` 和停用清单（`.workdata/config/skills.yaml`）；智能体的文件树挂一处只读的 `/skills/`，`SkillsFilesystem` 让停用的技能看不见、读不到。上传包的检查在 `backend/settings/skill_upload.py`（内容用 base64 放进 JSON，检查完才落盘：先写临时文件夹再改名；大小上限用设置 `max_upload_mb`）。
- **模型**：`ModelGateway` 的 `add_model` / `update_model` / `delete_model` / `test_model`；LiteLLM 实现调网关的 `/model/new`、`/model/delete`（修改 = 先新增一份再删旧的，失败时撤回：网关的 PATCH 是合并写入，去不掉参数），模型存进网关数据库（`STORE_MODEL_IN_DB`，参数用 `LITELLM_SALT_KEY` 加密）。价格要放在调用参数里（放在模型信息里会被丢掉）。业务规则在 `backend/models/`：与网关里已有模型重名就拒绝（网关同名不覆盖、会分摊调用）、没有部署编号的模型（写在 `config/models.yaml` 里的）页面上不能改、默认模型不能删、删除后会话改用默认对话模型、默认对话模型存进设置表并立即生效。
- **设置页**：`backend/settings/app_settings.py`（设置表的读写、来源与"重启后生效"的判断，被环境变量覆盖的不许改）、`backend/settings/data_files.py`（`.workdata` 各文件的状态）。

## 14. 用量、调用归属与备份（设计文档 7.1、7.7、12.1）

```
MainAgent 每段运行 / 标题生成 / 记忆提取 → with call_context(会话, 运行)
  ├→ LiteLLM 网关实现（_TaggedChatLiteLLM._client_params）：请求带 litellm_session_id 与 tags thread:/run:
  │    → 网关库 LiteLLM_SpendLogs 的 session_id、request_tags → 网关后台按会话核对
  ├→ 运行跟踪器 → usage 事件 → llm_usage（调用方 main / 子智能体名 / compaction / title / memory_extraction）
  └→ 向量化实现每次请求后 on_usage → 组装根写 llm_usage（调用方 embedding，会话与运行取 current_call，文档入库时为空）
GET /api/usage/summary?days=&tz= → UsageRepo.summary（llm_usage 的调用与 token；tool_usage 的工具、技能次数）+ ThreadRepo.titles（backend 补标题）→ 用量页
make backup / make restore → deploy/backup.sh、restore.sh（compose exec 里 pg_dump / pg_restore；tar workdata 的个人文件）
make doctor → deploy/doctor.py（宿主机上运行、只用标准库：compose ps / exec 与几个 GET 请求，只读）
```

约定：
1. **新的调用模型的地方要在 `call_context` 里**：如以后的后台任务、定时任务。否则网关里对不上会话，向量化的用量也记不到会话名下。它是上下文变量，LangGraph 新建的任务会复制它；用在异步生成器里时，复原失败（在别的上下文里关闭）就忽略。反过来，在运行里另开、只写库的后台任务（RunManager 的收尾与写用量、工具用量、产物登记）用 `detached_context()` 建：复制当前上下文、只去掉调用归属（积压小问题 G2）。
2. **给网关的会话与标签走 `extra_body`**：ChatLiteLLM 的 `metadata`、`tags` 参数名与 LangChain 冲突，直接传的 `litellm_session_id` 到不了网关（M5 先行探测）。已有 `extra_body` 时按键合并：`metadata` 里原有的键留着、`tags` 接在原有的后面（积压小问题 G3）。向量化请求把同样的字段直接写进请求体。
3. **按天汇总用用户所在的时区**：浏览器传 IANA 时区名（`Intl`），SQL 里 `AT TIME ZONE` 用参数，不拼接。接口与界面都只有调用次数、输入、输出（2026-10-19 起不再存、不再给费用，`llm_usage.cost` 已删，迁移 0012）；模型的价格只是模型页上的资料。
4. **备份脚本的参数都来自环境变量**：Makefile 给正式值，测试指向测试库与临时目录。导出只取标准输出——compose 的提示在标准错误里，混进来会损坏备份。脚本兼容 macOS 自带的 bash 3.2：变量名后紧跟中文时写 `${名字}`。恢复的顺序：检查（完整、能读出）→ 确认 → 停服务（`BEFORE_RESTORE`，Makefile 给出停 backend 与 litellm 的命令；之后不论成败都执行 `AFTER_RESTORE` 起回来）→ 自动备份当前数据（前缀 `pre-restore-`，单独保留 3 份，正要恢复的那份不删；备份轮换只算同一前缀、带 manifest.txt 的完整备份）→ 各库先恢复到 `<库名>__restoring`（单个事务、出错即停），全部成功后再改名替换（与备份完全一致，不残留以后迁移建的表）→ 文件先解到 `.workdata/.restoring` 再替换各目录的内容；`.seeded` 也在备份里（D22 第 8 条修订），备份里有就整份替换，旧备份没有就不动。备份脚本只在 `EMIT_NAME` 设了时打印 `BACKUP_NAME=`（恢复脚本用它找到自动备份）。恢复文件时只清空目录内容，不删目录本身（共享文件夹被容器挂载着）；macOS 的 find 删除失败仍返回成功，所以做完检查目录是否真的空了。各库恢复到临时库后、替换之前，比较现有库与临时库里 `threads`、`runs` 的行数（没有这两张表的库不比），变少了在最后一行提醒（设计 2026-10-23 7.2）。
5. **体检只读、不打印密钥**（设计 2026-10-23 7.1）：容器状态认两种格式——compose 的（每行一个对象，有 Service、Health）与 podman-compose 转给 podman ps 的（整段数组，服务名在 `com.docker.compose.service` 标签里，健康状况写在 Status 里）；模型列表经后端 `/api/models` 取（网关的 `/health` 会真的调用每个模型）；会话令牌只放请求头，输出前再抹一遍；命令与请求都有超时，连不上、超时、返回乱码都记成 ✗ 接着往下查。后端没起来时，要令牌的两项（模型、`.workdata` 文件）打"–"跳过，不重复计 ✗；后端正常却拿不到令牌时这两项算 ✗。

