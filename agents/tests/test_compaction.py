"""自建的上下文压缩（设计 2026-10-23 4.6）：摘要之外逐字附上用户原话与锚点索引，
token 用真实分词器算。压缩前不再提取记忆（用户 2026-10-24）：每一轮结束时已经提取过。"""

import uuid
from pathlib import Path
from typing import Any

from deepagents.backends import FilesystemBackend
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from agents.main_agent.context import AgentContext
from agents.main_agent.knowledge import KnowledgeHit
from agents.main_agent.runtime import MainAgent
from agents.main_agent.runtime.compaction import (
    ANCHORS_HEADER,
    USER_WORDS_HEADER,
    CompactionMiddleware,
    appendix,
    boundary,
    count_tokens,
    early_trigger,
)
from agents.main_agent.runtime.knowledge import related_prefix
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeKnowledgeStore, FakeSandbox, ScriptedChatModel
from config.settings import KnowledgeConfig


def _summary(text: str) -> HumanMessage:
    """以前压缩留下的摘要消息（deepagents 的写法：内容包在 <summary> 里）。"""
    return HumanMessage(
        content=f"Here is a summary:\n\n<summary>\n{text}\n</summary>",
        additional_kwargs={"lc_source": "summarization"},
    )


def test_appendix_lists_user_words_verbatim() -> None:
    hit = KnowledgeHit.model_validate(
        {
            "item": {
                "id": str(uuid.uuid4()),
                "kind": "memory",
                "tags": [],
                "pinned": False,
                "content": "用户在做后端开发",
                "source": "manual",
                "source_thread_id": None,
                "source_run_id": None,
                "document_id": None,
                "seq": None,
                "section_path": None,
                "page": None,
                "document_title": None,
                "token_count": 1,
                "embedding_model": "fake",
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-01T00:00:00Z",
            },
            "score": 1.0,
        }
    )
    text = appendix(
        [
            HumanMessage("把 a.py 改成异步\n顺便加注释"),
            AIMessage("好"),
            HumanMessage(related_prefix([hit], []) + "再加上重试"),
        ]
    )
    words = text.split(USER_WORDS_HEADER, 1)[1]
    assert "- 把 a.py 改成异步\n  顺便加注释" in words
    assert words.index("把 a.py") < words.index("再加上重试")
    assert "用户在做后端开发" not in text  # 系统附加的相关记忆不算用户的话


def test_appendix_carries_user_words_from_previous_summary() -> None:
    """压缩第二次：第一次附上的原话照样保留，排在前面。"""
    earlier = appendix([HumanMessage("第一句原话")])
    text = appendix([_summary(f"旧摘要\n\n{earlier}"), AIMessage("好"), HumanMessage("第二句")])
    words = text.split(USER_WORDS_HEADER, 1)[1]
    assert words.index("- 第一句原话") < words.index("- 第二句")
    assert text.count(USER_WORDS_HEADER) == 1


def test_long_user_words_are_clipped() -> None:
    """贴了长文时逐字只留开头（全文在压缩时另存的对话记录里），免得附录比原文还长。"""
    text = appendix([HumanMessage("长" * 5000)])
    assert "长" * 1000 in text
    assert "长" * 1001 not in text
    assert "（后略，原文共 5000 字）" in text


def test_anchor_index_finds_paths_errors_urls() -> None:
    messages: list[AnyMessage] = [
        HumanMessage("看看 https://example.com/doc 这篇"),
        AIMessage(
            "",
            tool_calls=[
                {"id": "c1", "name": "read_file", "args": {"file_path": "/workspace/c_1/a.py"}}
            ],
        ),
        ToolMessage("Traceback (most recent call last):\nValueError: bad", tool_call_id="c1"),
        AIMessage("写到了 /workspace/c_1/outputs/report.md，又改了 /workspace/c_1/a.py"),
    ]
    text = appendix(messages)
    anchors = text.split(ANCHORS_HEADER, 1)[1]
    assert "- /workspace/c_1/a.py" in anchors
    assert anchors.count("/workspace/c_1/a.py") == 1  # 去重
    assert "- /workspace/c_1/outputs/report.md" in anchors
    assert "- ValueError: bad" in anchors
    assert "- https://example.com/doc" in anchors
    assert "example.com/doc" not in anchors.split("网址：", 1)[0]  # 网址不当成文件


