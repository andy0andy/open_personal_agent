"""用户随消息上传的文件（设计文档 9.3）。

模型总会知道文件在哪里（可以用代码处理）；能看图的模型同时收到图片本身。
"""

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from agents.main_agent.workspace import Workspace

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 各家模型单张图片的上限大致在这里（Claude 为 5MB）
# 一条消息直接附上的图片合计上限：各家对整个请求有大小限制（base64 后还要再大三分之一），
# 超了整次运行会失败。图片会随对话历史每一轮重发，也不宜太多
MAX_INLINE_BYTES = 15 * 1024 * 1024
# 设计 2026-10-23 6.7：这几种文件提示用 markitdown 提取文字（镜像里已装，命令行可直接用）
MARKITDOWN_SUFFIXES = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})
MARKITDOWN_HINT = "（其中的 PDF、Word、PowerPoint、Excel 可以用 `markitdown <路径>` 提取文字）"


@dataclass(frozen=True)
class Attachment:
    path: str  # 相对会话目录，如 uploads/a.png
    media_type: str
    size: int


async def user_content(
    message: str,
    attachments: Sequence[Attachment],
    *,
    short_id: str,
    workspace: Workspace,
    vision: bool,
) -> str | list[dict[str, Any]]:
    """这一轮交给模型的用户消息：没有附件时就是原文；有附件时附上文件位置，能看图时再附上图片。"""
    if not attachments:
        return message
    paths = "、".join(f"/workspace/{short_id}/{item.path}" for item in attachments)
    text = f"{message}\n\n（用户上传了文件：{paths}）"
    if any(PurePosixPath(item.path).suffix.lower() in MARKITDOWN_SUFFIXES for item in attachments):
        text += f"\n{MARKITDOWN_HINT}"
    images: list[dict[str, Any]] = []
    skipped: list[str] = []  # 太大或超出合计上限、没有直接附上的图片
    budget = MAX_INLINE_BYTES
    for item in attachments:
        if not vision or item.media_type not in IMAGE_TYPES:
            continue
        if item.size > MAX_IMAGE_BYTES or item.size > budget:
            skipped.append(f"/workspace/{short_id}/{item.path}")
            continue
        try:
            data = await workspace.read_file(short_id, item.path)
        except OSError:
            continue  # 文件已不在：模型照样知道路径，会自己发现
        budget -= item.size
        encoded = base64.b64encode(data).decode()
        images.append(
            {"type": "image_url", "image_url": {"url": f"data:{item.media_type};base64,{encoded}"}}
        )
    if skipped:
        text += f"\n（以下图片没有直接附上，需要时可以用代码查看：{'、'.join(skipped)}）"
    return [{"type": "text", "text": text}, *images] if images else text
