"""工具真正开始执行时推 tool.running（设计 2026-10-23 5.7）；读技能说明时带上技能名（6.8）。"""

from typing import Any

import pytest

from agents.main_agent.runtime.tool_running import skill_of


@pytest.mark.parametrize(
    ("args", "skill"),
    [
        ({"file_path": "/skills/excel/SKILL.md"}, "excel"),
        ({"file_path": "/skills/excel/../excel/SKILL.md"}, "excel"),
        ({"file_path": "/skills/excel/SKILL.md", "offset": 0}, "excel"),
        ({"file_path": "/skills/excel/SKILL.md", "offset": 100}, None),  # 分页往下读不重复记
        ({"file_path": "/skills/excel/reference.md"}, None),
        ({"file_path": "/workspace/c_00000001/SKILL.md"}, None),
        ({}, None),
    ],
)
def test_reading_a_skill_file_names_the_skill(args: dict[str, Any], skill: str | None) -> None:
    assert skill_of("read_file", args) == skill


def test_only_read_file_counts_as_using_a_skill() -> None:
    assert skill_of("grep", {"file_path": "/skills/excel/SKILL.md"}) is None
