"""正式使用时由后端直接提供打包好的前端页面（设计文档 13.5）。"""

from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _is_page_path(path: str) -> bool:
    """前端页面路径才兜底：带扩展名的文件（如重新打包后已不存在的旧脚本）保持 404，
    否则浏览器会把首页当成脚本加载，页面白屏。"""
    return "." not in PurePosixPath(path).name


class _SinglePageApp(StaticFiles):
    """找不到的页面路径返回前端首页，交给前端路由。"""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.split("/", 1)[0] == "api":
            # 不存在的接口：任何请求方法都是 404（交给静态文件处理会对写操作返回 405）
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not _is_page_path(path):
                raise
            response = await super().get_response("index.html", scope)
        # 首页每次都向服务器确认：重新打包后脚本文件名会变，缓存的旧首页会引用已不存在的文件
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """前端打包结果存在时挂载到 /；开发时没有打包结果就跳过（前端用 make web 单独运行）。"""
    if not (dist / "index.html").is_file():
        return False
    app.mount("/", _SinglePageApp(directory=dist, html=True), name="frontend")
    return True
