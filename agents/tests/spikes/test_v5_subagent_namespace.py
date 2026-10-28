"""先行验证 V5（离线）：子智能体事件在输出流中的归属。

结论：子智能体的片段 ns 为 ("tools:<随机ID>",)，与 task 调用 ID 无关（M1b 更正）；
task 工具的最终结果以 ToolMessage 出现在主命名空间。命名空间与调用 ID 的对应关系由
运行跟踪器从工具开始回调中取得（见 agents/main_agent/runtime/tracker.py）。
"""

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.tests.fakes import ScriptedChatModel


async def test_subagent_chunks_carry_tools_namespace() -> None:
    task_call = {
        "name": "task",
        "args": {"description": "算一下 1+1", "subagent_type": "general-purpose"},
        "id": "c1",
        "type": "tool_call",
    }
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[task_call]),
            AIMessage(content="子结果"),  # 子智能体（与主智能体共用同一个假模型）
            AIMessage(content="答案"),
        ]
    )
    agent = create_deep_agent(model=model, checkpointer=InMemorySaver())

    main_text, sub_text, main_tool_results = "", "", []
    async for part in agent.astream(
        {"messages": [{"role": "user", "content": "go"}]},
        {"configurable": {"thread_id": "t"}},
        stream_mode=["messages"],
        subgraphs=True,
        version="v2",
    ):
        if part["type"] != "messages":
            continue
        chunk, _ = part["data"]
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str):
            if part["ns"]:
                assert part["ns"][0].startswith("tools:")
                sub_text += chunk.content
            else:
                main_text += chunk.content
        elif isinstance(chunk, ToolMessage) and not part["ns"]:
            main_tool_results.append(chunk.content)

    assert sub_text == "子结果"
    assert main_text == "答案"
    assert main_tool_results == ["子结果"]
