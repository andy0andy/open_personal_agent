import asyncio
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from agents.main_agent.integrations import McpClient, McpServerStatus
from agents.main_agent.models import CallContext, current_call
from agents.main_agent.runtime import (
    BUILTIN_TOOLS,
    ApprovalAnswer,
    ApprovalRequired,
    Attachment,
    FileCreated,
    MainAgent,
    MessageDelta,
    RunFinished,
    RunStarted,
    SubagentFinished,
    SubagentStarted,
    ThinkingDelta,
    TodosUpdated,
    ToolDecision,
    ToolFinished,
    ToolRunning,
    ToolStarted,
    UsageReported,
)
from agents.main_agent.runtime.interruption import (
    INTERRUPTED_NOTE,
    QUOTA,
    QUOTA_EXHAUSTED,
    STALLED,
    interrupted_note,
)
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import (
    BreakingChatModel,
    FailingAtChatModel,
    FailingChatModel,
    FakeConversationIndex,
    FakeGateway,
    FakeKnowledgeStore,
    FakeMcpClient,
    FakeSandbox,
    HangingChatModel,
    ScriptedChatModel,
    StallingChatModel,
    call,
    mcp_tool,
)
from config import ApprovalRulesConfig

SHORT, OTHER_SHORT = "c_000000a1", "c_000000a2"


def _agent(
    model: ScriptedChatModel,
    *,
    workspace: LocalWorkspace | None = None,
    skills_dir: Path | None = None,
    subagents_dir: Path | None = None,
    mcp: McpClient | None = None,
    approval: ApprovalRulesConfig | None = None,
    knowledge: FakeKnowledgeStore | None = None,
    conversations: FakeConversationIndex | None = None,
) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=workspace or LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills_dir=skills_dir,
        subagents_dir=subagents_dir,
        mcp=mcp,
        approval=approval,
        knowledge=knowledge,
        conversations=conversations,
    )


async def test_run_streams_tool_and_answer_events() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "ls", "args": {"path": "/"}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="你好"),
        ]
    )
    agent = _agent(model)
    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

    assert isinstance(events[0], RunStarted)
    flow = [type(e) for e in events if type(e).__name__ != "ContextUsage"]  # 每次调用前的占用
    assert flow[1:4] == [ToolStarted, ToolRunning, ToolFinished]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "你好"
    assert events[-1] == RunFinished(status="completed")


async def test_run_turns_model_failure_into_failed_event() -> None:
    events = [
        e
        async for e in _agent(FailingChatModel(responses=[])).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "failed"
    assert "模型调用失败" in (events[-1].error or "")


class _LeakyFailure(ScriptedChatModel):
    """报错文字里带着密钥（如网关把请求头原样写进了错误）。"""

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        raise RuntimeError("网关拒绝：Authorization: Bearer sk-abcdefgh12345678")


async def test_failure_text_is_redacted() -> None:
    """运行失败时写进数据库、显示在界面上的报错文字打码（设计 2026-10-23 5.12）。"""
    events = await _run_once(_agent(_LeakyFailure(responses=[])))
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "failed"
    error = events[-1].error or ""
    assert "sk-abcdefgh12345678" not in error
    assert "Bearer ***" in error


async def test_second_run_on_same_thread_keeps_history() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="一"), AIMessage(content="二")])
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="fake"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="b", model="fake"
        )
    ]

    graph = agent._graph_for("fake", "ask")
    state = await graph.aget_state({"configurable": {"thread_id": "t1"}})
    assert [m.content for m in state.values["messages"] if m.type == "human"] == ["a", "b"]


USAGE = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}


async def test_run_streams_thinking_todos_subagent_and_usage() -> None:
    todos = [{"content": "派人去查", "status": "in_progress"}]
    task = {"description": "查一下", "subagent_type": "general-purpose"}
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "先拆"},
                tool_calls=[
                    {
                        "name": "write_todos",
                        "args": {"todos": todos},
                        "id": "t1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata=USAGE,
                response_metadata={"model_name": "litellm_proxy/fake", "response_cost": 0.01},
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "task", "args": task, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="子结果", usage_metadata=USAGE),  # 子智能体（共用同一个假模型）
            AIMessage(content="完成"),
        ]
    )
    events = [
        e
        async for e in _agent(model).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    assert "".join(e.text for e in thinking) == "先拆"
    assert any(isinstance(e, TodosUpdated) and e.todos[0].content == "派人去查" for e in events)
    started = next(e for e in events if isinstance(e, SubagentStarted))
    assert (started.call_id, started.name) == ("c1", "general-purpose")
    inner = [e for e in events if isinstance(e, MessageDelta) and e.agent_path == ["main", "c1"]]
    assert "".join(e.text for e in inner) == "子结果"
    finished = next(e for e in events if isinstance(e, SubagentFinished))
    assert (finished.call_id, finished.output) == ("c1", "子结果")
    usage = [e for e in events if isinstance(e, UsageReported)]
    assert [(u.caller, u.agent_path) for u in usage] == [
        ("main", ["main"]),
        ("general-purpose", ["main", "c1"]),
    ]
    assert events[-1] == RunFinished(status="completed")


async def test_parallel_subagents_keep_their_own_steps() -> None:
    def task(call_id: str, description: str) -> dict[str, object]:
        args = {"description": description, "subagent_type": "general-purpose"}
        return {"name": "task", "args": args, "id": call_id, "type": "tool_call"}

    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task("cA", "任务甲"), task("cB", "任务乙")]),
            AIMessage(content="甲结果"),  # 两个子智能体并行，谁先取到哪条回复不确定
            AIMessage(content="乙结果"),
            AIMessage(content="完成"),
        ]
    )
    events = [
        e
        async for e in _agent(model).run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="hi", model="fake"
        )
    ]

    for call_id in ("cA", "cB"):
        inner = [
            e for e in events if isinstance(e, MessageDelta) and e.agent_path == ["main", call_id]
        ]
        finished = next(
            e for e in events if isinstance(e, SubagentFinished) and e.call_id == call_id
        )
        # 每个子智能体卡片里的文字，正是它自己交回的结果（没有和另一个混在一起）
        assert "".join(e.text for e in inner) == finished.output
    assert {e.output for e in events if isinstance(e, SubagentFinished)} == {"甲结果", "乙结果"}


