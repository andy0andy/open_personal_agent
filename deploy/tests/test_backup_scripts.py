"""备份与恢复脚本（deploy/backup.sh、restore.sh）：只用测试库里的专用库与临时目录，不碰正式数据。"""

import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
DB = "backup_probe"


def _compose() -> str:
    """与 Makefile 相同的选择：docker 可用就用 docker compose，否则 podman compose。"""
    docker = shutil.which("docker")
    if docker and subprocess.run([docker, "info"], capture_output=True).returncode == 0:
        return "docker compose"
    return "podman compose"


PG_EXEC = (
    f"{_compose()} --env-file {ROOT / '.env'} -f {ROOT / 'deploy/docker-compose.yml'} "
    "--profile test exec -T postgres-test"
)


def _makefile_file_dirs() -> str:
    """要打包的目录以 Makefile 的 BACKUP_ENV 为准：测试与 make backup 用同一份。"""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r'FILE_DIRS="([^"]+)"', makefile)
    assert match is not None
    return match.group(1)


def _psql(sql: str, database: str = "agent_test") -> str:
    result = subprocess.run(
        [*PG_EXEC.split(), "psql", "-U", "agent", "-d", database, "-At", "-c", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def env(tmp_path: Path) -> Iterator[dict[str, str]]:
    """测试库里的专用库（建表写一行）与临时的 workdata（两个文件）。"""
    _psql(f"DROP DATABASE IF EXISTS {DB}")
    _psql(f"CREATE DATABASE {DB}")
    _psql("CREATE TABLE notes (text text); INSERT INTO notes VALUES ('买牛奶')", DB)
    workdata = tmp_path / ".workdata"
    (workdata / "workspace" / "c_1").mkdir(parents=True)
    (workdata / "workspace" / "c_1" / "a.txt").write_text("文件 A", encoding="utf-8")
    (workdata / "knowledge" / "x").mkdir(parents=True)
    (workdata / "knowledge" / "x" / "b.pdf").write_bytes(b"%PDF-1.4")
    yield {
        **os.environ,
        "PG_EXEC": PG_EXEC,
        "PG_USER": "agent",
        "DATABASES": DB,
        "WORKDATA": str(workdata),
        "FILE_DIRS": _makefile_file_dirs(),
        "BACKUP_ROOT": str(workdata / "backups"),
        "KEEP": "7",
    }
    for leftover in (DB, f"{DB}__restoring", f"{DB}__old"):
        _psql(f"DROP DATABASE IF EXISTS {leftover} WITH (FORCE)")


def _run(
    script: str, env: dict[str, str], stdin: str = "", **extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / script)],
        env={**env, **extra},
        input=stdin,
        capture_output=True,
        text=True,
    )


def _backups(env: dict[str, str]) -> list[str]:
    root = Path(env["BACKUP_ROOT"])
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []


def test_backup_then_restore_brings_data_back(env: dict[str, str]) -> None:
    backup = _run("backup.sh", env)
    assert backup.returncode == 0, backup.stderr
    [name] = _backups(env)
    folder = Path(env["BACKUP_ROOT"]) / name
    assert (folder / f"{DB}.dump").read_bytes()[:5] == b"PGDMP"
    assert {p.name for p in folder.iterdir()} >= {f"{DB}.dump", "files.tar.gz", "manifest.txt"}

    workdata = Path(env["WORKDATA"])
    _psql("DELETE FROM notes", DB)
    (workdata / "workspace" / "c_1" / "a.txt").unlink()
    (workdata / "knowledge" / "x" / "new.txt").write_text("恢复后应消失", encoding="utf-8")

    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert _psql("SELECT text FROM notes", DB) == "买牛奶"
    assert (workdata / "workspace" / "c_1" / "a.txt").read_text(encoding="utf-8") == "文件 A"
    assert (workdata / "knowledge" / "x" / "b.pdf").exists()
    assert not (workdata / "knowledge" / "x" / "new.txt").exists()


def test_restore_backs_up_current_data_first(env: dict[str, str]) -> None:
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    workdata = Path(env["WORKDATA"])
    (workdata / "knowledge" / "x" / "new.txt").write_text("恢复前的数据", encoding="utf-8")
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    names = _backups(env)
    assert len(names) == 2
    safety = Path(env["BACKUP_ROOT"]) / names[-1]
    listing = subprocess.run(
        ["tar", "-tzf", str(safety / "files.tar.gz")], capture_output=True, text=True, check=True
    ).stdout
    assert "knowledge/x/new.txt" in listing
    assert names[-1] in restore.stdout  # 告诉用户恢复前的数据备份在哪


