"""自建的上下文压缩（设计 2026-10-23 4.6）：同名替换 deepagents 默认的压缩中间件，
主智能体与子智能体都用。

在默认做法（用到上下文的 85% 时把较早的对话交给模型写摘要、原文另存成文件）之上：
- 摘要后面由代码逐字附上这段对话里用户说过的话（不经过模型），再附上文件路径、报错行、网址的
  锚点索引——摘要难免漏掉用户的原始要求和具体的名字；
- token 用真实的分词器算：默认的"字数 ÷ 4"把中文低估好几倍，压缩来得太晚；
- 交界处提前压缩（R49）：用到 70% 且正处在任务的交界处（新一轮开始、刚完成一项待办、
  子智能体刚交回结果）就先压缩，免得这一段做到一半撞上 85%——那时压缩最容易丢掉手头的细节。
"""

import re
from collections.abc import Iterator, Sequence
from typing import Any, cast

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    compute_summarization_defaults,
)
from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from agents.main_agent.models import estimate_input_tokens
from agents.main_agent.runtime.content import text_of
from agents.main_agent.runtime.interjection import is_interjection
from agents.main_agent.runtime.knowledge import user_words

USER_WORDS_HEADER = "用户说过的原话（逐字，按时间顺序）："
ANCHORS_HEADER = "锚点索引（对话里出现过的文件、报错、网址）："
# 附录前的标记：下次压缩从最后一个标记往后取回上次附上的内容（模型写摘要时可能照抄上面的标题、
# 再写一份改写过的，所以不能按标题找）
APPENDIX_MARK = "〔以下由系统逐字附上，不是摘要的一部分〕"

# 逐字附上的原话：贴了长文时只留开头（全文在压缩时另存的对话记录里），整段也有上限（先丢最早的）
_WORDS_ITEM_LIMIT = 1000
_WORDS_TOTAL_LIMIT = 6000
_ANCHOR_LIMITS = {"文件": 30, "报错": 20, "网址": 20}  # 每组最多几条，超了先丢最早的
_ANCHOR_LENGTH = 200

# 交界处提前压缩的阈值：占上下文上限的比例（硬阈值是 deepagents 默认的 85%）
EARLY_FRACTION = 0.70
_DEFAULT_FRACTION = 0.85
_TODO_TOOL = "write_todos"
_SUBAGENT_TOOL = "task"

_URL = re.compile(r"https?://[^\s)>\]\"'，。）】」]+")
_PATH = re.compile(r"(?:/[\w.\-]+)+\.\w{1,8}|\b[\w\-]+(?:/[\w.\-]+)+\.\w{1,8}")
# 报错行：以异常名开头（ValueError: …）、Traceback、failed、中文的错误 / 失败、非 0 退出码；
# 代码里提到 error 的行（except ValueError as error:）不算
_ERROR_LINE = re.compile(
    r"(?i)^\s*(?:[\w.]+\.)?\w*(?:error|exception)\b|traceback|\bfailed\b|错误|失败|exit code [1-9]"
)


def count_tokens(messages: Sequence[BaseMessage], tools: Sequence[Any] | None = None) -> int:
    """真实分词器算的 token 数（消息 + 工具定义）；工具可以是工具对象或 OpenAI 格式的字典。"""
    schemas = [convert_to_openai_tool(tool) for tool in tools] if tools else None
    return estimate_input_tokens(messages, schemas)


