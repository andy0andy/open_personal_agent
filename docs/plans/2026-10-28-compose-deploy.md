# 部署改为 compose 直接启动（镜像模式） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不经 Makefile、用 `cd deploy && podman compose up -d` 以镜像模式起全部服务；镜像能在别的电脑上构建、打包成一个文件、拿来加载。

**Architecture:** compose 文件留在 `deploy/`。backend 改成镜像模式：用 `BACKEND_IMAGE`，不挂源码，等 `ollama-init` 跑完再启动。`deploy/.env` 链接到根目录的 `.env`。新增打包脚本 `deploy/bundle-images.sh` 与 `make bundle`。Makefile 只留作快捷命令。

**Tech Stack:** compose（docker-compose 5.0.1 经 `podman compose`）、bash 3.2、Makefile、pytest。

**Spec:** `docs/specs/2026-10-28-compose-deploy-design.md`（已审定）

## Global Constraints

- compose 文件留在 `deploy/docker-compose.yml`，`name: open-personal-agent` 不变。
- 不做开发模式，不新增依赖。项目没有 git，台账在 `.superpowers/sdd/2026-10-28-compose-deploy/progress.md`。
- 不读、不打印 `.env`。
- 本机不构建镜像，打包脚本只用 `SKIP_BUILD=1` 实测。
- 切换前先 `make backup`。

## Review Focus

1. 切换后容器名、数据卷不变，会话、知识库、模型都在。
2. 不经 make 时 `${LITELLM_SALT_KEY}`、`${SHARED_DIR}`、`${HOST_TZ}` 都从根目录 `.env` 取到。
3. `ollama-init` 已下载过模型时立即结束，不阻塞后端；没联网时第一次启动的报错看得懂。
4. 打包脚本在 macOS bash 3.2 与 Linux 上都能跑，`PLATFORM` 同时作用于构建与拉取。
5. 镜像模式下健康检查、迁移、MCP 的 npx 缓存照常。

---

### Task 1: compose 镜像模式

**Files:** `deploy/docker-compose.yml`、`deploy/.env`（链接）、`.dockerignore`、`.env.example`。

**Test:** `deploy/tests/test_compose.py`，新增 4 条：
- `test_backend_runs_the_image_code`：无源码挂载、无 `--reload`，`image` 引用 `BACKEND_IMAGE`；
- `test_backend_waits_for_embedding_model`；
- `test_compose_finds_root_env`：`deploy/.env` 是指向 `../.env` 的链接；
- `test_env_never_enters_image`：`.dockerignore` 里有 `**/.env`。

### Task 2: Makefile 与打包脚本

**Files:** `Makefile`（`up`、`restart`、`bundle`）、Create `deploy/bundle-images.sh`。

**Test:**
- `deploy/tests/test_makefile.py`：`make -n up` 是一条 `up -d --wait`；`make -n bundle` 调用打包脚本；
- `deploy/tests/test_bundle.py`：`bash -n`；镜像清单与 compose 一致（用替身 docker 命令跑 `SKIP_BUILD=1`，核对 save 的参数）。

### Task 3: 文档

D27、README、使用指南（启动、换机器部署、`.env` 链接在 Windows 上的处理）、CLAUDE.md 命令表、架构规范、测试规范、需求池（R46 完成）、changelog。

### Task 4: 检查、审查与本机切换

1. `make check`、`make test-int`、`make e2e`。
2. 独立审查，修 Critical / Important。
3. 本机切换：`make backup` → `cd deploy && podman compose up -d` → 核对数据、`make doctor`、8000 只看。
4. `SKIP_BUILD=1` 打包实测后删掉文件。
