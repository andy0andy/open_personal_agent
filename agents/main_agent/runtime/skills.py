"""智能体技能（设计文档 7.4）：技能目录下每个子文件夹里的 SKILL.md 是一个技能。

技能的加载由 deepagents 负责（按需读全文）；这里列出有哪些技能，给技能页看。
只有一个目录 .workdata/skills/（D22）：首次启动写入的 excel 与上传的都在这里，都能停用、删除；
停用清单在 .workdata/config/skills.yaml。技能按文件夹名区分，上传的不许与已有的同名。
"""

import logging
import os
import secrets
import shutil
import stat
import tempfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel

from common.errors import ConflictError, InvalidConfigError, InvalidRequestError, NotFoundError
from config import CONFIG_VERSIONS, display_path, leading_comments, read_config_yaml

logger = logging.getLogger(__name__)

_INCOMPLETE = "说明头不完整（需要 name 与 description）"
# 技能说明的长度（设计 2026-10-23 7.7）：每次对话都把所有技能的说明放进提示词，所以要短；
# deepagents 只保留前 1024 字（MAX_SKILL_DESCRIPTION_LENGTH）
_SHORT_ENOUGH = 300
_KEPT = 1024
_HEADER = "# 由管理页面写入，也可以手改：disabled 里的技能智能体看不到（D22）\n"


class SkillInfo(BaseModel):
    id: str = ""  # 文件夹名：停用、删除、查看都按它
    name: str
    description: str
    error: str | None = None  # 说明头写错时给用户看的原因（deepagents 会跳过这个技能）
    enabled: bool = True
    location: str = ""  # 存放位置，如 .workdata/skills/excel/
    added_at: date | None = None  # 取文件夹的修改日期
    notice: str | None = None  # 说明太长时的提示（上传时与技能页上都显示）
    last_used_at: datetime | None = None  # 最近一次读它的说明；由设置接口按技能用量填写


class SkillDetail(SkillInfo):
    body: str  # 去掉开头说明后的正文
    files: list[str]  # 相对路径，排好序；不含隐藏文件


class SkillPackage(BaseModel):
    """检查过的上传包：files 的键是相对路径（已去掉共同的第一层文件夹）。"""

    name: str
    description: str
    files: dict[str, bytes]


def list_skills(skills_dir: Path | None) -> list[SkillInfo]:
    """按文件夹名排序列出一个目录里的技能；没有技能目录时为空。"""
    return [_read(folder.name, folder / "SKILL.md") for folder in _folders(skills_dir)]


def _folders(skills_dir: Path | None) -> Iterator[Path]:
    if skills_dir is None or not skills_dir.is_dir():
        return
    for folder in sorted(skills_dir.iterdir()):
        if not folder.name.startswith(".") and (folder / "SKILL.md").is_file():
            yield folder


def read_front_matter(text: str) -> tuple[str, str] | str:
    """读 SKILL.md 开头的 name 与 description；写错时返回给用户看的原因。"""
    # 说明头夹在开头两行 --- 之间；少了结束的 --- 也按写错处理
    text = text.removeprefix("\ufeff")
    parts = text.split("---", 2) if text.startswith("---") else []
    head = parts[1] if len(parts) == 3 else ""
    try:
        meta = yaml.safe_load(head) if head else None
    except yaml.YAMLError:
        meta = None
    if not isinstance(meta, dict):
        return _INCOMPLETE
    # 照 deepagents 先去掉首尾空白再看：竖线块末尾的换行不算长度，只有空白的说明它会跳过
    # 这个技能，这里也算不完整（积压小问题 F2）
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name or not description:
        return _INCOMPLETE
    return name, description


def description_notice(description: str) -> str | None:
    """说明太长时给用户的提示；不长时为 None。"""
    length = len(description)
    if length > _KEPT:
        return f"说明有 {length} 字，超过 {_KEPT} 字的部分会被截断：智能体只读前 {_KEPT} 字"
    if length > _SHORT_ENOUGH:
        return f"说明有 {length} 字，说明尽量短：每次对话智能体都要读一遍所有技能的说明"
    return None


def _body(text: str) -> str:
    text = text.removeprefix("\ufeff")
    parts = text.split("---", 2) if text.startswith("---") else []
    return (parts[2] if len(parts) == 3 else text).strip()


