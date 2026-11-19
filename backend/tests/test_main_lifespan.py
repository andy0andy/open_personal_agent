"""真实的启动与关闭顺序（backend/main.py 的 lifespan，积压小问题 I13）：接口测试与端到端都不走它。

外部依赖全换成记录调用的替身，只看先后：迁移配置 → 写默认文件 → 组装智能体 → 标记中断的运行并
登记写索引 → 开始连 MCP → 启动两条队列；关闭时先停运行，再停队列、关 MCP，最后关连接池。
"""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI

from backend import main
from common.errors import UpstreamError


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def sync(self, name: str, result: Any = None) -> Any:
        def record(*_: Any, **__: Any) -> Any:
            self.calls.append(name)
            return result

        return record

    def run(self, name: str, result: Any = None) -> Any:
        async def record(*_: Any, **__: Any) -> Any:
            self.calls.append(name)
            return result

        return record


def _services(rec: _Recorder, workdata: Path) -> SimpleNamespace:
    return SimpleNamespace(
        runs=SimpleNamespace(fail_unfinished=rec.run("fail_unfinished", [uuid.uuid4()])),
        followups=SimpleNamespace(index_later=rec.run("index_later"), handlers=lambda: {}),
        integrations=SimpleNamespace(load=rec.run("mcp.load")),
        jobs=SimpleNamespace(start=rec.run("jobs.start"), stop=rec.run("jobs.stop")),
        document_queue=SimpleNamespace(
            start=rec.run("document_queue.start"), stop=rec.run("document_queue.stop")
        ),
        document_jobs=SimpleNamespace(handlers=lambda: {}),
        manager=SimpleNamespace(shutdown=rec.run("manager.shutdown")),
        settings=SimpleNamespace(workdata_dir=workdata),
    )


async def test_startup_and_shutdown_run_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rec = _Recorder()
    env = SimpleNamespace(workdata_dir=tmp_path, database_url="postgresql://unused")
    settings = SimpleNamespace(config_dir=tmp_path / "config", workdata_dir=tmp_path)
    pool = SimpleNamespace(open=rec.run("pool.open"), close=rec.run("pool.close"))
    agent = SimpleNamespace(close=rec.run("agent.close"))
    monkeypatch.setattr(main, "get_settings", lambda: env)
    monkeypatch.setattr(main, "configure_logging", rec.sync("logging"))
    monkeypatch.setattr(main, "create_pool", lambda _url: pool)
    monkeypatch.setattr(
        main, "AppSettingsRepo", lambda _pool: SimpleNamespace(all=rec.run("settings.read", {}))
    )
    monkeypatch.setattr(main, "load_settings", lambda _stored: settings)
    monkeypatch.setattr(main, "migrate_config_files", rec.sync("migrate_config"))
    monkeypatch.setattr(main, "seed_files_once", rec.sync("seed_files"))
    monkeypatch.setattr(main, "build_agent", rec.run("build_agent", agent))
    monkeypatch.setattr(
        main, "build_services", rec.sync("build_services", _services(rec, tmp_path))
    )
    monkeypatch.setattr(main, "_seed_models", rec.run("seed_models"))
    monkeypatch.setattr(main, "_prepare_embeddings", rec.run("prepare_embeddings"))

    async with main.lifespan(FastAPI()):
        await asyncio.sleep(0)  # 服务运行期间：后台导入模型的任务得以开始
        started = list(rec.calls)
    stopped = rec.calls[len(started) :]

    assert started[:10] == [
        "logging",
        "pool.open",
        "settings.read",
        "migrate_config",
        "seed_files",
        "build_agent",
        "build_services",
        "fail_unfinished",
        "index_later",
        "mcp.load",
    ]
    rest = started[10:]
    assert sorted(rest) == [
        "document_queue.start",
        "jobs.start",
        "prepare_embeddings",
        "seed_models",
    ]
    assert rest.index("jobs.start") < rest.index("document_queue.start")
    assert stopped == [
        "manager.shutdown",
        "jobs.stop",
        "document_queue.stop",
        "agent.close",
        "pool.close",
    ]


async def test_document_hashes_are_backfilled_on_every_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """补算文档内容哈希每次启动都做、只补还没有的（审查 Minor 3）：从升级前的备份恢复后也补得上。"""
    rec = _Recorder()
    for name in ("seed_models_once", "enable_prompt_caching_once", "retire_ollama_models_once"):
        monkeypatch.setattr(main, name, rec.run(name))
    monkeypatch.setattr(main, "load_seed_models", lambda _path: [])
    documents = SimpleNamespace(backfill_hashes=rec.run("backfill_hashes", 0))
    services = SimpleNamespace(
        settings=SimpleNamespace(workdata_dir=tmp_path, adapters=SimpleNamespace(embedder="onnx")),
        models=None,
        agent=SimpleNamespace(conversations=None, documents=documents),
    )
    await main._seed_models(cast(Any, services))
    await main._seed_models(cast(Any, services))
    assert rec.calls.count("backfill_hashes") == 2
    # 进程内跑向量模型时（D28），网关里指向 Ollama 的旧模型要清一次（做没做过由它自己记）
    assert rec.calls.count("retire_ollama_models_once") == 2
    # 改用经网关的向量模型时不清：它可能正是用户配的 Ollama
    services.settings.adapters.embedder = "litellm_proxy"
    await main._seed_models(cast(Any, services))
    assert rec.calls.count("retire_ollama_models_once") == 2