class CompactionMiddleware(SummarizationMiddleware):
    """deepagents 压缩中间件的同名替身：摘要后附上用户原话与锚点索引；交界处提前压缩。

    early：提前压缩的阈值（"fraction" 或 "tokens"）；不给就只按 trigger 压缩。
    """

    def __init__(self, *args: Any, early: ContextSize | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._early = early

    @property
    def name(self) -> str:
        """与默认的同名：deepagents 按名字把默认的那个原地换掉（不是并存两个）。"""
        return "SummarizationMiddleware"

    def _should_summarize(self, messages: list[AnyMessage], total_tokens: int) -> bool:
        if super()._should_summarize(messages, total_tokens):
            return True
        limit = self._early_limit()
        return limit is not None and total_tokens >= limit and boundary(messages) is not None

    def _early_limit(self) -> int | None:
        """提前压缩的 token 数；没设、或按比例算却还不知道模型的上下文上限时为 None。"""
        if self._early is None:
            return None
        kind, value = self._early
        if kind == "tokens":
            return int(value)
        max_input_tokens = self._get_profile_limits()
        return None if max_input_tokens is None else int(max_input_tokens * value)

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        summary = await super()._acreate_summary(messages_to_summarize)
        extra = appendix(messages_to_summarize)
        return f"{summary}\n\n{extra}" if extra else summary


def compaction_middleware(model: BaseChatModel, backend: BackendProtocol) -> CompactionMiddleware:
    """按模型的上下文上限取 deepagents 的默认阈值（同 create_summarization_middleware）。"""
    defaults = compute_summarization_defaults(model)
    return CompactionMiddleware(
        model,
        backend=backend,
        trigger=defaults["trigger"],
        early=early_trigger(defaults["trigger"]),
        keep=defaults["keep"],
        # deepagents 调用它时还会传 tools（它自己的类型标注只写了消息）
        token_counter=cast(Any, count_tokens),
        trim_tokens_to_summarize=None,
        truncate_args_settings=defaults["truncate_args_settings"],
    )


def early_trigger(trigger: ContextSize) -> ContextSize | None:
    """由硬阈值推出提前压缩的阈值：按比例触发时取 70%；没拿到上下文上限、按固定 token 数触发时
    同比例提前；按消息条数触发的不提前。"""
    kind, value = trigger
    if kind == "fraction":
        return ("fraction", min(EARLY_FRACTION, value))
    if kind == "tokens":
        return ("tokens", round(value * EARLY_FRACTION / _DEFAULT_FRACTION))
    return None


def boundary(messages: Sequence[AnyMessage]) -> str | None:
    """现在是不是任务的交界处：是的话返回哪一种，做到一半返回 None。

    - 新一轮开始：最后一条是用户新发的消息（插话接在工具结果后面，不算；以前的摘要也不算）；
    - 完成了一项待办：模型刚更新了待办清单，完成的项比上一次更新时多；
    - 子智能体交回结果：模型刚派出去的子智能体回来了。
    """
    if not messages:
        return None
    last = messages[-1]
    if isinstance(last, HumanMessage):
        ordinary = not is_interjection(last) and not _is_summary(last)
        return "新一轮开始" if ordinary else None
    calls = _answered_calls(messages)
    if any(call["name"] == _SUBAGENT_TOOL for call in calls):
        return "子智能体交回结果"
    done = [_completed(call) for call in calls if call["name"] == _TODO_TOOL]
    if done and max(done) > _completed_before(messages):
        return "完成了一项待办"
    return None


def _is_summary(message: AnyMessage) -> bool:
    return message.additional_kwargs.get("lc_source") == "summarization"


def _answered_calls(messages: Sequence[AnyMessage]) -> list[Any]:
    """最后一次模型调用发起、结果都已回来的工具调用；最后不是一批工具结果时为空。"""
    position = len(messages) - 1
    while position >= 0 and isinstance(messages[position], ToolMessage):
        position -= 1
    asked = messages[position] if position >= 0 else None
    if position == len(messages) - 1 or not isinstance(asked, AIMessage):
        return []
    return list(asked.tool_calls)


def _completed(call: Any) -> int:
    """一次待办清单更新里已完成的项数；参数不成样子（模型写坏了）时算 0。"""
    todos = call["args"].get("todos") if isinstance(call["args"], dict) else None
    if not isinstance(todos, list):
        return 0
    return sum(1 for todo in todos if isinstance(todo, dict) and todo.get("status") == "completed")


def _completed_before(messages: Sequence[AnyMessage]) -> int:
    """上一次更新待办清单时已完成的项数（最后一次模型调用之前）；没更新过为 0。"""
    asked = [message for message in messages if isinstance(message, AIMessage)][:-1]
    for message in reversed(asked):
        done = [_completed(call) for call in message.tool_calls if call["name"] == _TODO_TOOL]
        if done:
            return max(done)
    return 0


def appendix(messages: Sequence[AnyMessage]) -> str:
    """附在摘要后面的两段：用户原话与锚点索引（以前压缩时附上的接在前面，逐条合并）；都没有时为空。"""
    words: list[str] = []
    anchors: dict[str, list[str]] = {name: [] for name in _ANCHOR_LIMITS}
    for message in messages:
        if not isinstance(message, HumanMessage):
            continue
        text = text_of(message.content)
        if message.additional_kwargs.get("lc_source") == "summarization":
            earlier_words, earlier_anchors = _parse_appendix(text)
            words += earlier_words
            for name, items in earlier_anchors.items():
                anchors[name] += items
        elif said := user_words(text).strip():
            words.append(_item(said))
    for name, items in _anchors(messages).items():
        anchors[name] += items
    sections: list[str] = []
    if words := _keep_recent(words):
        sections.append(f"{USER_WORDS_HEADER}\n" + "\n".join(words))
    groups = [
        f"{name}：\n" + "\n".join(f"- {item}" for item in kept)
        for name, items in anchors.items()
        if (kept := _recent_unique(items, _ANCHOR_LIMITS[name]))
    ]
    if groups:
        sections.append(f"{ANCHORS_HEADER}\n" + "\n".join(groups))
    return f"{APPENDIX_MARK}\n" + "\n\n".join(sections) if sections else ""


def _item(words: str) -> str:
    """一条原话：多行时续行缩进两格（列表里不会出现空行，下次压缩能整段取回）。"""
    if len(words) > _WORDS_ITEM_LIMIT:
        words = f"{words[:_WORDS_ITEM_LIMIT]}……（后略，原文共 {len(words)} 字）"
    return "- " + words.replace("\n", "\n  ")


def _keep_recent(items: list[str]) -> list[str]:
    """原话整段超过上限时，从最早的一条起逐条丢（全文在另存的对话记录里）。"""
    total = sum(len(item) for item in items)
    start = 0
    while start < len(items) - 1 and total > _WORDS_TOTAL_LIMIT:
        total -= len(items[start])
        start += 1
    return items[start:]


def _recent_unique(items: list[str], limit: int) -> list[str]:
    """去重（同一条以最后一次出现为准），保留最近的 limit 条，按出现顺序排列。"""
    kept: list[str] = []
    for item in reversed(items):
        if item not in kept:
            kept.append(item)
    return list(reversed(kept[:limit]))


def _parse_appendix(summary: str) -> tuple[list[str], dict[str, list[str]]]:
    """取回上次压缩附上的原话（逐条）与锚点（按组）：只认最后一个系统附加标记之后的内容。"""
    words: list[str] = []
    anchors: dict[str, list[str]] = {name: [] for name in _ANCHOR_LIMITS}
    if APPENDIX_MARK not in summary:
        return words, anchors
    block = summary.rpartition(APPENDIX_MARK)[2].split("\n</summary>", 1)[0]
    section = ""
    group = ""
    for line in block.split("\n"):
        if line in (USER_WORDS_HEADER, ANCHORS_HEADER):
            section = line
        elif section == USER_WORDS_HEADER and line.startswith("- "):
            words.append(line)
        elif section == USER_WORDS_HEADER and line.startswith("  ") and words:
            words[-1] += "\n" + line
        elif section == ANCHORS_HEADER and line.endswith("：") and line[:-1] in anchors:
            group = line[:-1]
        elif section == ANCHORS_HEADER and group and line.startswith("- "):
            anchors[group].append(line[2:])
    return words, anchors


def _anchors(messages: Sequence[AnyMessage]) -> dict[str, list[str]]:
    """这段对话里的文件路径、报错行、网址（按出现顺序，每条最长 200 字）。"""
    found: dict[str, list[str]] = {name: [] for name in _ANCHOR_LIMITS}
    for text in _texts(messages):
        found["网址"] += [url[:_ANCHOR_LENGTH] for url in _URL.findall(text)]
        found["文件"] += [p[:_ANCHOR_LENGTH] for p in _PATH.findall(_URL.sub(" ", text))]
        found["报错"] += [
            line.strip()[:_ANCHOR_LENGTH] for line in text.splitlines() if _ERROR_LINE.search(line)
        ]
    return found


def _texts(messages: Sequence[AnyMessage]) -> Iterator[str]:
    """消息里的文字：用户的话、回答、工具调用的参数与工具结果（以前的摘要另行取回）。"""
    for message in messages:
        if message.additional_kwargs.get("lc_source") == "summarization":
            continue
        if isinstance(message, HumanMessage):
            yield user_words(text_of(message.content))
        elif isinstance(message, AIMessage):
            yield text_of(message.content)
            for call in message.tool_calls:
                yield from (str(value) for value in call["args"].values())
        elif isinstance(message, ToolMessage):
            yield text_of(message.content)
