"""把通用错误类型映射为 HTTP 状态码。"""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from common.errors import (
    AppError,
    ConflictError,
    InvalidConfigError,
    InvalidRequestError,
    NotFoundError,
    TooLargeError,
    UnsupportedError,
    UpstreamError,
)

logger = logging.getLogger(__name__)

_STATUS: dict[type[AppError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidConfigError: 422,
    InvalidRequestError: 422,
    TooLargeError: 413,
    UnsupportedError: 415,
    UpstreamError: 503,
}


def install_error_handlers(app: FastAPI) -> None:
    for error_type, status_code in _STATUS.items():
        app.add_exception_handler(error_type, _respond_with(status_code))
    app.add_exception_handler(ClientDisconnect, _client_gone)


async def _client_gone(_: Request, __: Exception) -> JSONResponse:
    """上传途中浏览器断开（关页面、取消上传）：不是服务器出错，记一行、回 400（积压小问题 D5）。
    浏览器已经走了，这个回应它收不到；写了一半的文件 save_upload 已经删掉。"""
    logger.info("上传中途断开")
    return JSONResponse(status_code=400, content={"detail": "上传中途断开"})


def _respond_with(status_code: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handle
