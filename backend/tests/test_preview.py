"""表格预览（设计文档 9.3）：CSV / Excel 只显示前若干行，单元格一律转成文字。"""

import io
from datetime import datetime

import pytest
from openpyxl import Workbook

from backend.files import PreviewError, table_preview
from common.errors import InvalidRequestError


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_csv_with_bom_or_from_chinese_excel_is_readable() -> None:
    """Excel 导出的 CSV 常带 BOM，中文系统上还常是 GBK 编码。"""
    utf8 = table_preview("a.csv", "﻿地区,金额\n华东,120\n".encode())
    gbk = table_preview("b.csv", "地区,金额\n华东,120\n".encode("gbk"))
    for preview in (utf8, gbk):
        assert preview.rows == [["地区", "金额"], ["华东", "120"]]
        assert (preview.sheets, preview.sheet, preview.truncated) == ([], None, False)


def test_only_the_first_rows_are_shown() -> None:
    data = "\n".join(f"{i},{i * 2}" for i in range(150)).encode()
    preview = table_preview("a.csv", data, limit=100)
    assert len(preview.rows) == 100
    assert preview.rows[-1] == ["99", "198"]
    assert preview.truncated is True


def test_rows_of_different_lengths_are_padded() -> None:
    preview = table_preview("a.tsv", b"a\tb\tc\n1\n")
    assert preview.rows == [["a", "b", "c"], ["1", "", ""]]


def test_excel_sheets_can_be_switched() -> None:
    data = _xlsx(
        {
            "汇总": [["地区", "金额"], ["华东", 120.5], ["华南", None]],
            "明细": [["日期"], [datetime(2026, 10, 1, 9, 30)]],
        }
    )
    first = table_preview("报表.xlsx", data)
    assert (first.sheets, first.sheet) == (["汇总", "明细"], "汇总")
    assert first.rows == [["地区", "金额"], ["华东", "120.5"], ["华南", ""]]
    detail = table_preview("报表.xlsx", data, sheet="明细")
    assert (detail.sheet, detail.rows) == ("明细", [["日期"], ["2026-10-01 09:30:00"]])


def test_unknown_sheet_or_broken_file_is_explained() -> None:
    data = _xlsx({"汇总": [["a"]]})
    with pytest.raises(PreviewError, match="工作表不存在：明细"):
        table_preview("a.xlsx", data, sheet="明细")
    with pytest.raises(PreviewError, match="不是有效的 Excel 文件"):
        table_preview("a.xlsx", b"not a zip")
    with pytest.raises(PreviewError, match="不能按表格预览"):
        table_preview("a.png", b"png")


def test_unusual_csv_files_are_shown_or_explained() -> None:
    """只用回车换行的旧 Mac 文件、超长单元格照常显示；
    二进制内容冒充 CSV 给出说明，而不是服务器错误。"""
    assert table_preview("old.csv", b"a,b\r1,2\r").rows == [["a", "b"], ["1", "2"]]
    long_cell = "x" * 200_000
    assert table_preview("long.csv", f"note\n{long_cell}\n".encode()).rows == [
        ["note"],
        [long_cell],
    ]
    with pytest.raises(PreviewError, match="不是有效的 CSV 文件"):
        table_preview("fake.csv", b"\x00\x01PK\x03\x04" * 100)


def test_wide_table_marks_columns_truncated() -> None:
    """超过 50 列时标出来，界面写"只显示前 50 列"（积压小问题 D4）。"""
    wide = ",".join(f"c{i}" for i in range(60)).encode()
    preview = table_preview("a.csv", wide + b"\n" + wide)
    assert preview.columns_truncated is True
    assert all(len(row) == 50 for row in preview.rows)
    assert table_preview("b.csv", b"a,b\n1,2").columns_truncated is False


def test_formula_without_cached_value_shows_the_formula() -> None:
    """程序写的 xlsx 里公式没有缓存的结果（积压小问题 D8）：显示公式原文，不是空格子。"""
    data = _xlsx({"表": [["数量"], [1], [2], ["=SUM(A2:A3)"]]})
    preview = table_preview("a.xlsx", data)
    assert preview.rows[-1] == ["=SUM(A2:A3)"]


def test_utf16_csv_with_bom_is_readable() -> None:
    """带文件头标记的 UTF-16 CSV（Excel"Unicode 文本"一类）能看（积压小问题 D9）。"""
    for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
        bom = {"utf-16-le": "﻿", "utf-16-be": "﻿"}.get(encoding, "")
        data = (bom + "名称,数量\n苹果,3\n").encode(encoding)
        assert table_preview("a.csv", data).rows == [["名称", "数量"], ["苹果", "3"]]


def test_preview_error_is_an_app_error() -> None:
    """不能预览的原因走统一的错误映射（积压小问题 I2）：仍是 422。"""
    assert issubclass(PreviewError, InvalidRequestError)
