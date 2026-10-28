"""设置页的".workdata 里的文件"（D22）：各文件的位置、用途与状态，写坏时给出原因。"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from agents.main_agent.runtime import SkillCatalog
from common.errors import InvalidConfigError
from config import (
    Settings,
    display_path,
    load_approval_rules,
    load_mcp_servers,
    read_config_yaml,
)


class DataFileView(BaseModel):
    path: str  # 如 .workdata/config/mcp_servers.yaml
    purpose: str
    state: Literal["ok", "missing", "error"]
    detail: str | None = None  # 写坏时的原因


def data_file_views(settings: Settings, skills: SkillCatalog | None) -> list[DataFileView]:
    """依次：MCP 服务清单、审批规则、停用的技能、技能目录。每次现读，手改坏了也能马上看到。"""
    servers, rules = settings.mcp_servers_file, settings.approval_rules_file

    def load_servers() -> None:
        load_mcp_servers(read_config_yaml(servers), os.environ, label=display_path(servers))

    def load_rules() -> None:
        load_approval_rules(read_config_yaml(rules), label=display_path(rules))

    def skills_state() -> None:
        error = skills.state_error() if skills is not None else None
        if error:
            raise InvalidConfigError(error)

    count = len(skills.list()) if skills is not None else 0
    return [
        _file(servers, "MCP 服务清单", load_servers),
        _file(rules, "审批规则", load_rules),
        _file(settings.skills_state_file, "停用的技能", skills_state),
        DataFileView(
            path=f"{display_path(settings.skills_dir)}/",
            purpose=f"技能（{count} 个）",
            state="ok" if settings.skills_dir.is_dir() else "missing",
        ),
    ]


def _file(path: Path, purpose: str, check: Callable[[], None]) -> DataFileView:
    shown = display_path(path)
    if not path.exists():
        return DataFileView(path=shown, purpose=purpose, state="missing")
    try:
        check()
    except InvalidConfigError as exc:
        return DataFileView(path=shown, purpose=purpose, state="error", detail=str(exc))
    return DataFileView(path=shown, purpose=purpose, state="ok")
