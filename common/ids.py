"""ID 生成。"""

import secrets
import uuid


def new_id() -> uuid.UUID:
    """通用主键。"""
    return uuid.uuid4()


def short_id(prefix: str = "c_") -> str:
    """会话短 ID：前缀 + 8 位十六进制，便于模型在路径中准确引用。"""
    return f"{prefix}{secrets.token_hex(4)}"
