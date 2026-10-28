# 个人智能体（open_personal_agent）设计文档

- 状态：已确认（第 5 版，2026-10-13）
- 设计讨论：2026-10-09 ~ 2026-10-12；成文：2026-10-12
- 技术栈：Python（uv 管理）+ deepagents + LiteLLM 网关 + PostgreSQL + 自写 FastAPI + 自写 React 前端（pnpm 管理）；第三方服务一律用 docker compose 管理
- 之后的改动以决策记录 D18～D23 与 [第一轮优化设计](2026-10-19-optimization-round1-design.md) 为准（正文只在个别小节加了注）：如去掉沙箱容器、命令在智能体所在环境执行（D20）；配置进数据库与 `.workdata`、去掉“自带 + 用户”的叠加（D22）；会话审批权限三档、去掉预算刹车、删除本机安全防护（D23）；用量只算输入与输出、不算费用（第一轮优化设计 4.11）。

### 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| 第 1 版 | 2026-10-12 | 初稿 |
| 第 2 版 | 2026-10-12 | ① 记忆并入统一知识库，记忆和个人画像都是带标记的知识条目；② Python 用 uv、前端用 pnpm，直接依赖一律写精确版本；③ 所有第三方服务一律由 docker-compose.yml 管理（含本地模型和测试用服务）；④ 开发规范与架构规范独立成文，并做成项目技能 |
| 第 3 版 | 2026-10-12 | 向量化确定为本地 Ollama + Qwen3 向量模型（0.6B，统一 1024 维）；Ollama 改为默认服务；新增决策 D15 与先行验证 V6 |
| 第 5 版 | 2026-10-13 | 前端改版：采用 assistant-ui（D16）+ 本项目主题系统（参考 Hermes Agent，一套代码按主题切换样式，M1 先做默认主题的深浅两版）；一键启动（backend 镜像内含打包好的前端）；M1 内容相应调整 |
| 第 4 版 | 2026-10-12 | Ollama 只做向量化，不跑本地对话模型（本地对话模型移入扩展路线）；实施分期改为"先跑起来"：M0 即交付可在浏览器对话的最小版本 |

---

## 1. 背景与目标

### 1.1 要做什么

自建一个**通用个人助理**：多轮对话、统一知识库（含长期记忆）、在隔离环境里执行代码处理文件、通过 MCP 接入外部工具（日历、邮件、飞书、GitHub 等），并能按会话切换各家大模型的具体版本。

> 名词说明（首次出现）：
> - **deepagents**：LangChain 出品的智能体框架，基于 LangGraph（一个把智能体流程建成"状态图"的底层框架），自带文件工具、子智能体、上下文压缩、人工审批等能力。
> - **LiteLLM**：用同一种写法调用各家大模型的开源工具，本项目把它部署成独立的"模型网关"服务。
> - **MCP**：模型上下文协议，一种让智能体接入外部工具的开放标准，外部工具以"MCP 服务"的形式提供。
> - **uv**：Python 的包与环境管理工具，负责 Python 版本、虚拟环境、依赖安装与锁定。
> - **pnpm**：前端的包管理工具，作用同 npm，安装更快、锁定更严格。

### 1.2 使用前提

| 项 | 结论 |
|---|---|
| 用户 | 只有本人，单用户 |
| 运行位置 | 本机，docker compose 启动，只监听 `127.0.0.1` |
| 主要开发语言 | Python 3.12（uv 管理）；前端 TypeScript（pnpm 管理） |
| 模型来源 | Claude、OpenAI / Gemini、国产模型（DeepSeek / Qwen / Kimi / GLM 等），全部要支持。本地对话模型 v1 不接（容器内无显卡加速、性能不足），Ollama 只用于向量化 |
| 前端 | React + Vite |
| 版本控制 | 当前是纯本地项目，暂不初始化 git；以后建立 git 仓库时再补上提交流程 |

### 1.3 成功标准

1. 能当日常主力助理用。
2. 同一会话中途换模型版本，上下文不丢。
3. 关掉浏览器再打开，会话和正在跑的任务都还在。
4. 越用越懂你：跨会话记得你的偏好和事实。
5. 加模型版本、加工具、换基础设施实现，只改配置或只加一个实现类，业务代码不动。
6. 每个模型版本的输入、输出 token 和费用都能统计到。
7. 任何人（或 AI 编程助手）开发新功能前读一份规范，就能写出与项目架构一致的代码。

---

## 2. 范围

| v1 做 | v1 不做（见第 19 节扩展路线） |
|---|---|
| 多轮对话、按会话切换**具体模型版本**、深度思考过程展示 | 联网搜索（以后通过 MCP 接入）；本地对话模型 |
| 待办清单、子智能体（通用助手、数据分析员）、技能 | 定时任务、主动提醒 |
| **统一知识库**：文档、记忆、常驻条目（个人画像）一套存储一套检索，回答带出处 | 多用户、登录、远程访问 |
| 沙箱执行代码、文件上传下载、产物预览 | 在前端编辑配置（v1 只读展示 + 重新加载） |
| MCP 接入、审批暂停与恢复、取消运行 | 多进程、云沙箱、外部向量库、对象存储 |
| 按模型版本统计输入 / 输出 / 缓存 / 思考 token 与费用 | 会话分支、编辑后重发 |
| 断线续传、预算刹车、本机安全防护、备份命令 | 语音、手机端、IM 机器人 |
| 独立的开发规范、架构规范与项目技能 | |
| 一套前端代码按主题切换样式（v1 先做默认主题的浅色、深色两版） | 更多预设主题、在界面中编辑主题 |

---

## 3. 关键决策汇总

每条决策在实现阶段补成 `docs/decisions/` 下的一份决策记录。

| 编号 | 决策 | 主要原因 |
|---|---|---|
| D1 | 模型调用全部走 **LiteLLM 网关**（独立容器） | 所有模型调用（含向量化）收拢到一个入口；集中管理密钥、重试、备用切换；本机其他工具也能共用 |
| D2 | 前后端通信用**自定义推送协议**（服务器单向推送，即 SSE），不用 AG-UI | 子智能体嵌套、待办、审批、产物需要定制界面；AG-UI 仍是 0.0.x 早期版本。以后可加 AG-UI 转换层 |
| D3 | 模型按**具体版本**登记（如 `claude-opus-4-8`、`claude-opus-4-6`） | 需要明确使用和统计到具体版本 |
| D4 | 用量用**自建表**按次记录，网关后台统计只作核对 | 自建表能与会话、子智能体关联，且不受网关内部表结构变化影响 |
| D5 | 架构总纲：**底层解耦，功能内聚**；所有基础设施走可替换接口 | 沙箱、网关、检索等都要能快速替换 |
| D6 | 三大块 `agents / backend / frontend` 同级，单向依赖；**单一 Python 项目**，用 import-linter 保证依赖方向 | 结构简洁；agents 可脱离 HTTP 独立运行 |
| D7 | **界面历史与模型上下文分开存** | 上下文压缩会替换旧消息，界面历史不能跟着"消失" |
| D8 | 沙箱用**常驻容器 + 共享工作区 + 内部专用网络**，backend 不持有 Docker 控制权 | 隔离足够、实现简单、不把宿主机最高权限交给 backend |
| D9 | v1 **单进程**运行，但预留运行时替换点，真实数据以数据库为准 | 单人使用足够；以后改配置即可切换到多进程 |
| D10 | **统一知识库**：只维护一套知识存储与一套检索（PostgreSQL + pgvector + jieba）。文档片段、记忆、个人画像都是带标记的知识条目 | 一套存储、一套检索、一套管理界面，概念最少；不引入独立向量库 |
| D11 | 记忆 = `kind=memory` 的知识条目；个人画像 = 打了"常驻"标记的条目；会话后**自动提取**记忆（可关闭） | 实现"越用越懂你"，同时你可在知识库界面统一查看和修改 |
| D12 | **依赖版本确定**：Python 用 uv，前端用 pnpm，直接依赖一律写精确版本，锁文件锁定全部间接依赖 | 可复现；deepagents 等迭代快、有破坏性变更，必须显式升级 |
| D13 | **第三方服务一律由 docker-compose.yml 管理和构建**（数据库、网关、向量模型服务、测试用服务及以后新增的服务） | 一条命令拉起完整环境，版本统一固定 |
| D14 | **开发规范与架构规范独立成文**，并做成项目技能；以官方规范为准、代码精简、与项目架构对齐 | 开发新功能时先读规范，保证长期一致 |
| D15 | **向量化用本地 Ollama + Qwen3 向量模型**（`qwen3-embedding:0.6b`），经网关调用；全部向量**统一 1024 维** | 知识库与记忆不出本机、零边际费用、中文表现强、苹果芯片可直接运行；1024 维兼容 pgvector 索引上限（2000 维），且各主流向量模型都能输出，以后换模型只需重建向量、不改表结构 |
| D16 | **前端对话组件采用 assistant-ui**（只用不带样式的基础组件，经"外部数据源"接法对接本项目的事件处理器），**样式由本项目主题系统决定**（参考 Hermes Agent：主题即数据 → CSS 变量 → 语义样式类） | 2026-10-13 一次性验证通过：兼容本项目配置，流式 / 工具卡片 / 错误 / 停止正常，自带中文输入法处理，并为思考过程、子智能体、审批、附件预留了数据结构；只在 `components/chat/` 一层引用，换实现只改这一层 |

---

## 4. 架构总纲：底层解耦，功能内聚

一句话：**横向靠接口隔离，纵向靠模块内聚。**

- **底层解耦**：每一种外部依赖都藏在一个我们自己定义的"可替换接口"后面。业务代码只认接口，不直接引用 `litellm`、`docker` 这类第三方库。用哪个具体实现由配置决定，启动时在"组装根"（`bootstrap.py`）统一装配。
- **功能内聚**：每个能力模块（如知识库、工作区）把自己的接口、具体实现、数据访问、中间件、提供给智能体的工具放在同一个模块里。模块之间只调用对方公开的服务方法，**不跨模块读写对方的数据表**。
- **不过度包装**：本身已是标准接口的东西直接用，不再套一层，包括 LangChain 的聊天模型对象、LangGraph 的对话存档接口、deepagents 的工作区（后端）协议。
- **只为基础设施建接口**：只有下表所列的外部依赖才定义可替换接口，其他地方不预设抽象（详见第 17 节开发规范）。

