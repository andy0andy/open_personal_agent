"""在智能体所在环境里执行命令（D20）：会话目录、超时与停止时杀掉进程组、长输出写日志、
不传密钥类环境变量、与智能体共用 Python 环境。"""

import asyncio
import gc
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agents.main_agent.workspace import LocalSandbox, local_sandbox
from agents.main_agent.workspace.local_sandbox import (
    WRITE_RIGHTS,
    exec_identity,
    exit_code_of,
    landlock_args,
)
from agents.tests.waiting import until

SESSION = "c_0123abcd"


def _sandbox(tmp_path: Path, **options: Any) -> LocalSandbox:
    return LocalSandbox(tmp_path / "workspace", **options)


async def _wait_dead(pid: int) -> bool:
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.1)  # 允许等待：有上限的轮询（进程退出没有可等的事件）
    return False


async def test_runs_in_the_session_directory(tmp_path: Path) -> None:
    """在会话目录里执行，标准错误也收进输出；输出里的真实路径换成智能体看到的 /workspace/…。"""
    result = await _sandbox(tmp_path).run(SESSION, "pwd; echo 中文 >&2; exit 3", time_limit=None)
    assert result.exit_code == 3
    assert f"/workspace/{SESSION}" in result.output
    assert str(tmp_path) not in result.output
    assert "中文" in result.output
    assert (result.truncated, result.timed_out) == (False, False)


