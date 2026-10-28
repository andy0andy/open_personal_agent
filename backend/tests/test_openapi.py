import json
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from backend.main import create_app
from backend.openapi import GENERATED_OPENAPI, build_openapi


def _doc() -> dict[str, Any]:
    return build_openapi(create_app(lifespan_handler=None))


def test_agent_events_are_included() -> None:
    """接口文档里只有信封（data 是任意字典），事件本身的定义要另外并进去，前端才能按类型区分。"""
    schemas = _doc()["components"]["schemas"]
    mapping = schemas["AgentEvent"]["discriminator"]["mapping"]
    assert set(mapping) == {
        "run.started",
        "message.delta",
        "thinking.started",  # 设计 2026-10-23 4.8
        "thinking.delta",
        "thinking.finished",
        "user.interjected",  # 设计 2026-10-23 6.3
        "tool.started",
        "tool.running",  # 设计 2026-10-23 5.7
        "tool.finished",
        "subagent.started",
        "subagent.finished",
        "todos.updated",
        "usage",
        "context.usage",  # 设计 2026-10-23 4.7
        "file.created",
        "memory.saved",
        "approval.required",
        "approval.resolved",
        "run.finished",
    }
    assert mapping["usage"] == "#/components/schemas/UsageReported"
    assert "UsageReported" in schemas


def test_fields_always_present_in_responses_are_required() -> None:
    """有默认值的字段在响应里总会出现：标为必有，前端类型才不会多出"可能没有"。"""
    schemas = _doc()["components"]["schemas"]
    assert "ts" in schemas["EventEnvelope"]["required"]
    assert "agent_path" in schemas["RunStarted"]["required"]
    assert schemas["UsageTotals"]["required"] == ["calls", "input_tokens", "output_tokens"]
    assert "max_input_tokens" in schemas["ModelInfo"]["required"]
    assert schemas["RunStatus"]["enum"] == [
        "queued",
        "running",
        "interrupted",
        "completed",
        "failed",
        "cancelled",
    ]


def test_rejects_same_name_with_different_shape() -> None:
    """事件里的类型与接口里的同名却不同时报错，而不是悄悄用其中一个（前端类型会错）。"""

    class UsageTotals(BaseModel):
        something_else: str

    app = FastAPI()

    @app.get("/x")
    async def x() -> UsageTotals:
        return UsageTotals(something_else="")

    with pytest.raises(ValueError, match="UsageTotals"):
        build_openapi(app)


def test_does_not_change_served_openapi() -> None:
    app = create_app(lifespan_handler=None)
    build_openapi(app)
    assert "AgentEvent" not in app.openapi()["components"]["schemas"]


def test_generated_file_is_up_to_date() -> None:
    """前端类型由 generated/openapi.json 生成：接口或事件改了却没重新生成时失败。"""
    committed = json.loads(GENERATED_OPENAPI.read_text(encoding="utf-8"))
    assert committed == _doc(), "接口或事件定义变了：运行 make types 重新生成前端类型"
