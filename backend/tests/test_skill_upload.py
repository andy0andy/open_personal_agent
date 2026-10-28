"""上传技能包的检查（D21）：zip / 文件夹 / 单个 SKILL.md；坏路径与超大的包一个文件都不落盘。"""

import io
import stat
import zipfile

import pytest

from agents.main_agent.runtime import SkillPackage
from backend.settings.skill_upload import MAX_SKILL_FILES, parse_skill_upload
from common.errors import InvalidRequestError, TooLargeError

SKILL = "---\nname: 周报写作\ndescription: 按模板写周报\n---\n\n# 怎么写\n".encode()


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


LIMIT = 1024 * 1024  # 测试用的上传上限（正式的取设置 max_upload_mb）


def _parse(files: list[tuple[str, bytes]]) -> SkillPackage:
    return parse_skill_upload(files, max_bytes=LIMIT)


def test_zip_with_one_top_folder() -> None:
    package = _parse(
        [("周报写作.zip", _zip({"周报写作/SKILL.md": SKILL, "周报写作/scripts/a.py": b"x"}))]
    )
    assert (package.name, package.description) == ("周报写作", "按模板写周报")
    assert sorted(package.files) == ["SKILL.md", "scripts/a.py"]


def test_single_skill_md() -> None:
    package = _parse([("SKILL.md", SKILL)])
    assert (package.name, list(package.files)) == ("周报写作", ["SKILL.md"])


def test_folder_upload_paths() -> None:
    package = _parse([("周报/SKILL.md", SKILL), ("周报/ref/a.md", b"a")])
    assert sorted(package.files) == ["SKILL.md", "ref/a.md"]


@pytest.mark.parametrize("bad", ["../evil", "/abs", "a/../../evil", "a\\b"])
def test_rejects_path_escape(bad: str) -> None:
    with pytest.raises(InvalidRequestError, match="路径"):
        _parse([("x.zip", _zip({"SKILL.md": SKILL, bad: b"x"}))])


def test_rejects_symlink_in_zip() -> None:
    with pytest.raises(InvalidRequestError, match="链接"):
        _parse([("x.zip", _zip({"SKILL.md": SKILL}, symlink="link"))])


def test_rejects_too_big() -> None:
    with pytest.raises(TooLargeError):
        _parse([("SKILL.md", SKILL), ("big.bin", b"0" * (LIMIT + 1))])
    many = [("SKILL.md", SKILL), *((f"f{i}.txt", b"x") for i in range(MAX_SKILL_FILES))]
    with pytest.raises(TooLargeError):
        _parse(many)


def test_rejects_zip_bomb_by_declared_size() -> None:
    with pytest.raises(TooLargeError):
        _parse([("x.zip", _zip({"SKILL.md": SKILL, "big.bin": b"0" * (LIMIT + 1)}))])


def test_requires_skill_md_at_root() -> None:
    with pytest.raises(InvalidRequestError, match=r"文件夹或压缩包里要有 SKILL\.md"):
        _parse([("x/readme.md", b"a"), ("x/sub/SKILL.md", SKILL)])


def test_bad_name() -> None:
    text = b"---\nname: ../x\ndescription: d\n---\n"
    with pytest.raises(InvalidRequestError, match="技能名只能用文字、数字、- 和 _"):
        _parse([("SKILL.md", text)])


def test_ignores_mac_metadata() -> None:
    package = _parse(
        [("x.zip", _zip({"s/SKILL.md": SKILL, "__MACOSX/s/._SKILL.md": b"m", "s/.DS_Store": b"d"}))]
    )
    assert list(package.files) == ["SKILL.md"]


def test_unsupported_single_file() -> None:
    with pytest.raises(InvalidRequestError, match=r"只能上传技能文件夹、\.zip 或 SKILL\.md"):
        _parse([("report.pdf", b"%PDF")])


MB = 1024 * 1024


def test_skill_upload_uses_the_given_limit() -> None:
    """技能包与附件、文档共用上传上限（设计 2026-10-19 4.5），由调用方按设置给出。"""
    with pytest.raises(TooLargeError, match="技能太大：最多 1MB"):
        parse_skill_upload([("SKILL.md", SKILL), ("big.bin", b"0" * (2 * MB))], max_bytes=MB)
    assert parse_skill_upload([("SKILL.md", SKILL), ("ok.bin", b"0" * 10)], max_bytes=MB)


def _damaged_zip(how: str) -> bytes:
    """压缩包里 a.txt 那一项读不出来：内容被改（CRC 不符）、标成加密、或压缩方式不认识。"""
    data = bytearray(_zip({"周报写作/SKILL.md": SKILL, "周报写作/a.txt": b"hello world"}))
    if how == "crc":
        at = data.index(b"hello world")
        data[at : at + 5] = b"HELLO"
        return bytes(data)
    # 本地文件头里标志位在第 6 字节、压缩方式在第 8 字节；中央目录里分别在第 8、10 字节
    for signature, flags_at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = data.find(signature)
        while start != -1:
            if how == "encrypted":
                data[start + flags_at] |= 0x01
            else:
                data[start + flags_at + 2 : start + flags_at + 4] = (99).to_bytes(2, "little")
            start = data.find(signature, start + 4)
    return bytes(data)


@pytest.mark.parametrize("how", ["crc", "encrypted", "method"])
def test_unreadable_zip_entry_is_a_clear_error(how: str) -> None:
    """压缩包里有一项读不出来（积压小问题 F5，原来 500）：说清楚是哪个文件、可能的原因。"""
    with pytest.raises(
        InvalidRequestError, match="读不出来：可能已损坏、加了密码或用了不支持的压缩方式"
    ):
        _parse([("周报写作.zip", _damaged_zip(how))])


def test_rejects_paths_differing_only_in_case() -> None:
    """SKILL.md 与 skill.md 在 Mac 上会互相覆盖（积压小问题 F11）：上传时就拒绝。"""
    with pytest.raises(InvalidRequestError, match="有只差大小写的同名文件"):
        _parse([("周报/SKILL.md", SKILL), ("周报/skill.md", b"x")])
