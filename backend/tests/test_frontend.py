from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


def _dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>首页</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def test_serves_built_frontend_with_spa_fallback(tmp_path: Path) -> None:
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert "首页" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log(1)"
        # 前端路由：未知页面路径返回首页
        assert "首页" in client.get("/threads/abc").text
        # 接口路径不兜底：仍然是 JSON 404（写操作也一样，不是 405）
        token = {"X-Session-Token": app.state.session_token}
        missing = client.get("/api/not-exist", headers=token)
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found"}
        assert client.post("/api/not-exist", json={}, headers=token).status_code == 404
        assert client.get("/api/health").json() == {"status": "ok"}


def test_skips_frontend_when_not_built(tmp_path: Path) -> None:
    app = create_app(lifespan_handler=None, frontend_dist=tmp_path / "missing")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").json() == {"status": "ok"}


def test_missing_asset_is_404_not_index(tmp_path: Path) -> None:
    """重新打包后旧首页引用的脚本已不存在：应返回 404，而不是把首页当脚本返回。"""
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/assets/app-old.js").status_code == 404
        assert client.get("/favicon.ico").status_code == 404


def test_index_page_is_not_cached(tmp_path: Path) -> None:
    """首页每次都向服务器确认，重新打包后浏览器能拿到新的首页。"""
    app = create_app(lifespan_handler=None, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
        assert client.get("/threads/abc").headers["cache-control"] == "no-cache"


def test_cannot_read_files_outside_the_build(tmp_path: Path) -> None:
    """路径穿越（../）拿不到打包目录以外的文件。"""
    (tmp_path / "dist").mkdir()
    dist = _dist(tmp_path / "dist")
    (tmp_path / "secret.txt").write_text("机密", encoding="utf-8")
    app = create_app(lifespan_handler=None, frontend_dist=dist)
    with TestClient(app, base_url="http://localhost") as client:
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
            response = client.get(path)
            assert "机密" not in response.text, path
