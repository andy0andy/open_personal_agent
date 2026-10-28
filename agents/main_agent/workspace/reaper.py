"""停止命令时补杀逃逸的子进程（设计 2026-10-23 5.5）。

杀进程组只能杀到还在组里的进程；用 setsid、setpgid 脱离的会留下来。所以：
- 等命令结束时顺带记下它的后代进程（进程号与启动时间：进程号可能被复用）；
- 结束时把还活着、启动时间对得上、属于执行命令那个用户的逐个杀掉；
- 两次脱离（父进程也退出了，记不到）的，靠命令环境变量里的随机标记找：读 /proc/<pid>/environ。
  后端以 root 运行但没有 SYS_PTRACE，读不到别的用户进程的 environ，扫描要以执行命令的用户运行。
没有 /proc（macOS 上跑测试）时这些都跳过。
"""

import asyncio
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

PROC = Path("/proc")
MARK_VARIABLE = "OPA_EXEC_MARK"  # 命令环境里的随机标记
# 以执行命令的用户起的辅助进程（扫描、Landlock 探测）只给这些环境变量：同一用户的命令读得到
# 它们的 /proc/<pid>/environ，后端自己的环境里有网关密钥等（审查 I1）
BARE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin"}

# 以执行命令的用户运行的扫描脚本：打印环境里带着标记的进程号
_SCAN = (
    "import os, sys\n"
    "mark = sys.argv[1].encode()\n"
    "for pid in os.listdir('/proc'):\n"
    "    if not pid.isdigit():\n"
    "        continue\n"
    "    try:\n"
    "        with open(f'/proc/{pid}/environ', 'rb') as f:\n"
    "            env = f.read().split(b'\\0')\n"
    "    except OSError:\n"
    "        continue\n"
    "    if mark in env:\n"
    "        print(pid)\n"
)


def _stat(proc: Path, pid: int) -> tuple[int, int] | None:
    """（父进程号，启动时间）；进程已不在或读不了时为 None。"""
    try:
        text = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    # 进程名可能带空格和括号：从最后一个右括号之后数字段（状态、父进程……第 22 个是启动时间）
    fields = text[text.rindex(")") + 2 :].split()
    return int(fields[1]), int(fields[19])


def _uid(proc: Path, pid: int) -> int | None:
    try:
        lines = (proc / str(pid) / "status").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("Uid:"):
            return int(line.split()[1])
    return None


def descendants(root: int, proc: Path = PROC) -> dict[int, int]:
    """root 的全部后代（不含它自己）：进程号 → 启动时间。"""
    known: dict[int, tuple[int, int]] = {}
    for entry in proc.iterdir():
        if entry.name.isdigit() and (info := _stat(proc, int(entry.name))) is not None:
            known[int(entry.name)] = info
    children: dict[int, list[int]] = defaultdict(list)
    for pid, (parent, _) in known.items():
        children[parent].append(pid)
    found: dict[int, int] = {}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found[child] = known[child][1]
                pending.append(child)
    return found


def still_alive(recorded: Mapping[int, int], proc: Path = PROC, *, uid: int) -> list[int]:
    """记下的进程里还活着、启动时间对得上、属于 uid 的（进程号被复用的不算）。"""
    alive: list[int] = []
    for pid, started in recorded.items():
        info = _stat(proc, pid)
        if info is not None and info[1] == started and _uid(proc, pid) == uid:
            alive.append(pid)
    return alive


async def marked_pids(mark: str, as_user: Sequence[str]) -> list[int]:
    """环境变量里带着这个标记的进程号（以执行命令的用户扫描 /proc）。"""
    process = await asyncio.create_subprocess_exec(
        *as_user,
        sys.executable,
        "-I",
        "-c",
        _SCAN,
        f"{MARK_VARIABLE}={mark}",
        env=BARE_ENV,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await process.communicate()
    return [int(line) for line in output.split() if line.isdigit()]
