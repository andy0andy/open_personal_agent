"""Makefile 的命令（只用 make -n 打印、不执行）。"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _dry_run(target: str) -> str:
    """make -n 只打印要执行的命令；COMPOSE=echo 免得去探测 docker。去掉外层 make 传下来的参数。"""
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    result = subprocess.run(
        ["make", "-n", target, "COMPOSE=echo"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_restart_prepares_shared_dir() -> None:
    """用 compose 的命令都先建好共享文件夹（G7），restart 也一样。

    compose 自己也会建，留着无害。"""
    assert ".workdata/shared" in _dry_run("restart")


def test_up_is_one_compose_command() -> None:
    """make up 只是 compose 启动的快捷命令（设计 2026-10-28）：
    向量模型由 compose 里的依赖先下好。"""
    out = _dry_run("up")
    assert "up -d --wait backend" in out
    assert "run --rm ollama-init" not in out


def test_bundle_calls_the_script() -> None:
    assert "deploy/bundle-images.sh" in _dry_run("bundle")


def _dry_run_in(tmp_path: Path, target: str) -> str:
    """把 Makefile 拷到 tmp_path 里 make -n：项目目录本身有 .env，测不出没有时的样子。"""
    (tmp_path / "Makefile").write_text((ROOT / "Makefile").read_text(encoding="utf-8"))
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    result = subprocess.run(
        ["make", "-n", target, "COMPOSE=echo"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_compose_commands_need_no_env(tmp_path: Path) -> None:
    """没有 .env 也能用 make 启动（用户决定 2026-11-02，R47）：不再要求先有 .env，
    也不给 compose 传不存在的 --env-file（compose 会直接报找不到文件）。"""
    for target in ("up", "down", "doctor", "backup", "restart", "test-up"):
        out = _dry_run_in(tmp_path, target)
        assert "缺少 .env" not in out
        assert "--env-file" not in out


def test_compose_reads_env_when_present(tmp_path: Path) -> None:
    """有 .env 时照旧用 --env-file 指明它，不靠 deploy/.env 链接（Windows 上链接可能丢）。"""
    (tmp_path / ".env").write_text("")
    assert "--env-file .env" in _dry_run_in(tmp_path, "up")
