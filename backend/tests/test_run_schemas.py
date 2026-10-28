"""发起运行的请求体（backend/runs/schemas.py）。"""

import uuid

from backend.runs import RunCreate


def test_repeated_attachments_are_kept_once() -> None:
    """同一个附件 ID 出现两次只算一次（积压小问题 D7），顺序不变。"""
    a, b = uuid.uuid4(), uuid.uuid4()
    assert RunCreate(message="看看", attachments=[a, a, b, a]).attachments == [a, b]
