"""接口的错误映射（backend/api/errors.py）。"""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import ClientDisconnect

from backend.api.errors import install_error_handlers


async def test_client_disconnect_is_not_a_server_error(caplog: pytest.LogCaptureFixture) -> None:
    """上传途中浏览器断开（积压小问题 D5）：不再当成服务器出错（500 + 整段堆栈），
    记一行、回 400。"""
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/upload")
    async def upload() -> None:
        raise ClientDisconnect()

    with caplog.at_level(logging.INFO):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post("/upload", content=b"x")
    assert resp.status_code == 400
    assert "上传中途断开" in caplog.text
    assert "Traceback" not in caplog.text
