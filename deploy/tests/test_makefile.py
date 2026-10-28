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