### 4.1 可替换接口清单

| 接口 | 负责什么 | v1 实现 | 以后可替换成 | 所在位置 |
|---|---|---|---|---|
| 模型网关 | 按版本名给出聊天模型对象；列出模型信息（上下文长度、价格、能力） | LiteLLM 网关 | 代码内直接调 LiteLLM 库、直连各厂商、OpenRouter 等 | `agents/main_agent/models/` |
| 向量化 | 文字转向量 | 经 LiteLLM 网关 | 本地向量模型、厂商直连 | `agents/main_agent/models/` |
| 工作区（文件 + 执行） | 读写和列出文件、上传下载、执行命令、杀进程 | 本地数据卷 + Docker 沙箱 | E2B、Daytona、Modal 等云沙箱（deepagents 有官方适配包）、每会话独立容器 | `agents/main_agent/workspace/` |
| 原文件存储 | 知识库文档的原始文件 | 本地磁盘（`workdata/knowledge/`） | S3 / MinIO 对象存储 | `agents/main_agent/knowledge/` |
| 知识检索 | 知识条目（文档片段、记忆等）的写入与语义 + 关键词混合检索 | pgvector + jieba | Qdrant、Milvus、Elasticsearch | `agents/main_agent/knowledge/` |
| 文档解析 | 各种文件转 Markdown | markitdown（微软开源的格式转换工具） | Docling、Unstructured、云端解析 | `agents/main_agent/knowledge/` |
| MCP 客户端 | 连接 MCP 服务、取出工具 | `langchain-mcp-adapters` | LangChain 内置的 `langchain.mcp`（目前测试版） | `agents/main_agent/integrations/` |
| 运行时（4 个替换点） | 事件总线、运行执行器、运行控制、任务队列 | 单进程内存版 | PostgreSQL 版（推荐）、Redis 版 | `backend/runtime/` |
| 智能体运行器 | 输入一次运行，输出**我们自己的**事件流；支持恢复、取消 | deepagents | 其他智能体框架 | `agents/main_agent/runtime/` |

说明：
- 只有 `agents/main_agent/runtime/` 知道 deepagents 的存在，其他模块只认我们自己的事件格式。
- 工作区把"文件"和"执行"合为一个接口，因为换成云沙箱时两者必须一起换。前端的上传、下载、产物列表也都走这个接口，不直接读本地磁盘。

### 4.2 用配置切换实现

```yaml
# config/app.yaml（节选）
adapters:
  model_gateway: litellm_proxy   # litellm_sdk | direct
  embedder: litellm_proxy
  workspace: docker_local        # e2b | daytona
  blob_storage: local_disk       # s3
  knowledge_index: pgvector      # qdrant
  doc_parser: markitdown
  mcp_client: mcp_adapters
  runtime: memory                # postgres | redis
```

新增一种实现 = 写一个实现类 + 在登记表里注册 + 配置里选中。

### 4.3 防止解耦随时间被破坏的三个机制

1. **契约测试**：每个接口一套共享测试，所有实现必须跑通同一套。
2. **依赖规则自动检查**：用 import-linter（检查模块间引用关系的工具）把规则写死，违反即检查失败（规则见 6.2）。
3. **组装集中**：所有"用哪个实现"的决定只出现在 `bootstrap.py`。

---

## 5. 整体架构与容器

```
┌────────────────── 浏览器（React 网页）──────────────────┐
│  会话列表  │  对话区  │  侧栏：待办 / 文件 / 审批 / 知识   │
└────────────────────────┬────────────────────────────────┘
                         │  普通接口请求 + 服务器单向推送（SSE）
┌────────────────────────▼──────────── backend 容器 ───────┐
│  接口层 → 运行管理 → agents（deepagents 智能体）          │
│                          ├─ 工作区文件 / 技能（按路径分流）│
│                          ├─ 知识库（文档 + 记忆）          │
│                          ├─ MCP 外部工具                  │
│                          └─ 子智能体                      │
└──────┬─────────────────────┬────────────────────┬────────┘
       │                     │                    │
┌──────▼──────┐      ┌───────▼──────┐     ┌───────▼──────┐
│ PostgreSQL  │      │ LiteLLM 网关 │     │   沙箱容器   │
│ + pgvector  │      │              │     │  （跑代码）  │
└─────────────┘      └───────┬──────┘     └──────────────┘
                             │
   Claude / OpenAI / Gemini / 国产模型（对话）   Ollama 容器（仅向量化）
```

### 5.1 docker compose 统一管理（D13）

**规则：所有第三方服务一律在 `deploy/docker-compose.yml` 中定义、构建和启动**，镜像写死具体版本标签和摘要（digest）。以后新增的服务（Redis、SearXNG、Langfuse、MinIO 等）同样加进这份文件。

| 服务 | 作用 | 启用方式 | 对外端口 |
|---|---|---|---|
| `postgres` | 带 pgvector 扩展的数据库。两个库：`agent`（业务数据、对话存档、知识库）和 `litellm`（网关自用） | 默认 | 仅 `127.0.0.1:5432`，便于调试 |
| `litellm` | 模型网关，直接挂载 `config/models.yaml` 作为模型版本清单 | 默认 | `127.0.0.1:4000`（含网关管理后台） |
| `sandbox` | 执行代码的隔离容器（本项目自建镜像），只接入内部专用网络 | 默认 | 不对外 |
| `backend` | FastAPI + agents（本项目自建镜像）。正式使用时也托管前端打包后的静态文件，打开 `http://localhost:8000` 即可 | 默认 | `127.0.0.1:8000` |
| `ollama` | **只做向量化**：运行 `qwen3-embedding:0.6b`，不跑对话模型。首次启动时由一个一次性初始化服务自动拉取该模型 | 默认 | 不对外 |
| `postgres-test`、`sandbox-test` | 自动化测试专用：数据库数据放内存盘，测完即弃 | compose 配置组 `test` | 仅 `127.0.0.1`，端口与正式服务错开 |

**为什么 Ollama 只做向量化**：Mac 上的 Docker 无法使用苹果芯片的显卡（Metal）加速，只能 CPU 运行。0.6B 向量模型在 CPU 上足够个人知识库使用（先行验证 V6 确认速度）；本地对话模型在 CPU 上太慢，不适合日常对话，所以 v1 不接。以后若需要本地对话模型，见第 19 节扩展路线（宿主机原生运行以获得显卡加速，届时作为 D13 的例外补一份决策记录）。

### 5.2 关键约定

- **backend 不直接操作 Docker**：沙箱做成常驻容器，按会话划分工作目录；单人使用，目录级隔离足够。
- **MCP 服务**：本地进程型（`npx` / `uvx` 启动的）作为 backend 容器内的子进程运行，所以 backend 镜像需要带 Node.js 和 uv；需要自建的 MCP 服务一律加进 compose；远程网络型直接连接。
- **只监听本机地址**，v1 不做登录，但所有表都带 `user_id`，以后加多用户不改表结构。
- **开发方式**：backend 在容器里运行，源码以目录挂载方式映射进去并开启自动重载；前端在本机用 Vite 开发服务器运行（Node 版本固定，见第 16 节），接口请求转发到 `localhost:8000`。沙箱始终只接内部网络。
- **密钥**：所有模型厂商的密钥、网关管理密钥、可选的访问令牌都放在根目录 `.env`（不进版本库），仓库里只提供 `.env.example` 模板。

---

## 6. 目录结构与依赖方向

### 6.1 目录结构