class SkillCatalog:
    """技能目录里的技能，加上停用清单（D22：只有 .workdata/skills/ 一处）。"""

    def __init__(self, skills_dir: Path | None, state_file: Path | None = None) -> None:
        self.skills_dir = skills_dir
        self._state_file = state_file

    def list(self) -> list[SkillInfo]:
        hidden = self.hidden()
        result: list[SkillInfo] = []
        for folder in _folders(self.skills_dir):
            info = _read(folder.name, folder / "SKILL.md")
            result.append(
                info.model_copy(
                    update={
                        "id": folder.name,
                        "enabled": folder.name not in hidden,
                        "location": f"{display_path(folder)}/",
                        "added_at": _modified(folder),
                    }
                )
            )
        return result

    def detail(self, skill_id: str) -> SkillDetail:
        info = self._find(skill_id)
        folder = self._folder(info)
        text = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        files = sorted(
            path.relative_to(folder).as_posix()
            for path in folder.rglob("*")
            if path.is_file() and not any(p.startswith(".") for p in path.relative_to(folder).parts)
        )
        return SkillDetail(**info.model_dump(), body=_body(text), files=files)

    def hidden(self) -> frozenset[str]:
        """停用的技能（文件夹名）：每次现读，停用、启用都不用重新加载。

        停用清单写坏了（手改出错）时什么都不隐藏、记日志：不能因为它让所有对话失败。
        """
        try:
            return self._read_state()
        except InvalidConfigError as exc:
            logger.warning("技能停用清单有误，先不隐藏任何技能：%s", exc)
            return frozenset()

    def state_error(self) -> str | None:
        """停用清单写坏时给用户看的原因。"""
        try:
            self._read_state()
        except InvalidConfigError as exc:
            return str(exc)
        return None

    def _read_state(self) -> frozenset[str]:
        if self._state_file is None:
            return frozenset()
        disabled = read_config_yaml(self._state_file).get("disabled") or []
        if not isinstance(disabled, list) or not all(isinstance(n, str) for n in disabled):
            raise InvalidConfigError(
                f"{display_path(self._state_file)} 有误：disabled 应是技能文件夹名的列表"
            )
        return frozenset(disabled)

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillInfo:
        self._find(skill_id)
        disabled = set(self._read_state())  # 写坏了就报原因，不覆盖用户的文件
        if enabled:
            disabled.discard(skill_id)
        else:
            disabled.add(skill_id)
        self._write_state(disabled)
        return self._find(skill_id)

    def install(self, package: SkillPackage) -> SkillInfo:
        """装进技能目录：先写到临时文件夹，写完再改名，免得留下半个技能。"""
        if self.skills_dir is None:
            raise InvalidRequestError("没有配置技能目录")
        taken = {skill.id.casefold() for skill in self.list()} | {
            skill.name.casefold() for skill in self.list()
        }
        # Mac 的文件系统不分大小写：Excel 和 excel 是同一个文件夹
        if package.name.casefold() in taken:
            raise ConflictError(f"已有同名技能：{package.name}")
        if (self.skills_dir / package.name).exists():
            # 不是技能的同名文件夹（没有 SKILL.md）：原来改名失败报 500（积压小问题 F5）
            raise ConflictError(
                f"技能目录里已有同名文件夹 {package.name}（里面没有 SKILL.md）：先删掉或改名"
            )
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        staging = self.skills_dir / f".installing-{secrets.token_hex(4)}"
        try:
            for relative, data in package.files.items():
                target = (staging / relative).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise InvalidRequestError(f"文件路径不合法：{relative}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            staging.rename(self.skills_dir / package.name)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return self._find(package.name)

    def remove(self, skill_id: str) -> None:
        """删除一个技能（任何技能都能删，D22），连同它在停用清单里的那一行。"""
        info = self._find(skill_id)
        shutil.rmtree(self._folder(info))
        if skill_id in self.hidden():
            self._write_state(set(self._read_state()) - {skill_id})

    def _find(self, skill_id: str) -> SkillInfo:
        for info in self.list():
            if info.id == skill_id:
                return info
        raise NotFoundError(f"没有这个技能：{skill_id}")

    def _folder(self, info: SkillInfo) -> Path:
        assert self.skills_dir is not None  # list() 只会列出存在的目录
        return self.skills_dir / info.id

    def _write_state(self, disabled: set[str]) -> None:
        if self._state_file is None:
            raise InvalidRequestError("没有配置技能的停用清单")
        directory = self._state_file.parent
        directory.mkdir(parents=True, exist_ok=True)
        # 版本号和手写的其他字段都留着（设计 2026-10-23 7.3）；调用前已读过一次，文件没写坏
        data = {
            "version": CONFIG_VERSIONS["skills.yaml"],
            **read_config_yaml(self._state_file),
            "disabled": sorted(disabled),
        }
        # 开头的注释留着（积压小问题 F8）；原文没有开头注释时才写一行说明
        existing = self._state_file.read_text(encoding="utf-8") if self._state_file.exists() else ""
        head = leading_comments(existing)
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        text = (head if head.strip() else _HEADER) + body
        # mkstemp 建的是 0600：保持原来的权限（不擅自放宽或收紧），新文件 0644 和默认文件一样，
        # 执行命令的普通用户也读得到（积压小问题 G10）
        mode = stat.S_IMODE(self._state_file.stat().st_mode) if self._state_file.exists() else 0o644
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".skills.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                os.fchmod(file.fileno(), mode)
                file.write(text)
            os.replace(tmp, self._state_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _modified(folder: Path) -> date:
    return datetime.fromtimestamp(folder.stat().st_mtime, UTC).date()


def is_safe_relative(path: str) -> bool:
    """相对路径不能跳出技能文件夹：不能是绝对路径、不能有 ..、不能用反斜杠。"""
    if not path or "\\" in path:
        return False
    parts = PurePosixPath(path).parts
    return not PurePosixPath(path).is_absolute() and ".." not in parts


def _read(folder: str, path: Path) -> SkillInfo:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return SkillInfo(
            id=folder, name=folder, description="", error="SKILL.md 不是 UTF-8 文字：请另存为 UTF-8"
        )
    meta = read_front_matter(text)
    if isinstance(meta, str):
        return SkillInfo(id=folder, name=folder, description="", error=meta)
    return SkillInfo(
        id=folder, name=meta[0], description=meta[1], notice=description_notice(meta[1])
    )
