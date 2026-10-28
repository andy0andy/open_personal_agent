from agents.main_agent.workspace import media_type


def test_types_do_not_depend_on_the_host() -> None:
    """后端容器的精简镜像没有系统的文件类型表，Python 自带的表又缺 Office、Markdown 等常用格式：
    只用自带的表再补上这些，结果在本机与容器里一致。"""
    office = "application/vnd.openxmlformats-officedocument"
    assert media_type("outputs/report.xlsx") == f"{office}.spreadsheetml.sheet"
    assert media_type("uploads/方案.docx") == f"{office}.wordprocessingml.document"
    assert media_type("a.pptx") == f"{office}.presentationml.presentation"
    assert media_type("uploads/说明.MD") == "text/markdown"
    assert media_type("photo.webp") == "image/webp"
    assert media_type("data.csv") == "text/csv"
    assert media_type("chart.png") == "image/png"
    assert media_type("Makefile") == "application/octet-stream"
