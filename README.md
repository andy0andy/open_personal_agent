# open_personal_agent

自建的通用个人助理：多轮对话、统一知识库与长期记忆、隔离环境里执行代码、通过 MCP 接入外部工具，按会话切换各家大模型的具体版本。

## 首次准备（只做一次）

前提：Podman（或 Docker）、uv、nvm 安装的 Node 24.21.0 与 pnpm 11.17.0。

```bash
cp .env.example .env      # 然后填写 LITELLM_MASTER_KEY（sk- 开头的随机串）、LITELLM_SALT_KEY（随机串，设了以后不能改）与 UPSTREAM_GATEWAY_KEY
make install              # 严格按锁文件安装 Python 与前端依赖
```

## 日常启动

```bash
podman machine start      # 电脑重启后需要；已在运行会提示 already running
make up                   # 一键启动：数据库、模型网关、Ollama、后端（含打包好的前端）
# 不用 make 也行：cd deploy && podman compose up -d（docker 同理）
```

然后打开 http://127.0.0.1:8000 。停止：`make down`（数据保留）。备份：`make backup`。

改了东西后：

| 改了什么 | 运行 |
|---|---|
| `.env`、设置页上标“重启后生效”的设置 | `make restart`（重建后端容器，读到新的 `.env`） |
| 后端接口或事件定义 | `make types`（重新生成前端类型；忘了运行，`make check` 会提示） |
| Python 代码、依赖、前端界面、`deploy/backend.Dockerfile` | `make build`（重新构建镜像：后端用的是镜像里的代码；依赖从本机构建缓存安装，不重新下载）。镜像也可以在别的电脑上构建、打包拿来加载，见使用指南第 2 节 |
| 智能体执行代码用的库 | 就是项目依赖：`uv add 包==版本`，然后 `make build` |

日常怎么用（对话、附件、会话的审批权限、记忆与知识库、文档与出处、外部工具与审批、技能、设置页、用量页）、怎么配置模型版本与 MCP 服务、怎么备份恢复、怎么在网关后台核对每次调用，见 **[使用指南 docs/usage.md](docs/usage.md)**。

开发前端界面时可另开终端运行 `make web`，打开 http://127.0.0.1:5173（改代码即时生效，接口转发到 8000）。**日常使用一律开 8000**；5173 只在开发界面时用，两者连的是同一个后端、同一份数据（见使用指南第 2 节）。

## 文档

见 [docs/README.md](docs/README.md)。
