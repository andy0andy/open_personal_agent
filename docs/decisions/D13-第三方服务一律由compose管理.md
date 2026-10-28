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
- 服务清单：`postgres`（带 pgvector；两个库：业务用 `agent`、网关自用 `litellm`）、`litellm`（网关）、`ollama`（只做向量化，首次由一次性初始化服务拉取模型）、`backend`（本项目镜像，正式使用时也托管打包好的前端）；`postgres-test` 属于 `test` 配置组，数据放内存盘、测完即弃。
- 对外端口一律只绑定 `127.0.0.1`；`ollama` 不对外。（2026-10-18：`sandbox`、`sandbox-test` 已随 D20 删除。）
- 需要自建的 MCP 服务也加进 compose；用 `npx` / `uvx` 启动的本地进程型 MCP 服务作为 backend 容器里的子进程运行。
- 常用操作统一走 `Makefile`：`make infra-up`、`make up`、`make test-int` 等。

落地：M0：`deploy/docker-compose.yml`（目前有 `postgres`、`litellm`、`ollama`、`ollama-init`、`backend`、`postgres-test`）、`deploy/backend.Dockerfile`、`deploy/postgres/init.sql`、`Makefile`；`sandbox`、`sandbox-test` 在 M2 加入。目前镜像只写了版本标签，尚未加摘要。

## 原因与代价

- 一条命令拉起完整环境，版本统一固定；测试用服务也由 compose 管理，集成测试自动启动、测完即弃。
- 代价：Mac 上的 Docker 用不了苹果芯片的显卡，容器里的 Ollama 只能用 CPU：本地对话模型 v1 因此不接，向量模型批量处理文档也偏慢（见 D15）。
- 代价：Mac 上容器收不到源码改动的通知，改了 Python 代码要 `make restart`；数据库数据放在 Docker 数据卷而不是 `workdata/`（Mac 上挂本地文件夹性能差、易出权限问题）。
- M0 遇到的环境问题：Docker Hub 不可达，镜像改经 `mirror.gcr.io` 与 `ghcr.io` 拉取；本机 Docker 配置残留凭据程序，Makefile 改用项目内的空配置；Ollama 镜像（arm64 约 2.7GB）与向量模型下载耗时较长。