async def test_switching_model_hides_previous_model_thinking_from_new_model() -> None:
    first = AIMessage(
        content="一",
        additional_kwargs={"reasoning_content": "旧模型的思考"},
        usage_metadata=USAGE,
        response_metadata={"model_name": "litellm_proxy/model-a"},
    )
    model = ScriptedChatModel(responses=[first, AIMessage(content="二")])
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="model-a"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="b", model="model-b"
        )
    ]

    previous = [m for m in model.received[-1] if isinstance(m, AIMessage)]
    assert [m.content for m in previous] == ["一"]
    assert "reasoning_content" not in previous[0].additional_kwargs
    # 对话存档保持原样
    state = await agent._graph_for("model-a", "ask").aget_state(
        {"configurable": {"thread_id": "t1"}}
    )
    stored = next(m for m in state.values["messages"] if m.type == "ai")
    assert stored.additional_kwargs["reasoning_content"] == "旧模型的思考"


async def test_thread_continues_normally_after_cancel() -> None:
    model = HangingChatModel(responses=[AIMessage(content="第二次的回答")])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="一", model="fake"
        ):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task  # 取消照常向外传播，由调用方收尾

    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="二", model="fake"
        )
    ]
    assert "".join(e.text for e in events if isinstance(e, MessageDelta)) == "第二次的回答"
    assert events[-1] == RunFinished(status="completed")


async def test_interrupted_answer_is_kept_for_the_next_turn() -> None:
    model = HangingChatModel(responses=[AIMessage(content="好的")])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        ):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="一句话", model="fake"
        )
    ]

    # 被停止的请求后面是已输出的部分 + 中断说明：由下一句话决定是否接着做，不会被当成尚未回答而重做
    sent = [(m.type, m.content) for m in model.received[-1] if m.type in ("human", "ai")]
    assert sent == [
        ("human", "写长文"),
        ("ai", f"想\n\n{INTERRUPTED_NOTE}"),
        ("human", "一句话"),
    ]


async def test_stalled_model_fails_the_run_but_keeps_the_partial_answer() -> None:
    """模型中途不再发数据：运行失败并给出中文原因（不带异常类名），已输出的部分与估算用量都留下，
    下一句话说"继续"就能接着做。"""
    model = StallingChatModel(responses=[AIMessage(content="好的")])
    agent = _agent(model)

    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        )
    ]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status == "failed"
    assert finished.error is not None
    assert finished.error.startswith("模型超过 120 秒没有发来新内容")
    assert finished.interrupted_usage is not None
    assert finished.interrupted_usage.output_tokens > 0  # 已输出的"想"

    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="继续", model="fake"
        )
    ]
    sent = [(m.type, m.content) for m in model.received[-1] if m.type in ("human", "ai")]
    assert sent == [
        ("human", "写长文"),
        ("ai", f"想\n\n{interrupted_note(STALLED)}"),
        ("human", "继续"),
    ]
    assert "用户停止" not in sent[1][1]


async def test_cancel_leaves_an_estimate_of_the_interrupted_call() -> None:
    model = HangingChatModel(responses=[])
    agent = _agent(model)
    first_delta = asyncio.Event()

    async def consume() -> None:
        async for event in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        ):
            if isinstance(event, MessageDelta):
                first_delta.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_delta.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    estimate = agent.take_interrupted_usage("r1")
    assert estimate is not None
    assert estimate.input_tokens > 0
    assert estimate.output_tokens > 0  # 已输出的"想"
    assert agent.take_interrupted_usage("r1") is None  # 取走后清除


async def test_delete_thread_clears_its_conversation_archive() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="一"), AIMessage(content="二")])
    agent = _agent(model)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="a", model="fake"
        )
    ]
    _ = [
        e
        async for e in agent.run(
            thread_id="t2", thread_short_id=OTHER_SHORT, run_id="r2", message="b", model="fake"
        )
    ]

    await agent.delete_thread("t1", SHORT)

    graph = agent._graph_for("fake", "ask")
    assert (await graph.aget_state({"configurable": {"thread_id": "t1"}})).values == {}
    kept = await graph.aget_state({"configurable": {"thread_id": "t2"}})
    assert [m.content for m in kept.values["messages"]] == ["b", "二"]  # 其他会话不受影响


