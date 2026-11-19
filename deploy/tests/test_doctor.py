"""make doctor（设计 2026-10-23 7.1）：逐项 ✓ / ✗，✗ 下面写怎么修；不打印令牌；不会卡住。"""

import json
import socket
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from agents.main_agent.models import ONNX_MODELS
from config.settings import KnowledgeConfig
from deploy.doctor import (
    BACKEND,
    EMBEDDING_DIR,
    EMBEDDING_FILES,
    GATEWAY,
    Run,
    compose_runner,
    http_fetch,
    main,
)

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "tok-secret-123"
FILES = f"{BACKEND}/api/settings/files"


class Fake:
    """一套全部正常的服务：测试里改掉其中一项来模拟故障。"""

    def __init__(self) -> None:
        self.states = dict.fromkeys(("backend", "litellm", "postgres"), "running")
        self.commands: dict[str, tuple[int, str]] = {
            "postgres": (0, "/var/run/postgresql:5432 - accepting connections\n"),
        }
        # 向量模型在后端进程里跑（D28），网关里只有对话模型
        models = [{"name": "claude-sonnet", "mode": "chat"}, {"name": "deepseek", "mode": "chat"}]
        files = [
            {"path": ".workdata/config/mcp_servers.yaml", "state": "ok", "detail": None},
            {"path": ".workdata/config/skills.yaml", "state": "missing", "detail": None},
        ]
        self.responses: dict[str, tuple[int, str]] = {
            f"{BACKEND}/api/health": (200, '{"status": "ok"}'),
            f"{GATEWAY}/health/readiness": (200, '{"status": "healthy", "db": "connected"}'),
            f"{BACKEND}/api/session": (200, json.dumps({"token": TOKEN})),
            f"{BACKEND}/api/models": (200, json.dumps(models)),
            FILES: (200, json.dumps(files)),
        }
        self.tokens: list[str | None] = []
        self.compose_ok = True

    def run(self, args: list[str]) -> tuple[int, str]:
        if not self.compose_ok:
            return 127, "No such file or directory: 'podman'"
        if args[0] == "ps":
            lines = [json.dumps({"Service": s, "State": st}) for s, st in self.states.items()]
            return 0, "\n".join(lines) + "\n"
        return self.commands[args[2]]  # exec -T <服务> 命令…

    def fetch(self, url: str, headers: Mapping[str, str]) -> tuple[int, str]:
        self.tokens.append(headers.get("X-Session-Token"))
        return self.responses[url]


def _model_files(workdata: Path) -> Path:
    """按体检认的字节数造出向量模型的占位文件（只看在不在、大小对不对）。"""
    folder = workdata / EMBEDDING_DIR
    folder.mkdir(parents=True)
    for name, size in EMBEDDING_FILES.items():
        with (folder / name).open("wb") as handle:
            handle.truncate(size)
    return folder


def _workdata(tmp_path: Path, *backups: str) -> Path:
    _model_files(tmp_path)
    for name in backups:
        (tmp_path / "backups" / name).mkdir(parents=True)
        (tmp_path / "backups" / name / "manifest.txt").write_text("备份清单\n", encoding="utf-8")
    return tmp_path


def _plenty(path: Path) -> int:
    return 120 * 1024**3


def _check(fake: Fake, workdata: Path) -> int:
    return main(fake.run, fake.fetch, workdata, disk_free=_plenty)


