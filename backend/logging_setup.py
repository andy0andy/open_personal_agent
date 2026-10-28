"""统一的日志配置（设计 2026-10-23 5.12）。

- 从 INFO 起，带时间、级别、来源，输出到标准错误（容器日志）；
- 警告以上另写一份到 .workdata/logs/backend-error.log：按大小轮转，5MB × 3 份，只有自己能读写；
- 两处都打码（common.redact）。uvicorn 的日志不往上传：它的处理器也换成打码的格式，
  并挂上错误日志。
已知限制：本地 MCP 进程自己的 stderr 直接写到容器日志，不经过这里，打不了码。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from common.redact import redact, secret_values

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
ERROR_LOG = Path("logs") / "backend-error.log"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 3
_OURS = "opa-"  # 自己加的处理器的名字前缀：再配置一次时先拿掉旧的
# 每次请求都记一条 INFO 的库（经网关调模型、HTTP 方式的 MCP），只看警告以上，免得刷屏；
# LiteLLM 还自带处理器，不压的话同一条会以两种格式各打印一遍
_CHATTY = ("httpx", "httpcore", "LiteLLM", "LiteLLM Proxy", "LiteLLM Router")


class RedactingFormatter(logging.Formatter):
    """格式化好的整条日志（含异常栈）再打一遍码。"""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__(FORMAT)
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secrets)


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """轮转出来的新文件也只有自己能读写（默认按 umask 是 0644）。"""

    def _open(self):  # type: ignore[no-untyped-def]
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


def configure_logging(workdata: Path) -> None:
    """配置根日志与 uvicorn 的日志；可以重复调用（先拿掉上次加的处理器）。"""
    formatter = RedactingFormatter(secret_values())
    root = logging.getLogger()
    uvicorn = logging.getLogger("uvicorn")
    for logger in (root, uvicorn):
        _drop_ours(logger)
    root.setLevel(logging.INFO)
    for name in _CHATTY:
        logging.getLogger(name).setLevel(logging.WARNING)

    console = logging.StreamHandler(sys.stderr)
    console.set_name(f"{_OURS}console")
    console.setFormatter(formatter)
    root.addHandler(console)

    path = workdata / ERROR_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    errors = _PrivateRotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    errors.set_name(f"{_OURS}errors")
    errors.setLevel(logging.WARNING)
    errors.setFormatter(formatter)
    root.addHandler(errors)

    for name in ("uvicorn", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)
    if not uvicorn.propagate:
        uvicorn.addHandler(errors)


def _drop_ours(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if (handler.get_name() or "").startswith(_OURS):
            logger.removeHandler(handler)
            handler.close()