def test_token_count_uses_real_tokenizer() -> None:
    """默认的估算是字数 ÷ 4，中文被严重低估；改用真实分词器。"""
    messages = [HumanMessage("你好世界" * 100)]
    assert count_tokens(messages) > 1.5 * count_tokens_approximately(messages)


def test_middleware_takes_the_default_ones_name() -> None:
    """同名才能替换 deepagents 默认的压缩中间件（主智能体与子智能体都用它）。"""
    middleware = CompactionMiddleware(
        ScriptedChatModel(responses=[]), backend=FilesystemBackend(root_dir=Path("/tmp"))
    )
    assert middleware.name == "SummarizationMiddleware"


class _SummarizingModel(ScriptedChatModel):
    """生成摘要时回"摘要"，其余按剧本；记下每次调用是哪一种。"""

    kinds: list[str] = Field(default_factory=list)

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        if any("Context Extraction Assistant" in str(m.content) for m in messages):
            self.kinds.append("summary")
            return AIMessage("摘要")
        self.kinds.append("main")
        return super()._next(messages)


async def _compact(tmp_path: Path) -> tuple[_SummarizingModel, list[str]]:
    """一个只带压缩中间件的小智能体：超过 4 条消息就压缩、保留最后 2 条；跑三轮。"""
    model = _SummarizingModel(responses=[AIMessage("好")] * 3)
    middleware = CompactionMiddleware(
        model,
        backend=FilesystemBackend(root_dir=tmp_path),
        trigger=("messages", 4),
        keep=("messages", 2),
    )
    create: Any = create_agent  # 类型参数从 context_schema 推不出来
    graph = create(
        model, middleware=[middleware], context_schema=AgentContext, checkpointer=InMemorySaver()
    )
    context = AgentContext(str(uuid.uuid4()), "c_1", str(uuid.uuid4()))
    config: Any = {"configurable": {"thread_id": "t"}}
    for text in ("第一句：把 /workspace/c_1/a.py 改成异步", "第二句：再加上重试", "第三句"):
        await graph.ainvoke({"messages": [HumanMessage(text)]}, config, context=context)
    return model, [str(m.content) for m in model.received[-1]]


async def test_compaction_keeps_user_words_in_the_summary(tmp_path: Path) -> None:
    model, last = await _compact(tmp_path)
    assert "summary" in model.kinds
    summary = next(text for text in last if "摘要" in text)
    assert USER_WORDS_HEADER in summary
    assert "- 第一句：把 /workspace/c_1/a.py 改成异步" in summary
    assert "- /workspace/c_1/a.py" in summary.split(ANCHORS_HEADER, 1)[1]


# ---- 主智能体的接线 ----


def _agent(model: ScriptedChatModel, tmp_path: Path, **options: Any) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
        knowledge=FakeKnowledgeStore(),
        knowledge_options=KnowledgeConfig(**options),
    )


def test_graph_is_not_cached_without_context_limit(tmp_path: Path) -> None:
    """一时拿不到模型的上下文上限：不缓存组装好的智能体，下次运行重新组装（拿到后按它压缩）。"""
    model = ScriptedChatModel(responses=[])
    agent = _agent(model, tmp_path)
    assert agent._graph_for("fake", "ask") is not agent._graph_for("fake", "ask")
    gateway = FakeGateway(model, max_input_tokens=200_000)
    known = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
    )
    assert known._graph_for("fake", "ask") is known._graph_for("fake", "ask")


# ---- 审查 I2 / M10：多次压缩时以前附上的内容逐条保留 ----


def test_earlier_words_survive_the_cap_item_by_item() -> None:
    """以前的原话很多时，超出上限只从最早的逐条丢，不是一次全丢。"""
    earlier = appendix([HumanMessage(f"第{i:02d}句" + "话" * 290) for i in range(18)])
    assert "- 第00句" in earlier  # 上次附上时还没超限（约 5300 字）
    newer = [HumanMessage(f"新的第{i}句" + "字" * 400) for i in range(2)]
    text = appendix([_summary(f"旧摘要\n\n{earlier}"), *newer])
    words = text.split(USER_WORDS_HEADER, 1)[1]
    assert "- 第00句" not in words  # 合起来超了：从最早的一条起丢
    assert "- 第01句" in words  # 只丢够数的，不是一次全丢
    assert "- 第17句" in words
    assert "- 新的第0句" in words
    assert "- 新的第1句" in words


