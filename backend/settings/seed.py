"""首次启动写入默认内容（D22）：.workdata 里缺的默认文件、网关里缺的模型；升级时的一次性
补做（打开提示缓存、补建会话索引）；每次启动先把配置文件迁移到当前格式版本。

只补缺的、从不覆盖；做过的部分记在 .workdata/.seeded（files、models、prompt_caching、
conversation_index 各一行），之后用户删掉的默认项不会被重新写回。
网关暂时连不上时模型这一部分不记，下次启动再导入。
"""

import logging
import re
import shutil
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from agents.main_agent.conversations import ConversationIndex
from backend.models import ModelAdmin
from backend.models.schemas import ModelInput
from backend.runs.followups import CONVERSATION_INDEX
from backend.runs.repo import RunRepo
from backend.settings.store import UserConfigFiles
from common.errors import InvalidConfigError, UpstreamError
from config import CONFIG_VERSIONS, config_version, display_path, is_preamble_line

logger = logging.getLogger(__name__)

_MARKER = ".seeded"
# 顶格写的 version: 0（后面只能是空白或注释）：迁移时只改这个数，行尾注释留着
_VERSION_0 = re.compile(r"^version:[ \t]*0(?=[ \t]*(?:#.*)?$)", re.MULTILINE)


def migrate_config_files(config_dir: Path, *, now: datetime) -> list[str]:
    """把 .workdata/config 里的配置文件逐步迁移到当前格式版本（设计 2026-10-23 7.3）。

    在写默认文件之前做。要改的先原样复制到 history/<文件名>.<时间>.bak；不存在的、空的、已是
    当前（或更新）版本的不动；写坏的、没法安全改的也不动，只记警告（页面与"重新加载"会报出原因）。
    返回迁移了的文件名。
    """
    files = UserConfigFiles(config_dir)
    migrated: list[str] = []
    for name, current in CONFIG_VERSIONS.items():
        path = files.path(name)
        label = display_path(path)
        try:
            data = files.read(name)
            version = config_version(data, label=label)
        except InvalidConfigError as exc:
            logger.warning("%s；这个文件先不迁移", exc)
            continue
        if not data or version >= current:
            continue
        text = _migrate(path.read_text(encoding="utf-8"), version, current)
        if text is None:
            logger.warning(
                "%s 没法自动改成第 %d 版，内容没动："
                "请手动把 version 改成 %d（没有这一项就加上 version: %d）",
                label,
                current,
                current,
                current,
            )
            continue
        history = config_dir / "history"
        try:
            history.mkdir(exist_ok=True)
            shutil.copy2(path, history / f"{name}.{now:%Y%m%d-%H%M%S}.bak")
            files.write_text(name, text)
        except OSError as exc:
            logger.warning("%s 没能迁移（%s），内容没动", label, exc)
            continue
        migrated.append(name)
    if migrated:
        logger.info("配置文件已迁移到当前格式：%s（原文件备份在 history/）", "、".join(migrated))
    return migrated


def seed_files_once(workdata: Path, seed_dir: Path) -> list[str]:
    """把 seed_dir/files 里 .workdata 缺的项写进去：config/ 下按文件，skills/ 下按整个技能文件夹。

    返回写入的相对路径；已经写过一次（标记里有 files）时什么都不做。
    """
    if "files" in _done(workdata):
        return []
    source = seed_dir / "files"
    written: list[str] = []
    for item in _seed_items(source):
        relative = item.relative_to(source)
        target = workdata / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        written.append(relative.as_posix())
    _mark(workdata, "files")
    if written:
        logger.info("首次启动写入默认内容：%s", "、".join(written))
    return written


def load_seed_models(path: Path) -> list[ModelInput]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [ModelInput.model_validate(item) for item in data.get("models") or []]


async def seed_models_once(
    workdata: Path, models: ModelAdmin, items: Sequence[ModelInput]
) -> list[str]:
    """把网关里还没有的模型导入（模型页同一套检查）；全部成功后才记标记。

    返回这次加上的模型名；网关出错时记日志、不记标记，返回已经加上的。
    """
    if "models" in _done(workdata):
        return []
    added: list[str] = []
    try:
        existing = {model.name for model in (await models.list()).models}
        for item in items:
            if item.name in existing:
                continue
            await models.add(item)
            added.append(item.name)
    except UpstreamError:
        logger.warning("导入默认模型时网关出错，下次启动再试（已导入：%s）", added, exc_info=True)
        return added
    _mark(workdata, "models")
    if added:
        logger.info("首次启动导入模型：%s", "、".join(added))
    return added