```
open_personal_agent/
├── pyproject.toml                   # 唯一的 Python 项目配置（uv 管理，直接依赖写精确版本）
├── uv.lock                          # uv 锁文件（全部间接依赖 + 哈希）
├── .python-version                  # 3.12
├── Makefile                         # 常用命令入口：make up / check / test / backup …
├── README.md                        # 一句话介绍、快速启动、指向 docs/
├── CLAUDE.md                        # 给 AI 编程助手的约定，指向开发规范技能
├── .env.example                     # 密钥模板
├── .claude/skills/dev-standards/    # 项目技能：开发、审查本项目代码时自动加载（见第 17 节）
│   └── SKILL.md
│
├── agents/                          # ① 智能体：不依赖 backend 和 frontend
│   ├── main_agent/                  # 主 agent，也是基础 agent
│   │   ├── runtime/                 # 对外总入口、组装 deepagents、运行/恢复/取消、
│   │   │                            #   事件协议定义、事件翻译、预算刹车、子智能体加载
│   │   ├── models/                  # 模型网关接口 + LiteLLM 实现、模型信息、向量化、换模型清理
│   │   ├── knowledge/               # 统一知识库：知识条目与文档、解析切块、混合检索、
│   │   │                            #   记忆（主动记、自动提取、召回、常驻条目）、知识工具
│   │   ├── workspace/               # 文件 + 执行接口、Docker 沙箱实现、产物检测
│   │   ├── integrations/            # MCP 客户端、审批规则
│   │   ├── usage/                   # 用量记录回调、费用计算、统计查询
│   │   └── bootstrap.py             # 组装根：按配置选实现，产出 agent 总入口对象
│   ├── prompts/                     # 系统提示词模板（system.md 等）
│   ├── skills/                      # 给智能体用的 SKILL.md 技能文件
│   ├── subagents/                   # 子智能体定义文件
│   └── tests/
│
├── backend/                         # ② 服务接口：只依赖 agents 的公开内容
│   ├── api/                         # 路由：会话、运行、审批、文件、知识库、模型、用量、设置
│   ├── runs/                        # 运行管理：后台执行、同会话互斥、断线补发、重启恢复
│   ├── runtime/                     # 运行时替换点：事件总线、执行器、运行控制、任务队列
│   ├── threads/                     # 会话信息、界面历史（事件表）
│   ├── jobs/                        # 后台任务调度：文档处理、记忆提取、标题生成
│   ├── main.py
│   └── tests/
│
├── frontend/                        # ③ 前端：只依赖 backend 的接口和推送协议
│   ├── package.json                 # 依赖一律写精确版本
│   ├── pnpm-lock.yaml               # pnpm 锁文件
│   ├── .nvmrc  .npmrc               # 固定 Node 版本；save-exact=true
│   ├── vite.config.ts
│   └── src/
│       ├── api/                     # 接口调用、推送订阅、自动生成的类型
│       ├── features/                # 对话 / 知识库 / 文件 / 用量 / 设置
│       └── components/
│
├── common/                          # 公共基础（只放与业务无关的东西）：日志、数据库连接池、
│                                    #   错误基类、ID 生成、时间工具、通用算法（如检索结果融合）
├── config/                          # 配置：读取代码 + 所有可编辑的配置文件
│   ├── settings.py                  # 把 yaml + 环境变量读成带类型校验的配置对象
│   ├── app.yaml                     # 各接口选哪个实现、默认模型、预算刹车、沙箱资源等
│   ├── models.yaml                  # LiteLLM 模型版本清单（网关容器直接挂载）
│   ├── mcp_servers.yaml             # MCP 服务清单
│   └── approval_rules.yaml          # 工具审批规则
│
├── assets/                          # 随仓库提交的静态资源：图标、中文字体、示例文件
├── deploy/                          # 部署：所有第三方服务与本项目镜像的定义
│   ├── docker-compose.yml
│   ├── backend.Dockerfile
│   └── sandbox/                     # 沙箱镜像 + 执行服务（独立小程序，自带最小依赖）
├── workdata/                        # 长期保存的个人数据（不进版本库，需要备份）
│   ├── workspace/<会话短ID>/        # 会话上传文件、智能体产物；随会话删除
│   ├── knowledge/                   # 知识库文档原始文件；直到你删除该文档
│   └── backups/                     # 定期备份；保留最近 N 份
└── docs/                            # 项目文档（见第 18 节）
```

补充说明：
- 顶层目录本身就是可直接导入的 Python 包，例如 `from agents.main_agent.knowledge import KnowledgeService`、`from config import settings`，不加前缀、不套 `src/`。
- `workdata/` 的位置可用环境变量 `WORKDATA_DIR` 改到别的磁盘。数据库数据不在 `workdata/`，而是在 Docker 数据卷中（Mac 上把数据库目录挂成本地文件夹性能差、易出权限问题），同样长期保存。
- 临时数据不进 `workdata/`：沙箱 `/tmp` 是内存盘，容器重启即清空；运行事件缓冲只在内存。

### 6.2 依赖方向（import-linter 强制检查）

```
frontend ──(HTTP 接口 + 推送协议)──→ backend ──→ agents ──→ common、config
                                        └─────────────────→ common、config
```

规则：
1. `common`、`config` 不依赖任何业务包；`common` 内不放业务逻辑。
2. `agents` 不得引用 `backend`。
3. `backend` 只得引用 agents 各模块对外公开的内容（`bootstrap.build_agent` 总入口、事件定义、各能力模块 `__init__.py` 导出的服务类型与数据结构），以及 `common`、`config`；不得深入引用 agents 的内部子模块。
4. `agents/main_agent/` 内各能力模块之间只得引用对方的公开服务（各模块 `__init__.py` 导出的内容）。
5. 以后在 `agents/` 下新增其他 agent 时，可依赖 `main_agent` 的能力，`main_agent` 不得反向依赖它们。

### 6.3 命名冲突预案

OpenAI Agents SDK 的导入名也是 `agents`。用 `import ... as ...` 改名**无法**解决：Python 先按名字 `agents` 查找模块，找到后才改名，同一进程只能有一个顶层 `agents`。本项目不使用该 SDK，所以照常使用 `agents` 目录名。如果以后确需使用，二选一：
1. 重命名本项目目录（编辑器重构一次完成，并更新 import-linter 配置）；
2. （推荐）把基于该 SDK 的 agent 作为独立进程运行，通过 HTTP 或 MCP 接入，两边都不改名。

### 6.4 agents 总入口（backend 只调用这些）

```python
agent = build_agent(settings)                       # bootstrap.py 产出

agent.run(thread_id, run_id, message, model) -> AsyncIterator[Event]
agent.resume(thread_id, run_id, decisions) -> AsyncIterator[Event]
agent.cancel(run_id)
agent.models      # 模型版本列表与信息
agent.knowledge   # 知识条目增删改查、常驻标记、检索；文档添加 / ingest(...) 处理 / 删除；
                  #   extract_memories(...) 记忆提取
agent.workspace   # 上传、下载、列出产物、删除会话工作区
agent.usage       # 用量统计查询
agent.utils       # generate_title(...) 等小能力
```

agents 只提供能力、不管调度：记忆提取、文档处理、标题生成何时执行，由 backend 的任务调度决定。

---

## 7. 智能体内核（agents/main_agent）

### 7.1 模型接入：按具体版本登记，全部走网关

`config/models.yaml` 就是网关的模型清单，一个具体版本一条记录，名字即版本名：

```yaml
# config/models.yaml（示例，价格数值仅作格式示意，以厂商官方价格为准）
model_list:
  - model_name: claude-opus-4-8              # 智能体和前端看到的名字 = 具体版本
    litellm_params:
      model: anthropic/claude-opus-4-8       # 厂商侧真实模型 ID
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info:
      max_input_tokens: 200000
      input_cost_per_token: 0.000015         # 新模型网关可能尚未内置价格，在此手动补上
      output_cost_per_token: 0.000075
  - model_name: claude-opus-4-6
    litellm_params: { model: anthropic/claude-opus-4-6, api_key: os.environ/ANTHROPIC_API_KEY }
  - model_name: embed-qwen3-0.6b             # 向量模型同样登记在此（D15）
    litellm_params: { model: ollama/qwen3-embedding:0.6b, api_base: http://ollama:11434 }
    model_info: { mode: embedding, output_vector_size: 1024 }
```

要点：
- **可选"最新版"快捷名**：可加 `claude-opus-latest` 指向某个具体版本，方便日常选择；统计中永远记录实际服务的具体版本。
- **请求的模型与实际模型分开记**：网关因故障自动切到备用模型时，用量表同时记录"请求的版本"和"实际回答的版本"。
- **启动时读取模型信息**：`build_agent` 时由模型网关接口向网关查询每个版本的上下文长度、价格、是否支持深度思考、是否能看图（`config/models.yaml` 修改后经 `POST /api/settings/reload` 重新读取）。前端模型下拉框、上下文压缩阈值、费用计算都用这份信息。
- **智能体侧客户端**：用 `langchain-litellm` 的 `ChatLiteLLM` 连接网关（LiteLLM 自家客户端对思考内容兼容性最好），不用通用的 `ChatOpenAI`（它会丢弃思考内容，Claude 深度思考 + 工具调用会报错）。具体连接方式在先行验证 V1 中确认。
- **上下文压缩阈值**：deepagents 按模型的 `max_input_tokens` 决定何时压缩，LiteLLM 模型对象没有这项信息，需由模型网关接口把读到的上下文长度填入模型对象的 profile。
- **提示缓存**：deepagents 自带的 Anthropic 缓存中间件只对官方 `ChatAnthropic` 生效，走网关用不上；改为在网关配置中为 Claude 系列开启缓存注入点（`cache_control_injection_points`）。
- **花费按会话归类**：每次调用都带上会话 ID 和运行 ID 作为网关元数据，方便在网关后台核对。
- **中途换模型**：对话历史是通用格式，换模型一般不丢上下文；但 Claude 的思考内容不能交给别家模型，由"换模型清理"中间件在模型变化时剥除这类内容。

### 7.2 智能体组装

```python
agent = create_deep_agent(
    model=models.get(model_version),          # 走网关的具体版本
    system_prompt=load_prompt("system.md"),
    tools=[*knowledge_tools, *mcp_tools],
    middleware=[TodoListMiddleware(),          # deepagents 0.7 默认移除了待办清单，手动加回
                KnowledgeContextMiddleware(),  # 常驻条目 + 相关记忆注入，见 8.3
                ModelSwitchCleanupMiddleware(),# 见 7.1
                BudgetBrakeMiddleware()],      # 见 10.8
    subagents=load_subagents("agents/subagents/"),
    backend=composite_backend,                 # 见 7.3
    skills=["/skills/"],
    interrupt_on=approval_rules,               # 见 7.5
    checkpointer=pg_saver,                     # AsyncPostgresSaver
    context_schema=AgentContext,               # user_id、thread_id、run_id、timezone、model
)
```

- 组装好的智能体按"模型版本 + 工具配置版本"缓存，不必每次请求重建；MCP 配置重新加载后自动失效重建。
- 不使用 deepagents 自带的文件式记忆（`memory=` 参数）和长期存储（`store=`），记忆统一由知识库承担（D10、D11）。
- deepagents 0.7 的注意点：基础提示词已为空（需自写）；工作区后端需传实例而非工厂函数；`FilesystemBackend` 默认开启虚拟路径模式；`write_file` 会覆盖已有文件。

### 7.3 文件按路径分流

智能体看到同一棵文件树，背后按路径分流（deepagents 的 `CompositeBackend`）：

| 路径 | 实际存在哪 | 生命周期 |
|---|---|---|
| 默认（即 `/workspace/<会话短ID>/...`） | **工作区后端**（文件 + 执行），作为 `CompositeBackend` 的默认后端：虚拟根 `/` 映射到 `WORKDATA_DIR`，所以 `/workspace/...` 落在 `workdata/workspace/...`；只允许读写本会话目录 `/workspace/<会话短ID>/`，其他路径一律拒绝 | 每个会话一个子目录，随会话删除 |
| `/skills/` | 项目 `agents/skills/` 目录，只读 | 随代码版本管理 |

