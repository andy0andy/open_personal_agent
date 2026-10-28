# 首次启动写入的默认内容（D22）

后端启动时，`.workdata/` 里缺的才写入，从不覆盖；写过的部分记在 `.workdata/.seeded`（`files`、`models` 各一行），之后用户删掉的默认项不会被重新写回。

- `files/`：按 `.workdata/` 的目录结构放的默认文件——`config/mcp_servers.yaml`（`files` 服务）、`config/approval_rules.yaml`（默认审批规则）、`skills/excel/`。`config/` 下按文件、`skills/` 下按整个技能文件夹补。
- `models.yaml`：4 个模型，首次启动时经网关的模型管理接口导入网关数据库（模型页同一套检查）。之后模型全部在网关数据库里，在模型页增删改。

想找回删掉的默认项：从这里复制回 `.workdata/` 对应的位置，然后在 MCP 页点"重新加载"（技能每次运行都重读）。
