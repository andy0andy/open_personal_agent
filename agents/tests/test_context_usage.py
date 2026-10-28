"""上下文占用分段（设计 2026-10-23 4.7）：系统提示词、常驻记忆、工具定义、相关记忆、对话历史。"""

import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.main_agent.knowledge import KnowledgeHit, KnowledgeItem
from agents.main_agent.models import estimate_input_tokens, estimate_text_tokens
from agents.main_agent.runtime.context_usage import context_usage
from agents.main_agent.runtime.knowledge import MATERIAL_NOTE, related_prefix

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件的内容" * 20,
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
]


def _hit(content: str) -> KnowledgeHit:
    moment = datetime(2026, 10, 1, tzinfo=UTC)
    item = KnowledgeItem(
        id=uuid.uuid4(),
        kind="memory",
        tags=[],
        pinned=False,
        content=content,
        source="manual",
        source_thread_id=None,
        source_run_id=None,
        document_id=None,
        seq=None,
        section_path=None,
        page=None,
        document_title=None,
        token_count=1,
        embedding_model="fake",
        created_at=moment,
        updated_at=moment,
    )
    return KnowledgeHit(item=item, score=1.0)


def _messages() -> list[Any]:
    profile = "<user_profile>\n- 用户希望回答简洁\n</user_profile>"
    system = f"你是个人智能体。{'规则。' * 50}\n\n{MATERIAL_NOTE}\n{profile}"
    return [
        SystemMessage(system),
        HumanMessage("上一轮的问题" * 30),
        AIMessage("上一轮的回答" * 30),
        HumanMessage(related_prefix([_hit("用户养了一只狗叫豆豆" * 5)], []) + "我家狗叫什么"),
    ]


def _usage(messages: list[Any], ratio: float = 1.0, limit: int | None = None) -> Any:
    whole = estimate_input_tokens(messages, TOOLS)
    return context_usage(messages, TOOLS, whole=whole, ratio=ratio, limit=limit)


def test_segments_add_up_to_total() -> None:
    usage = _usage(_messages(), limit=200_000)
    parts = (usage.system, usage.profile, usage.tools, usage.related, usage.history)
    assert all(part > 0 for part in parts)
    assert usage.total == sum(parts)
    assert usage.max_input_tokens == 200_000


def test_profile_and_related_are_split_out() -> None:
    """常驻记忆从系统提示词里分出来，相关记忆从本轮用户消息里分出来，不算进历史。"""
    with_memories = _usage(_messages())
    plain = [
        SystemMessage("你是个人智能体。" + "规则。" * 50),
        *_messages()[1:3],
        HumanMessage("我家狗叫什么"),
    ]
    without = _usage(plain)
    assert (without.profile, without.related) == (0, 0)
    assert with_memories.profile > 0
    assert with_memories.related > 0
    assert abs(with_memories.history - without.history) <= 5  # 历史不含记忆


def test_calibration_scales_segments() -> None:
    once = _usage(_messages())
    twice = _usage(_messages(), ratio=2.0)
    assert abs(twice.history - 2 * once.history) <= 1
    assert abs(twice.total - 2 * once.total) <= 5


def test_skills_after_the_profile_count_as_system_prompt() -> None:
    """常驻条目后面还接着技能清单（技能中间件排在后面）：只有常驻那段算常驻记忆（审查 I1）。"""
    profile = f"{MATERIAL_NOTE}\n<user_profile>\n- 用户希望回答简洁\n</user_profile>"
    skills = "\n\n## Skills System\n" + "- excel：读写表格文件，先读 SKILL.md\n" * 40
    messages = [SystemMessage(f"你是个人智能体。\n\n{profile}{skills}"), HumanMessage("你好")]
    usage = _usage(messages)
    assert usage.profile == estimate_text_tokens(profile)
    assert usage.system >= estimate_text_tokens(skills)
