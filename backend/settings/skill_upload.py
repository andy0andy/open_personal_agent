"""上传技能包的检查（D21）：技能文件夹 / .zip / 单个 SKILL.md。

全部在内存里检查完才交给 SkillCatalog 落盘：坏路径、软链接、超大的包一个文件都不写。
"""

import base64
import binascii
import io
import lzma
import re
import stat
import zipfile
import zlib
from pathlib import PurePosixPath

from agents.main_agent.runtime import SkillPackage, is_safe_relative, read_front_matter
from common.errors import InvalidRequestError, TooLargeError

MAX_SKILL_FILES = 500  # 大小上限与附件、文档共用设置 max_upload_mb，由调用方给出
# 技能名就是文件夹名：文字（含中文）、数字、- 和 _，不能以 - 开头
_SKILL_NAME = re.compile(r"^\w[\w-]{0,63}$")
_UNSUPPORTED = "只能上传技能文件夹、.zip 或 SKILL.md"
_NO_SKILL_MD = "文件夹或压缩包里要有 SKILL.md"
# zipfile 读一项时可能抛的：坏数据、加密（RuntimeError）、不支持的压缩方式（NotImplementedError）
_UNREADABLE = (
    zipfile.BadZipFile,
    zlib.error,
    lzma.LZMAError,
    EOFError,
    OSError,
    RuntimeError,
    NotImplementedError,
)


def decode_upload(files: list[tuple[str, str]], *, max_bytes: int) -> list[tuple[str, bytes]]:
    """(路径, base64) → (路径, 内容)；先按 base64 的长度粗查大小，免得解出一大块再拒绝。"""
    if sum(len(content) for _, content in files) > max_bytes * 4 // 3 + 4 * len(files):
        raise TooLargeError(_too_big(max_bytes))
    try:
        return [(path, base64.b64decode(content, validate=True)) for path, content in files]
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequestError("上传的内容不完整，请重新选择文件") from exc


def parse_skill_upload(files: list[tuple[str, bytes]], *, max_bytes: int) -> SkillPackage:
    """files 的每一项是（相对路径，内容）；选择文件夹时路径带着文件夹名。"""
    if len(files) == 1 and files[0][0].lower().endswith(".zip"):
        entries = _unzip(files[0][1], max_bytes)
    elif len(files) == 1 and PurePosixPath(files[0][0]).name != "SKILL.md":
        raise InvalidRequestError(_UNSUPPORTED)
    else:
        entries = list(files)  # 反斜杠路径在下面按不合法拒绝
    entries = [(path, data) for path, data in entries if not _is_metadata(path)]
    _check_size(len(entries), sum(len(data) for _, data in entries), max_bytes)
    for path, _ in entries:
        if not is_safe_relative(path):
            raise InvalidRequestError(f"文件路径不合法：{path}")
    relative = _strip_common_folder({path: data for path, data in entries})
    if len({path.casefold() for path in relative}) < len(relative):
        # Mac 的磁盘不分大小写，写进去时后一个会盖掉前一个（积压小问题 F11）
        raise InvalidRequestError(
            "有只差大小写的同名文件（如 SKILL.md 与 skill.md），在 Mac 上会互相覆盖：改名后再传"
        )
    if "SKILL.md" not in relative:
        raise InvalidRequestError(_NO_SKILL_MD)
    try:
        text = relative["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidRequestError("SKILL.md 不是 UTF-8 文字：请另存为 UTF-8") from exc
    meta = read_front_matter(text)
    if isinstance(meta, str):
        raise InvalidRequestError(f"SKILL.md 的{meta}")
    name, description = meta
    if not _SKILL_NAME.match(name):
        raise InvalidRequestError("技能名只能用文字、数字、- 和 _（最多 64 个字），用作文件夹名")
    return SkillPackage(name=name, description=description, files=relative)


def _unzip(data: bytes, max_bytes: int) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidRequestError("压缩包打不开：不是有效的 .zip 文件") from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        # 先按压缩包里写的解压后大小检查，免得一个很小的压缩包解开后占满内存
        _check_size(len(infos), sum(info.file_size for info in infos), max_bytes)
        entries: list[tuple[str, bytes]] = []
        for info in infos:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise InvalidRequestError(f"压缩包里有链接文件，不能安装：{info.filename}")
            if not is_safe_relative(info.filename):
                raise InvalidRequestError(f"文件路径不合法：{info.filename}")
            entries.append((info.filename, _read_entry(archive, info)))
    return entries


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """读出一项；坏了（CRC 不符、谎报大小）、加了密码、压缩方式不认识时说清楚
    （积压小问题 F5，原来 500）。"""
    try:
        return archive.read(info)
    except _UNREADABLE as exc:
        raise InvalidRequestError(
            f"压缩包里的 {info.filename} 读不出来：可能已损坏、加了密码或用了不支持的压缩方式"
        ) from exc


def _check_size(count: int, total: int, max_bytes: int) -> None:
    if count > MAX_SKILL_FILES:
        raise TooLargeError(f"技能里的文件太多：最多 {MAX_SKILL_FILES} 个")
    if total > max_bytes:
        raise TooLargeError(_too_big(max_bytes))


def _too_big(max_bytes: int) -> str:
    return f"技能太大：最多 {max_bytes // 1024 // 1024}MB"


def _is_metadata(path: str) -> bool:
    """Mac 打包时夹带的 __MACOSX/ 与 .DS_Store。"""
    parts = PurePosixPath(path).parts
    return "__MACOSX" in parts or (bool(parts) and parts[-1] == ".DS_Store")


def _strip_common_folder(files: dict[str, bytes]) -> dict[str, bytes]:
    """所有文件都在同一个第一层文件夹里时去掉它（选择文件夹、zip 里套了一层文件夹）。"""
    tops = {PurePosixPath(path).parts[0] for path in files}
    if len(tops) == 1 and all(len(PurePosixPath(path).parts) > 1 for path in files):
        return {
            str(PurePosixPath(*PurePosixPath(path).parts[1:])): data for path, data in files.items()
        }
    return files
