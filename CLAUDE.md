# open_personal_agent

个人智能体：deepagents + LiteLLM 网关 + PostgreSQL + FastAPI + React。设计文档：`docs/specs/2026-10-10-personal-agent-design.md`。

**开发、修改、审查任何代码前，先加载 `dev-standards` 技能**（`.claude/skills/dev-standards/SKILL.md`）。

## 常用命令

| 命令 | 作用 |
|---|---|
| `make install` | 严格按锁文件安装前后端依赖 |
| `make infra-up` | 启动数据库、网关、Ollama，并拉取向量模型 |
| `make up` | 一键启动全部服务，然后打开 http://127.0.0.1:8000（日常使用的地址；等同于 `cd deploy && podman compose up -d`） |
| `make restart` | 改了 `.env` 后重建后端容器（用的是镜像里的代码） |
| `make build` | 改了代码、依赖或前端界面后重新构建镜像并启动（后端不挂源码，2026-10-28 起） |
| `make bundle` | 在构建电脑上把全部镜像打包成一个文件，拿到别的机器 `podman load` 后直接 compose 启动 |
| `make web` | 前端开发服务器 http://127.0.0.1:5173（只在开发界面时用：改代码即时生效，接口转发到 8000） |
| `make types` | 改了后端接口或事件定义后，重新生成前端类型 |
| `make check` | 格式、类型（含生成的前端类型是否最新）、依赖方向、前后端单元测试 |
| `make test-int` | 集成测试（自动启动测试数据库） |
| `make e2e` | 端到端测试：本机 Chrome 自动点一遍主要流程（测试库 + 假模型，不花钱） |
| `make smoke` | 真实模型先行验证（会产生少量费用） |
| `make doctor` | 体检（只读）：容器、后端、网关、模型、Ollama、数据库、`.workdata` 文件、磁盘与备份，逐项 ✓ / ✗，✗ 下面写怎么修 |
| `make backup` / `make restore BACKUP=<名字>` | 备份到 `.workdata/backups/`（保留 7 份）/ 恢复（恢复前自动备份当前数据） |
| `make down` | 停止所有服务 |

## 约定

- 用中文交流与写文档；代码标识符用英文。
- 代码在 git 仓库里：只有用户明确要求时才提交，推送由用户自己做。
- 一个功能完成 = `make check` 通过 + backlog / changelog 已更新（见 `docs/development/coding-standards.md` 第 5 节）。
- **需求先核对、保持质疑**：用户有时会忘记项目细节。沟通和开发新需求前，先对照现有的开发规则与已有功能（架构规范、决策记录、需求池、实际代码与部署方式）。需求与现状冲突、重复、过度，或者前提不成立时，先指出来、说明理由并给出建议，用户确认后再做；不要照字面直接实现。例：用户要"显示绝对路径"，而智能体本来就跑在容器里，`/workspace/<会话>/` 已经是容器里的绝对路径——应当先说明这一点，而不是去取 Mac 上的路径（2026-10-18，这次改动已回退）。