def _files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


async def _run(agent: MainAgent, message: str = "go") -> list[object]:
    """跑完一轮；执行命令固定先问（D21），遇到审批就全部同意再接着跑。"""
    events: list[object] = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message=message, model="fake"
        )
    ]
    while events and isinstance(paused := events[-1], ApprovalRequired):
        answers = [
            ApprovalAnswer(
                interrupt_id=request.interrupt_id,
                decisions=[ToolDecision(type="approve") for _ in request.actions],
            )
            for request in paused.requests
        ]
        await agent.check_answers(thread_id="t1", model="fake", answers=answers)
        events += [
            e
            async for e in agent.resume(
                thread_id="t1",
                thread_short_id=SHORT,
                run_id="r1",
                model="fake",
                message=message,
                answers=answers,
            )
        ]
    return events


async def test_commands_run_in_the_sandbox_for_this_thread(tmp_path: Path) -> None:
    sandbox = FakeSandbox(output="a.csv")
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    assert sandbox.calls == [(SHORT, "ls", None)]


async def test_new_threads_work_directory_exists_from_the_first_call(tmp_path: Path) -> None:
    """新会话的目录原来要等沙箱第一次执行命令才建：模型先查看自己的目录会得到"路径不存在"。"""
    model = ScriptedChatModel(
        responses=[call("ls", {"path": f"/workspace/{SHORT}/"}), AIMessage("好")]
    )
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, FakeSandbox())))
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert finished.status == "success"
    assert "outputs" in finished.output


async def test_files_land_in_this_threads_directory(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        responses=[
            call("write_file", {"file_path": f"/workspace/{SHORT}/outputs/a.txt", "content": "x"}),
            AIMessage("写好了"),
        ]
    )
    await _run(_agent(model, workspace=LocalWorkspace(tmp_path, FakeSandbox())))
    assert (tmp_path / "workspace" / SHORT / "outputs" / "a.txt").read_text() == "x"


async def test_prompt_tells_the_model_its_work_directory() -> None:
    model = ScriptedChatModel(responses=[AIMessage("好")])
    await _run(_agent(model))
    system = str(model.received[0][0].content)
    assert f"/workspace/{SHORT}/" in system
    assert f"/workspace/{SHORT}/outputs/" in system


async def test_skills_are_offered_and_read_only(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "excel"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: excel\ndescription: 处理 Excel 的规范\n---\n正文")
    model = ScriptedChatModel(
        responses=[
            call("read_file", {"file_path": "/skills/excel/SKILL.md"}),
            call("write_file", {"file_path": "/skills/excel/x.md", "content": "改"}),
            AIMessage("好"),
        ]
    )
    events = await _run(_agent(model, skills_dir=tmp_path / "skills"))
    assert "处理 Excel 的规范" in str(model.received[0][0].content)
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [(e.name, e.status) for e in finished] == [
        ("read_file", "success"),
        ("write_file", "error"),
    ]
    assert not (skill / "x.md").exists()


async def test_data_analyst_works_in_the_same_directory(tmp_path: Path) -> None:
    """数据分析员子智能体来自定义文件；它跟随主对话的模型，在同一个会话目录里执行代码。"""
    subagents = tmp_path / "subagents"
    subagents.mkdir()
    (subagents / "data_analyst.md").write_text(
        "---\nname: data_analyst\ndescription: 分析数据\n---\n你是数据分析员。"
    )
    sandbox = FakeSandbox(output="均值 3")
    task = {"description": "算均值", "subagent_type": "data_analyst"}
    model = ScriptedChatModel(
        responses=[
            call("task", task),
            call("execute", {"command": "python stats.py"}),  # 子智能体（同一个模型）
            AIMessage("均值是 3"),  # 子智能体交回
            AIMessage("算好了，均值是 3"),
        ]
    )
    agent = _agent(model, workspace=LocalWorkspace(tmp_path, sandbox), subagents_dir=subagents)
    events = await _run(agent)
    assert sandbox.calls == [(SHORT, "python stats.py", None)]
    started = [e for e in events if isinstance(e, SubagentStarted)]
    assert [e.name for e in started] == ["data_analyst"]
    sub_system = str(model.received[1][0].content)
    assert "你是数据分析员。" in sub_system
    assert f"/workspace/{SHORT}/" in sub_system


async def test_long_command_output_stays_out_of_the_workspace(tmp_path: Path) -> None:
    """超长输出由 deepagents 另存（/.agent/，在对话存档里），不在会话目录里留下文件。"""
    model = ScriptedChatModel(responses=[call("execute", {"command": "cat big"}), AIMessage("好")])
    sandbox = FakeSandbox(output="行" * 120_000)
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].status == "success"
    assert "/.agent/large_tool_results/" in finished[0].output
    assert _files(tmp_path) == []


async def test_delete_thread_removes_its_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    (tmp_path / "workspace" / SHORT / "outputs").mkdir(parents=True)
    agent = _agent(ScriptedChatModel(responses=[]), workspace=workspace)
    await agent.delete_thread("t1", SHORT)
    assert not (tmp_path / "workspace" / SHORT).exists()


