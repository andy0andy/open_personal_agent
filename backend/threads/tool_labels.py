"""工具的中文动词与摘要（照前端 components/chat/tools.ts；导出 Markdown 用，设计 6.2）。"""

import re
from collections.abc import Mapping
from typing import Any

# 工具名 → （动词，作摘要的参数）
_BUILTIN: dict[str, tuple[str, str | None]] = {
    "execute": ("执行命令", "command"),
    "read_file": ("读取文件", "file_path"),
    "write_file": ("写入文件", "file_path"),
    "edit_file": ("修改文件", "file_path"),
    "delete": ("删除文件", "file_path"),
    "ls": ("列出目录", "path"),
    "glob": ("查找文件", "pattern"),
    "grep": ("搜索文件内容", "pattern"),
    "write_todos": ("更新待办", None),
    "task": ("派出子智能体", "description"),
    "search_knowledge": ("检索知识库", "query"),
    "read_document": ("读取文档", None),
    "remember": ("记住", "content"),
    "update_memory": ("更正记忆", "new"),
    "forget_memory": ("忘掉记忆", "fragment"),
    "search_conversations": ("查以前的对话", "query"),
}
# MCP 服务的工具名是"服务名_工具名"（服务名只含小写字母、数字、连字符）
_EXTERNAL = re.compile(r"^([a-z0-9-]+)_(.+)$")


def tool_label(name: str, args: Mapping[str, Any]) -> tuple[str, str]:
    """（动词，摘要）；MCP 工具是（"外部工具"，"服务 · 工具"），不认识的是（原名，""）。"""
    if name in _BUILTIN:
        verb, arg = _BUILTIN[name]
        value = args.get(arg) if arg else None
        return verb, value if isinstance(value, str) else ""
    if external := _EXTERNAL.match(name):
        return "外部工具", f"{external[1]} · {external[2]}"
    return name, ""
