"""打包镜像（deploy/bundle-images.sh，设计 2026-10-28 4.4）。

用替身命令代替 docker / podman，只看它被怎样调用。"""

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "bundle-images.sh"
_IMAGES = "mirror.gcr.io/ollama/ollama:0.40.3\nopen-personal-agent-backend:latest\n"


def _fake(tmp_path: Path, name: str) -> Path:
    """记下每次调用的参数与 DOCKER_DEFAULT_PLATFORM；config --images 时输出镜像清单。"""
    tool = tmp_path / name
    tool.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$* | ${{DOCKER_DEFAULT_PLATFORM:-}}" >> "{tmp_path}/calls.log"\n'
        f'case "$*" in *"config --images"*) printf "{_IMAGES}" ;; esac\n',
        encoding="utf-8",
    )
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    return tool


def _bundle(tmp_path: Path, name: str, **extra: str) -> tuple[list[str], str]:
    tool = _fake(tmp_path, name)
    env = {**os.environ, "COMPOSE": f"{tool} compose", "OUT_DIR": str(tmp_path / "out"), **extra}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines(), result.stdout


def test_script_is_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_builds_pulls_then_saves_every_image(tmp_path: Path) -> None:
    calls, out = _bundle(tmp_path, "docker", PLATFORM="linux/arm64")
    assert any("build backend" in call for call in calls)
    assert any(" pull " in f" {call} " for call in calls)
    [save] = [call for call in calls if call.startswith("save ")]
    assert save.split(" | ")[0].endswith(
        "mirror.gcr.io/ollama/ollama:0.40.3 open-personal-agent-backend:latest"
    )
    # 目标机器的芯片同时作用于构建与拉取
    assert all(call.endswith("| linux/arm64") for call in calls)
    assert "load -i" in out


def test_skip_build_only_saves(tmp_path: Path) -> None:
    calls, _ = _bundle(tmp_path, "docker", SKIP_BUILD="1")
    assert not [call for call in calls if " build backend" in call or " pull " in call]
    assert [call for call in calls if call.startswith("save ")]


def test_podman_saves_several_images_in_one_archive(tmp_path: Path) -> None:
    """podman save 存多个镜像要加 -m（--multi-image-archive），docker 不用。"""
    calls, _ = _bundle(tmp_path, "podman", SKIP_BUILD="1")
    [save] = [call for call in calls if call.startswith("save ")]
    assert save.startswith("save -m ")


def test_build_machine_needs_no_env(tmp_path: Path) -> None:
    """构建电脑上不需要 .env（用户决定 2026-10-28：.env 只是本机运行时的环境变量）：
    compose 用一份空的环境文件解析，必填的密钥给占位值，只影响解析、不进镜像。"""
    (tmp_path / "deploy").mkdir()
    copy = tmp_path / "deploy" / "bundle-images.sh"
    copy.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    tool = _fake(tmp_path, "docker")
    env = {k: v for k, v in os.environ.items() if not k.startswith("LITELLM_")}
    env |= {"COMPOSE": f"{tool} compose", "OUT_DIR": str(tmp_path / "out")}
    result = subprocess.run(["bash", str(copy)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    assert all("--env-file" in call for call in calls if call.startswith("compose"))


def test_platform_with_skip_build_warns(tmp_path: Path) -> None:
    """只存不构建时 PLATFORM 不起作用：要说出来，不能悄悄存成本机芯片的镜像（审查 M4）。"""
    tool = _fake(tmp_path, "docker")
    env = {
        **os.environ,
        "COMPOSE": f"{tool} compose",
        "OUT_DIR": str(tmp_path / "out"),
        "SKIP_BUILD": "1",
        "PLATFORM": "linux/amd64",
    }
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "PLATFORM" in result.stderr
