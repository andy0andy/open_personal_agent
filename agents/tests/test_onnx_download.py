"""向量模型文件的下载与校验（D28）：按固定的哈希校验，不留半个文件；大文件分段并发下载。"""

import hashlib
from pathlib import Path

import httpx
import pytest

from agents.main_agent.models import OnnxModelFile, OnnxModelSpec, ensure_model, onnx_download
from common.errors import UpstreamError

BASE = "https://models.test"
CONTENT = {
    "onnx/model.onnx": b"model-entry",
    "onnx/model.onnx_data": bytes(range(35)),
    "tokenizer.json": b'{"version": "1.0"}',
}


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onnx_download, "_RETRY_DELAY", 0)  # 重试前的等待在测试里不用真等


def _spec(content: dict[str, bytes] = CONTENT) -> OnnxModelSpec:
    return OnnxModelSpec(
        name="tiny",
        repo="org/tiny-ONNX",
        revision="abc123",
        files={
            path.rsplit("/", 1)[-1]: OnnxModelFile(
                path, hashlib.sha256(data).hexdigest(), len(data)
            )
            for path, data in content.items()
        },
        model_file="model.onnx",
        dimensions=768,
        max_tokens=16,
        query_prefix="",
        document_prefix="",
        output="sentence_embedding",
    )


class _Server:
    """模拟支持分段（Range）的文件服务；记下每个请求。"""

    def __init__(self, content: dict[str, bytes] = CONTENT) -> None:
        self.content = dict(content)
        self.requests: list[httpx.Request] = []
        self.fail_once: set[str] = set()  # 这些 Range 第一次请求时返回 500

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        prefix = "/org/tiny-ONNX/resolve/abc123/"
        assert request.url.path.startswith(prefix), request.url
        data = self.content[request.url.path.removeprefix(prefix)]
        span = request.headers.get("range")
        if span is None:
            return httpx.Response(200, content=data)
        if span in self.fail_once:
            self.fail_once.discard(span)
            return httpx.Response(500)
        start, end = (int(part) for part in span.removeprefix("bytes=").split("-"))
        return httpx.Response(
            206,
            content=data[start : end + 1],
            headers={"Content-Range": f"bytes {start}-{end}/{len(data)}"},
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def _files(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


EXPECTED = {
    "model.onnx": CONTENT["onnx/model.onnx"],
    "model.onnx_data": CONTENT["onnx/model.onnx_data"],
    "tokenizer.json": CONTENT["tokenizer.json"],
}


async def test_downloads_and_verifies(tmp_path: Path) -> None:
    server = _Server()
    target = tmp_path / "models" / "tiny"  # 目录不存在时自己建
    done = await ensure_model(target, _spec(), base_url=BASE, transport=server.transport)
    assert sorted(done) == ["model.onnx", "model.onnx_data", "tokenizer.json"]
    assert _files(target) == EXPECTED  # 没有留下 .part
    assert {str(r.url) for r in server.requests} == {
        f"{BASE}/org/tiny-ONNX/resolve/abc123/{path}" for path in CONTENT
    }


async def test_does_nothing_when_files_are_valid(tmp_path: Path) -> None:
    for name, data in EXPECTED.items():
        (tmp_path / name).write_bytes(data)
    server = _Server()
    assert await ensure_model(tmp_path, _spec(), base_url=BASE, transport=server.transport) == []
    assert server.requests == []  # 已经下好的不联网


async def test_replaces_a_corrupt_file(tmp_path: Path) -> None:
    for name, data in EXPECTED.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "tokenizer.json").write_bytes(b'{"version": "9.9"}')  # 大小一样，内容被改过
    server = _Server()
    done = await ensure_model(tmp_path, _spec(), base_url=BASE, transport=server.transport)
    assert done == ["tokenizer.json"]
    assert _files(tmp_path) == EXPECTED


async def test_hash_mismatch_fails_cleanly(tmp_path: Path) -> None:
    """下载地址给的内容不对（镜像站被换了文件、传坏了）：报错，不留下任何像是下好了的文件。"""
    tampered = dict(CONTENT) | {"tokenizer.json": b'{"version": "6.6"}'}
    server = _Server(tampered)
    with pytest.raises(UpstreamError, match="校验没通过"):
        await ensure_model(tmp_path, _spec(), base_url=BASE, transport=server.transport)
    # 校验通过的两个留着，下次不用重下；没通过的不留下，也没有 .part
    assert sorted(_files(tmp_path)) == ["model.onnx", "model.onnx_data"]


async def test_large_file_uses_ranges(tmp_path: Path) -> None:
    server = _Server()
    await ensure_model(tmp_path, _spec(), base_url=BASE, transport=server.transport, part_bytes=10)
    spans = sorted(
        r.headers["range"] for r in server.requests if r.url.path.endswith("model.onnx_data")
    )
    assert spans == ["bytes=0-9", "bytes=10-19", "bytes=20-29", "bytes=30-34"]
    assert (tmp_path / "model.onnx_data").read_bytes() == CONTENT["onnx/model.onnx_data"]


async def test_retries_a_failed_part(tmp_path: Path) -> None:
    server = _Server()
    server.fail_once = {"bytes=10-19"}
    await ensure_model(tmp_path, _spec(), base_url=BASE, transport=server.transport, part_bytes=10)
    assert _files(tmp_path) == EXPECTED


async def test_retries_a_connection_blip(tmp_path: Path) -> None:
    """几十个分段请求里有一个没连上（网络抖了一下）：重试这一段，不要整个文件从头再来。"""
    server = _Server()
    blips = {"bytes=20-29"}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.headers.get("range") in blips:
            blips.clear()
            raise httpx.ConnectError("connection reset")
        return server(request)

    await ensure_model(
        tmp_path, _spec(), base_url=BASE, transport=httpx.MockTransport(flaky), part_bytes=10
    )
    assert _files(tmp_path) == EXPECTED


async def test_invalid_file_is_removed_before_downloading_again(tmp_path: Path) -> None:
    """大小对、内容坏了的文件（拷坏了、磁盘坏块）：重新下载之前先删掉，
    不然下载的这几分钟里它看起来还是"下好了"，会被加载去算向量。"""
    for name, data in EXPECTED.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "tokenizer.json").write_bytes(b'{"version": "9.9"}')

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(UpstreamError):
        await ensure_model(tmp_path, _spec(), base_url=BASE, transport=httpx.MockTransport(refuse))
    assert sorted(_files(tmp_path)) == ["model.onnx", "model.onnx_data"]  # 好的两个留着


async def test_network_error_becomes_upstream_error(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(UpstreamError, match="向量模型下载失败：连不上下载地址"):
        await ensure_model(tmp_path, _spec(), base_url=BASE, transport=httpx.MockTransport(refuse))
    assert _files(tmp_path) == {}


async def test_missing_file_on_server_is_explained(tmp_path: Path) -> None:
    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(UpstreamError, match="向量模型下载失败：下载地址返回 404"):
        await ensure_model(tmp_path, _spec(), base_url=BASE, transport=httpx.MockTransport(missing))