async def test_new_and_changed_outputs_are_reported(tmp_path: Path) -> None:
    """outputs/ 下新增或改动的文件推送 file.created（显示为产物卡片）；其他目录的文件不算产物。"""
    outputs = tmp_path / "workspace" / SHORT / "outputs"

    def make_chart(session: str, command: str) -> None:
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "chart.png").write_bytes(b"png!")

    model = ScriptedChatModel(
        responses=[
            call("write_file", {"file_path": f"/workspace/{SHORT}/scratch.py", "content": "x"}),
            call("execute", {"command": "python plot.py"}),
            call("write_file", {"file_path": f"/workspace/{SHORT}/outputs/r.md", "content": "一"}),
            call(
                "write_file", {"file_path": f"/workspace/{SHORT}/outputs/r.md", "content": "二二"}
            ),
            AIMessage("图和报告都好了"),
        ]
    )
    sandbox = FakeSandbox(effect=make_chart)
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, sandbox)))
    files = [e for e in events if isinstance(e, FileCreated)]
    assert [(f.path, f.size, f.media_type) for f in files] == [
        ("outputs/chart.png", 4, "image/png"),
        ("outputs/r.md", 3, "text/markdown"),
        ("outputs/r.md", 6, "text/markdown"),  # 改动后再报一次
    ]
    assert all(f.agent_path == ["main"] and f.file_id is None for f in files)
    finished = events.index(next(e for e in events if isinstance(e, ToolFinished)))
    assert events.index(files[0]) > finished  # 在产生它的工具结束之后


async def test_files_from_earlier_runs_are_not_reported_again(tmp_path: Path) -> None:
    outputs = tmp_path / "workspace" / SHORT / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "old.csv").write_text("a")
    model = ScriptedChatModel(responses=[call("execute", {"command": "ls"}), AIMessage("好")])
    events = await _run(_agent(model, workspace=LocalWorkspace(tmp_path, FakeSandbox())))
    assert [e for e in events if isinstance(e, FileCreated)] == []


async def test_uploaded_image_reaches_only_models_that_can_see(tmp_path: Path) -> None:
    """能看图的模型收到图片本身；同一会话换到不能看图的模型时，历史里的图片换成说明。"""
    uploads = tmp_path / "workspace" / SHORT / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.png").write_bytes(b"png")
    model = ScriptedChatModel(responses=[AIMessage("是一张图表"), AIMessage("好")])
    agent = MainAgent(
        gateway=FakeGateway(model, vision_models=frozenset({"eyes"})),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
    )
    image = Attachment("uploads/a.png", "image/png", 3)
    async for _ in agent.run(
        thread_id="t1",
        thread_short_id=SHORT,
        run_id="r1",
        message="图里是什么",
        model="eyes",
        attachments=[image],
    ):
        pass
    async for _ in agent.run(
        thread_id="t1", thread_short_id=SHORT, run_id="r2", message="再说说", model="blind"
    ):
        pass
    first, second = model.received
    assert _block_types(first[-1]) == ["text", "image_url"]
    earlier_question = next(m for m in second if isinstance(m, HumanMessage))
    assert _block_types(earlier_question) == ["text", "text"]


async def test_vision_is_decided_per_request(tmp_path: Path) -> None:
    """启动时网关还没就绪、拿不到模型信息时按"不能看图"处理；之后拿到了，图片要照常送达，
    不能在第一次组装智能体时就定死（组装好的智能体会一直缓存到重启）。"""
    uploads = tmp_path / "workspace" / SHORT / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.png").write_bytes(b"png")
    model = ScriptedChatModel(responses=[AIMessage("你好"), AIMessage("是一张图表")])
    gateway = FakeGateway(model)
    agent = MainAgent(
        gateway=gateway,
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
    )
    async for _ in agent.run(
        thread_id="t1", thread_short_id=SHORT, run_id="r1", message="你好", model="eyes"
    ):
        pass
    gateway.vision_models = frozenset({"eyes"})  # 之后取到了模型信息
    async for _ in agent.run(
        thread_id="t1",
        thread_short_id=SHORT,
        run_id="r2",
        message="图里是什么",
        model="eyes",
        attachments=[Attachment("uploads/a.png", "image/png", 3)],
    ):
        pass
    assert _block_types(model.received[1][-1]) == ["text", "image_url"]


def _block_types(message: BaseMessage) -> list[str]:
    assert isinstance(message.content, list)
    return [block["type"] for block in message.content if isinstance(block, dict)]


@tool
def demo_list_notes() -> str:
    """列出笔记"""
    return "notes=[买牛奶]"


@tool
def demo_flaky() -> str:
    """总是断开"""
    raise RuntimeError("断开")


@tool
def demo_add_note(text: str) -> str:
    """记一条笔记"""
    return f"added {text}"


async def _run_once(agent: MainAgent, run_id: str = "r1", thread_id: str = "t1") -> list[object]:
    return [
        e
        async for e in agent.run(
            thread_id=thread_id, thread_short_id=SHORT, run_id=run_id, message="hi", model="fake"
        )
    ]


