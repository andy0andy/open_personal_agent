"""上传技能包（D21）：把页面传来的 base64 解出来；包本身的检查在智能体那一层
（agents 的 parse_skill_package），对话里装技能（D29）走的是同一套。
"""

import base64
import binascii

from agents.main_agent.runtime import MAX_SKILL_FILES, parse_skill_package, too_big
from common.errors import InvalidRequestError, TooLargeError

__all__ = ["MAX_SKILL_FILES", "decode_upload", "parse_skill_upload"]

parse_skill_upload = parse_skill_package


def decode_upload(files: list[tuple[str, str]], *, max_bytes: int) -> list[tuple[str, bytes]]:
    """(路径, base64) → (路径, 内容)；先按 base64 的长度粗查大小，免得解出一大块再拒绝。"""
    if sum(len(content) for _, content in files) > max_bytes * 4 // 3 + 4 * len(files):
        raise TooLargeError(too_big(max_bytes))
    try:
        return [(path, base64.b64decode(content, validate=True)) for path, content in files]
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequestError("上传的内容不完整，请重新选择文件") from exc
