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
    assert sorted(rest) == ["document_queue.start", "jobs.start", "seed_models"]
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
    for name in ("seed_models_once", "enable_prompt_caching_once"):
        monkeypatch.setattr(main, name, rec.run(name))
    monkeypatch.setattr(main, "load_seed_models", lambda _path: [])
    documents = SimpleNamespace(backfill_hashes=rec.run("backfill_hashes", 0))
    services = SimpleNamespace(
        settings=SimpleNamespace(workdata_dir=tmp_path),
        models=None,
        agent=SimpleNamespace(conversations=None, documents=documents),
    )
    await main._seed_models(cast(Any, services))
    await main._seed_models(cast(Any, services))
    assert rec.calls.count("backfill_hashes") == 2