def test_backup_keeps_only_the_latest(env: dict[str, str]) -> None:
    root = Path(env["BACKUP_ROOT"])
    root.mkdir(parents=True)
    (root / "notes.txt").write_text("用户自己放的文件", encoding="utf-8")
    (root / "my-old-copy").mkdir()
    for second in range(3):
        assert (
            _run("backup.sh", env, KEEP="2", BACKUP_TIME=f"20261024-03000{second}").returncode == 0
        )
    names = [n for n in _backups(env) if n != "my-old-copy"]
    assert len(names) == 2
    assert (root / "notes.txt").exists()
    assert (root / "my-old-copy").exists()  # 不是备份格式的名字不删


def test_restore_refuses_missing_or_incomplete_backup(env: dict[str, str]) -> None:
    missing = _run("restore.sh", env, BACKUP="20000101-000000", CONFIRM="yes")
    assert missing.returncode == 1
    assert "找不到备份" in missing.stdout + missing.stderr

    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    (Path(env["BACKUP_ROOT"]) / name / "files.tar.gz").unlink()
    _psql("INSERT INTO notes VALUES ('买豆浆')", DB)
    incomplete = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert incomplete.returncode == 1
    assert "不完整" in incomplete.stdout + incomplete.stderr
    assert _psql("SELECT count(*) FROM notes", DB) == "2"  # 现有数据没动
    assert _backups(env) == [name]  # 也没有做恢复前的备份


def test_restore_without_confirmation_does_nothing(env: dict[str, str]) -> None:
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    _psql("INSERT INTO notes VALUES ('买豆浆')", DB)
    refused = _run("restore.sh", env, stdin="no\n", BACKUP=name)
    assert refused.returncode != 0
    assert _psql("SELECT count(*) FROM notes", DB) == "2"
    assert _backups(env) == [name]


# ---- 最终审查发现的问题（C1、I1～I3、M2）----


def test_restoring_the_oldest_backup_keeps_it(env: dict[str, str]) -> None:
    """恢复前的自动备份单独命名、单独保留：恢复最旧的那份时它不会被"只留几份"删掉（C1）。"""
    for second in range(2):
        assert (
            _run("backup.sh", env, KEEP="2", BACKUP_TIME=f"20261024-03000{second}").returncode == 0
        )
    oldest = _backups(env)[0]
    restore = _run("restore.sh", env, KEEP="2", BACKUP=oldest, CONFIRM="yes")
    assert restore.returncode == 0, restore.stdout + restore.stderr
    names = _backups(env)
    assert oldest in names
    assert len([n for n in names if not n.startswith("pre-restore-")]) == 2
    assert len([n for n in names if n.startswith("pre-restore-")]) == 1


def test_an_incomplete_backup_does_not_push_out_good_ones(env: dict[str, str]) -> None:
    """中断的备份留下的半成品（没有 manifest.txt）不算一份：不会挤掉好的备份（M2）。"""
    assert _run("backup.sh", env, KEEP="2", BACKUP_TIME="20261024-030000").returncode == 0
    [good] = _backups(env)
    (Path(env["BACKUP_ROOT"]) / f"{good}-5").mkdir()  # 名字晚于 good 的半成品
    assert _run("backup.sh", env, KEEP="2", BACKUP_TIME="20261024-030001").returncode == 0
    assert good in _backups(env)


def test_refusals_do_not_touch_services(env: dict[str, str], tmp_path: Path) -> None:
    """名字打错、回答不是 yes：不停服务也不重启（I1）；成功时停了还会起来。"""
    hooks = {
        "BEFORE_RESTORE": f"touch {tmp_path / 'stopped'}",
        "AFTER_RESTORE": f"touch {tmp_path / 'started'}",
    }
    assert _run("restore.sh", env, BACKUP="20000101-000000", CONFIRM="yes", **hooks).returncode == 1
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    assert _run("restore.sh", env, stdin="no\n", BACKUP=name, **hooks).returncode != 0
    assert not (tmp_path / "stopped").exists()
    assert not (tmp_path / "started").exists()
    assert _run("restore.sh", env, BACKUP=name, CONFIRM="yes", **hooks).returncode == 0
    assert (tmp_path / "stopped").exists()
    assert (tmp_path / "started").exists()


