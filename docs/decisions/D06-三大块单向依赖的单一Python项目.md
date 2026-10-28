# D06：agents / backend / frontend 三大块同级、单向依赖；单一 Python 项目

- 状态：已采纳
- 日期：2026-10-12

## 背景

项目由三部分组成：智能体能力（agents）、对外提供接口与运行调度的服务（backend）、浏览器界面（frontend）。希望结构简洁，并且 agents 能脱离 HTTP 独立运行；以后还可能在 agents 下新增其他专职 agent。依赖方向如果只靠自觉，时间一长就会被破坏。

## 备选方案

设计文档没有展开比较其他整体结构。明确否定的细节做法有：给包加统一前缀或套一层 `src/` 目录（6.1 补充说明）；用 `import ... as ...` 改名来避开与 OpenAI Agents SDK 的同名冲突（6.3，做不到）。

## 结论

- 顶层 `agents/`、`backend/`、`frontend/` 同级；`common/`（与业务无关的基础设施）和 `config/`（配置读取与配置文件）是公共基础。
- 依赖只能单向：`frontend ──(HTTP 接口 + 推送协议)──→ backend ──→ agents ──→ config ──→ common`。agents 不得引用 backend；backend 只能用 agents 对外公开的内容（`build_agent` 总入口、事件定义、各模块 `__init__.py` 导出的服务与数据结构），不得深入内部子模块；agents 内各能力模块之间也只走公开服务。
- 以后在 agents 下新增的 agent 可以依赖 `main_agent`，`main_agent` 不得反向依赖它们。
- 只有一个 Python 项目：唯一的 `pyproject.toml` 与 `uv.lock`；顶层目录本身就是可直接导入的包（如 `from config import settings`）。
- 用 import-linter（检查模块之间引用关系的工具）把规则写死，违反即 `make check` 失败。
- agents 只提供能力、不管调度：记忆提取、文档处理、标题生成何时执行由 backend 决定。

落地：M0：`pyproject.toml` 的 `[tool.importlinter]`（两条规则："单向依赖"分层规则、"backend 只使用 agents 的公开入口"禁止规则），`make check` 中的 `lint-imports`；说明见 `docs/development/architecture.md` 第 2 节。

## 原因与代价

- 结构简洁，一份依赖清单、一个锁文件（配合 D12）；agents 不依赖 HTTP，可以单独运行和测试。
- 依赖方向由工具自动检查，不靠人记。
- 代价：backend 不得引用的 agents 内部模块目前在 `pyproject.toml` 里逐个列出，新增内部模块时要记得补进清单，否则检查发现不了越界。
- 代价：顶层包名 `agents` 与 OpenAI Agents SDK 的导入名相同，同一进程只能有一个。本项目不使用该 SDK；确需使用时，要么重命名本项目目录，要么（推荐）把基于该 SDK 的 agent 作为独立进程经 HTTP 或 MCP（让智能体接入外部工具的开放协议）接入。
