"""管理页面写配置文件（D22）：保留你写在开头的注释（积压小问题 F8）。"""

import stat
from pathlib import Path

from backend.settings.store import UserConfigFiles


def test_page_write_keeps_leading_comments(tmp_path: Path) -> None:
    files = UserConfigFiles(tmp_path)
    files.write_text(
        "approval_rules.yaml",
        "# 我自己的说明\n# 第二行\n\nversion: 1\nmcp_default: ask\ntools: {}\n",
    )
    files.write("approval_rules.yaml", {"version": 1, "mcp_default": "auto", "tools": {}})
    text = (tmp_path / "approval_rules.yaml").read_text(encoding="utf-8")
    assert text.startswith("# 我自己的说明\n# 第二行\n\nversion: 1\n")
    assert text.count("version:") == 1
    assert files.read("approval_rules.yaml")["mcp_default"] == "auto"


def test_page_write_without_comments_adds_the_note(tmp_path: Path) -> None:
    files = UserConfigFiles(tmp_path)
    files.write("approval_rules.yaml", {"mcp_default": "ask"})
    text = (tmp_path / "approval_rules.yaml").read_text(encoding="utf-8")
    assert text.startswith("# 由管理页面写入，也可以手改（D22）\n")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_page_write_keeps_file_mode(tmp_path: Path) -> None:
    """页面写入保持文件原来的权限（不擅自放宽，也不收紧），新文件 0644（积压小问题 G10）。"""
    files = UserConfigFiles(tmp_path)
    files.write("approval_rules.yaml", {"mcp_default": "ask"})
    assert _mode(tmp_path / "approval_rules.yaml") == 0o644
    for mode in (0o600, 0o644):
        files.write_text("mcp_servers.yaml", "version: 1\nservers: {}\n")
        (tmp_path / "mcp_servers.yaml").chmod(mode)
        files.write("mcp_servers.yaml", {"servers": {}})
        assert _mode(tmp_path / "mcp_servers.yaml") == mode
