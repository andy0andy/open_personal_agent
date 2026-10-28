"""管理页面写入的配置文件（D22）：都在 .workdata/config/ 下，只有这一份。"""

import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

from config import CONFIG_VERSIONS, leading_comments, read_config_yaml

_HEADER = "# 由管理页面写入，也可以手改（D22）\n"


class UserConfigFiles:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, name: str) -> Path:
        return self.directory / name

    def read(self, name: str) -> dict[str, Any]:
        """文件不存在时为空；写坏了（手改出错）时抛 InvalidConfigError，页面的修改随之被拒绝。"""
        return read_config_yaml(self.path(name))

    def write(self, name: str, data: dict[str, Any]) -> None:
        """页面写的都是当前格式：没写版本号的补上（设计 2026-10-23 7.3），其余字段原样保留。
        开头的注释留着（积压小问题 F8）；原文没有开头注释时才写一行说明。"""
        if name in CONFIG_VERSIONS and "version" not in data:
            data = {"version": CONFIG_VERSIONS[name], **data}
        path = self.path(name)
        head = leading_comments(path.read_text(encoding="utf-8")) if path.exists() else ""
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        self.write_text(name, (head if head.strip() else _HEADER) + body)

    def write_text(self, name: str, text: str) -> None:
        """原子写入：先写同目录的临时文件再换名，写到一半停电也不会留下半份文件。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(name)
        # mkstemp 建的是 0600：保持原来的权限（不擅自放宽或收紧），新文件 0644 和默认文件一样，
        # 执行命令的普通用户也读得到（积压小问题 G10）
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                os.fchmod(file.fileno(), mode)
                file.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
