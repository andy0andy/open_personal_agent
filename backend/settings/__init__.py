"""设置：设置页的设置（存数据库，D22）、可在运行中重新加载的集成配置（MCP 服务清单、
工具审批规则）、技能上传、首次启动写入的默认内容。
"""

from backend.settings.service import IntegrationSettings

__all__ = ["IntegrationSettings"]
