# 积压小问题·第四批「运维、部署与测试卫生」 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉备份恢复、镜像与 compose、配置迁移、体检、测试卫生上积压的约 14 条小问题（D15、G4～G13、I7、I14、I17）。

**Architecture:** 每条按核对明细的"最小修法"：备份恢复在 `deploy/backup.sh`、`deploy/restore.sh` 与 Makefile，镜像在 `deploy/backend.Dockerfile`，compose 在 `deploy/docker-compose.yml`，配置迁移在 `backend/settings/seed.py`，文件权限在 `backend/settings/store.py` 与 `agents/main_agent/runtime/skills.py`，体检在 `deploy/doctor.py`，测试卫生在 `backend/tests/test_test_hygiene.py`、`frontend/src/test-hygiene.test.ts` 与新的 `deploy/tests/test_wording.py`。

**Tech Stack:** bash（兼容 macOS 自带 3.2）、Makefile、Dockerfile、compose、Python 3.12、pytest、vitest。

**Spec:** `docs/specs/2026-10-26-minor-fixes-design.md`（已审定）；明细 `docs/specs/2026-10-26-minor-fixes-verification/04-设置技能与运维.md`（G、I 各行）与 `03-执行命令文件与MCP.md`（D15）。

## Global Constraints

- 不新增依赖；项目没有 git：台账 `.superpowers/sdd/2026-10-26-minor-fixes-batch4/progress.md`。不读、不打印 `.env`。
- 用户的决定（2026-10-26）：D15 去掉系统 Python 的 pip（要 `make build`）；G5 `.seeded` 随备份走（恢复时用备份里的替换，旧备份没有就不动现有的）；G8 后端跟着宿主机时区（Makefile 导出 `HOST_TZ`，compose 只给 backend 设 `TZ`）；G10 页面写配置保持原来的权限，新文件 0644；E16 不改。
- 备份脚本测试只用测试库实例里的 `backup_probe` 与临时目录；绝不对正式数据库执行恢复。
- 固定文案：G9 警告"请手动把 version 改成 1（没有这一项就加上 version: 1）"。

## Review Focus

1. G5：恢复一份没有 `.seeded` 的旧备份时，现有的 `.seeded` 不动；有的就整份替换（不合并）。
2. G8：`HOST_TZ` 取不到（不是 macOS、`/etc/localtime` 不是链接）时后端仍是 UTC，不报错；网关不跟着改。
3. G10：已经是 0600 的文件保持 0600（不擅自放宽）；新文件 0644。
4. I14：旧说法扫描不误伤测试里讲历史的文字、不误伤正常提到的 `config/models.yaml`。
5. D15：去掉 pip 后后端健康检查、`make doctor`、执行命令里的 Python 照常。

---

### Task 1: 备份与恢复（G4、G5、G13）

**Files:** `deploy/backup.sh`（`EMIT_NAME` 时才打印 `BACKUP_NAME=`；`.seeded` 存在时一起打包、manifest 记一行）、`deploy/restore.sh`（调用备份时带 `EMIT_NAME=1`；解开后有 `.seeded` 就替换）、`docs/usage.md` 第 5 节。Test: `INT deploy/tests/test_backup_scripts.py`（`test_backup_output_is_for_humans`、`test_seeded_marker_travels_with_backup`、旧备份没有 `.seeded` 时不动现有的）。

### Task 2: 镜像、compose 与 Makefile（D15、G6、G7、G8）

**Files:** `deploy/backend.Dockerfile`（删 pip；CMD 去掉 `backend.security`）、`deploy/docker-compose.yml`（backend 加 `TZ: ${HOST_TZ:-UTC}`）、`Makefile`（导出 `HOST_TZ`；`NEED_ENV` 一并建 `.workdata/shared`）。Test: `PY deploy/tests/test_compose.py`（`test_image_cmd_only_runs_existing_modules`、`test_backend_timezone_follows_host`、`test_system_python_has_no_pip`）、`PY deploy/tests/test_makefile.py::test_restart_prepares_shared_dir`；Linux 容器里 `command -v pip` 退出码 1。

### Task 3: 配置迁移与文件权限（G9、G10）

**Files:** `backend/settings/seed.py`（已有 `version: 0` 时按行替换；警告文案）、`backend/settings/store.py`、`agents/main_agent/runtime/skills.py`（写入保持原权限，新文件 0644）。Test: `PY backend/tests/test_seed.py::test_explicit_version_0_is_migrated`、`PY backend/tests/test_settings_store.py::test_page_write_keeps_file_mode`、`PY agents/tests/test_skills.py::test_state_write_keeps_file_mode`。

### Task 4: 体检（G11、G12）

**Files:** `deploy/doctor.py`（整段 JSON 数组也认；服务名从 Labels 取；Status 里的 unhealthy）。Test: `PY deploy/tests/test_doctor.py`（`test_embedding_name_matches_compose_and_seed`、`test_containers_understand_podman_ps_output`）。

### Task 5: 测试卫生（I7、I14、I17）

**Files:** `backend/tests/e2e_server.py`（`_fresh_workdata()`：固定目录，每次先删再建）、Create `deploy/tests/test_wording.py`（旧说法扫描）、`backend/tests/test_test_hygiene.py`（规则加 `anyio`、`trio`）、`agents/tests/fixtures/mcp/demo_server.py`（`hang` 注明允许等待）、`frontend/src/test-hygiene.test.ts`（按括号配对找跨行的 `setTimeout`）。Test: 各自的"规则本身"自测；`PY backend/tests/test_e2e_server.py::test_e2e_workdata_is_reused_and_cleared`。

### Task 6: 文档、全量检查、整批审查、升级与收尾

- [ ] 文档：changelog（"积压小问题·第四批"）、backlog 全部 R18～R42 定状态、R43 完成、usage（备份范围、时区）、architecture、D22 第 8 条修订（备份范围加 `.seeded`）、testing。
- [ ] `make check`、`make test-int`、`make e2e`；独立审查 → 修 Critical / Important → 全量再跑。
- [ ] 升级：查运行状态 → `make backup` → `make build`（Dockerfile 改了）→ 看启动日志 → `make doctor` → 8000 只看核对。
- [ ] 记台账，汇报全部四批的结果。
