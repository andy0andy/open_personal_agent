"""导出接口文档，供前端生成类型（make types）。

FastAPI 自动生成的接口文档里，推送事件只是信封（data 是任意字典）；这里把智能体的事件定义
（agents 的 EVENT_ADAPTER）以 AgentEvent 的名字并进去，前端才能按事件类型区分 data 的内容。
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from agents.main_agent.runtime import EVENT_ADAPTER

_ROOT = Path(__file__).resolve().parent.parent
GENERATED_OPENAPI = _ROOT / "frontend" / "src" / "api" / "generated" / "openapi.json"


def build_openapi(app: FastAPI) -> dict[str, Any]:
    # 复制一份再改：app.openapi() 的结果被缓存，也是 /openapi.json 返回的内容
    doc = copy.deepcopy(app.openapi())
    events = EVENT_ADAPTER.json_schema(
        ref_template="#/components/schemas/{model}", mode="serialization"
    )
    schemas = doc["components"]["schemas"]
    for name, schema in events.pop("$defs", {}).items():
        # 同一个模型两边都有时（如 UsageTotals）保留接口里的；同名却不同则是两个模型撞了名
        existing = schemas.setdefault(name, schema)
        if _without_defaults(existing) != _without_defaults(schema):
            raise ValueError(f"事件定义与接口里有同名但不同的类型：{name}")
    schemas["AgentEvent"] = events
    return doc


def _without_defaults(schema: Any) -> Any:
    """比较时忽略默认值：FastAPI 导出接口文档时会去掉 null 默认值，事件定义里则保留。"""
    if isinstance(schema, dict):
        return {key: _without_defaults(value) for key, value in schema.items() if key != "default"}
    if isinstance(schema, list):
        return [_without_defaults(item) for item in schema]
    return schema


def main() -> None:
    from backend.main import create_app

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else GENERATED_OPENAPI
    doc = build_openapi(create_app(lifespan_handler=None))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
