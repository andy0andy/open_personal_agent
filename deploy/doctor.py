"""一条命令体检全部服务（设计 2026-10-23 7.1）：make doctor。

只读：逐项打 ✓ 或 ✗，✗ 下面一行写怎么修，有 ✗ 时退出码为 1；前面的项坏了、这项查不了的打 –。
不打印任何密钥：会话令牌只放在请求头里，输出前还会把它抹掉。模型列表经后端 /api/models 取（不花
token），不用网关的 /health：那个接口会真的调用每个模型。在宿主机上运行，只用标准库；执行命令、
发请求的函数都可以换成替身，单测不碰容器。
"""

import http.client
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

type Run = Callable[[list[str]], tuple[int, str]]
type Fetch = Callable[[str, Mapping[str, str]], tuple[int, str]]

BACKEND = "http://127.0.0.1:8000"
GATEWAY = "http://127.0.0.1:4000"
SERVICES = ("postgres", "litellm", "ollama", "backend")
EMBEDDING = "qwen3-embedding:0.6b"  # docker-compose.yml 里 ollama-init 下载的向量模型
TOKEN_HEADER = "X-Session-Token"
HTTP_TIMEOUT = 5.0  # 秒：每个请求最多等这么久
COMMAND_TIMEOUT = 10.0  # 秒：每条 compose 命令最多等这么久（平时不到 1 秒）
MIN_FREE_GB = 5  # 备份、重新构建镜像都要空间
_BACKUP_TIME = re.compile(r"(\d{8}-\d{6})$")  # 备份名：20261024-030639、pre-restore-20261024-030639


@dataclass(frozen=True)
class Result:
    mark: str  # ✓、✗ 或 –
    name: str
    text: str
    fix: str = ""

    def lines(self) -> str:
        head = f"{self.mark} {self.name}：{self.text}"
        return f"{head}\n  → {self.fix}" if self.fix else head


def main(
    run: Run,
    fetch: Fetch,
    workdata: Path,
    *,
    disk_free: Callable[[Path], int] | None = None,
) -> int:
    """依次体检、打印每一项；返回退出码（有 ✗ 时为 1）。"""
    containers, backend = _containers(run), _backend(fetch)
    token, session = _session_token(fetch)
    if token is None:
        models, files = (
            _no_token("模型", backend, session),
            [_no_token(".workdata 文件", backend, session)],
        )
    else:
        models, files = _models(fetch, token), _data_files(fetch, token)
    results = [
        containers,
        backend,
        _gateway(fetch),
        models,
        _ollama(run),
        _postgres(run),
        *files,
        _disk(workdata, disk_free or _disk_free),
        _backups(workdata),
    ]
    for result in results:
        text = result.lines()
        print(text.replace(token, "***") if token else text)
    failed = sum(result.mark == "✗" for result in results)
    print(f"有 {failed} 项要处理（见上面的 ✗）" if failed else "全部正常")
    return 1 if failed else 0


