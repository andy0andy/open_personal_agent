"""工作区契约测试（设计文档 4.1、7.3、9.1）：所有 Workspace 实现都必须通过同一套测试。

交给智能体的工作区后端只能读写本会话目录 /workspace/<会话短 ID>/；
越界时返回错误（智能体能看到原因），而不是抛出异常让整次运行失败。
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from agents.main_agent.workspace import LocalWorkspace, Workspace
from agents.tests.fakes import FakeSandbox
from common.errors import TooLargeError

ME, OTHER = "c_0123abcd", "c_99999999"

# 第三个参数可选：当前是哪个智能体在调用（主智能体、某个子智能体），读过记录按它分开（D16）
type Factory = Callable[..., Workspace]


def _local(root: Path, sandbox: FakeSandbox, caller: Callable[[], str] = lambda: "") -> Workspace:
    return LocalWorkspace(root, sandbox, session=lambda: ME, caller=caller)


@pytest.fixture(params=[_local])
def make(request: pytest.FixtureRequest) -> Factory:
    factory: Factory = request.param
    return factory


def _seed_other_session(root: Path) -> None:
    other = root / "workspace" / OTHER
    other.mkdir(parents=True)
    (other / "secret.txt").write_text("别人的文件")


def test_reads_and_writes_inside_own_session(tmp_path: Path, make: Factory) -> None:
    backend = make(tmp_path, FakeSandbox()).agent_backend
    assert backend.write(f"/workspace/{ME}/notes/a.txt", "你好").error is None
    assert (tmp_path / "workspace" / ME / "notes" / "a.txt").read_text() == "你好"
    read = backend.read(f"/workspace/{ME}/notes/a.txt")
    assert read.error is None
    assert "你好" in str(read.file_data)


def test_other_sessions_and_outside_paths_are_refused(tmp_path: Path, make: Factory) -> None:
    """越界：别的会话、虚拟根下的其他目录都拒绝，错误信息告诉智能体自己的工作目录。"""
    _seed_other_session(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    for result in (
        backend.write(f"/workspace/{OTHER}/x.txt", "x"),
        backend.read(f"/workspace/{OTHER}/secret.txt"),
        backend.write("/etc/passwd", "x"),
        backend.read(f"/workspace/{ME}/../{OTHER}/secret.txt"),
    ):
        assert result.error is not None
        assert f"/workspace/{ME}/" in result.error or "traversal" in result.error
    assert not (tmp_path / "workspace" / OTHER / "x.txt").exists()


def test_searches_without_a_path_stay_in_own_session(tmp_path: Path, make: Factory) -> None:
    _seed_other_session(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    backend.write(f"/workspace/{ME}/mine.txt", "别人的文件也在找")
    found = backend.glob("**/*.txt")
    assert [m["path"] for m in found.matches or []] == [f"/workspace/{ME}/mine.txt"]
    grepped = backend.grep("别人的文件")
    assert grepped.error is None
    assert [m["path"] for m in grepped.matches or []] == [f"/workspace/{ME}/mine.txt"]


async def test_commands_run_in_the_sandbox_for_this_session(tmp_path: Path, make: Factory) -> None:
    sandbox = FakeSandbox(output="hello", exit_code=2)
    backend = make(tmp_path, sandbox).agent_backend
    response = await backend.aexecute("python run.py", timeout=30)
    assert (response.output, response.exit_code) == ("hello", 2)
    assert sandbox.calls == [(ME, "python run.py", 30)]


async def test_lists_files_under_outputs(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    session = tmp_path / "workspace" / ME
    (session / "outputs" / "charts").mkdir(parents=True)
    (session / "outputs" / "charts" / "a.png").write_bytes(b"png")
    (session / "outputs" / "report.xlsx").write_bytes(b"xlsx!")
    (session / "scratch.py").write_text("不是产物")
    outputs = await workspace.list_outputs(ME)
    assert sorted((f.path, f.size) for f in outputs) == [
        ("outputs/charts/a.png", 3),
        ("outputs/report.xlsx", 5),
    ]
    assert await workspace.list_outputs(OTHER) == []


async def test_reads_a_file_for_download(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    (tmp_path / "workspace" / ME / "outputs").mkdir(parents=True)
    (tmp_path / "workspace" / ME / "outputs" / "a.png").write_bytes(b"png")
    assert await workspace.read_file(ME, "outputs/a.png") == b"png"
    _seed_other_session(tmp_path)
    for path in (f"../{OTHER}/secret.txt", "/etc/passwd", "outputs/../../x"):
        with pytest.raises(PermissionError):
            await workspace.read_file(ME, path)
    with pytest.raises(FileNotFoundError):
        await workspace.read_file(ME, "outputs/missing.png")


async def test_removes_a_session(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    _seed_other_session(tmp_path)
    (tmp_path / "workspace" / ME / "outputs").mkdir(parents=True)
    await workspace.remove(ME)
    await workspace.remove(ME)  # 已删除时不报错
    assert not (tmp_path / "workspace" / ME).exists()
    assert (tmp_path / "workspace" / OTHER / "secret.txt").exists()


async def test_prepare_creates_the_work_directory(tmp_path: Path, make: Factory) -> None:
    """运行开始前建好会话目录与 outputs/：模型第一次查看自己的目录时不会得到"路径不存在"。"""
    workspace = make(tmp_path, FakeSandbox())
    await workspace.prepare(ME)
    await workspace.prepare(ME)  # 已存在时不报错
    listing = workspace.agent_backend.ls(f"/workspace/{ME}/")
    assert listing.error is None
    assert [entry["path"] for entry in listing.entries or []] == [f"/workspace/{ME}/outputs/"]


async def test_opens_a_file_in_chunks_for_streaming(tmp_path: Path, make: Factory) -> None:
    """下载时分块读取，不把整个文件读进内存。"""
    workspace = make(tmp_path, FakeSandbox())
    outputs = tmp_path / "workspace" / ME / "outputs"
    outputs.mkdir(parents=True)
    data = bytes(range(256)) * 1024
    (outputs / "big.bin").write_bytes(data)
    opened = await workspace.open_file(ME, "outputs/big.bin")
    chunks = [chunk async for chunk in opened.chunks]
    assert opened.size == len(data)
    assert b"".join(chunks) == data
    assert len(chunks) > 1


async def test_unusable_paths_fail_when_opening(tmp_path: Path, make: Factory) -> None:
    """打开时就报错（下载接口据此返回 404，而不是响应开始以后才失败）：
    不存在或是目录 → FileNotFoundError；越界（含指向会话目录外的链接）→ PermissionError。"""
    workspace = make(tmp_path, FakeSandbox())
    _seed_other_session(tmp_path)
    outputs = tmp_path / "workspace" / ME / "outputs"
    (outputs / "folder").mkdir(parents=True)
    (outputs / "link.txt").symlink_to(tmp_path / "workspace" / OTHER / "secret.txt")
    for path in ("outputs/missing.txt", "outputs/folder"):
        with pytest.raises(FileNotFoundError):
            await workspace.open_file(ME, path)
        with pytest.raises(FileNotFoundError):
            await workspace.read_file(ME, path)
    for path in ("outputs/link.txt", f"../{OTHER}/secret.txt"):
        with pytest.raises(PermissionError):
            await workspace.open_file(ME, path)
        with pytest.raises(PermissionError):
            await workspace.read_file(ME, path)


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_saves_uploads_with_safe_unique_names(tmp_path: Path, make: Factory) -> None:
    """上传存到 uploads/：只取文件名本身（去掉目录部分与开头的点），同名时加序号、不覆盖。"""
    workspace = make(tmp_path, FakeSandbox())
    saved = [
        await workspace.save_upload(ME, name, _chunks(*parts), max_bytes=10)
        for name, parts in (
            ("销售.xlsx", (b"ab", b"c")),
            ("销售.xlsx", (b"x",)),
            ("../../etc/passwd", (b"x",)),
            ("C:\\Users\\me\\.env", (b"x",)),
            ("  ", (b"",)),
        )
    ]
    assert [(f.path, f.size) for f in saved] == [
        ("uploads/销售.xlsx", 3),
        ("uploads/销售 (2).xlsx", 1),
        ("uploads/passwd", 1),
        ("uploads/env", 1),
        ("uploads/未命名文件", 0),
    ]
    assert await workspace.read_file(ME, "uploads/销售.xlsx") == b"abc"
    listing = workspace.agent_backend.ls(f"/workspace/{ME}/uploads/")
    assert len(listing.entries or []) == 5  # 智能体在自己的目录里能看到


async def test_upload_over_the_limit_leaves_nothing(tmp_path: Path, make: Factory) -> None:
    workspace = make(tmp_path, FakeSandbox())
    with pytest.raises(TooLargeError):
        await workspace.save_upload(ME, "big.bin", _chunks(b"12345", b"67890"), max_bytes=8)
    assert list((tmp_path / "workspace" / ME / "uploads").iterdir()) == []


async def test_concurrent_uploads_to_a_new_session(tmp_path: Path, make: Factory) -> None:
    """新会话里一次拖进多个文件：几个上传同时建目录，都要能保存。"""
    workspace = make(tmp_path, FakeSandbox())
    saved = await asyncio.gather(
        *(workspace.save_upload(ME, f"{i}.txt", _chunks(b"x"), max_bytes=10) for i in range(8))
    )
    assert sorted(f.path for f in saved) == sorted(f"uploads/{i}.txt" for i in range(8))


async def test_very_long_file_names_are_shortened(tmp_path: Path, make: Factory) -> None:
    """文件系统限制文件名不超过 255 字节（约 85 个汉字）：过长的保留开头与后缀，加序号后也不超。"""
    workspace = make(tmp_path, FakeSandbox())
    long_name = "季度报告" * 25 + ".xlsx"
    for _ in range(2):
        saved = await workspace.save_upload(ME, long_name, _chunks(b"x"), max_bytes=10)
        name = saved.path.removeprefix("uploads/")
        assert name.startswith("季度报告")
        assert name.endswith(".xlsx")
        assert len(name.encode()) <= 255


# ---- 覆盖、修改已有文件前要读过最新版（设计 2026-10-23 5.6） ----

READ_FIRST = "先用 read_file 读最新版再改"


def _seed(root: Path, name: str = "a.txt", text: str = "原文") -> Path:
    path = root / "workspace" / ME / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_write_existing_file_requires_reading_first(tmp_path: Path, make: Factory) -> None:
    path = _seed(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    refused = backend.write(f"/workspace/{ME}/a.txt", "新")
    assert refused.error is not None
    assert READ_FIRST in refused.error
    assert path.read_text() == "原文"
    assert backend.read(f"/workspace/{ME}/a.txt").error is None
    assert backend.write(f"/workspace/{ME}/a.txt", "新").error is None
    assert path.read_text() == "新"


def test_write_after_outside_change_requires_rereading(tmp_path: Path, make: Factory) -> None:
    """读过之后文件又被改了（如命令改的）：要再读一次最新版。"""
    path = _seed(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    assert backend.read(f"/workspace/{ME}/a.txt").error is None
    path.write_text("命令改过的内容")
    refused = backend.write(f"/workspace/{ME}/a.txt", "新")
    assert refused.error is not None
    assert READ_FIRST in refused.error


def test_new_file_can_be_written_without_reading(tmp_path: Path, make: Factory) -> None:
    backend = make(tmp_path, FakeSandbox()).agent_backend
    assert backend.write(f"/workspace/{ME}/new.txt", "你好").error is None


def test_consecutive_edits_do_not_need_rereading(tmp_path: Path, make: Factory) -> None:
    path = _seed(tmp_path, text="一二三")
    backend = make(tmp_path, FakeSandbox()).agent_backend
    assert backend.read(f"/workspace/{ME}/a.txt").error is None
    assert backend.edit(f"/workspace/{ME}/a.txt", "一", "1").error is None
    assert backend.edit(f"/workspace/{ME}/a.txt", "二", "2").error is None
    assert path.read_text() == "12三"


def test_write_after_another_agent_changed_the_file_requires_rereading(
    tmp_path: Path, make: Factory
) -> None:
    """主智能体读过、子智能体改过之后，主智能体要先重读才能覆盖（积压小问题 D16：原来读过记录
    主、子智能体共用，主智能体会拿着旧内容盖掉子智能体的修改）；子智能体改之前也要自己读过。"""
    path = _seed(tmp_path)
    who = ["main"]
    backend = make(tmp_path, FakeSandbox(), lambda: who[0]).agent_backend
    file = f"/workspace/{ME}/a.txt"
    assert backend.read(file).error is None  # 主智能体读过
    who[0] = "sub"
    assert READ_FIRST in (backend.write(file, "子改的").error or "")
    assert backend.read(file).error is None
    assert backend.write(file, "子改的").error is None
    who[0] = "main"
    assert READ_FIRST in (backend.write(file, "主改的").error or "")
    assert path.read_text() == "子改的"
    assert backend.read(file).error is None
    assert backend.write(file, "主改的").error is None


def test_hard_links_in_the_session_are_read_like_regular_files(
    tmp_path: Path, make: Factory
) -> None:
    """会话目录里的硬链接按普通文件读（积压小问题 I1：把现状钉住；从会话目录以外建硬链接由
    Landlock 挡住，在 Linux 容器里验证）。"""
    path = _seed(tmp_path, text="原文")
    os.link(path, path.with_name("b.txt"))
    backend = make(tmp_path, FakeSandbox()).agent_backend
    result = backend.read(f"/workspace/{ME}/b.txt")
    assert result.error is None
    assert "原文" in str(result.file_data)


def test_edit_requires_reading_first(tmp_path: Path, make: Factory) -> None:
    path = _seed(tmp_path)
    backend = make(tmp_path, FakeSandbox()).agent_backend
    refused = backend.edit(f"/workspace/{ME}/a.txt", "原", "新")
    assert refused.error is not None
    assert READ_FIRST in refused.error
    assert path.read_text() == "原文"