> 为什么工作区必须是默认后端：deepagents 的 `CompositeBackend` 只把"执行命令"交给**默认后端**（路由出去的后端不能执行）。因此工作区后端做默认，`/skills/` 作为路由；不再使用 `StateBackend` 临时草稿区。工作区后端通过 LangGraph 的 `get_runtime()` 读取运行上下文（`AgentContext`）中的会话短 ID 来定位目录。

- 每个会话的工作目录是 `/workspace/<会话短ID>/`，系统提示词会告知智能体。会话短 ID 由 backend 创建会话时生成（形如 `c_8f3a2b9d`，便于模型准确引用），存于 `threads` 表；要执行的代码和产物都放在这里，放到 `/workspace/<会话短ID>/outputs/` 的文件会在前端显示为产物。

### 7.4 子智能体与技能

- **子智能体（v1 两个）**：
  - 通用助手：deepagents 自带。
  - 数据分析员：在沙箱里写代码、跑代码、处理 Excel / PDF，只把结论和产物路径交回主对话，避免大段执行输出占满主对话上下文。
- 每个子智能体是 `agents/subagents/` 下的一个定义文件（名称、职责、提示词、可用工具、所用模型版本），新增无需写代码；可给子智能体指定更便宜的模型版本。
- **技能**：采用 Anthropic 的 SKILL.md 格式（带说明头的 Markdown，按需加载全文），放在 `agents/skills/`。v1 先放一两个，例如"处理 Excel 的规范"。（注意区分：这是给智能体用的技能；给开发者用的规范技能在 `.claude/skills/`，见第 17 节。）

### 7.5 审批规则

`config/approval_rules.yaml` 为每个工具标记 `auto`（自动执行）或 `ask`（先问你）。默认：
- 只读工具自动执行：读文件、检索知识库、MCP 中的查询类工具。
- 有副作用的先问：MCP 中发消息、建日程、删除等工具。
- 沙箱执行代码、记住一条记忆默认自动：前者已隔离且断网，后者你可随时在知识库界面修改删除。

审批时四种选择：同意、修改参数后执行、拒绝、回复一句话让智能体调整做法。

### 7.6 系统提示词

自写 `agents/prompts/system.md`，包括：角色与行为原则、当前时间和时区、文件约定（工作目录、产物放 `outputs/`）、何时拆待办、何时派子智能体、何时记住信息、回答引用知识库出处的格式。常驻条目（个人画像）由 `KnowledgeContextMiddleware` 在每次调用模型前拼入。

### 7.7 用量统计

> 2026-10-19 起口径改为只算 token（第一轮优化设计 4.11）：只有"输入"（实际发给模型的全部输入，含命中缓存的部分）与"输出"两个数，后台不再计算、存储、返回费用，模型的价格只是资料。下文提到费用的地方以此为准。

- **记录位置**：一个"用量记录器"挂在每次运行配置的全局回调上，自动覆盖所有调用模型的地方——主对话、子智能体、上下文自动压缩（这项也花钱，最易漏）。
- **向量化调用**不经过聊天回调，由向量化接口的实现在每次调用后直接调用用量服务记录。
- **记录内容**：见 11.1 的 `llm_usage` 表。费用按记录当时的价格计算后存入，以后调价不影响历史。
- **展示**：每条回复下方显示本轮输入 / 输出 token 和费用（可展开每次调用明细）；会话侧栏显示本会话累计并按模型版本拆分；统计页按天、按模型版本看趋势。

---

## 8. 统一知识库（含记忆）

### 8.1 一个知识库，条目带标记

**只维护一个知识库**。知识库里的最小单位是"知识条目"，每条都带标记，记忆只是其中特殊的一类：

| 标记 | 取值 | 说明 |
|---|---|---|
| 种类 `kind` | `document_chunk`（文档片段）、`memory`（记忆） | 以后可扩展，如 `note`（手写笔记）、`web_page`（网页）、`conversation_summary`（对话摘要） |
| 类别标签 `tags` | 自由标签，如 `偏好`、`事实`、`人物`、`项目`、`工作`、`生活` | 一条可有多个标签，检索时可按标签过滤 |
| 常驻 `pinned` | 是 / 否 | **常驻条目 = 个人画像**：每次都拼进系统提示词，如"我在 某公司 做后端""回答简洁点"；总量设上限（默认约 2000 token），超出时前端提示精简 |
| 来源 `source` | `conversation`（对话中产生）、`document`（文档切块）、`manual`（你在界面手动添加） | 附带来源会话 / 运行 / 文档，便于追溯 |

文档本身（文件名、处理状态等）记在 `knowledge_documents` 表；文档切出的片段、记忆、以后的其他知识，全部是 `knowledge_items` 表里的条目，共用**一套向量化、一套混合检索、一套管理界面**。

| 原"四层记忆"中的概念 | 统一后对应 |
|---|---|
| 对话记忆 | 不属于知识库，仍是 deepagents 对话存档（快满时自动压缩） |
| 个人画像 | `pinned=是` 的知识条目 |
| 事实记忆 | `kind=memory` 的知识条目 |
| 知识库文档 | `kind=document_chunk` 的知识条目 + `knowledge_documents` |

### 8.2 知识怎么进来

- **对话中主动记**：智能体调用 `remember(content, tags, pinned?)` 工具（你说"记住……"或它判断值得记），前端提示"已记住：xxx"（推送 `memory.saved` 事件）。
- **会话后自动提取记忆**：每次运行结束后，backend 创建"记忆提取"任务，调用 `agent.knowledge.extract_memories(...)`：用便宜的模型读刚结束的对话，对每条信息判断"新增 / 更新已有 / 删除过时 / 忽略"，避免重复和矛盾。可在 `config/app.yaml` 关闭或更换模型，费用计入用量表（调用方"记忆提取"）。
- **上传文档**：

```
上传 → 原文件存 workdata/knowledge/，knowledge_documents 记一行（状态：待处理）
     → backend 创建处理任务 → agent.knowledge.ingest(doc_id)：
         解析为 Markdown（markitdown）
         → 按标题结构切块（每块约 600 token，重叠约 80 token）
         → 经网关向量化 → jieba 分词 → 写入 knowledge_items（kind=document_chunk）
     → 状态：完成 / 失败（失败可重试）
```

- **手动添加**：在知识库界面直接写一条知识或记忆，可打标签、设常驻。

### 8.3 知识怎么用

- **常驻条目**：`KnowledgeContextMiddleware` 在每次调用模型前，把全部常驻条目拼入系统提示词。
- **相关记忆自动召回**：同一中间件在每条新用户消息到来时将其向量化，在 `kind=memory` 的条目中查出相似度超过阈值（初始值 0.75，后续按实际效果调整）的前 5 条，作为一段"相关记忆"注入上下文。文档片段不自动召回（量大，避免干扰），由智能体按需检索。
- **混合检索**：向量检索（找意思相近）与关键词检索（找人名、型号、报错码等精确词）两路结果，按"倒数排名融合"合并排序。中文关键词检索：PostgreSQL 默认不会给中文分词，在 Python 中用 jieba 先分词再存入全文检索字段，无需自建带中文分词插件的数据库镜像。
- **智能体工具**（只有一个检索工具）：
  - `search_knowledge(query, kinds?, tags?, top_k?)`：统一检索所有知识，可按种类、标签过滤；文档片段结果带文档名、页码或章节路径。
  - `read_document(document_id, around_item_id, window)`：读取文档片段前后原文。
  - `remember(content, tags, pinned?)`：记住一条知识。
- 回答引用出处，前端点击可打开原文定位。
- **会话附件与知识库文档的区别**：会话附件放在本会话 `uploads/`，供当场处理；知识库文档长期保存、所有会话可检索。会话附件可一键"同时加入知识库"。

### 8.4 你完全可控

知识库界面统一管理所有知识：按种类（全部 / 记忆 / 文档）、标签、常驻筛选与搜索；可修改、删除任一条目；可给任一条目设或取消"常驻"；文档可删除、重新处理。

### 8.5 向量模型

- **默认（D15）**：千问 Qwen3 向量模型 0.6B（`qwen3-embedding:0.6b`），由 compose 中的 `ollama` 服务提供，经网关调用；免费、知识与记忆不出本机、中文表现强；在 CPU 上运行，个人知识库规模足够。
- **统一 1024 维**：所有向量固定 1024 维。pgvector 的向量索引上限为 2000 维，1024 维是各主流向量模型都能输出的尺寸。
- **查询与文档区别对待**：Qwen3 向量模型对"查询"加一句任务说明前缀效果更好（官方称可提升约 1%～5%），文档片段不加。前缀写在知识模块的检索实现里。
- **可替换**：备选包括更大的 `qwen3-embedding:4b`（更准、更慢）、`bge-m3`，或云端的百炼 `text-embedding-v4`、OpenAI `text-embedding-3-small`（都可输出 1024 维）。换模型只需改 `config/models.yaml` 与 `config/app.yaml`，再运行"重建向量"脚本；每个知识条目都记录所用向量模型。
- **说明**：只有向量化在本机完成；记忆提取、标题生成等需要对话模型的任务，使用云端的便宜模型版本（在 `config/app.yaml` 中指定）。

---

## 9. 代码执行与文件

### 9.1 运作方式

**读写文件由 backend 直接做，只有执行命令交给沙箱**；两个容器挂载同一个工作区数据卷。

```
backend 容器 ──挂载──┐
                     ├── workdata/workspace/<会话短ID>/{uploads, outputs, ...}
沙箱容器     ──挂载──┘   （在沙箱内挂载为 /workspace）

智能体写文件   → backend 直接写入数据卷
智能体执行命令 → 交给沙箱执行服务 → 在 /workspace/<会话短ID>/ 下运行 → 返回输出
```