def compose_runner(prefix: list[str], *, timeout: float = COMMAND_TIMEOUT) -> Run:
    """在 prefix（Makefile 传入的 compose 命令）后面接上子命令执行，返回退出码与标准输出。"""

    def run(args: list[str]) -> tuple[int, str]:
        try:
            done = subprocess.run(
                [*prefix, *args],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, f"超过 {timeout:g} 秒没有结束"
        except OSError as exc:  # 找不到 docker / podman
            return 127, str(exc)
        return done.returncode, done.stdout

    return run


def http_fetch(
    url: str, headers: Mapping[str, str], *, timeout: float = HTTP_TIMEOUT
) -> tuple[int, str]:
    """GET 一个地址，返回状态码与正文；连不上、超时时返回 0 与原因，不抛异常（体检接着往下查）。"""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return 0, f"超过 {timeout:g} 秒没有响应"
        return 0, str(exc.reason)
    except TimeoutError:  # 连上了但迟迟不回：读响应时超时，urllib 不包装这一种
        return 0, f"超过 {timeout:g} 秒没有响应"
    except (OSError, http.client.HTTPException) as exc:
        return 0, str(exc) or type(exc).__name__


def _session_token(fetch: Fetch) -> tuple[str | None, int]:
    """会话令牌与 /api/session 的状态码（连不上时为 0）。"""
    status, body = fetch(f"{BACKEND}/api/session", {})
    token = _json(body).get("token") if status == 200 else None
    return (token if isinstance(token, str) and token else None), status


def _no_token(name: str, backend: Result, status: int) -> Result:
    """要令牌的两项拿不到令牌：后端没起来就跳过（后端那一项已经是 ✗），后端好好的却拿不到算 ✗。"""
    if backend.mark != "✓":
        return Result("–", name, "后端没在运行，跳过")
    fix = "make restart；还不行就 make logs 看后端日志"
    return Result("✗", name, f"取不到会话令牌（/api/session 返回 {status}）", fix)


def _containers(run: Run) -> Result:
    code, out = run(["ps", "--format", "json"])
    if code != 0:
        return Result(
            "✗", "容器", "查不到容器状态", "确认 podman（podman machine start）或 Docker 在运行"
        )
    states = {_service(item): item for item in _json_lines(out)}
    down = [name for name in SERVICES if states.get(name, {}).get("State") != "running"]
    if down:
        return Result("✗", "容器", f"{'、'.join(down)} 没在运行", "make up")
    sick = [name for name in SERVICES if _unhealthy(states[name])]
    if sick:
        return Result("✗", "容器", f"{'、'.join(sick)} 健康检查不通过", "make logs 看原因")
    return Result("✓", "容器", f"{'、'.join(SERVICES)} 都在运行")


def _service(item: dict[str, Any]) -> str | None:
    """compose 的输出有 Service；podman-compose 转给 podman ps 的输出没有，
    服务名在 compose 打的标签里。"""
    labels = item.get("Labels")
    from_labels = labels.get("com.docker.compose.service") if isinstance(labels, dict) else None
    return item.get("Service") or from_labels


def _unhealthy(item: dict[str, Any]) -> bool:
    """compose 的输出有 Health；podman ps 的没有，
    健康状况写在 Status 里（如 "Up 2 hours (unhealthy)"）。"""
    if "Health" in item:
        return bool(item["Health"] == "unhealthy")
    return "(unhealthy)" in str(item.get("Status", ""))


def _backend(fetch: Fetch) -> Result:
    status, body = fetch(f"{BACKEND}/api/health", {})
    if status == 200:
        return Result("✓", "后端", "/api/health 正常")
    fix = "make up；起不来时 make logs 看后端日志里的原因"
    return Result("✗", "后端", _unreachable(BACKEND, status, body), fix)


def _gateway(fetch: Fetch) -> Result:
    status, body = fetch(f"{GATEWAY}/health/readiness", {})
    db = _json(body).get("db")
    if status == 200 and db == "connected":
        return Result("✓", "网关", "就绪，网关数据库已连接")
    if status == 200 or db is not None:  # 网关在回话：连不上自己的数据库时返回 503，正文照样带 db
        fix = "先看 PostgreSQL 那一项，再 make restart-gateway"
        return Result("✗", "网关", f"网关自己的数据库没连上（{db}）", fix)
    fix = "make restart-gateway；还不行就 make logs 看 litellm 的日志"
    return Result("✗", "网关", _unreachable(GATEWAY, status, body), fix)


def _models(fetch: Fetch, token: str) -> Result:
    status, body = fetch(f"{BACKEND}/api/models", {TOKEN_HEADER: token})
    models = _json_list(body) if status == 200 else None
    if models is None:
        fix = "先看网关那一项；网关正常时 make logs 看后端日志"
        return Result("✗", "模型", f"取不到模型列表（后端返回 {status}）", fix)
    chat = sum(model.get("mode", "chat") == "chat" for model in models)
    embedding = sum(model.get("mode") == "embedding" for model in models)
    text = f"对话模型 {chat} 个、向量模型 {embedding} 个"
    if chat == 0:
        return Result("✗", "模型", text, "在模型页添加对话模型")
    if embedding == 0:
        return Result("✗", "模型", text, "在模型页添加向量模型（来源选“本机 Ollama”）")
    return Result("✓", "模型", text)


def _ollama(run: Run) -> Result:
    code, out = run(["exec", "-T", "ollama", "ollama", "list"])
    if code != 0:
        return Result("✗", "Ollama", "执行不了 ollama list（容器没在运行？）", "make infra-up")
    if EMBEDDING not in out:
        fix = "make infra-up（会自动下载，约 640 MB）"
        return Result("✗", "Ollama", f"没有向量模型 {EMBEDDING}", fix)
    return Result("✓", "Ollama", f"向量模型 {EMBEDDING} 已下载")


def _postgres(run: Run) -> Result:
    code, _ = run(["exec", "-T", "postgres", "pg_isready", "-U", "agent"])
    if code != 0:
        fix = "make infra-up；还不行就 make logs 看 postgres 的日志"
        return Result("✗", "PostgreSQL", "不接受连接", fix)
    return Result("✓", "PostgreSQL", "接受连接")


def _data_files(fetch: Fetch, token: str) -> list[Result]:
    """设置页同一个接口：写坏的每个一行；没有的（比如还没停用过技能）用默认，不算问题。"""
    name = ".workdata 文件"
    status, body = fetch(f"{BACKEND}/api/settings/files", {TOKEN_HEADER: token})
    files = _json_list(body) if status == 200 else None
    if files is None:
        return [Result("✗", name, f"取不到文件状态（后端返回 {status}）", "make logs 看后端日志")]
    fix = "照提示改好这个文件；MCP 服务清单、审批规则改好后在 MCP 页点“重新加载”"
    broken = [
        Result("✗", name, str(item.get("detail") or f"{item.get('path')} 有误"), fix)
        for item in files
        if item.get("state") == "error"
    ]
    if broken:
        return broken
    missing = [str(item.get("path")) for item in files if item.get("state") == "missing"]
    note = f"（还没有：{'、'.join(missing)}，用默认）" if missing else ""
    return [Result("✓", name, f"{len(files) - len(missing)} 项正常{note}")]


def _disk(workdata: Path, disk_free: Callable[[Path], int]) -> Result:
    free = disk_free(workdata)
    text = f"剩余 {free / 1024**3:.1f} GB"
    if free < MIN_FREE_GB * 1024**3:
        return Result("✗", "磁盘", text, f"清理出至少 {MIN_FREE_GB} GB：备份、重新构建镜像都要空间")
    return Result("✓", "磁盘", text)


def _backups(workdata: Path) -> Result:
    names = [path.parent.name for path in (workdata / "backups").glob("*/manifest.txt")]
    if not names:
        return Result("✗", "备份", "还没有", "make backup")
    latest = max(names, key=_backup_time)
    try:
        when = datetime.strptime(_backup_time(latest), "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:  # 名字里没有时间，或者像时间其实不是（如 20261399-999999）
        when = "?"
    return Result("✓", "备份", f"{len(names)} 份，最近一次 {when}（{latest}）")


def _backup_time(name: str) -> str:
    match = _BACKUP_TIME.search(name)
    return match.group(1) if match else ""


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path if path.exists() else Path.cwd()).free


def _unreachable(url: str, status: int, reason: str) -> str:
    return f"连不上 {url}（{reason}）" if status == 0 else f"{url} 返回 {status}"


def _json(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _json_list(body: str) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [item for item in data if isinstance(item, dict)]


def _json_lines(text: str) -> list[dict[str, Any]]:
    """compose ps --format json：新版每行一个对象，旧版是一行数组；
    podman ps（podman-compose 转过去的）是多行排版的整段数组。"""
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, list):
        return [row for row in whole if isinstance(row, dict)]
    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        rows = data if isinstance(data, list) else [data]
        items += [row for row in rows if isinstance(row, dict)]
    return items


if __name__ == "__main__":
    compose = os.environ.get("DC")
    if not compose:
        sys.exit("请用 make doctor 运行（它会选好 docker compose 或 podman compose）")
    sys.exit(main(compose_runner(shlex.split(compose)), http_fetch, Path(".workdata")))
