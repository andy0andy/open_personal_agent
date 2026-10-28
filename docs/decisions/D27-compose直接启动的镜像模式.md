# D27：部署改为 compose 直接启动的镜像模式，镜像可在别的电脑构建后打包加载

- 状态：已采纳（2026-10-28 用户决定）
- 日期：2026-10-28
- 设计：`docs/specs/2026-10-28-compose-deploy-design.md`
- 修订：架构规范里"后端源码挂载、改了代码自动重载、`make restart` 就生效"的做法；D20 里"源码与配置以只读方式挂进容器"那条缓解改为"代码在镜像里、属于 root"。

## 背景

- 原来要 `make up` 才能起来：Makefile 替 compose 指定文件与 `.env`、先下载向量模型、建目录、算时区；后端以开发模式运行（挂源码、自动重载）。
- 用户想换机器部署时"拿镜像来加载、一条 compose 命令起来"，并且本机 Mac 不负责构建镜像。

## 备选方案

1. 把数据库、网关、Ollama、后端合成一个容器：镜像很大，网关与后端的 Python 依赖冲突，要另装进程管家，失去各服务的健康检查与自动重启，升级数据库要重打整个镜像。不采用。
2. 保持 4 个容器，只让 compose 自己能完成启动，镜像打包成一个文件带走（采用）。
3. compose 文件挪到项目根目录：用户决定留在 `deploy/`。
4. 另起开发模式叠加文件（挂源码、自动重载）：用户决定先不做。

## 决定

1. 4 个容器不变；compose 文件留在 `deploy/docker-compose.yml`，项目名 `open-personal-agent` 不变（容器名、数据卷名都由它来，换了会新建空数据卷）。
2. 后端是镜像模式：`image: ${BACKEND_IMAGE:-open-personal-agent-backend:latest}`，保留 `build:`；不挂源码、不带 `--reload`，启动命令用镜像自带的。
3. 后端等 `ollama-init` 跑完再启动：不经 make 也会先下载向量模型。
4. `deploy/.env` 是指向根目录 `.env` 的链接：在 `deploy/` 里执行 compose 时，`${变量}` 也从根目录 `.env` 取；`.dockerignore` 排除所有 `.env`；扫描类测试不读它。
5. 时区：`.env.example` 加 `HOST_TZ`，不经 make 时用它；经 make 时仍以本机系统时区为准。
6. 构建电脑不需要 `.env`（用户决定：`.env` 只是本机运行时的环境变量）：compose 里 `env_file` 写成可选；打包脚本用一份空的环境文件解析 compose，两项必填密钥给占位值，不进镜像。
7. 新增 `deploy/bundle-images.sh`（`make bundle`）：构建后端、拉取另外 3 个镜像，存成一个文件；`PLATFORM` 指定目标芯片，`SKIP_BUILD=1` 只存不构建。目标机器 `load` 后直接 compose 启动。
8. Makefile 不再是启动的必经之路，只留作快捷命令；备份恢复、体检、测试照旧。

## 代价

- 改了 Python 代码不再是 `make restart` 就生效，要重新构建镜像（本机 `make build`，或在构建电脑上打包拿来加载）。需要时再加开发模式。
- 构建电脑与目标机器芯片不同时要指定 `PLATFORM`，跨芯片构建靠模拟，较慢。
- Windows 上拷贝项目文件夹时 `deploy/.env` 链接可能丢失，要手动复制一份或用 `--env-file`。
- 这台 Mac 的全局 Docker 配置残留了凭据程序：不经 make 拉取或构建镜像会失败（镜像都在本机时 `up -d` 不受影响）。