- **智能体看到的虚拟路径 = 沙箱里的真实路径**（都是 `/workspace/<会话短ID>/...`）；backend 一侧由工作区实现把虚拟路径映射到 `WORKDATA_DIR/workspace/` 下的实际位置。
- **实现**：在 deepagents 本地文件后端（`FilesystemBackend`）基础上增加"执行命令"能力（**显式继承** deepagents 的 `SandboxBackendProtocol`——它是抽象基类，只实现方法而不继承时 deepagents 不会提供执行能力；实现 `id` 属性与 `execute()`），命令转发给沙箱；该后端作为 `CompositeBackend` 的默认后端（见 7.3），deepagents 随即自动为智能体提供 `execute` 工具。
- 会话短 ID 通过 `get_runtime().context` 获取（先行验证 V4 确认）。

### 9.2 安全边界

| 措施 | 做法 |
|---|---|
| 不能上外网 | 只接入内部专用网络（compose 中 `internal: true`），只能与 backend 通信；可在配置中开启联网以便 `pip install` |
| 降权运行 | 非 root 用户；除 `/workspace` 与 `/tmp` 外文件系统只读 |
| 资源上限 | 默认 2 核 CPU、2GB 内存，限制最大进程数 |
| 命令超时 | 默认 120 秒，超时杀掉整个进程组 |
| 输出截断 | 超过 30KB 的输出写入文件，告诉智能体自行读取 |
| 内部认证 | backend 调用执行服务时携带共享密钥 |

**预装**（版本同样写死在沙箱镜像的依赖文件中）：pandas、numpy、matplotlib、seaborn（**含中文字体**，否则图中中文显示为方框）、openpyxl、python-docx、python-pptx、pymupdf、pillow。LibreOffice（格式互转）体积大，作为可选镜像变体。

### 9.3 文件进出

- **上传**：对话中拖入的文件存到 `/workspace/<会话>/uploads/`，智能体收到提示"用户上传了 uploads/xxx"；默认单文件上限 100MB。**图片**若当前模型能看图，同时作为图片内容发给模型。
- **产物**：每次写文件或执行命令后检查 `outputs/` 的新增或改动，有则推送 `file.created` 事件，前端显示产物卡片。
- **预览**：图片直接显示；CSV / Excel 显示前若干行表格；PDF 用浏览器阅读器；Markdown 和代码渲染或高亮；HTML 放在隔离的内嵌框；其他提供下载。下载接口校验路径，防止 `../` 越界。
- **登记与清理**：上传与产物记入 `workspace_files` 表；删除会话时连同工作目录一起删除。

---

## 10. 运行与实时推送

### 10.1 基本概念

- **会话**：一个对话窗口，对应 deepagents 的一个对话存档（thread_id 由 backend 生成）。
- **运行**：一次"发消息 → 智能体处理完"的全过程。

```
排队 → 运行中 ──→ 完成
          │  ├──→ 失败
          │  └──→ 已取消
          ↓
       等待审批 ──（你做出决定）──→ 运行中（同一次运行继续）
```

状态值依次对应 `queued`（排队）、`running`（运行中）、`interrupted`（等待审批）、`completed`、`failed`、`cancelled`。同一会话同一时间只能有一个处于"排队 / 运行中 / 等待审批"的运行；运行中输入框变"停止"按钮，有待审批时须先处理审批。

### 10.2 一次运行的流程

```
1. 前端发送消息（可附文件、指定模型版本）→ backend 建运行记录，立即返回运行 ID
2. 运行管理在后台启动：调用 agent.run(...)，内部订阅 deepagents 输出流
   （stream_mode = messages / updates / custom，subgraphs=True 以包含子智能体）
3. agents 的事件翻译器把原始输出翻译成我们的事件
4. backend 给每个事件加递增序号，同时送往：
     ├─ 内存事件缓冲 → 实时推给浏览器
     └─ run_events 表 → 每 200 毫秒批量写入，逐字小片段合并后存储
5. 前端订阅该运行的推送，边收边渲染
6. 运行结束 → backend 创建后续任务：记忆提取；首轮对话后还有标题生成
```

**界面历史与模型上下文分开存（D7）**：界面历史读 `run_events` 表，模型上下文读 deepagents 对话存档。前端只有一套渲染逻辑：实时显示是"边收事件边处理"，打开历史会话是"把存好的事件按顺序重放"。

### 10.3 推送事件格式

所有事件共用一个信封：

```json
{ "seq": 42, "run_id": "...", "type": "tool.started",
  "agent_path": ["main", "数据分析员#1"], "ts": "...", "data": { } }
```

| 事件 | 含义 |
|---|---|
| `run.started` | 运行开始，所用模型版本 |
| `message.delta` | 回答文字逐字输出 |
| `thinking.delta` | 思考过程逐字输出（前端默认折叠） |
| `tool.started` / `tool.finished` | 开始调用工具（名称、参数）/ 结束（状态、结果摘要） |
| `subagent.started` / `subagent.finished` | 派出子智能体 / 交回结果 |
| `todos.updated` | 待办清单变化（完整清单） |
| `file.created` | 产生新文件 |
| `memory.saved` | 记住一条新记忆（知识条目） |
| `approval.required` | 需要审批：待审批操作、可选处理方式；预算刹车也通过它暂停 |
| `usage` | 一次模型调用的用量（输入、输出、缓存读写、思考 token、费用） |
| `run.finished` | 运行结束：状态、错误信息、本次用量合计 |

- `agent_path` 由 deepagents 输出流中的命名空间推导，前端据此把子智能体内部事件嵌套显示。
- 每 15 秒发一次心跳，防止连接被中间环节掐断。
- 事件定义（pydantic 模型）放在 `agents/main_agent/runtime/`；backend 原样转发，只加 `seq`；前端类型由脚本自动生成。

### 10.4 断线续传

使用浏览器自带的 SSE 连接（`EventSource`），断线自动重连并带上最后收到的序号（`Last-Event-ID`）。backend 先补发其后的事件（优先内存缓冲，没有则查 `run_events`），再接着实时推送。刷新页面、关浏览器再开、网络抖动，运行都不中断、界面不漏内容。

### 10.5 审批暂停与恢复

1. 智能体调用标记为 `ask` 的工具时，deepagents 自动暂停并存档状态。哪些工具要先问，按会话的审批权限（每次先问 / 只问执行命令 / 跳过所有审批，D23）；一次运行开始时定下档位，审批后继续也沿用它。
2. 推送 `approval.required`，运行状态改为 `interrupted`，后台任务结束，暂停期间不占资源。
3. 你在审批卡片上做出决定，前端提交到 `POST /api/runs/{id}/resume`，智能体在同一次运行里从存档处继续（底层为 `Command(resume={"decisions": [...]})`），事件序号接着往下编。

状态存在数据库，几小时后再审批、服务重启后再审批都可以。

### 10.6 取消

点"停止"后取消后台任务；若沙箱有命令在跑，同时让沙箱杀掉对应进程组。被打断的工具调用"有调用无结果"，deepagents 自带的 `PatchToolCallsMiddleware` 会在下次运行时自动补上结果，对话不会因此出错。

### 10.7 错误处理

| 情况 | 处理 |
|---|---|
| 模型调用失败 | 网关先自动重试、切换备用模型；仍失败才结束运行，给出看得懂的原因（如"claude-opus-4-8 触发频率限制"）并提供"重试"；已输出的部分连同实际原因写进对话存档，说"继续"能接着做（D23）。额度用完时提示充值后说"继续" |
| 工具出错 | 不算运行失败，错误作为工具结果交给智能体自行调整 |
| 服务重启时有运行未跑完 | 启动时把 `queued` / `running` 的运行标记为 `failed`（原因"服务重启中断"），前端提供重试；`interrupted` 的运行不受影响 |
| 文档处理 / 记忆提取失败 | 任务记录错误并按次数重试；文档状态显示"失败"并可手动重试 |

### 10.8 预算刹车（已取消，D23）

> 2026-10-19 起去掉：不再按调用次数暂停；模型额度用完时结束这次运行并提示（见 10.7）。以下为原设计，仅作记录。

deepagents 默认的步数上限约为一万，过于宽松。`BudgetBrakeMiddleware` 按每次运行限制：默认最多调用模型 100 次、花费不超过 2 美元（`config/app.yaml` 可调）。触达上限时以一次特殊审批的形式暂停（`approval.required`），由你选择"继续"（再追加一份同样的额度：100 次 / 2 美元）或"停止"。

### 10.9 单进程约束与替换点（D9）

v1 的 backend 以单进程运行。妨碍多进程的 5 样东西及处理：

| 替换点 | v1 实现 | 多进程实现 | 现在的准备 |
|---|---|---|---|
| ① 同会话互斥 | **数据库唯一索引**：同一会话只能有一条 `queued` / `running` / `interrupted` 的运行 | 不用改 | 天然支持多进程 |
| ② 事件推送（发布、按序号订阅、补发） | 内存缓冲 + `run_events` 表 | PostgreSQL 消息通知（推荐）或 Redis 消息流 | "事件总线"接口 |
| ③ 取消信号 | 直接取消本进程任务 | 经事件总线广播，持有该运行的进程执行取消 | "运行控制"接口 |
| ④ 运行在哪执行 | backend 进程内后台任务 | 独立工作进程从 `runs` 表抢任务（行锁 + 跳过已锁行），backend 只建任务和推送 | "运行执行器"接口 |
| ⑤ 后台任务 | 进程内异步任务 + `jobs` 表 | 同④，工作进程抢任务 | "任务队列"接口 |

保障：真实数据以数据库为准，内存只做加速；前端续传靠序号而非连接粘滞；四个接口各有契约测试。以后切换的工作量：2～3 个新实现类（约 300 行）+ 一个 `python -m backend.worker` 启动命令（作为 compose 新服务）+ 配置 `runtime: postgres`。例外：跨多台机器还需把工作区换成共享存储；各进程的智能体缓存与 MCP 连接各存一份，MCP 配置变更时经事件总线通知刷新。

