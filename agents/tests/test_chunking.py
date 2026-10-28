"""按标题切块（设计文档 8.2：每块约 600 token，重叠约 80 token）。"""

from itertools import pairwise

from agents.main_agent.knowledge import chunk_markdown, page_mark
from agents.main_agent.models import estimate_text_tokens


def test_section_paths_follow_headings() -> None:
    markdown = (
        "# 第一章 考勤\n\n上班 9:30。\n\n## 1.1 请假\n\n病假要证明。\n\n"
        "# 第二章 报销\n\n30 天内提交。"
    )
    chunks = chunk_markdown(markdown, target_tokens=15, overlap_tokens=0)
    assert [c.section_path for c in chunks] == [
        "第一章 考勤",
        "第一章 考勤 › 1.1 请假",
        "第二章 报销",
    ]
    assert [c.seq for c in chunks] == [0, 1, 2]
    assert chunks[1].content.startswith("## 1.1 请假")


def test_pages_come_from_page_marks() -> None:
    markdown = f"{page_mark(1)}\n\n第一页的正文。\n\n{page_mark(2)}\n\n第二页的正文。"
    chunks = chunk_markdown(markdown, target_tokens=8, overlap_tokens=0)
    assert [(c.page, c.content) for c in chunks] == [(1, "第一页的正文。"), (2, "第二页的正文。")]
    assert chunks[0].section_path is None


def test_long_text_is_split_with_overlap() -> None:
    text = "".join(f"第{i}句话讲订单系统的一个细节。" for i in range(300))  # 无标题、无空行
    chunks = chunk_markdown(text, target_tokens=600, overlap_tokens=80)
    assert len(chunks) > 2
    assert all(estimate_text_tokens(c.content) <= 660 for c in chunks)
    for before, after in pairwise(chunks):
        assert after.content[:30] in before.content  # 相邻两块有重叠


def test_empty_markdown_gives_no_chunks() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown(f"{page_mark(1)}\n\n  \n") == []


def test_pages_never_share_a_chunk() -> None:
    """默认大小下，短短几页也各成一段：出处的页码要准（"打开原文"跳到对应页）。"""
    markdown = "\n\n".join(f"{page_mark(n)}\n\n第 {n} 页的正文。" for n in (1, 2, 3))
    chunks = chunk_markdown(markdown)
    assert [(c.page, c.content) for c in chunks] == [
        (1, "第 1 页的正文。"),
        (2, "第 2 页的正文。"),
        (3, "第 3 页的正文。"),
    ]


def test_sections_never_share_a_chunk() -> None:
    """默认大小下，每节各成一段（不带上一节的结尾）；开头没有标题的前言不标章节。"""
    markdown = (
        "员工手册\n\n# 第一章 考勤\n\n上班 9:30。\n\n## 1.1 请假\n\n病假要证明。\n\n"
        "# 第二章 报销\n\n30 天内提交。"
    )
    chunks = chunk_markdown(markdown)
    assert [c.section_path for c in chunks] == [
        None,
        "第一章 考勤",
        "第一章 考勤 › 1.1 请假",
        "第二章 报销",
    ]
    assert chunks[3].content == "# 第二章 报销\n\n30 天内提交。"


def test_code_blocks_are_not_headings() -> None:
    """代码块里以 # 开头的行（注释）不是标题，代码块也不从中间切开。"""
    markdown = (
        "# 安装\n\n```bash\n# 安装依赖\nmake install\n\n# 启动\nmake up\n```\n\n"
        "## 配置\n\n改 app.yaml。"
    )
    chunks = chunk_markdown(markdown)
    assert [c.section_path for c in chunks] == ["安装", "安装 › 配置"]
    assert "# 启动\nmake up\n```" in chunks[0].content


def test_long_table_repeats_its_header_in_every_chunk() -> None:
    """长表格切成几块时，每块开头都补上表头（积压小问题 C13：原来只有第 1 块有）。"""
    header = "| 编号 | 说明 |\n| --- | --- |"
    rows = "\n".join(f"| {i} | 第 {i} 个订单的处理说明写得比较长 |" for i in range(80))
    chunks = chunk_markdown(f"{header}\n{rows}", target_tokens=200, overlap_tokens=0)
    assert len(chunks) > 2
    assert all(chunk.content.startswith(f"{header}\n") for chunk in chunks)
    assert sum(chunk.content.count("订单的处理说明") for chunk in chunks) == 80
