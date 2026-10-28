"""按标题结构切块（设计文档 8.2：每块约 600 token，相邻块重叠约 80 token）。

每块记下所在的章节路径（如"第一章 考勤 › 1.1 请假"）与页码，检索结果据此给出出处。
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from pydantic import BaseModel

from agents.main_agent.knowledge.parsing import PAGE_MARK_PATTERN
from agents.main_agent.models import estimate_text_tokens

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[。！？.!?\n])")
_SECTION_SEPARATOR = " › "


class Chunk(BaseModel):
    seq: int  # 在文档里的顺序，从 0 开始
    content: str
    section_path: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class _Block:
    text: str
    tokens: int
    section_path: str | None
    page: int | None
    heading: bool
    page_start: bool  # 新的一页的第一段


def chunk_markdown(
    markdown: str, *, target_tokens: int = 600, overlap_tokens: int = 80
) -> list[Chunk]:
    """切块。新的一页、新的一节总是另起一块（出处的页码、章节才准）；
    一节太长时在节内按大小切开，相邻块重叠 overlap_tokens。"""
    groups: list[list[_Block]] = []  # 每块的新段落（不含从上一块带过来的重叠）
    overlaps: list[list[_Block]] = []
    current: list[_Block] = []
    carried: list[_Block] = []
    size = 0
    for block in _blocks(markdown, target_tokens, overlap_tokens):
        has_body = any(not item.heading for item in current)
        boundary = (block.heading or block.page_start) and has_body
        if current and (boundary or size + block.tokens > target_tokens):
            groups.append(current)
            overlaps.append(carried)
            # 换页、换节时不带上一块的结尾；同一节里按大小切开时带上
            carried = [] if boundary else _tail(carried + current, overlap_tokens)
            current = []
            size = sum(item.tokens for item in carried)
        current.append(block)
        size += block.tokens
    if current:
        groups.append(current)
        overlaps.append(carried)
    return [
        Chunk(
            seq=seq,
            content="\n\n".join(item.text for item in tail + blocks),
            section_path=_section_of(blocks),
            page=blocks[0].page,
        )
        for seq, (blocks, tail) in enumerate(zip(groups, overlaps, strict=True))
    ]


def _section_of(blocks: list[_Block]) -> str | None:
    """块的章节：第一个正文段落所在的节；只有标题时取最后一个标题。"""
    body = next((block for block in blocks if not block.heading), blocks[-1])
    return body.section_path


def _blocks(markdown: str, target_tokens: int, overlap_tokens: int) -> Iterator[_Block]:
    """把正文拆成段落块：标题单独成块；页码标记只更新页码；代码块里的内容原样保留
    （其中以 # 开头的注释不是标题）；过长的段落再切开。"""
    headings: list[tuple[int, str]] = []
    page: int | None = None
    page_start = False
    lines: list[str] = []
    fence: str | None = None  # 正在其中的代码块的开头记号（``` 或 ~~~）

    def flush() -> Iterator[_Block]:
        nonlocal lines, page_start
        text = "\n".join(lines).strip()
        lines = []
        if not text:
            return
        for index, piece in enumerate(
            _with_table_header(text, _split(text, target_tokens, overlap_tokens))
        ):
            yield _Block(
                piece,
                estimate_text_tokens(piece),
                _path(headings),
                page,
                heading=False,
                page_start=page_start and index == 0,
            )
        page_start = False

    for line in markdown.splitlines():
        stripped = line.strip()
        if fence is not None:
            lines.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            lines.append(line)
            continue
        if not stripped:
            yield from flush()
            continue
        mark = PAGE_MARK_PATTERN.fullmatch(stripped)
        if mark is not None:
            yield from flush()
            page = int(mark.group(1))
            page_start = True
            continue
        heading = _HEADING.match(stripped)
        if heading is not None:
            yield from flush()
            level = len(heading.group(1))
            headings = [(lv, title) for lv, title in headings if lv < level]
            headings.append((level, heading.group(2)))
            yield _Block(
                stripped,
                estimate_text_tokens(stripped),
                _path(headings),
                page,
                heading=True,
                page_start=page_start,
            )
            page_start = False
            continue
        lines.append(line)
    yield from flush()


def _with_table_header(text: str, pieces: list[str]) -> list[str]:
    """长表格切成几块时，后面几块开头补上表头与分隔行：单看一块也知道每列是什么
    （积压小问题 C13）。"""
    lines = text.split("\n", 2)
    if len(pieces) < 2 or len(lines) < 3 or not _is_table_rule(lines[1]):
        return pieces
    if not lines[0].lstrip().startswith("|"):
        return pieces
    header = f"{lines[0]}\n{lines[1]}"
    return [pieces[0], *(p if p.startswith(header) else f"{header}\n{p}" for p in pieces[1:])]


def _is_table_rule(line: str) -> bool:
    """Markdown 表格的分隔行（| --- | :---: |）。"""
    stripped = line.strip()
    return "---" in stripped and set(stripped) <= set("|-: ")


def _split(text: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    """过长的段落先在句末切开，单句仍然过长时按字数切；相邻片段重叠 overlap_tokens。"""
    if estimate_text_tokens(text) <= target_tokens:
        return [text]
    units: list[str] = []
    for sentence in (part for part in _SENTENCE_END.split(text) if part):
        tokens = estimate_text_tokens(sentence)
        if tokens <= target_tokens:
            units.append(sentence)
            continue
        width = max(1, len(sentence) * target_tokens // tokens)
        units.extend(sentence[i : i + width] for i in range(0, len(sentence), width))
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        tokens = estimate_text_tokens(unit)
        if current and size + tokens > target_tokens:
            pieces.append("".join(current))
            current = _tail_text(current, overlap_tokens)
            size = sum(estimate_text_tokens(item) for item in current)
        current.append(unit)
        size += tokens
    if current:
        pieces.append("".join(current))
    return [piece.strip() for piece in pieces if piece.strip()]


def _tail(blocks: list[_Block], overlap_tokens: int) -> list[_Block]:
    """前一块末尾合计不超过 overlap_tokens 的段落。"""
    tail: list[_Block] = []
    size = 0
    for block in reversed(blocks):
        if size + block.tokens > overlap_tokens:
            break
        tail.insert(0, block)
        size += block.tokens
    return tail


def _tail_text(units: list[str], overlap_tokens: int) -> list[str]:
    tail: list[str] = []
    size = 0
    for unit in reversed(units):
        tokens = estimate_text_tokens(unit)
        if size + tokens > overlap_tokens:
            break
        tail.insert(0, unit)
        size += tokens
    return tail


def _path(headings: list[tuple[int, str]]) -> str | None:
    return _SECTION_SEPARATOR.join(title for _, title in headings) or None