---

## 11. 数据表

所有表带 `user_id`（v1 固定为一个值）。表结构变更用一套 Alembic（Python 常用的数据库迁移工具）统一管理，每张表的定义放在所属模块中；deepagents 自带的对话存档表由其 `setup()` 自行创建。

### 11.1 agents 拥有的表

| 表 | 主要字段 |
|---|---|
| `knowledge_documents` | id、标题、文件名、类型、大小、原文件路径、状态（待处理 / 处理中 / 完成 / 失败）、错误信息、条目数、创建时间 |
| `knowledge_items` | id、种类 `kind`、标签 `tags`（数组）、常驻 `pinned`、内容、所属文档（可空）、序号、章节路径、页码、来源 `source`、来源会话、来源运行、token 数、向量、向量模型、分词检索字段、创建时间、更新时间 |
| `workspace_files` | id、会话、路径、来源（上传 / 产物）、类型、大小、创建时间 |
| `llm_usage` | id、会话、运行、调用方（主智能体 / 子智能体名 / 自动压缩 / 记忆提取 / 知识向量化 / 标题生成）、请求的模型版本、实际的模型版本、输入 token、输出 token、缓存读取 token、缓存写入 token、思考 token、费用、耗时、时间 |
| deepagents 自带 | 对话存档相关表（checkpoints 等） |

`knowledge_items` 上建：向量索引（HNSW）、全文检索索引、`(kind, pinned)` 与 `tags` 的过滤索引。

### 11.2 backend 拥有的表

| 表 | 主要字段 |
|---|---|
| `threads` | id、会话短 ID（唯一）、标题、默认模型版本、所用 agent（默认 `main_agent`）、是否归档、创建时间、更新时间 |
| `runs` | id、所属会话、状态、模型版本、用户输入（消息 + 附件引用）、开始时间、结束时间、错误、用量合计；部分唯一索引：`(thread_id) WHERE status IN ('queued','running','interrupted')` |
| `run_events` | 运行 ID、序号、事件类型、内容（JSON）、时间；主键（运行 ID, 序号） |
| `jobs` | id、任务类型、参数、状态、重试次数、最后错误、计划时间、加锁时间 |

---

## 12. 接口与本机安全

### 12.1 接口列表（均在 `/api` 下）

> 2026-10-19 起：用量接口不再返回费用；会话加 `PATCH /threads/{id}` 改标题、模型、审批权限（D23）；设置接口加 `/settings/app`（设置表，D22）与 `/settings/files`；MCP 目录接口已去掉。下表为原设计，以代码与生成的接口类型为准。

| 分组 | 接口 |
|---|---|
| 会话 | `GET/POST /threads`；`PATCH /threads/{id}`（改名、换默认模型、归档）；`DELETE /threads/{id}`（同时删除工作区）；`GET /threads/{id}/history`（界面历史） |
| 运行 | `POST /threads/{id}/runs`（发消息，返回运行 ID；已有运行时返回 409）；`GET /runs/{id}/events`（推送订阅，支持续传）；`POST /runs/{id}/resume`（审批决定）；`POST /runs/{id}/cancel` |
| 文件 | `POST /threads/{id}/files`（上传，可选同时加入知识库）；`GET /threads/{id}/files`；`GET /threads/{id}/files/{fid}/content`（下载或预览） |
| 知识库 | `GET /knowledge/items?kind=&tags=&pinned=&q=`（筛选与检索）；`POST /knowledge/items`（手动添加）；`PATCH /knowledge/items/{id}`（改内容、标签、常驻）；`DELETE /knowledge/items/{id}`；`POST/GET /knowledge/documents`；`GET/DELETE /knowledge/documents/{id}`；`POST /knowledge/documents/{id}/reprocess` |
| 模型 | `GET /models`（版本、能力、价格） |
| 用量 | `GET /usage/summary`（按模型版本 / 按天 / 按会话汇总）；`GET /threads/{id}/usage`；`GET /runs/{id}/usage`（每次调用明细） |
| 设置 | `GET /settings/mcp-servers`、`GET /settings/approval-rules`（只读）；`POST /settings/reload`（重新加载配置）；`GET /health` |

前端类型自动生成：普通接口从 FastAPI 自动产出的接口文档（OpenAPI）生成；推送事件从 agents 的事件定义生成。

### 12.2 本机安全防护（已作废，D23）

> 2026-10-19 起删除本节全部防护（用户两次确认后接受风险，见 D23）：端口只绑本机，以后由第三方防护补上。以下为原设计，仅作记录。

只监听本机地址不等于安全：浏览器里打开的任何网页都可能向 `localhost:8000` 发请求，而本服务能执行代码、能调用 MCP。v1 必须做到：
1. **校验 Host 请求头**，只接受 `localhost` / `127.0.0.1`，防止 DNS 重绑定攻击。
2. **跨域只放行自己的前端来源**。
3. **写操作只接受 JSON 请求体**（文件上传接口额外要求自定义请求头），迫使浏览器先发预检请求，第三方网页无法直接伪造。
4. **可选访问令牌**，在 `.env` 中配置。

另外：避开曾被投毒的 litellm 1.82.7 / 1.82.8；按 `langgraph-checkpoint-postgres` 的建议设置 `LANGGRAPH_STRICT_MSGPACK=true`。依赖与镜像的版本固定见第 16 节。

---

## 13. 前端

### 13.1 技术选型

- React + Vite + TypeScript；Tailwind 4；Markdown 渲染用 assistant-ui 自带的 Markdown 组件（基于 react-markdown，支持表格、数学公式、代码高亮）；普通接口数据用 TanStack Query；包管理 pnpm，版本固定见第 16 节。
- **对话组件：assistant-ui（D16）**，只用不带样式的基础组件（`@assistant-ui/react`、`@assistant-ui/react-markdown`）。通用组件（按钮、对话框、下拉框等）按 shadcn/ui 的写法放在本项目源码里。所有样式都来自本项目主题（13.2）。
- **运行实时状态由本项目的事件处理器管理**（13.4），不交给 assistant-ui。

**assistant-ui 的接入方式：**
- 用它的"外部数据源"接法（`useExternalStoreRuntime`）：消息和运行状态由本项目的事件处理器维护，经一个转换函数映射成 assistant-ui 的消息格式。推送协议、事件处理器及其测试保持不变。
- 只在 `frontend/src/components/chat/` 这一层引用 assistant-ui，其他代码不直接依赖它；以后要换实现，只改这一层。
- 版本写死（当前 0.15.28，尚未到 1.0）；升级前要跑全部前端测试和端到端检查。
- 映射关系：

| 本项目 | assistant-ui |
|---|---|
| 用户消息 | `user` 消息 |
| 两条用户消息之间的回答与工具调用 | 一条 `assistant` 消息，内容依次为文本片段、工具调用片段 |
| 运行失败 | 消息状态"未完成"并带错误原因 |
| 深度思考过程（M1） | 思考片段，用思考过程组件展示 |
| 子智能体（M1） | 工具调用片段里的嵌套消息 |
| 审批暂停（M4） | 工具调用片段的审批 / 中断字段 |
| 会话附件（M2） | 附件 |

- 验证结论（2026-10-13，一次性验证，代码不保留）：与本项目的 React 19、Vite 8、Tailwind 4、严格类型检查和 ESLint 配置兼容；流式回答、工具卡片、错误、停止均正常；切换主题不需要改组件；自带中文输入法处理（包括 `keyCode 229`）。代价：前端打包后体积从 417KB（压缩后 128KB）增加到 738KB（压缩后 220KB）。

### 13.2 设计系统与主题（参考 Hermes Agent）

**原则：一套代码，主题只换样式。** 组件只使用语义化样式类，具体的颜色、字体、圆角、紧凑度都由主题决定。

```
主题文件（frontend/src/themes/<主题名>.ts，纯数据）
  ├ 基础色：background（背景）、primary（主色，兼作文字与强调）—— 浅色、深色各一组
  ├ 固定色：danger（危险）、success（成功）、warning（警告）
  ├ 字体：正文字体、等宽字体、基准字号、行高
  └ 布局：圆角、紧凑度
        ↓ 主题切换器把它们写到 <html> 上（data-theme、data-mode 属性与 CSS 变量）
令牌层（frontend/src/styles/tokens.css）：用 color-mix 由基础色派生出 card、secondary、muted、accent、border 等
        ↓ Tailwind 的 @theme inline 映射
语义样式类：bg-background、bg-card、text-foreground、text-muted-foreground、border-border、bg-primary …
        ↓
组件（只用语义样式类）
```

- **派生规则**（参考 Hermes）：card、secondary、muted、accent、border 分别由主色按 4% / 6% / 8% / 10% / 约 14% 的比例混入背景得到；正文颜色是主色，次要文字是主色的半透明。具体比例实现时按观感微调。
- **默认主题（v1 唯一主题）**：深色科技感，参考 Hermes 的 "Hermes Teal"。
  - 深色版：背景 `#041c1c`（深墨绿），主色 `#ffe6cb`（暖奶油）。
  - 浅色版：背景 `#fbf7f0`（暖白），主色 `#0b3b3a`（深墨绿）。
  - 字体用系统字体，基准字号 15px，行高 1.55，圆角 0.5rem，紧凑度"舒适"。
- **深浅色**：默认跟随系统，可在设置里固定为深色或浅色。选择保存在浏览器本地；页面加载前由 `index.html` 里的一小段内联脚本先应用，避免刷新时闪一下。
- **新增主题**：新增一个主题文件，并在主题登记表里登记一行，组件不用改。
- **其他也读主题变量**：代码高亮、Markdown 排版、用量图表配色（输入、输出 token 两种系列色）都读同一套变量。
- **两条自动检查（放进 `make check`）：**
  1. **主题契约测试**：每个主题（深浅两版）都必须提供全部必需字段。
  2. **写死颜色检查**：扫描组件代码，一旦出现 `bg-blue-600`、`text-gray-900`、`#1a2b3c` 这类具体颜色就报错（主题文件和令牌文件除外）。