class _Knowledge:
    """假的知识存储：每次补算返回预设的条数，记下被调用了几次。"""

    def __init__(self, counts: list[int], *, broken: bool = False) -> None:
        self.counts = counts
        self.broken = broken
        self.calls = 0

    async def reembed_missing(self) -> int:
        self.calls += 1
        if self.broken:
            raise UpstreamError("向量化服务不可用：向量模型运行出错")
        return self.counts.pop(0)


def _embedding_services(
    tmp_path: Path, knowledge: _Knowledge | None, *, embedder: str = "onnx"
) -> Any:
    settings = SimpleNamespace(
        adapters=SimpleNamespace(embedder=embedder),
        knowledge=SimpleNamespace(embedding_model="embeddinggemma-300m-q4"),
        models_dir=tmp_path / "models",
        embedding_download_base="https://models.test",
    )
    return SimpleNamespace(settings=settings, agent=SimpleNamespace(knowledge=knowledge))


async def test_embeddings_are_prepared_in_the_background(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """启动后在后台（D28）：先确认向量模型文件齐全（缺了就下载），再给没有向量的条目补算到补完。"""
    downloads: list[tuple[Any, ...]] = []

    async def ensure(model_dir: Path, spec: Any, *, base_url: str) -> list[str]:
        downloads.append((model_dir, spec.name, base_url))
        return []

    monkeypatch.setattr(main, "ensure_model", ensure)
    knowledge = _Knowledge([20, 3, 0])
    await main._prepare_embeddings(_embedding_services(tmp_path, knowledge))
    assert downloads == [
        (
            tmp_path / "models" / "embeddinggemma-300m-q4",
            "embeddinggemma-300m-q4",
            "https://models.test",
        )
    ]
    assert knowledge.calls == 3


async def test_download_is_retried_until_it_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """模型下不下来（没联网、网络抖动）：只记日志、后端照常可用，隔一会儿自己再试，
    不用用户重启；下好以后接着补算。"""
    attempts = 0

    async def ensure(*_: Any, **__: Any) -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise UpstreamError("向量模型下载失败：连不上下载地址")
        return ["model_q4.onnx_data"]

    monkeypatch.setattr(main, "ensure_model", ensure)
    monkeypatch.setattr(main, "_DOWNLOAD_RETRY_SECONDS", (0,))
    knowledge = _Knowledge([5, 0])
    await main._prepare_embeddings(_embedding_services(tmp_path, knowledge))
    assert attempts == 3
    assert knowledge.calls == 2


async def test_backfill_waits_while_the_download_keeps_failing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """一直下不下来就一直隔一会儿再试（后端关闭时取消这个任务）；没有模型不去补算。"""
    tried = asyncio.Event()
    attempts = 0

    async def ensure(*_: Any, **__: Any) -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            tried.set()
        raise UpstreamError("向量模型下载失败：连不上下载地址")

    monkeypatch.setattr(main, "ensure_model", ensure)
    monkeypatch.setattr(main, "_DOWNLOAD_RETRY_SECONDS", (0,))
    knowledge = _Knowledge([5, 0])
    task = asyncio.create_task(main._prepare_embeddings(_embedding_services(tmp_path, knowledge)))
    await asyncio.wait_for(tried.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert knowledge.calls == 0


async def test_unexpected_errors_stay_in_the_background(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """磁盘满、没权限这类意外也只记日志：后台任务的异常没人接，不能让它带着异常悄悄结束。"""

    async def ensure(*_: Any, **__: Any) -> list[str]:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(main, "ensure_model", ensure)
    knowledge = _Knowledge([5, 0])
    await main._prepare_embeddings(_embedding_services(tmp_path, knowledge))
    assert knowledge.calls == 0


async def test_backfill_stops_quietly_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def ensure(*_: Any, **__: Any) -> list[str]:
        return []

    monkeypatch.setattr(main, "ensure_model", ensure)
    knowledge = _Knowledge([], broken=True)
    await main._prepare_embeddings(_embedding_services(tmp_path, knowledge))
    assert knowledge.calls == 1  # 出错就停，下次启动再补


async def test_gateway_embedder_downloads_nothing_but_still_backfills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """改用经网关的向量模型时没有本机模型可下，补算照做。"""

    async def ensure(*_: Any, **__: Any) -> list[str]:
        raise AssertionError("不该下载")

    monkeypatch.setattr(main, "ensure_model", ensure)
    knowledge = _Knowledge([1, 0])
    services = _embedding_services(tmp_path, knowledge, embedder="litellm_proxy")
    await main._prepare_embeddings(services)
    assert knowledge.calls == 2
    # 没有知识库也不出错
    await main._prepare_embeddings(_embedding_services(tmp_path, None, embedder="litellm_proxy"))
