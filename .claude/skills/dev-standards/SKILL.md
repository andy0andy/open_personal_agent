---
name: dev-standards
description: 在 open_personal_agent 项目中开发、修改、审查或重构任何代码之前必须加载（Python 智能体与后端、React 前端、配置、docker compose、数据库迁移、测试）。给出架构边界、编码规范、测试要求与完成定义；细节在 docs/development/ 下的三份规范中。
---

# open_personal_agent 开发规范（要点与检查清单）

开始前，按改动范围阅读：
- 架构与目录：`docs/development/architecture.md`
- 编码规范：`docs/development/coding-standards.md`
- 测试规范：`docs/development/testing.md`
- 设计文档：`docs/specs/2026-10-10-personal-agent-design.md`

## 硬性规则

1. 依赖方向 `backend → agents → config → common`；backend 只用 agents 各模块 `__init__.py` 公开的内容。
2. 外部依赖必须藏在可替换接口后面，在 `agents/main_agent/bootstrap.py` 装配，并有契约测试；其他地方不预设抽象。
3. deepagents 只能出现在 `agents/main_agent/runtime/`；例外是 `workspace/` 可用 `deepagents.backends`（工作区后端协议）。
4. 所有输入输出异步；边界数据用 pydantic；SQL 参数化；可预期错误用 `common.errors`。
5. 第三方服务一律进 `deploy/docker-compose.yml`；配置进 `config/`；密钥只在 `.env`。
6. 直接依赖一律精确版本（`uv add 包==版本`、`pnpm add -E`）。
7. 中文注释与文档，英文标识符；注释只写"为什么"。
8. 当前没有 git 仓库：不要执行 git 命令。

## 开发流程

0. 先核对需求、保持质疑：对照现有规则、决策记录、已有功能和实际部署方式，需求有冲突、重复、过度或前提不成立时，先向用户指出并给出建议，确认后再做（用户有时会忘记项目细节，见 `CLAUDE.md` 的约定）。
1. 在 `docs/requirements/backlog.md` 登记或认领需求（较大功能写需求记录）。
2. 涉及架构取舍：先写 `docs/decisions/` 决策记录。
3. 先写失败的测试，再写最少的实现让它通过。
4. 运行 `make check`（数据库相关再运行 `make test-int`）。
5. 文档同步：backlog 状态、`docs/changelog.md`，必要时更新 `architecture.md`。

## 完成定义

- [ ] `make check` 通过（格式、类型、依赖方向、前后端单元测试）
- [ ] 涉及数据库：`make test-int` 通过
- [ ] 新的外部依赖有接口、契约测试并在组装根登记
- [ ] backlog、changelog（必要时决策记录、架构规范）已更新