async def test_mcp_tools_are_available_to_the_agent() -> None:
    model = ScriptedChatModel(responses=[call("demo_list_notes", {}), AIMessage(content="好了")])
    mcp = FakeMcpClient([mcp_tool(demo_list_notes, read_only=True)])
    events = await _run_once(_agent(model, mcp=mcp))
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [(e.name, e.status) for e in finished] == [("demo_list_notes", "success")]
    assert "买牛奶" in finished[0].output
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"


async def test_failing_mcp_tool_becomes_error_result() -> None:
    model = ScriptedChatModel(responses=[call("demo_flaky", {}), AIMessage(content="换个办法")])
    mcp = FakeMcpClient([mcp_tool(demo_flaky, read_only=True)])
    events = await _run_once(_agent(model, mcp=mcp))
    [finished] = [e for e in events if isinstance(e, ToolFinished)]
    assert finished.status == "error"
    assert "调用失败" in finished.output
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"


async def test_reload_rebuilds_agent_with_new_tools() -> None:
    model = ScriptedChatModel(
        responses=[AIMessage(content="一"), call("demo_list_notes", {}), AIMessage(content="二")]
    )
    mcp = FakeMcpClient([])
    agent = _agent(model, mcp=mcp)
    await _run_once(agent)
    assert "demo_list_notes" not in model.bound
    mcp.next_tools = [mcp_tool(demo_list_notes, read_only=True)]
    await agent.reload_integrations([], ApprovalRulesConfig())
    events = await _run_once(agent, run_id="r2")
    assert "demo_list_notes" in model.bound
    assert [e.status for e in events if isinstance(e, ToolFinished)] == ["success"]
    assert mcp.connected == [[]]


async def test_mcp_tool_change_after_reconnect_rebuilds_agent() -> None:
    """MCP 服务断线重连后工具变了（设计 2026-10-23 5.8）：不用重新加载，下一次运行就组装新的。"""
    model = ScriptedChatModel(
        responses=[AIMessage(content="一"), call("demo_list_notes", {}), AIMessage(content="二")]
    )
    mcp = FakeMcpClient([])
    # 有上下文上限时组装结果才缓存（设计 4.6）：这里要验证的正是缓存被清掉
    agent = MainAgent(
        gateway=FakeGateway(model, max_input_tokens=200_000),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        mcp=mcp,
    )
    await _run_once(agent)
    assert "demo_list_notes" not in model.bound
    mcp.change_tools([mcp_tool(demo_list_notes, read_only=True)])
    events = await _run_once(agent, run_id="r2")
    assert "demo_list_notes" in model.bound
    assert [e.status for e in events if isinstance(e, ToolFinished)] == ["success"]
    assert mcp.connected == []


async def test_builtin_tool_names_match_the_agent() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="好")])
    mcp = FakeMcpClient([mcp_tool(demo_add_note)])
    agent = _agent(
        model, mcp=mcp, knowledge=FakeKnowledgeStore(), conversations=FakeConversationIndex()
    )
    await _run_once(agent)
    assert sorted(model.bound) == sorted([*BUILTIN_TOOLS, "demo_add_note"])
    approvals = {row.name: row.action for row in agent.tool_approvals()}
    assert approvals["demo_add_note"] == "ask"
    assert set(approvals) == {*BUILTIN_TOOLS, "demo_add_note"}


async def test_failing_mcp_tool_in_subagent_becomes_error_result() -> None:
    """子智能体继承了 MCP 工具：它调用时出错同样只是工具结果，不让整次运行失败（审查 C1）。"""
    task = {
        "name": "task",
        "args": {"description": "查笔记", "subagent_type": "general-purpose"},
        "id": "t1",
        "type": "tool_call",
    }
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task]),
            call("demo_flaky", {}),
            AIMessage(content="子任务：服务断开了"),
            AIMessage(content="换个办法"),
        ]
    )
    mcp = FakeMcpClient([mcp_tool(demo_flaky, read_only=True)])
    events = await _run_once(_agent(model, mcp=mcp))
    [finished] = [e for e in events if isinstance(e, ToolFinished) and e.name == "demo_flaky"]
    assert finished.status == "error"
    assert "调用失败" in finished.output
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"


async def test_model_calls_know_their_thread_and_run() -> None:
    """主智能体、子智能体的每次模型调用都在这次运行的调用归属里；运行结束后不再有。"""
    task = {
        "name": "task",
        "args": {"description": "查一下", "subagent_type": "general-purpose"},
        "id": "t1",
        "type": "tool_call",
    }
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task]),
            AIMessage(content="子任务完成"),
            AIMessage(content="好了"),
        ]
    )
    await _run_once(_agent(model), run_id="r1", thread_id="t1")
    assert model.calls_in == [CallContext("t1", "r1")] * 3
    assert current_call() is None


async def test_title_generation_belongs_to_its_thread() -> None:
    model = ScriptedChatModel(responses=[AIMessage(content="周报模板")])
    agent = _agent(model)
    await agent.generate_title(
        thread_id="t1", run_id="r1", model="fake", message="写周报", answer="好的"
    )
    assert model.calls_in == [CallContext("t1", "r1")]


