# 依赖下载走构建缓存目录（RUN --mount=type=cache）：重新构建时直接从本机缓存安装，不再重新下载

# 第一阶段：打包前端（设计文档 13.5），依赖严格按 pnpm-lock.yaml 安装
FROM mirror.gcr.io/library/node:24.21.0-trixie-slim AS frontend
WORKDIR /frontend
RUN npm install --global pnpm@11.17.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc frontend/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm-store pnpm install --frozen-lockfile --store-dir /pnpm-store
COPY frontend/ ./
RUN pnpm build

# 第二阶段：后端（官方 uv 镜像，内含 Python 3.12），依赖严格按 uv.lock 安装
FROM ghcr.io/astral-sh/uv:0.11.7-python3.12-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    LANGGRAPH_STRICT_MSGPACK=true

WORKDIR /app

# Node.js：运行 npx 启动的 MCP 服务（设计文档 6 节：本地进程型 MCP 服务是 backend 容器里的子进程）。
# 从前端构建阶段复制（同为 Debian trixie），不另装；只要 node 与 npm，不带 pnpm
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# 智能体执行的命令也在这个容器里跑（D20）：
# - 中文字体（文泉驿微米黑，约 5MB）与 matplotlib 配置：图表里的中文不会显示成方框；
# - 执行命令用的普通用户 uid 1000（后端是 root，命令改用它执行：改不动项目的 Python 环境与代码）；
# - /workspace 指向工作区目录：智能体看到的路径与真实路径一致，脚本里写的绝对路径照样能用
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-wqy-microhei=0.2.0-beta-4 \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f \
    && (id -u 1000 >/dev/null 2>&1 || useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin agentexec) \
    && ln -s /app/.workdata/workspace /workspace
COPY deploy/matplotlibrc /etc/matplotlibrc
ENV MATPLOTLIBRC=/etc/matplotlibrc
# 去掉系统 Python 自带的 pip（积压小问题 D15，修订 D20）：命令里的 python 是后端的虚拟环境（里面没有 pip），系统 pip 装到
# 用户目录的包它看不到，会"装好了却用不上"；去掉后 pip 直接找不到命令，与提示词"不能安装新包"一致
RUN python -m pip uninstall -y pip

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

COPY agents ./agents
COPY backend ./backend
COPY common ./common
COPY config ./config
COPY --from=frontend /frontend/dist ./frontend/dist

EXPOSE 8000
# 停止时让进行中的运行写完结果（见 backend/main.py 的 lifespan）：exec 让 uvicorn 直接收到停止信号，
# 最多等 3 秒让连接关闭，之后中断运行并收尾
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && exec uv run --no-sync uvicorn backend.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 3"]
