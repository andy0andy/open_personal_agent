"""工作区（设计文档 4.1、7.3、9）：会话目录里的文件 + 在智能体所在环境里执行命令（D20）。"""

from agents.main_agent.workspace.base import (
    COMMAND_RESULTS,
    CommandResult,
    OpenedFile,
    OutputFile,
    Sandbox,
    Workspace,
)
from agents.main_agent.workspace.files import (
    WorkspaceFile,
    WorkspaceFileRepo,
    workspace_file_id,
)
from agents.main_agent.workspace.local import LocalWorkspace
from agents.main_agent.workspace.local_sandbox import LocalSandbox
from agents.main_agent.workspace.media import media_type

__all__ = [
    "COMMAND_RESULTS",
    "CommandResult",
    "LocalSandbox",
    "LocalWorkspace",
    "OpenedFile",
    "OutputFile",
    "Sandbox",
    "Workspace",
    "WorkspaceFile",
    "WorkspaceFileRepo",
    "media_type",
    "workspace_file_id",
]
