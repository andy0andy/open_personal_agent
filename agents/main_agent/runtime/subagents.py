"""子智能体定义（设计文档 7.4）：agents/subagents/ 下每个 Markdown 文件是一个子智能体。

新增子智能体只需加一个定义文件，无需写代码。

文件格式与技能文件相同——YAML 文件头 + 正文：
    ---
    name: data_analyst          # 主智能体派任务时用的名字
    description: 何时派它        # 主智能体据此决定是否派它
    model: gemini-3.5-flash     # 可选：指定模型版本；不写则跟随主对话所选的模型
    ---
    正文即它的系统提示词。
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SubagentDefinition:
    name: str
    description: str
    system_prompt: str
    model: str | None = None


def load_subagents(directory: Path) -> list[SubagentDefinition]:
    """读取目录下全部 *.md 定义（按文件名排序）；缺少文件头、名称或说明时报错并指出文件。"""
    return [_load(path) for path in sorted(directory.glob("*.md"))]


def _load(path: Path) -> SubagentDefinition:
    text = path.read_text(encoding="utf-8")
    _, head, body = text.split("---", 2) if text.startswith("---") else ("", "", "")
    meta = yaml.safe_load(head) if head else None
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        raise ValueError(f"子智能体定义不完整（需要 name 与 description 文件头）：{path.name}")
    return SubagentDefinition(
        name=str(meta["name"]),
        description=str(meta["description"]),
        system_prompt=body.strip(),
        model=str(meta["model"]) if meta.get("model") else None,
    )