async def enable_prompt_caching_once(workdata: Path, models: ModelAdmin) -> list[str]:
    """升级时给现有的 Claude 模型打开一次提示缓存（设计 2026-10-23 4.1）。

    记过标记就不再做：之后用户手动关掉的不会被重新打开。网关出错时不记标记，下次启动再试。
    """
    if "prompt_caching" in _done(workdata):
        return []
    try:
        result = await models.enable_prompt_caching()
    except UpstreamError:
        logger.warning("打开提示缓存时网关出错，下次启动再试", exc_info=True)
        return []
    if result is None:  # 网关还没载入数据库里的模型：不记标记，否则以后再也不会打开
        logger.warning("网关里还没有数据库里的模型（可能刚启动），下次启动再打开提示缓存")
        return []
    changed = list(result)
    _mark(workdata, "prompt_caching")
    if changed:
        logger.info("首次打开提示缓存：%s", "、".join(changed))
    return changed


class _Enqueue(Protocol):
    async def enqueue(self, kind: str, payload: dict[str, Any]) -> Any: ...


async def backfill_conversation_index_once(
    workdata: Path, runs: RunRepo, jobs: _Enqueue, conversations: ConversationIndex
) -> int:
    """升级后把已有的历史补进会话索引（设计 2026-10-23 6.1，jieba 只能在 Python 里跑）：
    已结束、还没索引的运行逐个登记写索引的后台任务，返回登记了几个。只做一次（.seeded 记
    conversation_index）；任务在队列里，中途重启也会接着做。"""
    if "conversation_index" in _done(workdata):
        return 0
    finished = await runs.finished_ids()
    missing = await conversations.missing(finished)
    for run_id in [run for run in finished if run in missing]:  # 按时间先后
        await jobs.enqueue(CONVERSATION_INDEX, {"run_id": str(run_id)})
    _mark(workdata, "conversation_index")
    if missing:
        logger.info("补建会话索引：登记了 %d 次运行", len(missing))
    return len(missing)


def _add_version(text: str) -> str | None:
    """第 0 版 → 第 1 版：已经写了 version: 0 的把它改成 1（再插一行会有两个 version，读出来还是
    后一个 0）；没写的在开头的注释、空行、"---" 之后插一行 version: 1。其余原样不动。

    改完读出来的内容必须正好只是 version 变成 1；做不到（比如整个文件写成一行 {…}）时返回 None。
    """
    original = yaml.safe_load(text)
    if "version" in original:
        migrated = _VERSION_0.sub("version: 1", text, count=1)
    else:
        lines = text.splitlines(keepends=True)
        head = 0
        while head < len(lines) and is_preamble_line(lines[head]):
            head += 1
        migrated = "".join([*lines[:head], "version: 1\n", *lines[head:]])
    try:
        same = yaml.safe_load(migrated) == {**original, "version": 1}
    except yaml.YAMLError:
        return None
    return migrated if same else None


# 第 n 版 → 第 n+1 版的改法（改的是原文，保留注释）；以后改了文件格式就在这里加一步
_STEPS: dict[int, Callable[[str], str | None]] = {0: _add_version}


def _migrate(text: str, version: int, current: int) -> str | None:
    for step in range(version, current):
        migrated = _STEPS[step](text)
        if migrated is None:
            return None
        text = migrated
    return text


def _seed_items(source: Path) -> list[Path]:
    items: list[Path] = []
    config = source / "config"
    if config.is_dir():
        items += sorted(path for path in config.iterdir() if path.is_file())
    skills = source / "skills"
    if skills.is_dir():
        items += sorted(path for path in skills.iterdir() if path.is_dir())
    return items


def _done(workdata: Path) -> set[str]:
    marker = workdata / _MARKER
    return set(marker.read_text(encoding="utf-8").split()) if marker.exists() else set()


def _mark(workdata: Path, part: str) -> None:
    done = _done(workdata) | {part}
    workdata.mkdir(parents=True, exist_ok=True)
    (workdata / _MARKER).write_text("\n".join(sorted(done)) + "\n", encoding="utf-8")
