"""先行验证 V4（离线）：工作区后端作为 CompositeBackend 的默认后端时的行为。

结论将指导 M2 的工作区实现：
1. 必须显式继承 SandboxBackendProtocol（抽象基类），否则 deepagents 不提供 execute 工具；
2. CompositeBackend 只把执行交给默认后端；
3. 执行时可通过 get_runtime(上下文类型).context 读到会话短 ID；
4. 虚拟根映射到 root_dir，/workspace/... 落在 root_dir/workspace/...；/skills/ 路由可读。
"""

from dataclasses import dataclass
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import get_runtime

from agents.tests.fakes import ScriptedChatModel


@dataclass
class _Context:
    thread_short_id: str


class _ProbeWorkspace(FilesystemBackend, SandboxBackendProtocol):
    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root, virtual_mode=True)
        self.calls: list[tuple[str, str]] = []

    @property
    def id(self) -> str:
        return "probe-workspace"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        short_id = get_runtime(_Context).context.thread_short_id
        self.calls.append((short_id, command))
        return ExecuteResponse(output=f"ran in {short_id}", exit_code=0, truncated=False)


def _call(name: str, args: dict[str, str], call_id: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]
    )


async def test_workspace_as_default_backend(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n技能正文")
    workspace = _ProbeWorkspace(tmp_path / "ws")
    backend = CompositeBackend(
        default=workspace,
        routes={"/skills/": FilesystemBackend(root_dir=tmp_path / "skills", virtual_mode=True)},
    )
    model = ScriptedChatModel(
        responses=[
            _call("execute", {"command": "echo hi"}, "c1"),
            _call("read_file", {"file_path": "/skills/demo/SKILL.md"}, "c2"),
            _call("write_file", {"file_path": "/workspace/c_test/a.txt", "content": "x"}, "c3"),
            AIMessage(content="完成"),
        ]
    )
    agent = create_deep_agent(
        model=model, backend=backend, context_schema=_Context, checkpointer=InMemorySaver()
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "go"}]},
        {"configurable": {"thread_id": "t"}},
        context=_Context(thread_short_id="c_test"),
    )

    statuses = {m.name: m.status for m in result["messages"] if m.type == "tool"}
    assert statuses == {"execute": "success", "read_file": "success", "write_file": "success"}
    assert workspace.calls == [("c_test", "echo hi")]
    assert (tmp_path / "ws" / "workspace" / "c_test" / "a.txt").read_text() == "x"
