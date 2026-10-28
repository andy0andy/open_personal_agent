"""后端容器整份读入 .env（D22），但网关转发模型请求要用的密钥不进后端（终审 I2）。

本地 MCP 服务以 root 跑在后端容器里，能读到后端进程的全部环境变量，所以这些密钥在 compose 里
给后端置空。智能体执行的命令只拿白名单里的变量（D20），本来就看不到。
"""

import importlib.util
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

from config.settings import ModelsConfig

ROOT = Path(__file__).resolve().parents[2]
_BACKEND_NEEDS = {"LITELLM_MASTER_KEY"}  # 后端用它调用本地网关


def _services() -> dict[str, Any]:
    text = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    services: dict[str, Any] = yaml.safe_load(text)["services"]
    return services


def _gateway_secrets() -> set[str]:
    """.env.example 里的各项密钥（…_KEY）、模型来源引用的变量、网关服务单独取的变量。"""
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    names = set(re.findall(r"^([A-Z0-9_]+_KEY)=", example, re.MULTILINE))
    names |= {
        value.removeprefix("os.environ/")
        for source in ModelsConfig().sources
        for value in (source.api_base, source.api_key)
        if value and value.startswith("os.environ/")
    }
    gateway = _services()["litellm"]["environment"]
    names |= {name for value in gateway.values() for name in re.findall(r"\$\{(\w+)", str(value))}
    return names - _BACKEND_NEEDS


def test_gateway_secrets_are_blank_in_backend() -> None:
    backend = _services()["backend"]
    # 前提：整份读入，没有置空的都会进后端
    assert backend["env_file"] == [{"path": "../.env", "required": False}]
    environment = backend["environment"]
    leaked = sorted(name for name in _gateway_secrets() if environment.get(name) != "")
    assert leaked == []


def test_backend_masks_backups_with_an_empty_dir() -> None:
    """后端容器里用不到备份：挂一个空的只读目录把它遮住，命令读不到（设计 2026-10-23 5.1）。

    不用内存盘：podman 的 tmpfs 默认 tmpcopyup，会把底下的备份复制进去，照样读得到（升级实测）；
    关掉它的 notmpcopyup 只有 podman 认，换成 Docker 会起不来。"""
    backend = _services()["backend"]
    assert "./empty-dir:/app/.workdata/backups:ro" in backend["volumes"]
    assert "/app/.workdata/backups" not in backend.get("tmpfs", [])
    empty = Path(__file__).resolve().parents[1] / "empty-dir"
    assert [path.name for path in empty.iterdir()] == ["README.md"]


def test_dependency_cooldown() -> None:
    """依赖冷却期（设计 2026-10-23 7.5）：新发布不满 3 天的版本不装。"""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["uv"]["exclude-newer"] == "3 days"
    assert 'exclude-newer-span = "P3D"' in (ROOT / "uv.lock").read_text(encoding="utf-8")
    workspace = yaml.safe_load(
        (ROOT / "frontend" / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    )
    assert (workspace["minimumReleaseAge"], workspace["saveExact"]) == (4320, True)
    dockerfile = (ROOT / "deploy" / "backend.Dockerfile").read_text(encoding="utf-8")
    assert "frontend/pnpm-workspace.yaml" in dockerfile


def _dockerfile() -> str:
    return (ROOT / "deploy" / "backend.Dockerfile").read_text(encoding="utf-8")


def test_image_cmd_only_runs_existing_modules() -> None:
    """直接运行镜像时的启动命令里，python -m 的模块都还在（G6：backend.security 早已删掉）。"""
    [cmd] = re.findall(r"^CMD (.+)$", _dockerfile(), re.MULTILINE)
    modules = re.findall(r"python -m ([\w.]+)", cmd)
    assert [name for name in modules if importlib.util.find_spec(name) is None] == []


def test_system_python_has_no_pip() -> None:
    """镜像去掉系统 Python 的 pip（积压小问题 D15，修订 D20）：命令里装不了包，模型一次就明白。

    后端用的是虚拟环境，用不到系统的 pip。"""
    assert "python -m pip uninstall -y pip" in _dockerfile()


def _environment_names(service: dict[str, Any]) -> set[str]:
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return set(environment)
    return {item.split("=", 1)[0] for item in environment}


def test_backend_timezone_follows_host() -> None:
    """后端跟着宿主机的时区（G8）：Makefile 取宿主机时区导出 HOST_TZ，取不到时是 UTC；
    只给 backend 设，网关等别的容器不跟着改（.env 里只写 HOST_TZ、不写 TZ）。"""
    services = _services()
    assert services["backend"]["environment"]["TZ"] == "${HOST_TZ:-UTC}"
    others = [name for name, service in services.items() if name != "backend"]
    assert [name for name in others if "TZ" in _environment_names(services[name])] == []
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^_SYSTEM_TZ := \$\(shell readlink /etc/localtime", makefile, re.M)
    # 取不到时不导出空值：不然会盖掉 .env 里写的 HOST_TZ（审查 M1）
    assert "ifneq ($(_SYSTEM_TZ),)\nexport HOST_TZ := $(_SYSTEM_TZ)\nendif" in makefile


def test_backend_runs_the_image_code() -> None:
    """镜像模式（设计 2026-10-28）：后端用镜像里的代码与前端，不挂源码、不自动重载；
    镜像名可在 .env 用 BACKEND_IMAGE 换版本。"""
    backend = _services()["backend"]
    assert backend["image"] == "${BACKEND_IMAGE:-open-personal-agent-backend:latest}"
    mounted = [str(volume).split(":")[1] for volume in backend["volumes"]]
    source = {"/app/agents", "/app/backend", "/app/common", "/app/config"}
    assert not [path for path in mounted if path in source]
    assert "--reload" not in str(backend.get("command", ""))


def test_backend_waits_for_embedding_model() -> None:
    """不经 make 也会先下载向量模型：后端等 ollama-init 跑完再启动。"""
    depends = _services()["backend"]["depends_on"]
    assert depends["ollama-init"] == {"condition": "service_completed_successfully"}


def test_compose_finds_root_env() -> None:
    """在 deploy/ 里执行 compose 时，替换 ${变量} 用的 .env 就是根目录那一份（链接）。"""
    link = ROOT / "deploy" / ".env"
    assert link.is_symlink()
    assert str(link.readlink()) == "../.env"


def test_env_never_enters_image() -> None:
    """密钥不进镜像：哪一层的 .env（包括 deploy/.env 链接）都不进构建上下文。"""
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/.env" in ignored


def test_bundles_never_enter_build_context() -> None:
    """打包出的镜像文件（dist/，几个 GB）不进构建上下文，否则每次构建都要传一遍（审查 I1）。"""
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "dist" in ignored


def test_embedding_download_failure_does_not_stop_backend() -> None:
    """向量模型下不下来（没联网）时 ollama-init 也正常结束：后端照常起来、能对话，
    知识库要等模型下好（make doctor 会报）；否则 make restart 会把正在用的后端弄停（审查 I3）。"""
    [command] = _services()["ollama-init"]["command"]
    assert command.rstrip().endswith("true; }")


def test_env_file_is_optional_for_building() -> None:
    """构建、打包时没有 .env 也能解析 compose 文件（用户决定 2026-10-28）；
    运行时缺密钥由 ${…:?} 报出。"""
    for name in ("litellm", "backend"):
        assert _services()[name]["env_file"] == [{"path": "../.env", "required": False}]
