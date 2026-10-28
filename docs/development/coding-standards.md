# 编码规范

> 以官方规范为准，代码尽量精简，与项目架构对齐（见 `architecture.md`）。

## 1. 通用

- 注释、文档字符串、文档用**中文**；代码标识符用**英文**。
- 注释只解释"为什么"，不复述代码；不留无用代码、不留注释掉的代码。
- 函数短小、职责单一；不为"以后可能"写代码。
- 优先用标准库和已选框架的原生能力，不引入功能重叠的新依赖。

## 2. Python

- 依据：PEP 8（风格）、PEP 257（文档字符串）、PEP 484 与 typing 官方文档（类型）。
- 工具：`ruff format` 统一格式；`ruff check` 规则见 `pyproject.toml`；`mypy --strict`（含 pydantic 插件）。行宽 100。
- **复杂度上限**（设计 2026-10-23 7.4）：函数的圈复杂度不超过 20（ruff C901）、语句不超过 50 条（PLR0915）；超了按职责拆小，不加 `noqa`。
- **所有输入输出操作一律异步**（数据库、HTTP、模型调用）。
- **边界数据一律用 pydantic 定义**：接口请求 / 响应、事件、配置。
- 可预期错误使用 `common.errors`（`NotFoundError` / `ConflictError` / `UpstreamError`）；不用裸 `except`。唯一允许捕获宽泛异常的地方是"运行边界"（把任何失败转成 `run.finished(failed)`），必须写 `# noqa: BLE001` 并注明原因。
- SQL：一律参数化（`%s`）；f-string 只能拼接常量列名，绝不拼接外部输入。
- FastAPI：按官方写法用 `APIRouter`、`Depends`、`lifespan`；推送用 `fastapi.sse.EventSourceResponse`（官方 SSE 支持），不额外引入 sse 库。
- LangChain / LangGraph / deepagents：按官方 API 使用；deepagents 只能出现在 `agents/main_agent/runtime/`。例外：`agents/main_agent/workspace/` 实现 deepagents 的工作区后端协议（`deepagents.backends`），这正是设计文档 4.1 的可替换"工作区"接口（换成 E2B 等云沙箱时有官方适配），只能用这个子包。
- 命名：模块与函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`；不使用会遮蔽内置名的方法名（如 `list`）。

## 3. TypeScript / React

- TypeScript 严格模式（`tsconfig.json`）；禁止非空断言 `!`（ESLint `typescript-eslint` strict）。
- 遵循官方"React 规则"与 Hooks 规则（`eslint-plugin-react-hooks` 推荐配置）：不要在 effect 里同步 setState 来派生状态——用 `key` 重建组件或在渲染时计算。
- 接口调用集中在 `src/api/`；类型从 `src/api/types.ts` 引入。它只给自动生成的类型（`src/api/generated/`，由 `make types` 从接口文档与事件定义生成，不手改）起别名；改了后端接口或事件定义后运行 `make types`，忘了会被 `make check` 发现。
- **样式只用语义样式类**（见架构规范第 5 节），不写 `bg-blue-600`、`#1a2b3c`、`rgba(...)` 这类具体颜色；颜色、字体、圆角只在 `src/themes/` 与 `src/styles/` 中定义。
- 图标统一用 `lucide-react`。
- assistant-ui 只在 `src/components/chat/` 中使用。
- Prettier 统一格式（行宽 100）。
- **复杂度上限**（设计 2026-10-23 7.4）：函数的圈复杂度不超过 20（eslint `complexity`）、语句不超过 50 条（`max-statements`）；组件超了就把一块界面拆成子组件、把一组状态拆成 hook（如 `features/chat/useUploads.ts`）。

## 4. 依赖与版本（D12）

- Python：`uv add 包名==版本`（直接依赖一律精确版本）；安装 `uv sync --locked`。
- 前端：`pnpm add -E 包名@版本`（`.npmrc` 已设 `save-exact=true`）；安装 `pnpm install --frozen-lockfile`。
- **冷却期 3 天**（设计 2026-10-23 7.5）：uv 的 `exclude-newer = "3 days"`（`pyproject.toml`）、pnpm 的 `minimumReleaseAge: 4320`（`frontend/pnpm-workspace.yaml`），新发布不满 3 天的版本不装（被投毒的包多在几天内被发现下架）。遇到时改选更早的稳定版本，不要放宽策略。
- 升级依赖要在 `docs/changelog.md` 记录原因；避开 litellm 1.82.7 / 1.82.8（曾被投毒）。

## 5. 文档同步（完成定义的一部分）

一个功能做到以下三点才算完成：
1. 更新 `docs/requirements/backlog.md` 的状态（较大功能另写 `docs/requirements/YYYY-MM-DD-<功能>.md`）；
2. 涉及架构取舍时，在 `docs/decisions/` 补决策记录；
3. 在 `docs/changelog.md` 记一笔。

（提交信息规范"约定式提交"待建立 git 仓库后启用。）
