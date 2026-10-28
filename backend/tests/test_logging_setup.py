"""统一日志配置（设计 2026-10-23 5.12）：带时间、级别、来源，打码；警告以上另写一份错误日志。"""

import logging
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.logging_setup import RedactingFormatter, configure_logging

LEAK = "verysecretvalue123"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """配置的是全局的日志：测完还原，别影响别的测试。"""
    loggers = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.access")]
    saved = [(logger, list(logger.handlers), logger.level) for logger in loggers]
    yield
    for logger, handlers, level in saved:
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers = handlers
        logger.setLevel(level)


def _error_log(workdata: Path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (workdata / "logs" / "backend-error.log").read_text(encoding="utf-8")


def test_errors_go_to_a_redacted_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", LEAK)
    configure_logging(tmp_path)
    logger = logging.getLogger("backend.test")
    logger.error("调用失败：key %s，sk-abcdefgh12345678", LEAK)
    logger.info("普通信息")
    text = _error_log(tmp_path)
    assert LEAK not in text
    assert "调用失败：key ***，sk-***" in text
    assert "ERROR backend.test:" in text
    assert "普通信息" not in text  # 错误日志只收警告以上
    mode = stat.S_IMODE((tmp_path / "logs" / "backend-error.log").stat().st_mode)
    assert mode == 0o600


def test_exception_traces_are_redacted(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    try:
        raise RuntimeError("Authorization: Bearer abcdefgh12345678")
    except RuntimeError:
        logging.getLogger("backend.test").exception("出错了")
    text = _error_log(tmp_path)
    assert "abcdefgh12345678" not in text
    assert "Bearer ***" in text
    assert "Traceback" in text


def test_configuring_twice_does_not_duplicate_handlers(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    configure_logging(tmp_path)
    logging.getLogger("backend.test").warning("只写一次")
    assert _error_log(tmp_path).count("只写一次") == 1
    assert logging.getLogger().level == logging.INFO


def test_uvicorn_errors_are_kept_too(tmp_path: Path) -> None:
    """uvicorn 的日志不往上传：它自己的处理器换成打码的格式，错误也写进错误日志。"""
    uvicorn = logging.getLogger("uvicorn")
    uvicorn.addHandler(logging.StreamHandler())
    uvicorn.propagate = False
    configure_logging(tmp_path)
    logging.getLogger("uvicorn.error").error("Exception in ASGI application: sk-abcdefgh12345678")
    text = _error_log(tmp_path)
    # litellm 导入时也给 uvicorn.error 挂了打码过滤器（换成 REDACTED）：只看密钥确实不在
    assert "ERROR uvicorn.error: Exception in ASGI application:" in text
    assert "sk-abcdefgh12345678" not in text
    assert all(isinstance(handler.formatter, RedactingFormatter) for handler in uvicorn.handlers)


def test_chatty_libraries_log_warnings_only(tmp_path: Path) -> None:
    """每次请求都记一条 INFO 的库只看警告以上（审查 Minor 8）：LiteLLM 还自带处理器，
    不压的话同一条会打印两遍。"""
    configure_logging(tmp_path)
    for name in ("httpx", "httpcore", "LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name