def test_model_copying_the_header_does_not_hide_the_verbatim_words() -> None:
    """模型写摘要时照抄了"原话"标题、下面写的是改写过的：认系统附加的那一份。"""
    earlier = appendix([HumanMessage("把 a.py 改成异步")])
    copied = f"{USER_WORDS_HEADER}\n- 用户要改异步（概括）"
    text = appendix([_summary(f"{copied}\n\n旧摘要\n\n{earlier}"), HumanMessage("再加重试")])
    assert "- 把 a.py 改成异步" in text
    assert "（概括）" not in text


def test_anchors_carry_over_from_previous_summary() -> None:
    earlier = appendix([AIMessage("改了 /workspace/c_1/a.py")])
    text = appendix([_summary(f"旧摘要\n\n{earlier}"), AIMessage("又看了 https://example.com/x")])
    anchors = text.split(ANCHORS_HEADER, 1)[1]
    assert "- /workspace/c_1/a.py" in anchors
    assert "- https://example.com/x" in anchors


def test_error_lines_skip_code_that_mentions_errors() -> None:
    text = appendix(
        [
            ToolMessage(
                "try:\n    run()\nexcept ValueError as error:\n    pass\n"
                "Traceback (most recent call last):\nValueError: bad",
                tool_call_id="c1",
            )
        ]
    )
    errors = text.split("报错：", 1)[1]
    assert "except ValueError as error" not in errors
    assert "- ValueError: bad" in errors
    assert "- Traceback (most recent call last):" in errors


def test_url_stops_at_fullwidth_paren() -> None:
    text = appendix([HumanMessage("文档（见 https://example.com/doc）讲了什么")])
    anchors = text.split(ANCHORS_HEADER, 1)[1]
    assert "- https://example.com/doc" in anchors
    assert "doc）" not in anchors


def _extraction_model(times: int) -> ScriptedChatModel:
    return ScriptedChatModel(responses=[AIMessage('{"changes": []}')] * times)


# ---- 交界处提前压缩（R49） ----


def _todos(*statuses: str, call_id: str = "t1") -> list[AnyMessage]:
    """模型更新了一次待办清单，工具结果已回来。"""
    todos = [{"content": f"第 {i} 步", "status": status} for i, status in enumerate(statuses)]
    call = {"name": "write_todos", "args": {"todos": todos}, "id": call_id}
    return [AIMessage("", tool_calls=[call]), ToolMessage("已更新", tool_call_id=call_id)]


def test_new_turn_is_a_boundary() -> None:
    messages: list[AnyMessage] = [HumanMessage("第一句"), AIMessage("好"), HumanMessage("第二句")]
    assert boundary(messages) == "新一轮开始"


def test_interjection_and_old_summary_are_not_a_new_turn() -> None:
    """插话接在工具结果后面，不是新的一轮；以前的摘要也不是用户新说的话。"""
    interjected = HumanMessage("等一下", additional_kwargs={"interjection": True})
    assert boundary([HumanMessage("开始"), AIMessage("好"), interjected]) is None
    assert boundary([_summary("摘要")]) is None


def test_a_newly_completed_todo_is_a_boundary() -> None:
    first = _todos("in_progress", "pending")
    assert boundary([HumanMessage("开始"), *first]) is None  # 只是列了清单，没有完成的
    done = _todos("completed", "in_progress", call_id="t2")
    assert boundary([HumanMessage("开始"), *first, *done]) == "完成了一项待办"
    # 完成的没有比上次多（只是改了别的项的状态）：不算
    same = _todos("completed", "pending", call_id="t3")
    assert boundary([HumanMessage("开始"), *first, *done, *same]) is None


def test_subagent_result_is_a_boundary() -> None:
    call = {"name": "task", "args": {"description": "调研"}, "id": "s1"}
    messages: list[AnyMessage] = [
        HumanMessage("开始"),
        AIMessage("", tool_calls=[call]),
        ToolMessage("调研结果", tool_call_id="s1"),
    ]
    assert boundary(messages) == "子智能体交回结果"


