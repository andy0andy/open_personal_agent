# 部署改为 compose 直接启动（镜像模式）设计

- 日期：2026-10-28
- 状态：已审定（2026-10-28 用户：compose 文件留在 `deploy/`，先不管开发模式，其余可以）
- 依据：2026-10-28 对话。
  - 用户决定保持 4 个容器（不合成一个），启动只靠 compose，不必经过 Makefile。
  - 本机 Mac 不负责构建镜像：镜像在别的电脑上构建，拿过来加载。
  - 不装 podman-compose，保持现状（`podman compose` 调用的是已装好的 docker-compose）。
  - 构建电脑的芯片暂不确定：先做，构建时有问题再改。

## 1. 为什么改

现在要 `make up` 才能把项目起来。Makefile 替 compose 做了这些事：

- 指定文件路径、读 `.env`；
- 先下载向量模型；
- 建目录、算时区。

后端还以"开发模式"跑：源码挂进容器，改了自动重载。换一台机器部署时，既要整套开发工具，又要从源码构建。目标是：

- 别的电脑上构建好镜像，打成一个文件拷过来；本机加载后用 compose 一条命令就能起来。
- 以后改了代码：重新构建、加载，再 `up -d`。
- Makefile 不再是启动的必经之路，留作运维与开发的快捷命令。

## 2. 不做什么

- 不把数据库、网关、Ollama 合进一个容器：镜像大、Python 依赖冲突、失去各服务的健康检查与自动重启、升级麻烦。
- 不把数据打进镜像。对话、知识库、模型在数据卷与 `.workdata/` 里，换机器照旧用备份恢复。
- 不把 `.env` 打进镜像（里面是密钥）。
- 不挪 compose 文件，留在 `deploy/docker-compose.yml`（用户决定）。
- 先不做开发模式：不另起叠加文件，不保留源码挂载与自动重载（用户决定）。
- 不搭镜像仓库；推到仓库的做法只在使用指南里提一句。
- 不支持另一个工具 podman-compose（中间是连字符），只保证 `podman compose` 与 `docker compose`。
- 本机 Mac 不负责构建镜像。`make build` 仍保留，给构建电脑用。

## 3. 现状要点（核对过）

- **项目名**：`deploy/docker-compose.yml` 里 `name: open-personal-agent` 固定了项目名，容器名、数据卷名（`open-personal-agent_pgdata`、`open-personal-agent_ollama-models`）都由它来。不挪文件，它也不变，现有容器与数据卷原样接上。
- **容器**：4 个常驻的是 `postgres`、`litellm`、`ollama`、`backend`。一次性的 `ollama-init` 只在 `make infra-up` 里用 `run --rm` 跑。测试库 `postgres-test` 在 `test` 配置组里。
- **后端**：compose 里挂源码只读、`uvicorn --reload`。镜像（`deploy/backend.Dockerfile`）里本来就有全部代码与打包好的前端，自带的启动命令不带重载。
- **Makefile 替 compose 做的事**：
  - `-f deploy/docker-compose.yml --env-file .env`；
  - `mkdir -p .workdata/workspace .workdata/shared`；
  - 导出 `HOST_TZ`；
  - `DOCKER_CONFIG` 指向项目里的空配置（本机全局配置残留了 Docker Desktop 的凭据程序，构建或拉镜像会失败）；
  - 先跑 `ollama-init`。
- **`.env` 的两种用法**：
  - 一是整份传进容器：`env_file: ../.env`，相对 compose 文件找，在 `deploy/` 下执行也找得到。
  - 二是替换 compose 文件里的 `${变量}`：`LITELLM_SALT_KEY`、`LITELLM_MASTER_KEY`、`SHARED_DIR`、`HOST_TZ`。compose 只在"项目目录"（即 compose 文件所在的 `deploy/`）里找 `.env`，所以现在不经 make、不带 `--env-file` 时这些都取不到：`:?` 检查直接报错，`SHARED_DIR` 退回默认值。
- **挂载目录会自己建好**（2026-10-28 实测，本机 `podman compose`，即 docker-compose 5.0.1）：挂载的宿主机目录不存在时，compose 会自己建好，容器正常运行。Makefile 里"podman 不会替你建目录"的说法对现在的用法已不成立。
- **芯片**：本机是 Apple 芯片（arm64），当前镜像是在本机构建的。

## 4. 方案

### 4.1 启动命令

compose 文件留在 `deploy/`，两种写法都行：

```bash
cd deploy && podman compose up -d                 # 在 deploy 目录里
podman compose -f deploy/docker-compose.yml up -d  # 在项目根目录
```

docker 同理，把 `podman compose` 换成 `docker compose`。

`.env` 仍放在项目根目录。为了让 compose 替换 `${变量}` 时找得到它，加一个链接 `deploy/.env → ../.env`。只有一份 `.env`，不用复制、不会两份不一致。`.dockerignore` 改成 `**/.env`，链接不进构建上下文。

### 4.2 默认是镜像模式

- backend 写 `image: ${BACKEND_IMAGE:-open-personal-agent-backend:latest}`，同时保留 `build:`：构建电脑用 `docker compose build` 构建出同名镜像。
- 去掉源码挂载与 `--reload`，用镜像里的代码与前端。启动命令照旧：先迁移数据库，再起 uvicorn。
- `.workdata`、共享文件夹、遮住备份的空目录照旧挂载。
- backend 等 `ollama-init` 跑完（`service_completed_successfully`）再启动。第一次启动自动下载向量模型，已下载时立即结束。这样不再需要 `make infra-up` 单独那一步。

