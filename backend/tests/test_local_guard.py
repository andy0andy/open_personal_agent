"""本机令牌与 Host 校验（设计 2026-10-23 5.11，D25 修订 D23 第 5 条）。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from backend.api.local_guard import LocalGuard
from backend.main import create_app

TOKEN = "t" * 43
UNAUTHORIZED = {"detail": "会话令牌不对或已过期，请刷新页面"}


async def _ok(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _guarded() -> TestClient:
    """守卫包着一个什么路径都回 ok 的应用：只看守卫放不放行。"""
    routes = [Route("/{path:path}", _ok, methods=["GET", "HEAD", "POST", "PATCH", "DELETE"])]
    return TestClient(LocalGuard(Starlette(routes=routes), TOKEN), base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize(
    "host", ["evil.example", "localhost.evil.example", "127.0.0.1.nip.io", "[::1]:8000"]
)
def test_foreign_host_is_rejected(host: str) -> None:
    """DNS 重绑定：Host 不是本机就拒绝，静态页面、免令牌的接口也一样。"""
    client = _guarded()
    for path in ("/", "/chat/abc", "/api/health", "/api/session", "/api/threads"):
        resp = client.get(path, headers={"Host": host, "X-Session-Token": TOKEN})
        assert resp.status_code == 400, path


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8000", "localhost:5173", "localhost:8100", "LOCALHOST", "127.0.0.1"]
)
def test_local_hosts_on_any_port_are_accepted(host: str) -> None:
    resp = _guarded().get("/api/threads", headers={"Host": host, "X-Session-Token": TOKEN})
    assert resp.status_code == 200


def test_api_needs_the_token() -> None:
    client = _guarded()
    missing = client.get("/api/threads")
    assert (missing.status_code, missing.json()) == (401, UNAUTHORIZED)
    assert client.get("/api/threads", headers={"X-Session-Token": "x" * 43}).status_code == 401
    assert client.get("/api/threads", headers={"X-Session-Token": TOKEN}).status_code == 200
    assert client.post("/api/threads", headers={"X-Session-Token": TOKEN}).status_code == 200


def test_cookie_works_for_get_but_not_for_writes() -> None:
    """推送、图片、下载带不了请求头，GET / HEAD 认 Cookie；写操作只认请求头。"""
    client = _guarded()
    client.cookies.set("opa_session", TOKEN)
    assert client.get("/api/runs/r1/events").status_code == 200
    assert client.head("/api/threads/t/files/f/content").status_code == 200
    assert client.post("/api/threads").status_code == 401
    assert client.patch("/api/threads/t").status_code == 401
    assert client.delete("/api/threads/t").status_code == 401
    client.cookies.set("opa_session", "x" * 43)
    assert client.get("/api/runs/r1/events").status_code == 401


def test_health_and_session_need_no_token() -> None:
    client = _guarded()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/session").status_code == 200


def test_static_page_needs_no_token(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>首页</html>", encoding="utf-8")
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert "首页" in client.get("/").text
        assert "首页" in client.get("/chat/abc").text
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
        assert client.get("/api/threads").status_code == 401


def test_session_sets_an_httponly_strict_cookie(tmp_path: Path) -> None:
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    token = app.state.session_token
    with TestClient(app, base_url="http://localhost:5173") as client:
        resp = client.get("/api/session")
        assert resp.json() == {"token": token}
        cookie = resp.headers["set-cookie"]
        assert f"opa_session={token}" in cookie
        assert "httponly" in cookie.lower()
        assert "samesite=strict" in cookie.lower()
        assert "path=/" in cookie.lower()
        # 带上令牌后接口照常（这里是不存在的接口：JSON 404，不是 401）
        assert client.get("/api/not-exist", headers={"X-Session-Token": token}).status_code == 404
    # 每次启动换一个新令牌
    other = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    assert other.state.session_token != token
    assert len(token) >= 40
