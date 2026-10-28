# 常用命令入口。容器命令自动选择 docker compose 或 podman compose。
COMPOSE ?= $(shell command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && echo "docker compose" || echo "podman compose")
# --env-file：compose 文件中的 ${变量} 取自根目录 .env
DC := $(COMPOSE) --env-file .env -f deploy/docker-compose.yml
# 用到 compose 的命令先检查 .env：缺少时 compose 只给出难懂的报错
# 同时确保工作区目录与共享文件夹（MCP 的 files 服务读写它）存在（compose 自己也会建，留着无害）
NEED_ENV = @test -f .env || { echo "缺少 .env：先运行 cp .env.example .env（见 README 的首次准备）"; exit 1; }; \
	mkdir -p .workdata/workspace .workdata/shared
# 启动后端；失败时直接显示后端日志里的原因（如数据库迁移失败），不必再去 make logs 里找
START_BACKEND = { $(DC) up -d --wait backend || { $(DC) logs --tail=20 backend; exit 1; }; }
# 后端跟着本机的时区（compose 里 backend 的 TZ）：Mac 的 /etc/localtime 指向 …/zoneinfo/Asia/Shanghai；
# 取不到（不是链接）时用 .env 里的 HOST_TZ，都没有就是 UTC
_SYSTEM_TZ := $(shell readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')
# 取不到时不导出：不然空值会盖掉 .env 里写的 HOST_TZ
ifneq ($(_SYSTEM_TZ),)
export HOST_TZ := $(_SYSTEM_TZ)
endif
# 备份与恢复脚本的参数（deploy/backup.sh 开头有说明）：两个数据库与 .workdata 里的个人文件
BACKUP_ENV = PG_EXEC="$(DC) exec -T postgres" PG_USER=agent DATABASES="agent litellm" \
	WORKDATA=.workdata FILE_DIRS="workspace knowledge shared config skills" BACKUP_ROOT=.workdata/backups KEEP=7
# 使用项目内的空 Docker 配置：本机全局配置残留了 Docker Desktop 的凭据程序（credsStore=desktop），会导致构建失败
export DOCKER_CONFIG := $(CURDIR)/deploy/docker-config
export LITELLM_LOCAL_MODEL_COST_MAP := True
# 对话存档只反序列化登记过的类型（langgraph-checkpoint-postgres 的建议，设计文档 12.2）
export LANGGRAPH_STRICT_MSGPACK := true
# 前端命令使用 frontend/.nvmrc 指定的 Node 版本（nvm 安装的那一份），不改动全局默认版本
NODE_VERSION := $(shell cat frontend/.nvmrc 2>/dev/null)
export PATH := $(HOME)/.nvm/versions/node/v$(NODE_VERSION)/bin:$(PATH)

.PHONY: install fmt check check-py check-web types test test-int smoke \
	infra-up up build restart down logs restart-gateway test-up test-down web migrate backup restore e2e \
	doctor bundle

install: ## 严格按锁文件安装前后端依赖
	uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

fmt: ## 自动格式化
	uv run ruff format .
	uv run ruff check --fix .
	cd frontend && pnpm exec prettier --write .

check: check-py check-web ## 完成一个任务前必须通过：格式、类型、依赖方向、单元测试

check-py:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy .
	uv run lint-imports
	uv run pytest

check-web:
	cd frontend && pnpm exec tsc --noEmit && pnpm types:check && pnpm lint && pnpm format && pnpm test


types: ## 改了接口或事件定义后运行：重新生成前端类型（frontend/src/api/generated/）
	uv run python -m backend.openapi
	cd frontend && pnpm types

test: ## 只跑单元测试（不需要任何容器）
	uv run pytest

test-up: ## 启动测试专用数据库
	$(NEED_ENV)
	$(DC) --profile test up -d --wait postgres-test

test-down:
	$(NEED_ENV)
	$(DC) --profile test rm -sf postgres-test

test-int: test-up ## 集成测试（连接 postgres-test）
	uv run pytest -m integration

e2e: test-up ## 端到端测试：用本机 Chrome 自动点一遍主要流程（后端接测试库与假模型，不花钱）
	cd frontend && pnpm build && pnpm e2e

smoke: ## 先行验证：调用真实模型，会产生少量费用（需先 make infra-up）
	uv run pytest -m live -s agents/tests/live

infra-up: ## 启动数据库、网关、Ollama；向量模型不存在时才下载
	$(NEED_ENV)
	$(DC) up -d --wait postgres litellm ollama
	$(DC) run --rm ollama-init

up: ## 一键启动全部服务（向量模型不存在时先下载），然后打开 http://127.0.0.1:8000；等同于在 deploy 目录里 podman compose up -d
	$(NEED_ENV)
	$(START_BACKEND)

build: ## 重新构建 backend 镜像并启动：代码、依赖或前端界面改了以后运行（依赖从本机构建缓存安装，不重新下载）
	$(NEED_ENV)
	$(DC) build backend
	$(START_BACKEND)

restart: ## 改了 .env 后重建后端容器（重读 .env）；用的是镜像里的代码，改了代码要 make build 或换新镜像
	$(NEED_ENV)
	@$(DC) up -d --force-recreate --wait backend || { $(DC) logs --tail=20 backend; exit 1; }

bundle: ## 在构建电脑上打包全部镜像成一个文件（dist/）：PLATFORM=linux/arm64 指定目标机器的芯片，SKIP_BUILD=1 只存不构建
	COMPOSE="$(COMPOSE)" bash deploy/bundle-images.sh

web: ## 本机启动前端开发服务器：http://127.0.0.1:5173
	cd frontend && pnpm dev

migrate: ## 在宿主机上对主库执行迁移（一般不需要，backend 启动时会自动执行）
	uv run alembic upgrade head

restart-gateway: ## 修改 config/models.yaml 或 .env 后重建网关容器
	$(NEED_ENV)
	$(DC) up -d --force-recreate --wait litellm

logs:
	$(NEED_ENV)
	$(DC) logs -f --tail=100

doctor: ## 体检（只读）：容器、后端、网关、模型、Ollama、数据库、.workdata 文件、磁盘与备份，逐项 ✓ / ✗
	$(NEED_ENV)
	@DC="$(DC)" uv run python deploy/doctor.py

backup: ## 备份对话、知识库与个人文件到 .workdata/backups/（保留最近 7 份）
	$(NEED_ENV)
	$(DC) up -d --wait postgres
	$(BACKUP_ENV) bash deploy/backup.sh

restore: ## 恢复备份：make restore BACKUP=<名字>（不带名字时列出已有的备份）；恢复前自动备份当前数据
	$(NEED_ENV)
	@if [ -z "$(BACKUP)" ]; then \
		echo "已有的备份（恢复：make restore BACKUP=<名字>；pre-restore- 开头的是恢复前自动做的）："; \
		found=; for d in .workdata/backups/*/; do \
			[ -f "$$d/manifest.txt" ] && { basename "$$d"; found=1; }; \
		done; [ -n "$$found" ] || echo "（还没有备份）"; \
		exit 0; \
	fi; \
	$(DC) up -d --wait postgres; \
	$(BACKUP_ENV) BACKUP="$(BACKUP)" \
		BEFORE_RESTORE='$(DC) stop backend litellm' \
		AFTER_RESTORE='$(DC) up -d --wait litellm; $(START_BACKEND)' \
		bash deploy/restore.sh

down: ## 停止所有服务（数据保留在数据卷中）
	$(NEED_ENV)
	$(DC) down
