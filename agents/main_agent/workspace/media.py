"""按文件名判断文件类型（产物登记、上传、预览都用它）。

不读系统的类型表：后端容器的精简镜像里没有，本机的又各不相同。只用 Python 自带的表，
再补上它缺的常用格式，结果在本机与容器里一致。
"""

import mimetypes

_OFFICE = "application/vnd.openxmlformats-officedocument"
_TYPES = mimetypes.MimeTypes()  # 不传文件名：只有 Python 自带的表
for _suffix, _type in {
    ".xlsx": f"{_OFFICE}.spreadsheetml.sheet",
    ".docx": f"{_OFFICE}.wordprocessingml.document",
    ".pptx": f"{_OFFICE}.presentationml.presentation",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".webp": "image/webp",
}.items():
    _TYPES.add_type(_type, _suffix)


def media_type(path: str) -> str:
    return _TYPES.guess_type(path.lower())[0] or "application/octet-stream"
