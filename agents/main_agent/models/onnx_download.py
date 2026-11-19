"""向量模型文件的下载与校验（D28）：模型不进仓库和镜像，缺了或坏了才从下载地址取。

每个文件按固定的 SHA-256 校验，所以下载地址可以换成镜像站；先写 `<文件名>.part`，校验通过
再改名，不会留下半个文件（OnnxEmbedder 只认名字和大小都对的文件）。大文件分段并发下载：
有的网络单个连接很慢，多开几个连接快得多。
"""

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path

import httpx

from agents.main_agent.models.onnx_embedder import OnnxModelFile, OnnxModelSpec
from common.errors import UpstreamError

logger = logging.getLogger(__name__)

_ATTEMPTS = 3  # 每一段最多试几次
_RETRY_DELAY = 1.0  # 秒：重试前等一下，每次加倍
_HASH_BLOCK = 1024 * 1024


async def ensure_model(
    model_dir: Path,
    spec: OnnxModelSpec,
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
    connections: int = 8,
    part_bytes: int = 4 * 1024 * 1024,
) -> list[str]:
    """文件齐全且哈希都对就什么都不做（不联网）；否则下载缺的、坏的。返回这次下载的本地文件名。"""
    wanted = [
        name
        for name, file in spec.files.items()
        if not await asyncio.to_thread(_valid, model_dir / name, file)
    ]
    if not wanted:
        return []
    await asyncio.to_thread(model_dir.mkdir, parents=True, exist_ok=True)
    for name in wanted:
        # 大小对、内容坏了的旧文件先删掉：不然重新下载的这几分钟里它看起来还是"下好了"，
        # OnnxEmbedder（只看名字和大小）会把坏模型加载进来
        await asyncio.to_thread((model_dir / name).unlink, missing_ok=True)
    limit = asyncio.Semaphore(connections)
    async with httpx.AsyncClient(
        transport=transport,  # 仅测试时注入
        timeout=httpx.Timeout(60, connect=10),
        follow_redirects=True,  # 模型仓库会转到存文件的服务器
    ) as client:
        for name in wanted:
            file = spec.files[name]
            url = f"{base_url.rstrip('/')}/{spec.repo}/resolve/{spec.revision}/{file.path}"
            started = time.monotonic()
            logger.info("开始下载向量模型文件 %s（%.0f MB）", name, file.size / 1024 / 1024)
            await _download(client, url, model_dir / name, file, limit, part_bytes)
            logger.info("向量模型文件 %s 下载完成，用了 %.0f 秒", name, time.monotonic() - started)
    return wanted


def _valid(path: Path, file: OnnxModelFile) -> bool:
    try:
        return path.stat().st_size == file.size and _sha256(path) == file.sha256
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


async def _download(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    file: OnnxModelFile,
    limit: asyncio.Semaphore,
    part_bytes: int,
) -> None:
    part = target.with_name(target.name + ".part")
    spans: list[tuple[int, int] | None] = (
        [None]  # 小文件一次取完
        if file.size <= part_bytes
        else [
            (start, min(start + part_bytes, file.size) - 1)
            for start in range(0, file.size, part_bytes)
        ]
    )
    descriptor = await asyncio.to_thread(os.open, part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        try:
            async with asyncio.TaskGroup() as group:
                for span in spans:
                    group.create_task(_fetch(client, url, span, file.size, descriptor, limit))
        except ExceptionGroup as errors:
            raise errors.exceptions[0] from None  # 一段失败其余的就取消了：给出那一段的原因
        finally:
            await asyncio.to_thread(os.close, descriptor)
        if not await asyncio.to_thread(_valid, part, file):
            raise UpstreamError(
                f"向量模型下载失败：{target.name} 校验没通过（下载地址给的内容不对）"
            )
        await asyncio.to_thread(os.replace, part, target)
    finally:
        await asyncio.to_thread(part.unlink, missing_ok=True)  # 成功时已改名，这里什么都不做


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    span: tuple[int, int] | None,
    size: int,
    descriptor: int,
    limit: asyncio.Semaphore,
) -> None:
    """取一段写到文件里对应的位置；网络抖动、服务器临时出错时重试几次。"""
    offset, length = (0, size) if span is None else (span[0], span[1] - span[0] + 1)
    headers = {} if span is None else {"Range": f"bytes={span[0]}-{span[1]}"}
    reason = ""
    for attempt in range(_ATTEMPTS):
        if attempt:
            await asyncio.sleep(_RETRY_DELAY * 2 ** (attempt - 1))
        try:
            async with limit:
                response = await client.get(url, headers=headers)
        except httpx.ConnectError:
            # 几十个分段请求里偶尔有一个没连上是常事：和别的临时故障一样重试这一段。
            # 真没联网时各段很快都试完，整体报错，由调用方过一会儿再来
            reason = "连不上下载地址"
            continue
        except httpx.TimeoutException:
            reason = "下载超时"
            continue
        except httpx.HTTPError as exc:
            logger.warning("向量模型下载出错：%s", exc)
            reason = "连接中断"
            continue
        if response.status_code >= 500:
            reason = f"下载地址返回 {response.status_code}"
            continue
        if response.status_code >= 400:
            raise UpstreamError(f"向量模型下载失败：下载地址返回 {response.status_code}")
        if len(response.content) != length:
            reason = "下载的内容不完整"
            continue
        await asyncio.to_thread(os.pwrite, descriptor, response.content, offset)
        return
    raise UpstreamError(f"向量模型下载失败：{reason}")