def test_doctor_all_good(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake()
    workdata = _workdata(tmp_path, "20261023-120000", "pre-restore-20261024-030639")
    assert _check(fake, workdata) == 0
    out = capsys.readouterr().out
    assert "✗" not in out
    for item in (
        "容器",
        "后端",
        "网关",
        "模型",
        "向量模型",
        "PostgreSQL",
        ".workdata 文件",
        "磁盘",
    ):
        assert f"✓ {item}：" in out
    assert "✓ 模型：对话模型 2 个\n" in out  # 网关里不需要有向量模型（D28）
    assert "✓ 向量模型：embeddinggemma-300m-q4 已下载" in out
    assert "还没有：.workdata/config/skills.yaml" in out
    assert "✓ 磁盘：剩余 120.0 GB" in out
    assert "✓ 备份：2 份，最近一次 2026-10-24 03:06（pre-restore-20261024-030639）" in out
    assert out.splitlines()[-1] == "全部正常"
    assert fake.tokens.count(TOKEN) == 2  # 模型列表与文件状态都带着令牌


def _backend_down(fake: Fake) -> None:
    fake.states["backend"] = "exited"
    for url in [url for url in fake.responses if url.startswith(BACKEND)]:
        fake.responses[url] = (0, "Connection refused")


def _gateway_down(fake: Fake) -> None:
    fake.responses[f"{GATEWAY}/health/readiness"] = (0, "Connection refused")


def _gateway_without_db(fake: Fake) -> None:
    # LiteLLM 连不上自己的数据库时返回 503，正文照样带 db
    fake.responses[f"{GATEWAY}/health/readiness"] = (
        503,
        '{"status": "healthy", "db": "disconnected"}',
    )


def _session_broken(fake: Fake) -> None:
    fake.responses[f"{BACKEND}/api/session"] = (500, "Internal Server Error")


def _no_chat_model(fake: Fake) -> None:
    fake.responses[f"{BACKEND}/api/models"] = (200, "[]")


def _broken_file(fake: Fake) -> None:
    detail = ".workdata/config/mcp_servers.yaml 有误：第 3 行不是合法的 YAML"
    broken = [{"path": ".workdata/config/mcp_servers.yaml", "state": "error", "detail": detail}]
    fake.responses[FILES] = (200, json.dumps(broken))


def _no_compose(fake: Fake) -> None:
    fake.compose_ok = False


def _garbage(fake: Fake) -> None:
    fake.responses[f"{BACKEND}/api/models"] = (200, "<html>出错了</html>")
    fake.responses[FILES] = (200, "{}")


@pytest.mark.parametrize(
    ("breaks", "expected"),
    [
        (
            _backend_down,
            [
                "✗ 容器：backend 没在运行\n  → make up",
                "✗ 后端：连不上 http://127.0.0.1:8000（Connection refused）\n  → make up",
                "– 模型：后端没在运行，跳过",
                "– .workdata 文件：后端没在运行，跳过",
            ],
        ),
        (
            _gateway_down,
            [
                "✗ 网关：连不上 http://127.0.0.1:4000（Connection refused）\n"
                "  → make restart-gateway"
            ],
        ),
        (_gateway_without_db, ["✗ 网关：网关自己的数据库没连上（disconnected）\n  → "]),
        (
            _session_broken,
            [
                "✓ 后端：",
                "✗ 模型：取不到会话令牌（/api/session 返回 500）\n  → make restart",
                "✗ .workdata 文件：取不到会话令牌（/api/session 返回 500）\n  → make restart",
            ],
        ),
        (_no_chat_model, ["✗ 模型：对话模型 0 个\n  → 在模型页添加对话模型"]),
        (
            _broken_file,
            [
                "✗ .workdata 文件：.workdata/config/mcp_servers.yaml 有误：第 3 行不是合法的 YAML\n"
                "  → "
            ],
        ),
        (
            _no_compose,
            [
                "✗ 容器：查不到容器状态\n  → ",
                "✗ PostgreSQL：",
            ],
        ),
        (_garbage, ["✗ 模型：取不到模型列表", "✗ .workdata 文件：取不到文件状态"]),
    ],
)
def test_doctor_reports_each_failure_with_a_fix(
    breaks: Callable[[Fake], None],
    expected: list[str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = Fake()
    breaks(fake)
    assert _check(fake, _workdata(tmp_path, "20261024-030639")) == 1
    out = capsys.readouterr().out
    for text in expected:
        assert text in out
    assert out.splitlines()[-1].startswith("有 ")


def test_no_backup_and_low_disk_are_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake()
    assert main(fake.run, fake.fetch, tmp_path, disk_free=lambda path: 3 * 1024**3) == 1
    out = capsys.readouterr().out
    assert "✗ 磁盘：剩余 3.0 GB\n  → " in out
    assert "✗ 备份：还没有\n  → make backup" in out


def test_odd_backup_names_do_not_crash(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake()
    assert _check(fake, _workdata(tmp_path, "20261399-999999")) == 0
    assert "✓ 备份：1 份，最近一次 ?（20261399-999999）" in capsys.readouterr().out


def test_doctor_never_prints_the_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake = Fake()
    # 后端把令牌写进了报错原文、模型接口也回显了它：输出里都不能出现
    leaked = [{"path": ".workdata/config/skills.yaml", "state": "error", "detail": f"令牌 {TOKEN}"}]
    fake.responses[FILES] = (200, json.dumps(leaked))
    fake.responses[f"{BACKEND}/api/models"] = (401, f"令牌 {TOKEN} 不对")
    _check(fake, _workdata(tmp_path, "20261024-030639"))
    out = capsys.readouterr().out
    assert TOKEN not in out
    assert "✗ .workdata 文件：令牌 ***" in out


def test_doctor_times_out_instead_of_hanging() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()  # 接受连接但永远不回
        port = server.getsockname()[1]
        status, reason = http_fetch(f"http://127.0.0.1:{port}/api/health", {}, timeout=0.2)
    assert (status, reason) == (0, "超过 0.2 秒没有响应")
    stuck = [sys.executable, "-c", "import time; time.sleep(30)"]  # 允许等待：模拟卡住的命令
    assert compose_runner(stuck, timeout=0.2)(["ps"]) == (124, "超过 0.2 秒没有结束")


def test_gateway_embedding_models_are_counted_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """改用经网关的向量模型时（adapters.embedder: litellm_proxy）照样数得出来。"""
    fake = Fake()
    models = [{"name": "claude-sonnet", "mode": "chat"}, {"name": "embed-x", "mode": "embedding"}]
    fake.responses[f"{BACKEND}/api/models"] = (200, json.dumps(models))
    assert _check(fake, _workdata(tmp_path, "20261024-030639")) == 0
    assert "✓ 模型：对话模型 1 个、向量模型 1 个" in capsys.readouterr().out


def test_missing_embedding_model_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """向量模型还没下好（首次启动在后台下载，或没联网）：说明缺哪个、怎么办。"""
    fake = Fake()
    workdata = _workdata(tmp_path, "20261024-030639")
    (workdata / EMBEDDING_DIR / "model_q4.onnx_data").unlink()
    assert _check(fake, workdata) == 1
    out = capsys.readouterr().out
    assert "✗ 向量模型：还没下载好（缺 model_q4.onnx_data）\n  → 后端启动后会自动下载" in out
    assert "EMBEDDING_DOWNLOAD_BASE" in out


def test_embedding_model_file_with_wrong_size(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = Fake()
    workdata = _workdata(tmp_path, "20261024-030639")
    (workdata / EMBEDDING_DIR / "tokenizer.json").write_bytes(b"{}")
    assert _check(fake, workdata) == 1
    assert "✗ 向量模型：文件大小不对（tokenizer.json）\n  → " in capsys.readouterr().out


def test_doctor_knows_the_same_model_files() -> None:
    """体检认的向量模型目录、文件名、字节数，和后端用的是同一份（体检只用标准库，
    不能直接导入后端的定义；积压小问题 G11 的做法）。"""
    spec = ONNX_MODELS[KnowledgeConfig().embedding_model]
    assert f"models/{spec.name}" == EMBEDDING_DIR
    assert {name: file.size for name, file in spec.files.items()} == EMBEDDING_FILES
    compose = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ollama" not in compose.lower()


def _podman_ps(fake: Fake, backend_status: str = "Up 2 hours (healthy)") -> Run:
    """podman ps --format json 的样子：多行排版的整段数组，没有 Service 和 Health，
    服务名在 compose 打的标签里，健康状况写在 Status 里。"""
    rows = [
        {
            "Names": [f"open-personal-agent-{name}-1"],
            "State": "running",
            "Status": backend_status if name == "backend" else "Up 2 hours (healthy)",
            "Labels": {"com.docker.compose.service": name},
        }
        for name in fake.states
    ]

    def run(args: list[str]) -> tuple[int, str]:
        if args[0] == "ps":
            return 0, json.dumps(rows, indent=2) + "\n"
        return fake.run(args)

    return run


def test_containers_understand_podman_ps_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """compose 换成 podman-compose 时 ps 的输出是 podman 的格式，也认得（积压小问题 G12）。"""
    fake = Fake()
    workdata = _workdata(tmp_path, "20261023-120000")
    assert main(_podman_ps(fake), fake.fetch, workdata, disk_free=_plenty) == 0
    assert "✓ 容器：" in capsys.readouterr().out
    sick = _podman_ps(fake, backend_status="Up 2 minutes (unhealthy)")
    assert main(sick, fake.fetch, workdata, disk_free=_plenty) == 1
    assert "✗ 容器：backend 健康检查不通过" in capsys.readouterr().out
