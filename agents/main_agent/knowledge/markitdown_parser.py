"""文档解析的 markitdown 实现（微软开源的格式转换工具，设计文档 4.2）。"""

import asyncio
import io
import logging
import re
from pathlib import PurePath

from markitdown import MarkItDown, StreamInfo

from agents.main_agent.knowledge.parsing import (
    EMPTY_FILE,
    PAGE_MARK_PATTERN,
    DocumentParseError,
    ParsedDocument,
    page_mark,
    unsupported_reason,
)

logger = logging.getLogger(__name__)

_SLIDE = re.compile(r"<!-- Slide number: (\d+) -->")
NO_TEXT = "没有提取到文字：可能是扫描件、图片或文件已损坏（暂不支持识别图片里的文字）"


class MarkItDownParser:
    def __init__(self) -> None:
        self._converter = MarkItDown(enable_plugins=False)

    async def parse(self, data: bytes, filename: str) -> ParsedDocument:
        if (reason := unsupported_reason(filename)) is not None:
            raise DocumentParseError(reason)
        if not data.strip():
            raise DocumentParseError(EMPTY_FILE)
        suffix = PurePath(filename).suffix.lower()
        try:
            # 解析是同步的 CPU 活：放到线程里，不挡住推送与其他请求
            result = await asyncio.to_thread(
                self._converter.convert_stream,
                io.BytesIO(data),
                stream_info=StreamInfo(extension=suffix, filename=filename),
            )
        except Exception as exc:  # 解析边界：各种格式库的异常都转成一句给用户看的原因
            logger.warning("解析文件 %s 失败：%s", filename, exc)
            raise DocumentParseError("无法解析这个文件：请确认文件没有损坏、没有加密") from exc
        markdown = _mark_pages(result.text_content, suffix)
        if not PAGE_MARK_PATTERN.sub("", markdown).strip():
            raise DocumentParseError(NO_TEXT)
        return ParsedDocument(title=result.title or None, markdown=markdown)


def _mark_pages(text: str, suffix: str) -> str:
    """PDF 的页之间是分页符，PPT 每页前有幻灯片编号：都换成统一的页码标记。"""
    if suffix == ".pdf":
        return "\n\n".join(
            f"{page_mark(number)}\n\n{page}" for number, page in enumerate(text.split("\f"), 1)
        )
    if suffix == ".pptx":
        return _SLIDE.sub(lambda match: page_mark(int(match.group(1))), text)
    return text
