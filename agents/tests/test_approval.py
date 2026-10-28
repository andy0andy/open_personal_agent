"""工具审批规则判定（设计文档 7.5）。"""

from langchain_core.tools import tool

from agents.main_agent.integrations import EXECUTE_ALWAYS_ASKS, ApprovalPolicy
from agents.tests.fakes import mcp_tool
from config import ApprovalRulesConfig


@tool
def files_read_text_file(path: str) -> str:
    """读文件"""
    return path


@tool
def files_write_file(path: str, content: str) -> str:
    """写文件"""
    return path


def test_first_matching_rule_wins() -> None:
    policy = ApprovalPolicy(
        ApprovalRulesConfig(tools={"files_*": "auto", "files_write_file": "ask"})
    )
    decision = policy.decide("files_write_file", server="files", read_only=False)
    assert (decision.action, decision.reason) == ("auto", "规则 files_*")
    assert decision.server == "files"


def test_builtin_tools_default_to_auto() -> None:
    policy = ApprovalPolicy(ApprovalRulesConfig())
    decision = policy.decide("write_file", server=None, read_only=None)
    assert (decision.action, decision.reason, decision.server) == (
        "auto",
        "内置工具默认自动执行",
        None,
    )
    strict = ApprovalPolicy(ApprovalRulesConfig(tools={"write_file": "ask"}))
    assert strict.decide("write_file", server=None, read_only=None).action == "ask"


def test_mcp_tools_follow_read_only_then_default() -> None:
    policy = ApprovalPolicy(ApprovalRulesConfig())
    read = policy.decide("files_read_text_file", server="files", read_only=True)
    assert (read.action, read.reason) == ("auto", "服务声明为只读")
    for read_only in (None, False):
        other = policy.decide("files_write_file", server="files", read_only=read_only)
        assert (other.action, other.reason) == ("ask", "MCP 工具默认（mcp_default）")
    relaxed = ApprovalPolicy(ApprovalRulesConfig(mcp_default="auto"))
    assert relaxed.decide("files_write_file", server="files", read_only=None).action == "auto"


def test_table_lists_mcp_then_builtin() -> None:
    policy = ApprovalPolicy(ApprovalRulesConfig())
    table = policy.table(
        ["execute"],
        [
            mcp_tool(files_read_text_file, server="files", read_only=True),
            mcp_tool(files_write_file, server="files"),
        ],
    )
    assert [(row.name, row.action) for row in table] == [
        ("files_read_text_file", "auto"),
        ("files_write_file", "ask"),
        ("execute", "ask"),
    ]


def test_execute_always_asks() -> None:
    """执行命令固定先问：workdata 里的规则（含通配）都放宽不了它（D21 第 7 条）。"""
    policy = ApprovalPolicy(ApprovalRulesConfig(tools={"*": "auto", "execute": "auto"}))
    decision = policy.decide("execute", server=None, read_only=None)
    assert (decision.action, decision.reason) == ("ask", "执行命令每次先问（固定，D21）")


def test_decision_carries_read_only_hint() -> None:
    """MCP 页的工具列表要标出"只读"：判定结果带上服务声明的只读与否。"""
    policy = ApprovalPolicy(ApprovalRulesConfig(tools={"files_write_file": "auto"}))
    assert policy.decide("files_read", server="files", read_only=True).read_only is True
    assert policy.decide("files_write_file", server="files", read_only=False).read_only is False
    assert policy.decide("write_file", server=None, read_only=None).read_only is None


def _strict() -> ApprovalPolicy:
    return ApprovalPolicy(ApprovalRulesConfig(mcp_default="ask", tools={"*": "ask"}))


def test_skip_mode_auto_for_everything() -> None:
    """会话权限"跳过所有审批"（设计 2026-10-19 4.1）：连执行命令也不问。"""
    policy = _strict()
    for name, server, read_only in (("execute", None, None), ("memo_add", "memo", False)):
        decision = policy.decide(name, server=server, read_only=read_only, mode="skip")
        assert (decision.action, decision.reason) == ("auto", "本会话跳过所有审批")


def test_ask_execute_only_asks_for_execute() -> None:
    """ "只问执行命令"：审批规则不看，只有执行命令先问。"""
    policy = _strict()
    execute = policy.decide("execute", server=None, read_only=None, mode="ask_execute")
    assert (execute.action, execute.reason) == ("ask", "本会话只问执行命令")
    for name, server, read_only in (("memo_add", "memo", False), ("write_file", None, None)):
        decision = policy.decide(name, server=server, read_only=read_only, mode="ask_execute")
        assert (decision.action, decision.reason) == ("auto", "本会话只问执行命令，其余自动")


def test_ask_mode_keeps_rules_and_execute_lock() -> None:
    """ "每次先问"（默认）：照旧按规则，执行命令仍固定先问。"""
    policy = ApprovalPolicy(ApprovalRulesConfig(tools={"*": "auto"}))
    execute = policy.decide("execute", server=None, read_only=None, mode="ask")
    assert (execute.action, execute.reason) == ("ask", EXECUTE_ALWAYS_ASKS)
    assert policy.decide("memo_add", server="memo", read_only=False, mode="ask").action == "auto"
