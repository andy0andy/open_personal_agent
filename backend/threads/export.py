"""导出 Markdown（设计 2026-10-23 6.2）：按界面历史生成，顶栏"更多"菜单里下载。

导出：用户原文和附件名、回答全文、工具调用一行一条（中文动词 + 摘要，不含输出）、审批决定、
生成的文件名、报错。不导出思考过程与工具输出；子智能体内部的事件不展开，只写派它去做什么。
被"重试这一轮"替换掉的那一轮不导出（界面上它收成一行，D26）。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, tzinfo
from pathlib import PurePosixPath
from typing import Any

from backend.runs.schemas import RunHistory
from backend.runtime import EventEnvelope
from backend.threads.schemas import Thread
from backend.threads.tool_labels import tool_label


@dataclass
class _Answer:
    text: str = ""


def to_markdown(thread: Thread, runs: Sequence[RunHistory], zone: tzinfo = UTC) -> str:
    """zone：每轮的时间按哪个时区写（浏览器所在时区，界面上看到的也是它）。"""
    replaced = {run.retry_of for run in runs if run.retry_of is not None}
    lines = [f"# {thread.title or '新会话'}", ""]
    turn = 0
    for run in runs:
        if run.id in replaced:
            continue
        turn += 1
        lines += [
            f"## 第 {turn} 轮 · {run.created_at.astimezone(zone):%Y-%m-%d %H:%M}",
            "",
            f"**你**：{run.message}",
        ]
        if run.attachments:
            names = "、".join(PurePosixPath(item.path).name for item in run.attachments)
            lines.append(f"\n附件：{names}")
        body = _body(run.events)
        if body:
            lines += ["", "**助手**：", "", *body]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _body(events: Sequence[EventEnvelope]) -> list[str]:
    """一轮里主智能体这边的内容，按发生的先后：回答段落、工具、审批、产物、报错。"""
    blocks: list[str | _Answer] = []
    answers: dict[str, _Answer] = {}
    pending: dict[str, list[dict[str, Any]]] = {}  # 审批请求：中断 ID → 操作
    for event in events:
        if len(event.agent_path) != 1:
            continue  # 子智能体内部的不展开
        data = event.data
        if event.type == "message.delta":
            answer = answers.get(data["message_id"])
            if answer is None:
                answer = answers[data["message_id"]] = _Answer()
                blocks.append(answer)
            # 合并过的片段（full_text）带着这段回答到此为止的全文
            answer.text = data["text"] if data.get("full_text") else answer.text + data["text"]
        elif event.type == "user.interjected":
            # 运行中插的话（设计 2026-10-23 6.3）：单独成段
            blocks.append(_Answer(f"**你（插话）**：{data['text']}"))
        elif event.type == "tool.started":
            blocks.append(_tool_line(data["name"], data.get("args") or {}))
        elif event.type == "subagent.started":
            blocks.append(f"- 派出子智能体：{data.get('description', '')}")
        elif event.type == "approval.required":
            for request in data.get("requests", []):
                pending[request["interrupt_id"]] = request.get("actions", [])
        elif event.type == "approval.resolved":
            for answer_data in data.get("answers", []):
                actions = pending.get(answer_data["interrupt_id"], [])
                for action, decision in zip(
                    actions, answer_data.get("decisions", []), strict=False
                ):
                    verb, detail = tool_label(action["name"], action.get("args") or {})
                    target = f"{verb}：{detail}" if detail else verb
                    blocks.append(f"- 审批：{_decision(decision)}（{target}）")
        elif event.type == "file.created":
            blocks.append(f"- 生成了文件：{data['path']}")
        elif event.type == "run.finished" and data.get("status") == "failed":
            blocks.append(f"- 出错：{data.get('error') or '未知原因'}")
        elif event.type == "run.finished" and data.get("status") == "cancelled":
            blocks.append("- 已停止")
    lines: list[str] = []
    for block in blocks:
        if isinstance(block, _Answer):
            if block.text.strip():
                lines += ["", block.text.strip(), ""]
        else:
            lines.append(block)
    return [line for i, line in enumerate(lines) if line or (i and lines[i - 1])]


def _tool_line(name: str, args: Mapping[str, Any]) -> str:
    verb, detail = tool_label(name, args)
    return f"- {verb}：{detail}" if detail else f"- {verb}"


def _decision(decision: Mapping[str, Any]) -> str:
    kind = decision.get("type")
    if kind == "approve":
        return "已同意"
    if kind == "edit":
        return "修改后执行"
    message = decision.get("message")
    return f"已回复：{message}" if message else "已拒绝"