### 4.3 启动准备不再靠 Makefile

| 原来 Makefile 做的 | 改后 |
|---|---|
| 指定 compose 文件与 `.env` | `-f` 或在 `deploy/` 里执行；`deploy/.env` 链接到根目录的 `.env` |
| 建 `.workdata/workspace`、`shared` | compose 自己建（已实测）；Makefile 里那句留着，无害 |
| 先下载向量模型 | backend 依赖 `ollama-init` 跑完 |
| 导出 `HOST_TZ` | `.env.example` 加 `HOST_TZ=Asia/Shanghai`（按所在地填）；Makefile 仍导出，经 make 时以它为准 |
| `DOCKER_CONFIG` | 只在构建、拉镜像时需要；镜像都已在本机时，`up -d` 用不到。使用指南写明：这台 Mac 上要拉镜像就经 make，或临时设 `DOCKER_CONFIG` |

### 4.4 打包与加载镜像

- **打包**：新脚本 `deploy/bundle-images.sh`（也可用 `make bundle` 调它），在构建电脑上执行：
  - 可选 `PLATFORM=linux/arm64`，即目标机器的芯片（本机就是 arm64）。经 `DOCKER_DEFAULT_PLATFORM` 同时作用于构建与拉取。
  - 构建 backend，拉取另外 3 个镜像（版本照 compose 文件），用 `save` 存成一个文件 `dist/open-personal-agent-images-<时间>.tar`。
  - 打印目标机器上要执行的加载命令。
  - 只保存、不构建的开关（`SKIP_BUILD=1`）：给已经有镜像的机器用，也方便本机验证脚本。
- **加载**：目标机器上 `podman load -i <文件>`（或 `docker load`），然后用 4.1 的命令启动。
- **镜像名**：用 compose 文件里写的，加载后 compose 直接认得。backend 默认标签 `latest`；要并存多个版本时，在 `.env` 设 `BACKEND_IMAGE`。

### 4.5 Makefile 变成可选的快捷命令

| 命令 | 改后 |
|---|---|
| `make up` | `up -d --wait`：一条命令起全部（不再先单独跑 `infra-up`） |
| `make restart` | 重建后端容器：重读 `.env`，用镜像里的代码。没有源码挂载了，改了 Python 代码要重新构建镜像才生效 |
| `make build` | 留给构建电脑 |
| `make bundle` | 新增 |
| 备份恢复、体检、各种测试、生成前端类型 | 照旧，命令不变 |

最后一行的命令本来就不靠镜像：

- 备份恢复是宿主机上的脚本，经 compose 进数据库容器导出、导入；
- 体检在宿主机上检查；
- 测试用宿主机的 Python 与 Node；端到端测试起的是自己的测试后端，不碰部署的镜像。

### 4.6 换机器部署要带的东西

- 项目文件夹，不带 `.venv`、`node_modules`、`.workdata`。里面有 compose 文件、网关设置 `config/models.yaml`、数据库初始化脚本、备份恢复脚本、`deploy/.env` 链接。
- `.env`：`LITELLM_SALT_KEY` 必须和旧机器一样。
- 镜像包文件。
- 旧机器 `make backup` 出来的备份。

步骤写进使用指南：加载镜像 → 启动 → `make restore BACKUP=…`。

## 5. 文档与规范

- **新决策记录 D27**：部署改为 compose 直接启动的镜像模式。修订架构规范里"源码挂载、自动重载"的说法，以及 CLAUDE.md、README 里"改了 Python 代码 `make restart` 就生效"的说法。
- **跟着改**：README、使用指南、`CLAUDE.md` 命令表、架构规范、测试规范。
- **需求池与变更记录**：需求池登记一条并标完成；changelog。

## 6. 验证

- **单元测试**：
  - backend 不挂源码、不带 `--reload`、用 `BACKEND_IMAGE` 镜像名；
  - backend 依赖 `ollama-init` 跑完；
  - `deploy/.env` 是指向 `../.env` 的链接；
  - `.dockerignore` 排除所有 `.env`；
  - 打包脚本过 `bash -n`；
  - 原有的密钥置空、遮住备份、时区几条测试照旧。
- **集成测试与端到端**：照旧全过。
- **本机实测**：
  1. 先 `make backup`；
  2. 停掉旧的，用 `cd deploy && podman compose up -d` 以现有镜像起来；
  3. 核对数据都在（会话、知识库、模型）、体检全部正常、8000 只看核对。
- **打包脚本**：本机只跑 `SKIP_BUILD=1`（只保存、不构建），确认能存出文件，验证后删掉（几个 GB）。真正的构建由你在构建电脑上做。

## 7. 风险与代价

- **芯片**：构建电脑若是 Intel/AMD 芯片，要 `PLATFORM=linux/arm64`（靠模拟构建，较慢）。用户已说明先做，构建时有问题再改。
- **改代码后的流程变慢**：本机后端从"开发模式"变成"镜像模式"，以后改了 Python 代码不再是 `make restart` 就生效，要重新构建镜像。开发模式按用户决定先不管，以后需要再加。
- **`deploy/.env` 链接**：Windows 上拷贝项目文件夹时，链接可能变成普通文件或丢失。那时把 `.env` 复制一份到 `deploy/`，或用 `--env-file ../.env`。使用指南写明。