async def _two_turns(model: ScriptedChatModel) -> tuple[RunFinished, list[tuple[str, Any]]]:
    """第一轮"写长文"（会失败），第二轮"继续"；返回第一轮的结束事件与第二轮发给模型的对话。"""
    agent = _agent(model)
    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="写长文", model="fake"
        )
    ]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    _ = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="继续", model="fake"
        )
    ]
    sent = [(m.type, m.content) for m in model.received[-1] if m.type in ("human", "ai")]
    return finished, sent


async def test_failure_keeps_partial_answer_with_reason() -> None:
    """上游报错：像停止一样留下已输出的部分，说明写清实际原因（D23，设计 4.4）。"""
    model = BreakingChatModel(
        error=RuntimeError("upstream exploded"), responses=[AIMessage(content="好的")]
    )
    finished, sent = await _two_turns(model)
    assert (finished.status, finished.error) == ("failed", "RuntimeError: upstream exploded")
    assert sent == [
        ("human", "写长文"),
        ("ai", f"前半段\n\n{interrupted_note('调用出错：upstream exploded')}"),
        ("human", "继续"),
    ]


class _PaymentRequiredError(Exception):
    status_code = 402


async def test_quota_failure_says_how_to_continue() -> None:
    """额度用完：运行结束并说明充值后说"继续"；已输出的部分留下。"""
    model = BreakingChatModel(
        error=_PaymentRequiredError("Payment Required"), responses=[AIMessage(content="好的")]
    )
    finished, sent = await _two_turns(model)
    assert (finished.status, finished.error) == ("failed", QUOTA_EXHAUSTED)
    assert sent[1] == ("ai", f"前半段\n\n{interrupted_note(QUOTA)}")


async def test_failure_without_output_notes_the_real_reason() -> None:
    """还没输出文字就失败：照样写一条中断说明，写明真实原因（设计 2026-10-23 4.5），
    不再由下一轮补上"用户停止或服务中断"的通用说明。"""
    model = BreakingChatModel(
        error=RuntimeError("boom"), partial="", responses=[AIMessage(content="好的")]
    )
    finished, sent = await _two_turns(model)
    assert finished.status == "failed"
    assert sent == [
        ("human", "写长文"),
        ("ai", interrupted_note("调用出错：boom")),
        ("human", "继续"),
    ]


class RateLimitError(Exception):  # 与 litellm 的同名：按类名认出限流
    pass


async def test_failed_run_carries_error_kind() -> None:
    model = BreakingChatModel(
        error=RateLimitError("slow down"), partial="", responses=[AIMessage(content="好的")]
    )
    finished, _ = await _two_turns(model)
    assert (finished.status, finished.error_kind) == ("failed", "rate_limit")


async def test_stalled_run_has_stalled_kind() -> None:
    model = StallingChatModel(responses=[AIMessage(content="好的")])
    finished, _ = await _two_turns(model)
    assert (finished.status, finished.error_kind) == ("failed", "stalled")


async def test_failure_before_the_turn_starts_adds_no_note() -> None:
    """还没进到这一轮就失败（如查常驻记忆时数据库出错）：存档里不写中断说明，
    上一轮的回答仍是最后一条。"""
    store = FakeKnowledgeStore()
    model = ScriptedChatModel(responses=[AIMessage(content="第一轮的回答")])
    agent = _agent(model, knowledge=store)
    first = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="你好", model="fake"
        )
    ]
    assert isinstance(first[-1], RunFinished)

    async def broken() -> list[Any]:
        raise RuntimeError("数据库暂时不可用")

    store.pinned = broken  # type: ignore[method-assign]
    second = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r2", message="再来", model="fake"
        )
    ]
    assert isinstance(second[-1], RunFinished)
    assert second[-1].status == "failed"
    state = await agent._graph_for("fake", "ask").aget_state({"configurable": {"thread_id": "t1"}})
    last = state.values["messages"][-1]
    assert (last.type, last.content) == ("ai", "第一轮的回答")


# ---- "重试这一轮"（D26，设计 2026-10-23 4.5）：从失败那次运行之前的存档分叉 ----


async def _turn(
    agent: MainAgent, run_id: str, message: str, retry_of: str | None = None
) -> RunFinished:
    events = [
        e
        async for e in agent.run(
            thread_id="t1",
            thread_short_id=SHORT,
            run_id=run_id,
            message=message,
            model="fake",
            retry_of=retry_of,
        )
    ]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    return finished


async def _archive(agent: MainAgent) -> list[tuple[str, Any]]:
    state = await agent._graph_for("fake", "ask").aget_state({"configurable": {"thread_id": "t1"}})
    return [(m.type, m.content) for m in state.values["messages"]]


async def test_retry_forks_from_before_the_failed_run() -> None:
    """重跑时模型看不到失败的那一轮：用户消息只出现一次，也没有中断说明。"""
    model = FailingAtChatModel(fail_at=1, responses=[AIMessage("回答1"), AIMessage("回答2")])
    agent = _agent(model)
    assert (await _turn(agent, "r1", "问题1")).status == "completed"
    assert (await _turn(agent, "r2", "问题2")).status == "failed"
    assert (await _turn(agent, "r3", "问题2", retry_of="r2")).status == "completed"
    assert await _archive(agent) == [
        ("human", "问题1"),
        ("ai", "回答1"),
        ("human", "问题2"),
        ("ai", "回答2"),
    ]