def test_middle_of_a_task_is_not_a_boundary() -> None:
    call = {"name": "read_file", "args": {"file_path": "/workspace/c_1/a.py"}, "id": "r1"}
    messages: list[AnyMessage] = [
        HumanMessage("开始"),
        AIMessage("", tool_calls=[call]),
        ToolMessage("文件内容", tool_call_id="r1"),
    ]
    assert boundary(messages) is None
    assert boundary([]) is None
    # 清单的参数不成样子（模型写坏了）：当作没有完成的，不报错
    broken = {"name": "write_todos", "args": {"todos": "不是列表"}, "id": "b1"}
    assert (
        boundary([AIMessage("", tool_calls=[broken]), ToolMessage("", tool_call_id="b1")]) is None
    )


def _early_middleware(tmp_path: Path) -> CompactionMiddleware:
    """硬阈值 1000 token、提前阈值 700 token。"""
    return CompactionMiddleware(
        ScriptedChatModel(responses=[]),
        backend=FilesystemBackend(root_dir=tmp_path),
        trigger=("tokens", 1000),
        keep=("messages", 2),
        early=("tokens", 700),
    )


def test_compacts_early_only_at_a_boundary(tmp_path: Path) -> None:
    """过了提前阈值：在交界处才压缩，做到一半不压；过了硬阈值照旧随时压缩。"""
    middleware = _early_middleware(tmp_path)
    new_turn: list[AnyMessage] = [HumanMessage("第一句"), AIMessage("好"), HumanMessage("第二句")]
    midway: list[AnyMessage] = [HumanMessage("开始"), AIMessage("我先看看")]
    assert not middleware._should_summarize(new_turn, 699)
    assert middleware._should_summarize(new_turn, 700)
    assert not middleware._should_summarize(midway, 999)
    assert middleware._should_summarize(midway, 1000)


def test_no_early_compaction_without_an_early_threshold(tmp_path: Path) -> None:
    middleware = CompactionMiddleware(
        ScriptedChatModel(responses=[]),
        backend=FilesystemBackend(root_dir=tmp_path),
        trigger=("tokens", 1000),
    )
    new_turn: list[AnyMessage] = [HumanMessage("第一句"), AIMessage("好"), HumanMessage("第二句")]
    assert not middleware._should_summarize(new_turn, 999)


def test_early_threshold_follows_the_default_trigger() -> None:
    """按上下文上限的比例触发时提前到 70%；没拿到上限、按固定 token 数触发时同比例提前。"""
    assert early_trigger(("fraction", 0.85)) == ("fraction", 0.70)
    assert early_trigger(("tokens", 170000)) == ("tokens", 140000)
    assert early_trigger(("messages", 20)) is None


async def test_new_turn_past_the_early_threshold_compacts_before_answering(tmp_path: Path) -> None:
    """接进智能体里走一遍：硬阈值远没到，但已过提前阈值——第二轮一开始就先压缩再回答。"""
    model = _SummarizingModel(responses=[AIMessage("好")] * 2)
    middleware = CompactionMiddleware(
        model,
        backend=FilesystemBackend(root_dir=tmp_path),
        trigger=("tokens", 10**9),
        keep=("messages", 1),
        early=("tokens", 1),
    )
    create: Any = create_agent
    graph = create(
        model, middleware=[middleware], context_schema=AgentContext, checkpointer=InMemorySaver()
    )
    context = AgentContext(str(uuid.uuid4()), "c_1", str(uuid.uuid4()))
    config: Any = {"configurable": {"thread_id": "t"}}
    await graph.ainvoke({"messages": [HumanMessage("第一句")]}, config, context=context)
    assert model.kinds == ["main"]  # 第一轮只有一条消息，没有可压的
    await graph.ainvoke({"messages": [HumanMessage("第二句")]}, config, context=context)
    assert model.kinds == ["main", "summary", "main"]
    last = [str(m.content) for m in model.received[-1]]
    assert any("- 第一句" in text for text in last)  # 压掉的那句原话附在摘要后面
    assert last[-1] == "第二句"