def test_corrupt_dump_is_refused_before_anything(env: dict[str, str], tmp_path: Path) -> None:
    """备份文件损坏：动数据之前就拒绝，说明原因；不停服务、不做恢复前备份（I2）。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    dump = Path(env["BACKUP_ROOT"]) / name / f"{DB}.dump"
    dump.write_bytes(dump.read_bytes()[:40])
    _psql("INSERT INTO notes VALUES ('买豆浆')", DB)
    result = _run(
        "restore.sh",
        env,
        BACKUP=name,
        CONFIRM="yes",
        BEFORE_RESTORE=f"touch {tmp_path / 'stopped'}",
    )
    assert result.returncode == 1
    assert "损坏" in result.stdout + result.stderr
    assert _psql("SELECT count(*) FROM notes", DB) == "2"
    assert not (tmp_path / "stopped").exists()
    assert _backups(env) == [name]


def test_failure_halfway_is_explained_and_services_come_back(
    env: dict[str, str], tmp_path: Path
) -> None:
    """恢复到一半失败：给一句中文说明怎么退回，停掉的服务照样起来（I1、I2）。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    workspace = Path(env["WORKDATA"]) / "workspace"
    workspace.chmod(0o555)  # 清空文件这一步会失败
    try:
        result = _run(
            "restore.sh",
            env,
            BACKUP=name,
            CONFIRM="yes",
            BEFORE_RESTORE=f"touch {tmp_path / 'stopped'}",
            AFTER_RESTORE=f"touch {tmp_path / 'started'}",
        )
    finally:
        workspace.chmod(0o755)
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "恢复中途失败" in output
    assert "pre-restore-" in output  # 告诉用户用哪份备份退回
    assert (tmp_path / "started").exists()


def test_restore_drops_tables_added_after_the_backup(env: dict[str, str]) -> None:
    """恢复后数据库与备份完全一致：备份之后新建的表（如以后的迁移）不会残留（I3）。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    _psql("CREATE TABLE added_later (x int)", DB)
    assert _run("restore.sh", env, BACKUP=name, CONFIRM="yes").returncode == 0
    assert _psql("SELECT count(*) FROM pg_tables WHERE tablename = 'added_later'", DB) == "0"


def test_backup_includes_user_config_and_skills(env: dict[str, str]) -> None:
    """管理页面的改动（.workdata/config/、.workdata/skills/，D21）也在备份里，恢复后回来。"""
    workdata = Path(env["WORKDATA"])
    (workdata / "config").mkdir()
    (workdata / "config" / "mcp_servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    (workdata / "skills" / "memo").mkdir(parents=True)
    (workdata / "skills" / "memo" / "SKILL.md").write_text("---\n", encoding="utf-8")
    backup = _run("backup.sh", env)
    assert backup.returncode == 0, backup.stderr
    [name] = _backups(env)
    shutil.rmtree(workdata / "config")
    shutil.rmtree(workdata / "skills")
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert (workdata / "config" / "mcp_servers.yaml").read_text(encoding="utf-8") == "servers: {}\n"
    assert (workdata / "skills" / "memo" / "SKILL.md").exists()


def test_manifest_has_format_2(env: dict[str, str]) -> None:
    """D22 之后的备份标明格式 2：迁移前的旧备份认得出来。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    manifest = (Path(env["BACKUP_ROOT"]) / name / "manifest.txt").read_text(encoding="utf-8")
    assert "format=2" in manifest.splitlines()