async def test_retry_of_the_first_run_starts_clean() -> None:
    model = FailingAtChatModel(fail_at=0, responses=[AIMessage("回答")])
    agent = _agent(model)
    assert (await _turn(agent, "r1", "问题")).status == "failed"
    assert (await _turn(agent, "r2", "问题", retry_of="r1")).status == "completed"
    assert await _archive(agent) == [("human", "问题"), ("ai", "回答")]


def test_has_side_effects_classification() -> None:
    """有副作用的调用：执行命令、写改删文件、记记忆、没声明只读的 MCP 工具；认不出的也算。"""
    mcp = FakeMcpClient([mcp_tool(demo_list_notes, read_only=True), mcp_tool(demo_add_note)])
    agent = _agent(ScriptedChatModel(responses=[]), mcp=mcp)
    for name in ("execute", "write_file", "edit_file", "delete", "remember", "demo_add_note"):
        assert agent.has_side_effects([name]), name
    assert agent.has_side_effects(["something_unknown"])
    assert not agent.has_side_effects(["read_file", "ls", "glob", "grep", "task", "write_todos"])
    assert not agent.has_side_effects(["search_knowledge", "read_document", "demo_list_notes"])
    assert not agent.has_side_effects([])


async def test_context_usage_comes_before_the_answer() -> None:
    """每次主智能体调用模型都先推一条上下文占用（设计 2026-10-23 4.7），排在这次的回答之前。"""
    model = ScriptedChatModel(responses=[AIMessage(content="好的")])
    agent = MainAgent(
        gateway=FakeGateway(model, max_input_tokens=200_000),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
    )
    events = await _run_once(agent)
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ContextUsage") < kinds.index("MessageDelta")
    usage = next(e for e in events if type(e).__name__ == "ContextUsage")
    assert usage.max_input_tokens == 200_000  # type: ignore[attr-defined]


async def test_execute_reports_exit_code_and_stderr() -> None:
    """沙箱给的退出码与错误输出经工具结果的附加信息到达工具结束事件（设计 2026-10-23 5.4）。"""
    model = ScriptedChatModel(
        responses=[call("execute", {"command": "python a.py"}), AIMessage(content="失败了")]
    )
    sandbox = FakeSandbox(output="x", exit_code=2, stderr="boom")
    events = await _run(_agent(model, workspace=LocalWorkspace(Path(tempfile.mkdtemp()), sandbox)))
    [finished] = [e for e in events if isinstance(e, ToolFinished) and e.name == "execute"]
    assert (finished.exit_code, finished.stderr) == (2, "boom")


class _ToolSpy(ScriptedChatModel):
    """记下绑定给模型的每个工具的说明。"""

    descriptions: dict[str, str] = Field(default_factory=dict)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        for item in tools:
            function = convert_to_openai_tool(item)["function"]
            self.descriptions[function["name"]] = function.get("description", "")
        return super().bind_tools(tools, **kwargs)


async def test_write_file_description_asks_to_read_first() -> None:
    """覆盖已有文件前要先读过最新版（设计 2026-10-23 5.6）：工具说明里不再说"不用先读"。"""
    model = _ToolSpy(responses=[AIMessage(content="好")])
    await _run_once(_agent(model))
    description = model.descriptions["write_file"]
    assert "read_file" in description
    assert "do not need to read" not in description


class _BindSpy(ScriptedChatModel):
    """记下每次绑定给模型的工具名（主智能体、子智能体各绑各的）。"""

    binds: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        bound = super().bind_tools(tools, **kwargs)
        self.binds.append(list(self.bound))
        return bound


def _task(description: str, call_id: str = "t1") -> AIMessage:
    return call("task", {"description": description, "subagent_type": "general-purpose"}, call_id)


async def test_subagents_cannot_write_memories() -> None:
    """子智能体收权（设计 2026-10-23 5.10、6.6）：没有 remember、update_memory、forget_memory，
    查知识库、MCP 工具照样有。"""
    model = _BindSpy(
        responses=[_task("查一下"), AIMessage(content="查好了"), AIMessage(content="好")]
    )
    mcp = FakeMcpClient([mcp_tool(demo_list_notes, read_only=True)])
    await _run_once(_agent(model, mcp=mcp, knowledge=FakeKnowledgeStore()))
    main = next(names for names in model.binds if "task" in names)
    sub = next(names for names in model.binds if "task" not in names)
    writes = {"remember", "update_memory", "forget_memory"}
    assert writes <= set(main)
    assert not writes & set(sub)
    assert {"demo_list_notes", "search_knowledge", "read_document"} <= set(sub)


async def test_long_subagent_report_is_saved_to_reports() -> None:
    """子智能体交回超过 4000 字：全文写进会话目录的 reports/，交回给主智能体的只留开头。"""
    report = "结论：" + "很长的分析。" * 1000
    model = ScriptedChatModel(
        responses=[_task("分析"), AIMessage(content=report), AIMessage(content="好")]
    )
    root = Path(tempfile.mkdtemp())
    events = await _run_once(_agent(model, workspace=LocalWorkspace(root, FakeSandbox())))
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status == "completed"
    result = next(
        m for m in model.received[-1] if isinstance(m, ToolMessage) and m.tool_call_id == "t1"
    )
    text = str(result.content)
    assert len(text) <= 4100
    assert text.startswith("结论：很长的分析。")
    assert f"（完整报告见 /workspace/{SHORT}/reports/子智能体-general-purpose-" in text
    [saved] = (root / "workspace" / SHORT / "reports").glob("子智能体-general-purpose-*.md")
    assert saved.read_text(encoding="utf-8") == report


