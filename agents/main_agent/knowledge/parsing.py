"""文档解析接口（设计文档 4.2 的 doc_parser）：各种文件 → Markdown。

页码统一成 `<!-- page: N -->` 标记（PDF 的页、PPT 的幻灯片），切块时据此记下每段在第几页。
"""

import re
from pathlib import PurePath
from typing import Protocol

from pydantic import BaseModel

SUPPORTED_SUFFIXES = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".md", ".markdown", ".txt", ".html", ".htm"}
)
PAGE_MARK_PATTERN = re.compile(r"<!-- page: (\d+) -->")


def page_mark(number: int) -> str:
    return f"<!-- page: {number} -->"


def unsupported_reason(filename: str) -> str | None:
    """不支持的文件给出原因（直接给用户看）；支持的返回 None。"""
    suffix = PurePath(filename).suffix.lower()
    if suffix in SUPPORTED_SUFFIXES:
        return None
    return (
        f"暂不支持这种文件：{suffix or filename}；Word、PowerPoint、Excel 的旧格式"
        "请另存为 .docx、.pptx、.xlsx 再上传"
    )


class ParsedDocument(BaseModel):
    title: str | None = None
    markdown: str


EMPTY_FILE = "文件是空的：没有内容可以加入知识库"


class DocumentParseError(Exception):
    """解析失败：消息直接给用户看。"""


class DocumentParser(Protocol):
    async def parse(self, data: bytes, filename: str) -> ParsedDocument:
        """文件内容 → Markdown；格式不支持、解析不出文字时抛 DocumentParseError。"""
        ...
