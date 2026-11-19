"""给模型看的工具说明要和真实环境一致（D29）。

deepagents 的 execute 说明写的是"在隔离的沙箱里执行"，而这里的命令和智能体在同一个环境里、
能联网（D20）：模型照着原说明会不试就说"沙箱不能联网"（2026-11-19 实际发生过）。
"""

import json
from pathlib import Path

from langchain_core.utils.function_calling import convert_to_openai_tool

from agents.main_agent.runtime.agent import _filesystem
from agents.main_agent.runtime.files import build_file_tree
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeSandbox


def _description(tmp_path: Path, name: str) -> str:
    backend = build_file_tree(LocalWorkspace(tmp_path, FakeSandbox()).agent_backend, None)
    [found] = [tool for tool in _filesystem(backend).tools if tool.name == name]
    return found.description


def test_nothing_sent_to_the_model_calls_execute_a_sandbox(tmp_path: Path) -> None:
    # 参数的说明也随工具定义发给模型：deepagents 原文是 "…in the sandbox environment"
    backend = build_file_tree(LocalWorkspace(tmp_path, FakeSandbox()).agent_backend, None)
    [execute] = [tool for tool in _filesystem(backend).tools if tool.name == "execute"]
    sent = convert_to_openai_tool(execute)  # 发给模型的工具定义就是这个样子
    assert "sandbox" not in json.dumps(sent, ensure_ascii=False).lower()
    assert set(sent["function"]["parameters"]["properties"]) == {"command", "timeout"}  # 参数没变


def test_execute_description_matches_the_real_environment(tmp_path: Path) -> None:
    text = _description(tmp_path, "execute")
    assert "sandbox" not in text.lower()
    assert "network access" in text  # 能联网
    assert "pip install" in text  # 能装包
    assert "apt" in text  # 装不了系统软件
    assert "cannot modify" in text  # 改不了自己的程序代码


def test_write_file_description_is_still_ours(tmp_path: Path) -> None:
    assert "先用 read_file 读最新版再改" in _description(tmp_path, "write_file")
