"""文档解析契约测试（设计文档 8.2）：所有 DocumentParser 实现都必须通过同一套测试。

样例文件在 agents/tests/fixtures/documents/（由同目录的 make_fixtures.py 生成）。
"""

from pathlib import Path

import pytest

from agents.main_agent.knowledge import (
    DocumentParseError,
    DocumentParser,
    MarkItDownParser,
    page_mark,
)

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture(params=[MarkItDownParser])
def parser(request: pytest.FixtureRequest) -> DocumentParser:
    made: DocumentParser = request.param()
    return made


async def _markdown(parser: DocumentParser, name: str) -> str:
    parsed = await parser.parse((SAMPLES / name).read_bytes(), name)
    return parsed.markdown


async def test_pdf_pages_are_marked(parser: DocumentParser) -> None:
    markdown = await _markdown(parser, "design.pdf")
    assert [page_mark(n) in markdown for n in (1, 2, 3)] == [True, True, True]
    assert (
        markdown.index(page_mark(2))
        < markdown.index("ERR_ORDER_200")
        < markdown.index(page_mark(3))
    )


async def test_word_keeps_headings(parser: DocumentParser) -> None:
    markdown = await _markdown(parser, "handbook.docx")
    assert "# 第一章 考勤" in markdown
    assert "## 1.1 请假" in markdown


async def test_slides_become_pages(parser: DocumentParser) -> None:
    markdown = await _markdown(parser, "review.pptx")
    assert markdown.index(page_mark(1)) < markdown.index("季度复盘") < markdown.index(page_mark(2))
    assert "Slide number" not in markdown


async def test_sheets_and_web_pages(parser: DocumentParser) -> None:
    assert "## 销售" in await _markdown(parser, "sales.xlsx")
    web = await _markdown(parser, "faq.html")
    assert "# 常见问题" in web
    assert "alert" not in web  # 网页里的脚本不进知识库


async def test_scanned_pdf_has_no_text(parser: DocumentParser) -> None:
    with pytest.raises(DocumentParseError, match="没有提取到文字"):
        await _markdown(parser, "scan.pdf")


async def test_old_office_formats_are_refused(parser: DocumentParser) -> None:
    with pytest.raises(DocumentParseError, match="另存为"):
        await _markdown(parser, "old.doc")


@pytest.mark.parametrize("name", ["空.txt", "空.md", "空.csv", "空.pdf", "空.docx"])
async def test_empty_file_is_reported_as_empty(parser: DocumentParser, name: str) -> None:
    """空文件说"是空的"（积压小问题 C14：原来说可能是扫描件，或请确认没有损坏、加密）。"""
    with pytest.raises(DocumentParseError, match="文件是空的：没有内容可以加入知识库"):
        await parser.parse(b"", name)