### 13.3 主界面布局（参考 Hermes 与 deep-agents-ui）

整体布局参考 Hermes 的聊天页：左侧会话侧栏，中间对话区，顶部显示状态。智能体专属的面板（待办、文件、子智能体）参考 LangChain 的 deep-agents-ui。

```
┌──────────┬───────────────────────────────────────┬──────────────┐
│ 会话列表   │ 顶栏：标题 · 模型版本选择 · 本会话用量         │ 侧栏（可收起） │
│ 🔍 搜索    │───────────────────────────────────────│ [待办][文件]  │
│ ＋ 新会话  │  👤 用户消息                               │ [知识][用量]  │
│           │  💭 思考过程（默认折叠）                      │              │
│ 今天       │  🔧 工具调用卡片（参数/结果可展开）             │  ☑ 读取数据   │
│  · ……     │  🤖 子智能体卡片（内部步骤嵌套显示）            │  ◻ 生成图表   │
│ 昨天       │  ⚠️ 审批卡片：同意 / 修改 / 拒绝 / 回复          │              │
│  · ……     │  📎 产物卡片：图片/表格预览、下载                │  📄 report.xlsx│
│           │  💬 回答（Markdown + 引用出处）· 本轮用量        │              │
│           │───────────────────────────────────────│              │
│ ⚙ 设置    │ [📎附件] 输入框……          [模型▾] [发送/停止] │              │
└──────────┴───────────────────────────────────────┴──────────────┘
```

其他页面：
- **知识库**：按种类（全部 / 记忆 / 文档）、标签、常驻筛选与搜索；编辑、删除、设常驻；上传文档、查看处理状态；"常驻"视图即个人画像，显示总 token 占用。
- **用量统计**：按天、按模型版本的输入 / 输出 / 缓存 / 费用趋势。
- **设置**：外观（深浅色，以后加主题选择）、模型列表、MCP 服务、审批规则（只读 + 重新加载）。

### 13.4 核心模块

- **事件处理器**：输入当前状态和一个事件，输出新状态。实时显示与历史重放共用。用录制的真实事件序列做单元测试，重点覆盖。
- **转换函数**：把事件处理器的状态转换成 assistant-ui 的消息格式（13.1 的映射表），有单元测试。

以桌面浏览器为主，窄屏可用。

### 13.5 一键启动（正式使用的方式）

- backend 镜像采用多阶段构建：第一阶段用 Node 打包前端，第二阶段把打包结果复制进后端镜像。
- FastAPI 在 `/` 提供前端页面，在 `/api` 提供接口；访问未知路径时返回前端首页，以支持前端路由。
- 正式使用：只需执行 `make up`，然后打开 `http://127.0.0.1:8000`。
- 开发前端时仍可用 `make web`（热更新，`/api` 转发到 8000）。

---

## 14. 测试策略

| 层次 | 测什么 | 怎么测 |
|---|---|---|
| 单元测试 | 事件翻译、预算刹车、切块、检索合并排序、费用计算、前端事件处理器等 | pytest；前端 Vitest。事件翻译与事件处理器用录制的真实事件序列做测试数据 |
| 契约测试 | 每个可替换接口（模型网关、工作区、知识检索、文档解析、MCP 客户端、运行时 4 个替换点） | 每个接口一套共享测试，所有实现跑同一套 |
| 智能体流程测试 | 调工具 → 审批暂停 → 恢复 → 取消 → 换模型 → 上下文压缩 → 预算刹车 | 用 LangChain 自带的按剧本回复的假模型，确定且零费用 |
| 集成测试 | 数据访问、对话存档、知识检索、沙箱执行 | 连接 compose `test` 配置组中的 `postgres-test`、`sandbox-test`（D13：测试用服务也由 compose 管理） |
| 接口测试 | 409 并发保护、断线续传、审批恢复、取消、Host 与跨域校验 | httpx 直接调用 FastAPI |
| 端到端测试 | 发消息、看到工具卡片、审批、下载产物 | Playwright 驱动浏览器，后端接假模型 |
| 真实模型冒烟测试 | 各家模型经网关的深度思考、工具调用、逐字输出、用量 | 单独标记、默认不跑（花钱），手动触发 |

静态检查：ruff（格式与风格）、mypy 严格模式（类型）、import-linter（依赖方向）；前端 ESLint、Prettier、`tsc --noEmit`，以及 13.2 的主题契约测试与写死颜色检查。统一由 `make check` 一条命令执行；建立 git 仓库后挂到提交前检查。

---

## 15. 先行验证清单（写正式代码之前）

任何一项失败，先调整设计再往上搭：

| 编号 | 验证内容 | 失败时的退路 |
|---|---|---|
| V1 | 经网关：Claude 开启深度思考 + 连续多轮工具调用 + 逐字输出，不报错，思考内容正确回传 | 仅让 Claude 走网关提供的 Anthropic 原生格式接口（`/v1/messages`），智能体侧对 Claude 用 `ChatAnthropic(base_url=网关)` |
| V2 | 逐字输出模式下，每次调用的输入、输出、缓存读写、思考 token 完整返回 | 用量记录器在运行结束后按网关的请求日志补齐缺失字段 |
| V3 | 中途换模型：Claude → GPT / Gemini / 国产，剥除思考内容后对方正常续聊 | 换模型时在发送前做更彻底的消息格式规整 |
| V4 | 工作区后端作为 `CompositeBackend` 默认后端时：能通过 `get_runtime().context` 拿到会话短 ID 定位目录；越界路径被拒绝；`execute` 工具出现且调用到该后端；`/skills/` 路由可读 | 若 `get_runtime()` 在执行线程中不可用，则在组装时按会话构建后端实例（每次运行一个） |
| V5 | 子智能体事件在输出流中的命名空间稳定，能可靠推导 `agent_path`（实施计划阶段已离线确认：子智能体片段的 `ns` 为 `("tools:<调用ID>",)`；`task` 工具的结果以 ToolMessage 出现在主命名空间，翻译时只取 `updates` 中的工具结果即可避免重复） | 在子智能体工具调用处记录映射关系，由事件翻译器补全归属 |
| V6 | 经网关调用容器内 Ollama 的 `qwen3-embedding:0.6b`：返回 1024 维；CPU 下单条查询向量化耗时与批量处理文档片段的速度可接受（目标：单条查询 < 300 毫秒，100 页 PDF 约 300 个片段在 1 分钟内处理完）；向量化调用的 token 数能拿到 | 速度不达标先换云端向量模型（百炼 `text-embedding-v4` 或 OpenAI `text-embedding-3-small`，同为 1024 维），记入决策记录 |

---

## 16. 依赖与版本管理（D12）

### 16.1 Python（uv）

- Python 版本由 uv 管理，写在 `.python-version`（3.12）。
- `pyproject.toml` 中**所有直接依赖写精确版本**（`==`）；开发工具（pytest、ruff、mypy、import-linter 等）放在 `dev` 依赖组，同样写精确版本。
- `uv.lock` 锁定全部间接依赖及其哈希；安装一律 `uv sync --locked`，锁文件与 `pyproject.toml` 不一致时直接报错。
- 新增或升级依赖：`uv add 包名==版本`，并在 `docs/changelog.md` 记录升级原因。
- 沙箱镜像的预装库同样写精确版本（独立的依赖文件）。

### 16.2 前端（pnpm）

- Node 版本写入 `.nvmrc` 和 `package.json` 的 `engines`；pnpm 版本写入 `package.json` 的 `packageManager` 字段，由 Node 自带的 corepack 自动使用对应版本。
- `package.json` **所有依赖写精确版本**（不带 `^`、`~`），`.npmrc` 设置 `save-exact=true` 保证新增时也是精确版本。
- `pnpm-lock.yaml` 锁定全部间接依赖；安装一律 `pnpm install --frozen-lockfile`。

### 16.3 Docker 镜像

compose 中所有第三方镜像写"具体版本标签 + 摘要（digest）"；本项目自建镜像（backend、sandbox）的基础镜像同样固定。

### 16.4 初始版本

M0 时选定各依赖当时的最新稳定版写入上述文件（附录 A 为 2026-10-09 的调研基线），此后只通过显式升级变更。

---

## 17. 开发规范与架构规范（D14，独立成文）

### 17.1 形式：一份规范文档 + 一个项目技能

| 文件 | 内容 |
|---|---|
| `docs/development/architecture.md` | **架构规范**：三大块与依赖方向、模块结构模板（每个能力模块里放什么）、可替换接口的写法模板（接口 + 实现 + 登记 + 契约测试的代码骨架）、数据归属规则、新增模块 / 新增实现 / 新增接口路由 / 新增前端功能的步骤清单 |
| `docs/development/coding-standards.md` | **编码规范**：Python、TypeScript / React、SQL 与迁移、配置、注释与文档、命名 |
| `docs/development/testing.md` | **测试规范**：测试分层、何时写哪种测试、假模型用法、契约测试写法、如何用 compose 起测试服务 |
| `.claude/skills/dev-standards/SKILL.md` | **项目技能**：在本项目中开发、审查、重构代码时自动加载。正文只放核心要点和检查清单，细节指向上面三份文档——**规范只维护一份**，技能不重复抄写 |
| `CLAUDE.md` | 声明"开发任何功能前先加载 `dev-standards` 技能"，并列出常用命令 |

### 17.2 三条原则

1. **官方规范优先**：
   - Python：PEP 8（代码风格）、PEP 257（文档字符串）、PEP 484 及 typing 官方文档（类型标注）；ruff 默认规则集加选定规则、mypy 严格模式。
   - FastAPI：按官方文档推荐写法（`APIRouter` 分组、依赖注入、`lifespan` 管理启动与关闭、pydantic v2 定义数据结构）。
   - LangChain / LangGraph / deepagents：按官方 API 与文档的用法，不自造轮子。
   - TypeScript：严格模式；React：遵循官方"React 规则"与 Hooks 规则（eslint-plugin-react-hooks 检查）。
   - 提交信息：约定式提交（建立 git 仓库后启用）。