def test_restore_refuses_old_format(env: dict[str, str]) -> None:
    """迁移前（第一轮优化之前）的备份不能恢复到现在的版本：拒绝并说明，现有数据不动。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    manifest = Path(env["BACKUP_ROOT"]) / name / "manifest.txt"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text("\n".join(x for x in lines if x != "format=2") + "\n", encoding="utf-8")
    _psql("INSERT INTO notes VALUES ('买豆浆')", DB)
    old = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert old.returncode == 1
    assert "旧格式" in old.stdout + old.stderr
    assert _psql("SELECT count(*) FROM notes", DB) == "2"
    assert _backups(env) == [name]  # 也没有做恢复前的备份


def _conversations(threads: int, runs: int) -> None:
    """主库那两张表的样子（只看表名与行数）：会话 threads，消息按 runs 的行数算。"""
    _psql(
        "CREATE TABLE IF NOT EXISTS threads (id int); CREATE TABLE IF NOT EXISTS runs (id int)", DB
    )
    _psql(
        "DELETE FROM threads; DELETE FROM runs; "
        f"INSERT INTO threads SELECT generate_series(1, {threads}); "
        f"INSERT INTO runs SELECT generate_series(1, {runs})",
        DB,
    )


def test_restore_warns_when_data_shrinks(env: dict[str, str]) -> None:
    """恢复后会话或消息比恢复前少：结尾提醒，并说用哪份自动备份退回（设计 2026-10-23 7.2）。"""
    _conversations(threads=1, runs=2)
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    _conversations(threads=3, runs=5)
    restore = _run(
        "restore.sh",
        env,
        BACKUP=name,
        CONFIRM="yes",
        BEFORE_RESTORE="echo 停服务",
        AFTER_RESTORE="echo 服务起来了",
    )
    assert restore.returncode == 0, restore.stderr
    # 提醒在起服务的输出之后：不被盖住
    assert restore.stdout.splitlines()[-2] == "服务起来了"
    safety = _backups(env)[-1]
    assert safety.startswith("pre-restore-")
    assert restore.stdout.splitlines()[-1] == (
        f"会话 3→1、消息 5→2，比恢复前少；不是你想要的就用 {safety} 退回"
        f"（make restore BACKUP={safety}）"
    )


def test_restore_without_those_tables_does_not_compare(env: dict[str, str]) -> None:
    assert _run("backup.sh", env).returncode == 0  # 只有 notes 表
    [name] = _backups(env)
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert restore.stdout.splitlines()[-1].startswith("已恢复备份")


def test_restore_with_no_loss_says_nothing_more(env: dict[str, str]) -> None:
    _conversations(threads=2, runs=4)
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    _conversations(threads=1, runs=4)  # 恢复后会话变多、消息一样多
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert restore.stdout.splitlines()[-1].startswith("已恢复备份")
    assert "比恢复前少" not in restore.stdout + restore.stderr


def test_backup_output_is_for_humans(env: dict[str, str]) -> None:
    """make backup 只给人看的话；BACKUP_NAME= 那行只在恢复脚本要（EMIT_NAME）时才打印（G4）。"""
    backup = _run("backup.sh", env)
    assert backup.returncode == 0, backup.stderr
    assert "BACKUP_NAME=" not in backup.stdout
    [name] = _backups(env)
    emitted = _run("backup.sh", env, EMIT_NAME="1")
    assert emitted.returncode == 0, emitted.stderr
    assert emitted.stdout.splitlines()[-1] == f"BACKUP_NAME={_backups(env)[-1]}"
    assert _backups(env)[-1] != name


def test_seeded_marker_travels_with_backup(env: dict[str, str]) -> None:
    """.seeded 跟着备份走，恢复时整份换成备份里的（不合并）：删掉的默认内容不会被写回（G5）。"""
    workdata = Path(env["WORKDATA"])
    (workdata / ".seeded").write_text("files\nmodels\n", encoding="utf-8")
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    manifest = (Path(env["BACKUP_ROOT"]) / name / "manifest.txt").read_text(encoding="utf-8")
    assert "seeded=yes" in manifest.splitlines()
    (workdata / ".seeded").write_text("files\nmodels\nsession_index\n", encoding="utf-8")
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert (workdata / ".seeded").read_text(encoding="utf-8") == "files\nmodels\n"


def test_restoring_a_backup_without_seeded_keeps_the_current_one(env: dict[str, str]) -> None:
    """旧备份（或备份时还没有 .seeded）：恢复时不动现有的 .seeded（G5）。"""
    assert _run("backup.sh", env).returncode == 0
    [name] = _backups(env)
    manifest = (Path(env["BACKUP_ROOT"]) / name / "manifest.txt").read_text(encoding="utf-8")
    assert "seeded=no" in manifest.splitlines()
    workdata = Path(env["WORKDATA"])
    (workdata / ".seeded").write_text("files\n", encoding="utf-8")
    restore = _run("restore.sh", env, BACKUP=name, CONFIRM="yes")
    assert restore.returncode == 0, restore.stderr
    assert (workdata / ".seeded").read_text(encoding="utf-8") == "files\n"
