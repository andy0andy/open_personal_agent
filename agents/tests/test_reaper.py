"""停止命令时补杀逃逸的子进程（设计 2026-10-23 5.5）：按 /proc 里的父进程链找后代、核对启动时间。"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agents.main_agent.workspace.reaper import descendants, marked_pids, still_alive


def _process(proc: Path, pid: int, ppid: int, start: int, *, uid: int = 1000) -> None:
    """假的 /proc/<pid>：stat 里第 4 个字段是父进程，第 22 个是启动时间；名字里带空格和括号。"""
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    rest = " ".join(["0"] * 17)
    (folder / "stat").write_text(f"{pid} (a (b) c) S {ppid} {rest} {start} 0 0\n")
    (folder / "status").write_text(f"Name:\ta\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


def test_descendants_follow_the_parent_chain(tmp_path: Path) -> None:
    _process(tmp_path, 10, 1, 100)
    _process(tmp_path, 11, 10, 101)
    _process(tmp_path, 12, 11, 102)
    _process(tmp_path, 20, 1, 200)
    (tmp_path / "self").mkdir()  # 不是数字的目录跳过
    assert descendants(10, tmp_path) == {11: 101, 12: 102}


def test_still_alive_ignores_reused_pids(tmp_path: Path) -> None:
    """进程号被别的进程复用了（启动时间对不上）：不杀；只杀指定用户的。"""
    _process(tmp_path, 11, 1, 101)
    _process(tmp_path, 12, 1, 999)  # 原来记的是 102
    _process(tmp_path, 13, 1, 103, uid=0)
    recorded = {11: 101, 12: 102, 13: 103, 14: 104}  # 14 已经不在了
    assert still_alive(recorded, tmp_path, uid=1000) == [11]


class _Finished:
    async def communicate(self) -> tuple[bytes, bytes]:
        return b"123\n", b""


async def test_scan_runs_without_backend_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """扫描进程以执行命令的用户运行：同一用户的命令读得到它的环境，不能带后端的密钥（审查 I1）。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-should-not-leak")
    seen: dict[str, Any] = {}

    async def spawn(*args: str, **kwargs: Any) -> _Finished:
        seen.update(kwargs)
        return _Finished()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await marked_pids("m", ["setpriv", "--reuid=1000"]) == [123]
    env = seen.get("env")
    assert env is not None
    assert set(env) <= {"PATH"}
    assert "sk-should-not-leak" not in str(env)