async def test_session_must_look_like_a_short_id(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        await _sandbox(tmp_path).run("../etc", "true", time_limit=None)


async def test_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    """超时要杀掉整个进程组：命令派生的后台子进程也不能留下来继续占用资源。"""
    started = time.monotonic()
    result = await _sandbox(tmp_path).run(
        SESSION, "sleep 30 & echo $! > child.pid; sleep 30", time_limit=1
    )
    assert time.monotonic() - started < 5
    assert result.timed_out is True
    assert "超过 1 秒" in result.output
    child = int((tmp_path / "workspace" / SESSION / "child.pid").read_text())
    assert await _wait_dead(child)


async def test_timeout_is_capped(tmp_path: Path) -> None:
    result = await _sandbox(tmp_path, max_timeout=600).run(SESSION, "true", time_limit=999)
    assert result.exit_code != 0
    assert "1～600 秒" in result.output


async def test_long_output_is_cut_and_saved_to_a_log(tmp_path: Path) -> None:
    """输出超过上限：给模型开头 40% 与结尾 60%，中间写明省略了多少、完整输出在 logs/ 哪个文件
    （设计 2026-10-23 5.4）。"""
    command = f"{sys.executable} -c \"print('x' * 5000)\""
    result = await _sandbox(tmp_path, max_output=1000).run(SESSION, command, time_limit=None)
    assert result.truncated is True
    logs = list((tmp_path / "workspace" / SESSION / "logs").glob("*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().count("x") == 5000
    head, _, rest = result.output.partition("\n（中间省略了 ")
    assert head == "x" * 400
    omitted, _, tail = rest.partition("\n")
    assert omitted == f"{5001 - 1000} 字，完整输出在 logs/{logs[0].name}）"
    assert tail == "x" * 599 + "\n"


async def test_cancelling_kills_the_command(tmp_path: Path) -> None:
    """停止运行 = 取消这次执行：连同后台子进程一起杀掉，命令不会在后台继续跑完。"""
    session_dir = tmp_path / "workspace" / SESSION
    command = "sleep 30 & echo $! > child.pid; sleep 2; touch finished"
    task = asyncio.create_task(_sandbox(tmp_path).run(SESSION, command, time_limit=30))
    pid_file = session_dir / "child.pid"
    await until(
        lambda: pid_file.exists() and bool(pid_file.read_text().strip()), what="后台子进程起来"
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await _wait_dead(int((session_dir / "child.pid").read_text()))
    await asyncio.sleep(2)  # 允许等待：断言命令被杀后 2 秒也不会写出 finished，只能等够时长
    assert not (session_dir / "finished").exists()


async def test_secrets_are_not_passed_to_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """执行的代码看不到智能体的密钥：只传白名单里的环境变量，HOME 不是智能体自己的。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://agent:secret@db/agent")
    result = await _sandbox(tmp_path).run(SESSION, "env", time_limit=None)
    assert "sk-should-not-leak" not in result.output
    assert "secret@db" not in result.output
    assert "PATH=" in result.output
    assert f"HOME={os.environ.get('HOME')}\n" not in result.output


async def test_uses_the_same_python_as_the_agent(tmp_path: Path) -> None:
    """与智能体共用 Python 环境（用户选定）：命令里的 python 就是智能体自己的那一个。"""
    result = await _sandbox(tmp_path).run(
        SESSION, 'python -c "import sys; print(sys.prefix)"', time_limit=None
    )
    assert result.output.strip() == sys.prefix


async def test_huge_files_are_stopped_by_the_size_limit(tmp_path: Path) -> None:
    result = await _sandbox(tmp_path, max_file_mb=1).run(
        SESSION, "head -c 3000000 /dev/zero > big.bin", time_limit=None
    )
    assert result.exit_code != 0
    assert (tmp_path / "workspace" / SESSION / "big.bin").stat().st_size <= 1024 * 1024


# 允许等待：下面是被测命令里的子进程在睡，不是测试在等
_ESCAPE = f'{sys.executable} -c "import os, time; os.setsid(); time.sleep(8)" & '  # 允许等待：同上


async def test_a_process_that_left_the_group_does_not_block_a_timeout(tmp_path: Path) -> None:
    """命令里有进程主动脱离进程组（杀不到）又占着输出：不一直等它，注明后返回。"""
    started = time.monotonic()
    result = await _sandbox(tmp_path).run(SESSION, _ESCAPE + "sleep 30", time_limit=1)
    assert time.monotonic() - started < 5
    assert result.timed_out is True
    assert "仍有后台进程" in result.output


# 脱离进程组之后才留下标记：等它真的脱离了再取消（命令一起来就取消，它多半还没脱离）
_ESCAPE_THEN_MARK = (
    f'{sys.executable} -c "import os, pathlib, time; os.setsid(); '
    "pathlib.Path('escaped').touch(); time.sleep(8)\" & "  # 允许等待：被测命令里的子进程在睡
)


async def test_a_process_that_left_the_group_does_not_block_stopping(tmp_path: Path) -> None:
    command = _ESCAPE_THEN_MARK + "sleep 30"
    task = asyncio.create_task(_sandbox(tmp_path).run(SESSION, command, time_limit=30))
    marker = tmp_path / "workspace" / SESSION / "escaped"
    await until(marker.exists, what="后台进程脱离进程组")
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 4


async def test_switching_to_the_normal_user_also_drops_root_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改用 uid 1000 由 setpriv 完成，并清掉附加用户组（否则子进程留着 root 组）；
    不靠 create_subprocess_exec 的 user / group 参数：后端用的 uvloop 不认它们。"""
    seen: dict[str, object] = {}

    async def spawn(*args: object, **kwargs: object) -> None:
        seen.update(args=args, kwargs=kwargs)
        raise RuntimeError("只看参数")

    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError):  # 只看切换用户：不加 Landlock（另有测试）
        await LocalSandbox(tmp_path / "workspace", landlock=False).run(
            SESSION, "true", time_limit=None
        )
    args = seen["args"]
    assert isinstance(args, tuple)
    assert args[:5] == ("setpriv", "--reuid=1000", "--regid=1000", "--clear-groups", "bash")
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert not {"user", "group", "extra_groups"} & set(kwargs)


def test_runs_under_uvloop(tmp_path: Path) -> None:
    """后端跑在 uvicorn 默认的 uvloop 事件循环上（实际出过错：它不认 user / group 等参数）。"""
    uvloop = pytest.importorskip("uvloop")
    result = uvloop.run(_sandbox(tmp_path).run(SESSION, "echo 能执行", time_limit=None))
    assert result.output.strip() == "能执行"


def test_commands_run_as_a_normal_user_when_the_agent_is_root() -> None:
    """智能体以 root 运行时（后端容器里就是）改用 uid 1000 执行，否则照原用户执行。"""
    assert exec_identity(euid=0) == (1000, 1000)
    assert exec_identity(euid=501) is None


@pytest.mark.skipif(sys.platform != "linux", reason="要读 /proc 数僵尸进程")
async def test_stopped_commands_leave_no_zombie_processes(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    command = "sleep 30 & touch started; sleep 31"
    task = asyncio.create_task(sandbox.run(SESSION, command, time_limit=30))
    await until((tmp_path / "workspace" / SESSION / "started").exists, what="命令起来")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    count = "grep -l '^State:.Z' /proc/[0-9]*/status 2>/dev/null | wc -l"

    async def no_zombies() -> bool:
        result = await sandbox.run(SESSION, count, time_limit=10)
        return result.output.strip() == "0"

    await until(no_zombies, what="被杀的进程都已回收")


# ---- 命令只能写放行的目录（设计 2026-10-23 5.1，R33） ----


def test_landlock_args_allow_only_listed_dirs() -> None:
    """只限写入（读不受限）：每个放行目录一条规则，权限串与限制的种类相同。

    refer（跨目录改名、硬链接）要显式放行：Landlock 对它默认一律拒绝，不放行时连放行目录
    之间的 os.rename 都会报 EXDEV（审查 I2）。"""
    assert WRITE_RIGHTS == (
        "write-file,remove-dir,remove-file,make-char,make-dir,make-reg,"
        "make-sock,make-fifo,make-block,make-sym,refer,truncate"
    )
    assert landlock_args([Path("/a"), Path("/tmp")]) == [
        "--landlock-access",
        f"fs:{WRITE_RIGHTS}",
        "--landlock-rule",
        f"path-beneath:{WRITE_RIGHTS}:/a",
        "--landlock-rule",
        f"path-beneath:{WRITE_RIGHTS}:/tmp",
    ]


async def _spawned_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: LocalSandbox
) -> tuple[object, ...]:
    seen: dict[str, tuple[object, ...]] = {}

    async def spawn(*args: object, **kwargs: object) -> None:
        seen["args"] = args
        raise RuntimeError("只看参数")

    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError):
        await sandbox.run(SESSION, "true", time_limit=None)
    return seen["args"]


async def test_commands_get_landlock_when_switching_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = LocalSandbox(tmp_path / "workspace", landlock=True)
    args = await _spawned_args(tmp_path, monkeypatch, sandbox)
    text = " ".join(str(arg) for arg in args)
    assert args[:4] == ("setpriv", "--reuid=1000", "--regid=1000", "--clear-groups")
    assert "--landlock-access" in args
    session = (tmp_path / "workspace").resolve() / SESSION
    home = (tmp_path / "workspace").resolve().parent / "cache" / "exec-home"
    for allowed in (session, home, Path("/tmp"), Path("/dev")):
        assert f"path-beneath:{WRITE_RIGHTS}:{allowed}" in text
    assert args.index("bash") > args.index("--landlock-access")


async def test_landlock_probe_runs_without_backend_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """探测进程以 uid 1000 运行：不能带后端的密钥（审查 I1）。"""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-should-not-leak")
    seen: dict[str, Any] = {}

    class _Done:
        async def wait(self) -> int:
            return 0

    async def spawn(*args: str, **kwargs: Any) -> _Done:
        seen.update(kwargs)
        return _Done()

    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    assert await LocalSandbox(tmp_path)._probe_landlock((1000, 1000)) is True
    env = seen.get("env")
    assert env is not None
    assert set(env) <= {"PATH"}


async def test_no_landlock_when_probe_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """内核或容器不支持时不加限制（先不管，残留风险写进 D25），只提示一次。"""
    sandbox = LocalSandbox(tmp_path / "workspace")

    async def unsupported(_: object) -> bool:
        return False

    monkeypatch.setattr(sandbox, "_probe_landlock", unsupported)
    args = await _spawned_args(tmp_path, monkeypatch, sandbox)
    assert "--landlock-access" not in args


# ---- 命令输出：分开读、头尾都留、真实退出码（设计 2026-10-23 5.4） ----


async def test_long_output_keeps_head_and_tail(tmp_path: Path) -> None:
    command = f'{sys.executable} -c "[print(i) for i in range(1, 50001)]"'
    result = await _sandbox(tmp_path).run(SESSION, command, time_limit=None)
    assert result.output.startswith("1\n2\n3\n")
    assert result.output.endswith("49999\n50000\n")
    assert "中间省略了" in result.output


async def test_stderr_is_captured_separately(tmp_path: Path) -> None:
    result = await _sandbox(tmp_path).run(
        SESSION, "echo out; sleep 0.2; echo err >&2", time_limit=None
    )
    assert result.output == "out\nerr\n"  # 给模型的仍按到达先后拼在一起
    assert result.stderr == "err\n"


def test_exit_code_of_maps_timeout_and_unknown() -> None:
    assert exit_code_of(3, timed_out=False) == 3
    assert exit_code_of(-9, timed_out=True) == 124
    assert exit_code_of(None, timed_out=False) == -1


async def test_timeout_reports_124(tmp_path: Path) -> None:
    result = await _sandbox(tmp_path).run(SESSION, "sleep 5", time_limit=1)
    assert (result.exit_code, result.timed_out) == (124, True)


@pytest.mark.skipif(sys.platform != "linux", reason="要读 /proc（只在 Linux 容器里跑）")
async def test_setsid_escapee_is_killed_on_timeout(tmp_path: Path) -> None:
    """用 setsid 脱离了进程组的后台进程：超时停止时按记下的后代与环境标记补杀（设计 5.5）。"""
    command = "setsid sleep 300 & echo $! > escapee.pid; sleep 30"
    await _sandbox(tmp_path).run(SESSION, command, time_limit=1)
    escapee = int((tmp_path / "workspace" / SESSION / "escapee.pid").read_text())
    assert await _wait_dead(escapee)


async def test_both_streams_crossing_the_limit_lose_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一路跨过上限、正在建日志（写盘慢）时另一路接着来：日志里一点不少（审查 I4：原来
    会再建一次日志把文件清空，或写进马上被清掉的缓存）。"""
    import agents.main_agent.workspace.local_sandbox as module

    original = module._make_open_dirs

    creating = threading.Event()

    def slow(*directories: Path) -> None:
        if any(directory.name == "logs" for directory in directories):
            creating.set()
            time.sleep(0.2)  # 允许等待：替身模拟写盘慢（Mac 上 podman 的共享目录）
        original(*directories)

    monkeypatch.setattr(module, "_make_open_dirs", slow)
    collector = module._Collector(tmp_path, limit=10, virtual=lambda data: data)

    async def stdout() -> None:
        await collector._add(b"a" * 20, "a" * 20, errors=False)  # 跨过上限，开始建日志

    async def stderr() -> None:
        await until(creating.is_set, what="开始建日志")  # 正在建日志的时候
        for i in range(5):
            await collector._add(f"b{i}".encode(), f"b{i}", errors=True)

    await asyncio.gather(stdout(), stderr())
    [log] = (tmp_path / "logs").glob("*.log")
    assert log.read_text() == "a" * 20 + "b0b1b2b3b4"


async def test_only_the_workspace_itself_is_mapped_back(tmp_path: Path) -> None:
    """输出里的真实路径只换工作区本身（积压小问题 D10）：
    同前缀的 workspace-old、workspace2 不动。"""
    root = tmp_path / "workspace"
    command = f"echo {root}/{SESSION}/a.txt {root}-old/b.txt {root}2/c.txt"
    result = await _sandbox(tmp_path).run(SESSION, command, time_limit=10)
    assert result.output.split() == [
        f"/workspace/{SESSION}/a.txt",
        f"{root}-old/b.txt",
        f"{root}2/c.txt",
    ]


async def test_commands_get_no_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """命令的标准输入是空的（积压小问题 D11）：读标准输入的命令不会卡到超时。"""
    seen: dict[str, object] = {}

    async def spawn(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        raise RuntimeError("只看参数")

    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError):
        await _sandbox(tmp_path).run(SESSION, "cat", time_limit=None)
    assert seen["stdin"] == asyncio.subprocess.DEVNULL


async def test_capped_log_says_partial_and_uses_virtual_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """日志写满上限后提示"只记了前…"，日志里也是 /workspace/…（积压小问题 D12）。"""
    monkeypatch.setattr(local_sandbox, "_LOG_LIMIT", 2000)
    root = tmp_path / "workspace"
    command = f'for i in $(seq 300); do echo "$i {root}/{SESSION}/x"; sleep 0.001; done'
    result = await _sandbox(tmp_path, max_output=500).run(SESSION, command, time_limit=30)
    assert "只记了前" in result.output
    [log] = (root / SESSION / "logs").iterdir()
    text = log.read_text(encoding="utf-8")
    assert str(root) not in text
    assert f"/workspace/{SESSION}/x" in text


async def test_giving_up_on_held_output_logs_no_error(tmp_path: Path) -> None:
    """放弃等脱离进程组的后台进程时，不再打"exception was never retrieved"（积压小问题 D14）。"""
    errors: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    # 所有测试共用一个事件循环：用完把原来的处理器放回去（第三批审查 Minor 5）
    original = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: errors.append(ctx))
    try:
        result = await _sandbox(tmp_path).run(SESSION, _ESCAPE + "true", time_limit=10)
        assert "仍有后台进程" in result.output
        for _ in range(5):  # 让取消掉的读取收完尾，再回收它
            await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(original)
    assert errors == []


@pytest.mark.skipif(sys.platform != "linux", reason="要读 /proc（只在 Linux 容器里跑）")
async def test_detached_process_holding_output_is_ended_on_normal_exit(tmp_path: Path) -> None:
    """正常结束时仍占着输出的脱离进程也结束（积压小问题 D14，用户 2026-10-26 决定）。"""
    pid_file = tmp_path / "workspace" / SESSION / "escaped.pid"
    command = (
        f'{sys.executable} -c "import os, pathlib, time; os.setsid(); '
        "pathlib.Path('escaped.pid').write_text(str(os.getpid())); "
        'time.sleep(8)" & '  # 允许等待：被测命令里的子进程在睡
        "sleep 0.5"
    )
    result = await _sandbox(tmp_path).run(SESSION, command, time_limit=10)
    assert "已结束" in result.output
    assert await _wait_dead(int(pid_file.read_text()))


@pytest.mark.skipif(sys.platform != "linux", reason="进程数上限只在换用户时设（容器里以 root 跑）")
async def test_many_threads_are_allowed(tmp_path: Path) -> None:
    """进程数上限 1024（积压小问题 D13）：起 300 个线程的 Python 能正常结束。"""
    script = (
        "import threading, time; "
        "ts = [threading.Thread(target=time.sleep, args=(0.2,)) for _ in range(300)]; "
        "[t.start() for t in ts]; [t.join() for t in ts]; print('ok')"
    )
    command = f'{sys.executable} -c "{script}"'
    result = await _sandbox(tmp_path).run(SESSION, command, time_limit=30)
    assert (result.exit_code, result.output.strip()) == (0, "ok")
