"""用户随消息上传的文件（设计文档 9.3）：告诉模型文件在哪里；能看图的模型同时收到图片本身。"""

import base64
from pathlib import Path

from agents.main_agent.runtime import Attachment, user_content
from agents.main_agent.runtime.attachments import MARKITDOWN_HINT, MAX_IMAGE_BYTES
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeSandbox

SHORT = "c_000000b1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workspace(tmp_path: Path, files: dict[str, bytes]) -> LocalWorkspace:
    for path, data in files.items():
        target = tmp_path / "workspace" / SHORT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return LocalWorkspace(tmp_path, FakeSandbox())


async def test_message_without_attachments_is_unchanged(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {})
    assert (
        await user_content("你好", [], short_id=SHORT, workspace=workspace, vision=True) == "你好"
    )


async def test_attachments_are_listed_with_their_full_paths(tmp_path: Path) -> None:
    files = [Attachment("uploads/销售.xlsx", XLSX, 10), Attachment("uploads/b.csv", "text/csv", 3)]
    content = await user_content(
        "分析一下", files, short_id=SHORT, workspace=_workspace(tmp_path, {}), vision=True
    )
    paths = f"/workspace/{SHORT}/uploads/销售.xlsx、/workspace/{SHORT}/uploads/b.csv"
    assert content == f"分析一下\n\n（用户上传了文件：{paths}）\n{MARKITDOWN_HINT}"


async def test_images_go_only_to_models_that_can_see(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"uploads/a.png": b"png-bytes"})
    image = Attachment("uploads/a.png", "image/png", 9)
    content = await user_content(
        "图里是什么", [image], short_id=SHORT, workspace=workspace, vision=True
    )
    encoded = base64.b64encode(b"png-bytes").decode()
    assert content == [
        {
            "type": "text",
            "text": f"图里是什么\n\n（用户上传了文件：/workspace/{SHORT}/uploads/a.png）",
        },
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ]
    # 不能看图的模型只知道文件在哪里（可以用代码处理）
    blind = await user_content(
        "图里是什么", [image], short_id=SHORT, workspace=workspace, vision=False
    )
    assert blind == f"图里是什么\n\n（用户上传了文件：/workspace/{SHORT}/uploads/a.png）"


async def test_images_too_large_or_gone_are_only_listed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"uploads/big.jpg": b"x"})
    big = Attachment("uploads/big.jpg", "image/jpeg", MAX_IMAGE_BYTES + 1)
    gone = Attachment("uploads/gone.png", "image/png", 10)
    content = await user_content(
        "看", [big, gone], short_id=SHORT, workspace=workspace, vision=True
    )
    assert isinstance(content, str)


async def test_images_beyond_the_per_message_budget_are_only_listed(tmp_path: Path) -> None:
    """一条消息里直接附上的图片合计有上限（各家对整个请求的大小有限制，超了整次运行会失败）：
    超出的只注明位置，并告诉模型可以用代码查看。"""
    names = [f"uploads/{i}.jpg" for i in range(4)]
    workspace = _workspace(tmp_path, dict.fromkeys(names, b"jpg"))
    photos = [Attachment(name, "image/jpeg", 4 * 1024 * 1024) for name in names]
    content = await user_content(
        "这些照片是什么", photos, short_id=SHORT, workspace=workspace, vision=True
    )
    assert isinstance(content, list)
    assert [block["type"] for block in content] == ["text", "image_url", "image_url", "image_url"]
    assert content[0]["text"].endswith(
        f"（以下图片没有直接附上，需要时可以用代码查看：/workspace/{SHORT}/uploads/3.jpg）"
    )


async def test_pdf_and_office_files_come_with_a_markitdown_hint(tmp_path: Path) -> None:
    """设计 2026-10-23 6.7：PDF、Word、PowerPoint、Excel 提示用 markitdown 提取文字（只提一次）。"""
    files = [
        Attachment("uploads/报告.PDF", "application/pdf", 10),
        Attachment("uploads/方案.docx", "application/octet-stream", 10),
    ]
    content = await user_content(
        "总结一下", files, short_id=SHORT, workspace=_workspace(tmp_path, {}), vision=False
    )
    assert isinstance(content, str)
    assert content.endswith("\n" + MARKITDOWN_HINT)
    assert content.count("markitdown") == 1
    assert "可以用 `markitdown <路径>` 提取文字" in MARKITDOWN_HINT


async def test_other_files_get_no_markitdown_hint(tmp_path: Path) -> None:
    files = [
        Attachment("uploads/b.csv", "text/csv", 3),
        Attachment("uploads/a.txt", "text/plain", 3),
    ]
    content = await user_content(
        "看看", files, short_id=SHORT, workspace=_workspace(tmp_path, {}), vision=False
    )
    assert "markitdown" not in str(content)