2. **代码精简**：
   - 只为第 4.1 节所列基础设施建接口，其他地方不预设抽象、不为"以后可能"写代码。
   - 优先用标准库和已选框架的原生能力；不引入功能重叠的新依赖。
   - 函数短小、职责单一；不留无用代码和注释掉的代码；注释只解释"为什么"，不复述代码。
3. **与项目架构对齐**：
   - 新代码放进对应的能力模块；遵守 6.2 的依赖方向；模块之间只走公开服务。
   - 新增外部依赖必须先定义接口和契约测试，再写实现，并在组装根登记。
   - 配置一律走 `config/`；第三方服务一律进 compose；依赖一律写精确版本。
   - 不新增顶层目录，除非先更新架构规范。

### 17.3 开发新功能的标准流程（写入技能）

```
加载 dev-standards 技能
→ 在 docs/requirements/backlog.md 登记需求（较大功能写需求记录）
→ 涉及架构取舍：写决策记录（必要时写设计文档）
→ 先写测试
→ 实现（按模块模板与接口模板）
→ make check（格式、类型、依赖方向、测试）全部通过
→ 文档同步：更新 backlog 状态、changelog，必要时更新 architecture.md
```

---

## 18. 项目文档（`docs/`）

```
README.md                    # 根目录：一句话介绍、快速启动、指向 docs/
CLAUDE.md                    # 给 AI 编程助手的约定，指向 dev-standards 技能
docs/
├── README.md                # 文档导航
├── usage.md                 # 使用指南：安装、启动、配置模型版本与 MCP、日常使用、备份恢复
├── development/
│   ├── architecture.md      # 架构规范（第 17 节）
│   ├── coding-standards.md  # 编码规范（第 17 节）
│   └── testing.md           # 测试规范（第 17 节）
├── requirements/
│   ├── backlog.md           # 需求池：每条一行，带状态（待定/计划/进行中/完成）与优先级
│   └── YYYY-MM-DD-<功能>.md  # 较大功能的需求记录：背景、目标、验收标准、变更历史
├── decisions/               # 架构决策记录：背景、选项、结论、原因（第 3 节 D1～D16 逐条补齐）
├── specs/                   # 设计文档（本文件所在）
├── plans/                   # 实施计划
└── changelog.md             # 版本变更记录（含依赖升级）
```

**文档同步规则**（同时写入技能与 `CLAUDE.md`）——一个功能做到以下三点才算完成：
1. 更新 `backlog.md` 状态，较大功能另写需求记录；
2. 涉及架构取舍时补一份决策记录；
3. 在 `changelog.md` 记一笔。

---

## 19. 后续扩展路线

| 阶段 | 内容 |
|---|---|
| 阶段 1：实用增强 | 本地对话模型（宿主机原生运行 Ollama 或 LM Studio，可用显卡加速）；联网搜索与网页阅读（MCP 接 Tavily / Brave，或在 compose 中自建 SearXNG）；会话分支与编辑后重发；前端直接编辑 MCP 与审批规则；会话导出 Markdown；语音输入；知识库新增种类（手写笔记、网页收藏） |
| 阶段 2：主动性 | 定时任务（如"每天早上 8 点汇总……"）；提醒与通知（浏览器通知、飞书）；知识库自动同步（监听本地文件夹、飞书文档） |
| 阶段 3：多 agent 与多入口 | agent 登记表，新的专职 agent 复用 `main_agent` 能力；飞书机器人等 IM 入口作为另一种前端；手机访问（可安装到桌面的网页 + Tailscale 远程组网 + 登录） |
| 阶段 4：落地可替换实现 | 多进程（10.9）、多用户、云沙箱、外部向量库、对象存储、AG-UI 适配层 |
| 贯穿始终 | 可观测性（在 compose 中自建 Langfuse，追踪每次运行的完整调用链）；评测集（记忆召回准确率、检索质量、工具成功率）；检索结果重排序；记忆合并与过期清理 |

---

## 20. 风险与注意事项

| 风险 | 应对 |
|---|---|
| 网关对思考内容、用量字段的传递未经确证 | 第 15 节 V1、V2 先行验证，并已备退路 |
| deepagents 迭代快（0.7 有破坏性变更） | 精确版本锁定；deepagents 只出现在 `agents/main_agent/runtime/`，升级影响面可控 |
| litellm 曾出现投毒版本 | 精确版本 + 锁文件哈希 + 网关镜像固定摘要，避开问题版本 |
| 自动记忆提取可能写入错误或过时信息 | 提取时做"新增 / 更新 / 删除 / 忽略"判断；知识库界面可查看、修改、删除；可关闭 |
| 文档片段与记忆共用一张表，量级差异大 | 检索按 `kind` 过滤并建过滤索引；记忆召回只查 `kind=memory`；文档片段不自动召回 |
| Mac 上容器内 Ollama 无显卡加速 | 向量模型 0.6B 在 CPU 上够用（V6 验证）；若速度不达标，先换云端向量模型（配置 + 重建向量）；本地对话模型不在 v1 |
| 单进程限制 | 已预留替换点（10.9） |
| `agents` 与 OpenAI Agents SDK 同名 | 不使用该 SDK；预案见 6.3 |

---

## 21. 实施分期

v1 拆成 6 期，原则是**先跑起来、再逐步完善**：M0 就交付一个能在浏览器里对话的最小版本。**每期单独写一份实施计划**（`docs/plans/`），每期结束都是一个能跑、能用、检查与测试全部通过的状态：

| 期 | 内容 | 完成标志 |
|---|---|---|
| M0 首跑 | **目标：尽快在浏览器里跑起来对话。** ① 精简版开发规范：三份规范先写要点、`dev-standards` 技能、`CLAUDE.md`（后续各期逐步充实）；② 项目骨架：uv / pnpm 精确版本、`config/`、`common/`、`Makefile`、ruff + mypy + import-linter；③ compose：postgres + litellm + ollama（自动拉取向量模型）；④ 最小端到端对话：agents runtime（组装 deepagents、经网关取模型、核心事件：回答逐字输出 / 工具调用 / 运行结束）、backend（会话、运行、SSE 推送、界面历史基础重放）、frontend（会话列表、对话流、模型版本选择）；⑤ 先行验证 V1～V6 以冒烟脚本完成，结论记入决策记录；`docs/` 骨架（导航、需求池、changelog） | `make up` 后打开浏览器，能与云端任一模型版本多轮对话；`make check` 通过 |
| M1 对话完善与前端改版 | **前端改版**：设计系统与默认主题（深浅两版，参考 Hermes）、assistant-ui 对话组件层、按新布局重做会话列表与对话区、两条主题检查；**一键启动**（13.5）；事件批量写入与续传完善（M0 已实现基础的历史重放与 `Last-Event-ID` 续传）、取消、深度思考展示、换模型清理、完整事件集（含子智能体 `agent_path`）、用量统计入库与每轮展示、本机安全防护（12.2）、前端类型自动生成；M0 延后的次要问题；补齐决策记录 D1～D16 | `make up` 后打开 `:8000` 即可使用；新界面支持深浅色切换；刷新续传、取消、换模型可用；用量按版本入库并展示 |
| M2 工作区与沙箱 | 沙箱镜像与执行服务、工作区实现、文件上传下载与预览、产物检测、待办清单、数据分析员子智能体、智能体技能 | 上传 Excel 让智能体分析并产出图表，产物可预览下载 |
| M3 统一知识库 | 知识条目与文档、解析切块、混合检索、常驻条目、记忆（主动记 + 自动提取 + 召回）、后台任务（jobs）、标题生成；前端知识库页 | 跨会话记得你；上传文档后能检索并带出处回答；常驻条目即画像 |
| M4 MCP 与审批 | MCP 客户端与配置、审批规则、审批暂停与恢复、预算刹车；前端审批卡片与设置页（只读 + 重新加载） | 接入一个 MCP 服务，有副作用的操作会先请你审批 |
| M5 收尾 | 用量统计页、备份命令、端到端测试、`docs/usage.md` 使用指南完善 | 满足第 1.3 节全部成功标准 |

---

## 附录 A：调研基线（2026-10-09 核对）

| 组件 | 版本 / 要点 |
|---|---|
| Python | 3.12（deepagents 要求 ≥ 3.11） |
| deepagents | 0.7.23；0.7 起不再默认包含 `TodoListMiddleware`、基础提示词为空、后端须传实例；默认中间件含文件、子智能体、上下文压缩、工具调用修补、Anthropic 缓存（仅 `ChatAnthropic` 生效）；`skills=`、`interrupt_on=` 按需启用（本项目不用 `memory=` 与 `store=`） |
| langchain / langgraph | langchain ≥ 1.4.3；langgraph 1.2.x |
| langgraph-checkpoint-postgres | 3.1.2；连接池须 `autocommit=True`、`row_factory=dict_row`，`prepare_threshold=0` 兼容连接池代理；`setup()` 执行一次 |
| langchain-litellm | 0.11.0；`ChatLiteLLM` 保留 Claude 带签名的思考内容；需自行提供模型的 `max_input_tokens` |
| langchain-mcp-adapters | 0.3.2（稳定）；langchain 1.4 起另有内置 `langchain.mcp`（测试版） |
| 推送 | `astream(..., stream_mode=["messages","updates","custom"], subgraphs=True, version="v2")`；审批中断出现在 `updates` 的 `__interrupt__`，用 `Command(resume={"decisions": [...]})` 恢复，决定类型 approve / edit / reject / respond |
| Ollama 向量模型 | 官方模型库提供 `qwen3-embedding`（0.6B / 4B / 8B）；Qwen3 向量模型 8B 曾于 2025-06 位列 MTEB 多语言榜第一（70.58）；0.6B 最大输出 1024 维 |
| 安全 | litellm 1.82.7 / 1.82.8 为恶意版本，须避开 |
