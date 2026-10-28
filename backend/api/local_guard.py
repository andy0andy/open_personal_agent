"""本机令牌与 Host 校验（设计 2026-10-23 5.11，D25 修订 D23 第 5 条）。

- Host：所有请求的主机名只认 127.0.0.1、localhost，端口不限（8000、开发用的 5173、端到端测试的
  8100）；挡住 DNS 重绑定。
- 令牌：后端每次启动生成一个随机令牌，只放在内存里。/api/ 下除了 /api/health（容器健康检查）与
  /api/session（发令牌）都要带它：请求头 X-Session-Token；推送、图片、下载这类带不了请求头的
  GET / HEAD 也认同值的 Cookie。写操作只认请求头：跨站网页拿不到令牌，伪造不了写请求。
- 防不住同一容器里的命令和 MCP 进程：它们能直接访问后端（写在 D25）。

纯 ASGI 中间件：不包装响应，推送（SSE）照常流式。
"""

import secrets
from http.cookies import CookieError, SimpleCookie

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "X-Session-Token"
COOKIE = "opa_session"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
UNAUTHORIZED = "会话令牌不对或已过期，请刷新页面"
FOREIGN_HOST = "只接受本机（127.0.0.1 或 localhost）的访问"
_OPEN = frozenset({"/api/health", "/api/session"})
_READS = frozenset({"GET", "HEAD"})


class LocalGuard:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if _hostname(headers.get("host", "")) not in LOCAL_HOSTS:
            await PlainTextResponse(FOREIGN_HOST, status_code=400)(scope, receive, send)
            return
        if _needs_token(scope["path"]) and not self._authorized(scope["method"], headers):
            await JSONResponse({"detail": UNAUTHORIZED}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _authorized(self, method: str, headers: Headers) -> bool:
        if self._matches(headers.get(TOKEN_HEADER)):
            return True
        return method in _READS and self._matches(_cookie(headers.get("cookie", ""), COOKIE))

    def _matches(self, value: str | None) -> bool:
        return value is not None and secrets.compare_digest(value.encode(), self.token.encode())


def _needs_token(path: str) -> bool:
    """接口要令牌（健康检查、发令牌除外）；页面与静态文件不要。"""
    return path.startswith("/api/") and path not in _OPEN


def _hostname(host: str) -> str:
    """Host 头里的主机名（去掉端口）；IPv6 地址原样返回（不在放行之列）。"""
    if host.startswith("["):
        return host
    return host.rpartition(":")[0].lower() if ":" in host else host.lower()


def _cookie(header: str, name: str) -> str | None:
    try:
        morsel = SimpleCookie(header).get(name)
    except CookieError:
        return None
    return morsel.value if morsel is not None else None