async def test_parallel_long_reports_do_not_overwrite_each_other() -> None:
    """同时派出两个子智能体、同一秒交回长报告：各存一份（审查 I5：原来第二份覆盖第一份）。"""
    first, second = "甲" * 5000, "乙" * 5000
    calls = [
        {"name": "task", "args": {"description": d, "subagent_type": "general-purpose"}}
        | {"id": i, "type": "tool_call"}
        for d, i in (("分析甲", "t1"), ("分析乙", "t2"))
    ]
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=calls),
            AIMessage(content=first),
            AIMessage(content=second),
            AIMessage(content="好"),
        ]
    )
    root = Path(tempfile.mkdtemp())
    await _run_once(_agent(model, workspace=LocalWorkspace(root, FakeSandbox())))
    reports = (root / "workspace" / SHORT / "reports").glob("子智能体-general-purpose-*.md")
    assert sorted(path.read_text(encoding="utf-8") for path in reports) == sorted([first, second])


async def test_short_subagent_report_is_kept_whole() -> None:
    model = ScriptedChatModel(
        responses=[_task("查"), AIMessage(content="晴，25 度"), AIMessage(content="好")]
    )
    root = Path(tempfile.mkdtemp())
    await _run_once(_agent(model, workspace=LocalWorkspace(root, FakeSandbox())))
    result = next(
        m for m in model.received[-1] if isinstance(m, ToolMessage) and m.tool_call_id == "t1"
    )
    assert result.content == "晴，25 度"
    assert not (root / "workspace" / SHORT / "reports").exists()


async def test_agents_can_search_past_conversations() -> None:
    """有会话索引时主智能体与子智能体都有 search_conversations（设计 2026-10-23 6.1）。"""
    model = _BindSpy(
        responses=[_task("查一下"), AIMessage(content="查好了"), AIMessage(content="好")]
    )
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        conversations=FakeConversationIndex(),
    )
    await _run_once(agent)
    assert all("search_conversations" in names for names in model.binds)


async def test_main_agent_must_reread_what_a_subagent_changed(tmp_path: Path) -> None:
    """主智能体读过、子智能体（读过后）改了同一个文件：主智能体再写要先重读（积压小问题 D16）。
    按真实的运行流程验证调用方认得出来：主、子智能体的检查点命名空间不同。"""
    workspace = LocalWorkspace(tmp_path, FakeSandbox())
    target = tmp_path / "workspace" / SHORT / "a.txt"
    target.parent.mkdir(parents=True)
    target.write_text("原文", encoding="utf-8")
    path = f"/workspace/{SHORT}/a.txt"
    model = ScriptedChatModel(
        responses=[
            call("read_file", {"file_path": path}, "r1"),
            _task("改一下 a.txt"),
            call("read_file", {"file_path": path}, "s1"),
            call("write_file", {"file_path": path, "content": "子改的"}, "s2"),
            AIMessage(content="改好了"),
            call("write_file", {"file_path": path, "content": "主改的"}, "w1"),
            AIMessage(content="好"),
        ]
    )
    events = await _run_once(_agent(model, workspace=workspace))
    [main_write] = [e for e in events if isinstance(e, ToolFinished) and e.call_id == "w1"]
    assert "先用 read_file 读最新版再改" in main_write.output
    assert target.read_text(encoding="utf-8") == "子改的"


@tool
def files_read_file(path: str) -> str:
    """读共享文件夹里的文件"""
    return f"读到 {path}"


async def test_system_prompt_lists_connected_services() -> None:
    """系统提示词按已接入的 MCP 服务说明每个服务是什么（积压小问题 E13，用户 2026-10-26 定为
    按服务说明动态写）：用户说"共享文件夹"时模型知道是 files 服务，不是会话工作目录。"""
    status = McpServerStatus(
        name="files",
        description="共享文件夹（本机 .workdata/shared/）",
        transport="stdio",
        state="connected",
        tools=["files_read_file"],
    )
    mcp = FakeMcpClient([mcp_tool(files_read_file, server="files")], [status])
    model = ScriptedChatModel(responses=[AIMessage(content="好")])
    await _run_once(_agent(model, mcp=mcp))
    system = str(model.received[0][0].content)
    assert "files（工具名以 files_ 开头）：共享文件夹（本机 .workdata/shared/）" in system
    assert "不要用会话工作目录" in system


def test_system_prompt_does_not_promise_confirmation_for_every_command() -> None:
    """ "每次执行命令前都会先请用户确认"在"跳过所有审批"档下不成立（D23）：按审批权限说。"""
    text = (Path(__file__).resolve().parents[1] / "prompts" / "system.md").read_text(
        encoding="utf-8"
    )
    assert "每次执行命令前都会先请用户确认" not in text
    assert "审批权限" in text
