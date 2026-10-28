"""设置接口（设计文档 12.1）：设置页的设置与 .workdata 文件状态；MCP 服务、工具审批规则、
技能与重新加载。

MCP 服务与审批规则可以在管理页面上改（D21），改动只写 .workdata/config/。
"""

from fastapi import APIRouter, status
from pydantic import BaseModel

from agents.main_agent.integrations import McpProbeResult, ToolApproval
from agents.main_agent.runtime import SkillCatalog, SkillDetail, SkillInfo
from backend.api.deps import Services, ServicesDep
from backend.settings.app_settings import SettingValue, SettingView
from backend.settings.data_files import DataFileView, data_file_views
from backend.settings.schemas import (
    EnabledInput,
    McpServerInput,
    McpServersInput,
    McpServersView,
    SkillUpload,
    ToolActionInput,
)
from backend.settings.skill_upload import decode_upload, parse_skill_upload
from common.errors import InvalidRequestError, NotFoundError
from config.integrations import ApprovalMode

settings_router = APIRouter(prefix="/settings")


class ApprovalRuleView(BaseModel):
    tool: str  # 工具名或通配
    action: ApprovalMode


class ApprovalSettingsView(BaseModel):
    mcp_default: ApprovalMode
    rules: list[ApprovalRuleView]  # 规则文件里的规则，按文件顺序
    tools: list[ToolApproval]  # 全部工具的生效结果与原因（按"每次先问"档位，D23）


class ReloadResult(BaseModel):
    servers: McpServersView
    approvals: ApprovalSettingsView


@settings_router.get("/mcp-servers")
async def mcp_servers(services: ServicesDep) -> McpServersView:
    return _servers(services)


@settings_router.post("/mcp-servers", status_code=status.HTTP_201_CREATED)
async def add_mcp_servers(body: McpServersInput, services: ServicesDep) -> McpServersView:
    """加入一个或多个服务（手动添加、粘贴 JSON）：全部成功或全部不加。"""
    await services.integrations.add_servers(body.servers)
    return _servers(services)


@settings_router.post("/mcp-servers/test")
async def test_mcp_server(body: McpServerInput, services: ServicesDep) -> McpProbeResult:
    """测试连接，不保存。"""
    return await services.integrations.probe(body)


@settings_router.put("/mcp-servers/{name}")
async def update_mcp_server(
    name: str, body: McpServerInput, services: ServicesDep
) -> McpServersView:
    await services.integrations.update_server(name, body)
    return _servers(services)


@settings_router.patch("/mcp-servers/{name}")
async def toggle_mcp_server(name: str, body: EnabledInput, services: ServicesDep) -> McpServersView:
    """停用 = 断开连接，配置保留。"""
    await services.integrations.set_server_enabled(name, body.enabled)
    return _servers(services)


@settings_router.delete("/mcp-servers/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(name: str, services: ServicesDep) -> None:
    await services.integrations.remove_server(name)


@settings_router.get("/approval-rules")
async def approval_rules(services: ServicesDep) -> ApprovalSettingsView:
    return _approvals(services)


@settings_router.put("/approval-rules/tools/{tool}")
async def set_tool_action(
    tool: str, body: ToolActionInput, services: ServicesDep
) -> ApprovalSettingsView:
    """改一个工具的"自动 / 先问"（执行命令除外，它固定先问）。"""
    await services.integrations.set_tool_action(tool, body.action)
    return _approvals(services)


@settings_router.get("/skills")
async def skills(services: ServicesDep) -> list[SkillInfo]:
    """每次现读技能目录（.workdata/skills/）：加了技能不用重新加载；最近使用时间取自技能用量。"""
    last_used = await services.usage.skill_last_used()
    return [
        skill.model_copy(update={"last_used_at": last_used.get(skill.id)})
        for skill in services.agent.skills()
    ]


@settings_router.get("/skills/{skill_id}")
async def skill_detail(skill_id: str, services: ServicesDep) -> SkillDetail:
    return await _with_last_used(services, _catalog(services).detail(skill_id))


@settings_router.post("/skills", status_code=status.HTTP_201_CREATED)
async def upload_skill(body: SkillUpload, services: ServicesDep) -> SkillInfo:
    """上传技能（文件夹 / .zip / 单个 SKILL.md）：检查完才写进 .workdata/skills/，不许同名。"""
    limit = services.settings.max_upload_mb * 1024 * 1024  # 与附件、知识库文档共用上限
    files = decode_upload([(item.path, item.content) for item in body.files], max_bytes=limit)
    return _catalog(services).install(parse_skill_upload(files, max_bytes=limit))


@settings_router.patch("/skills/{skill_id}")
async def toggle_skill(skill_id: str, body: EnabledInput, services: ServicesDep) -> SkillInfo:
    """停用 = 智能体暂时看不到它，文件保留。"""
    return await _with_last_used(services, _catalog(services).set_enabled(skill_id, body.enabled))


async def _with_last_used[S: SkillInfo](services: Services, skill: S) -> S:
    """详情、启停的返回也带上最近使用时间（积压小问题 F3：原来只有列表有）。"""
    last_used = await services.usage.skill_last_used()
    return skill.model_copy(update={"last_used_at": last_used.get(skill.id)})


@settings_router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: str, services: ServicesDep) -> None:
    _catalog(services).remove(skill_id)


@settings_router.get("/files")
async def data_files(services: ServicesDep) -> list[DataFileView]:
    """.workdata 里各文件的位置与状态（D22）。"""
    return data_file_views(services.settings, services.agent.skill_catalog)


# ---- 设置页的设置（D22）：存数据库，同名环境变量优先 ----

_DEFAULT_MODEL = "agent.default_model"


@settings_router.get("/app")
async def app_settings(services: ServicesDep) -> list[SettingView]:
    return await services.app_settings.views()


@settings_router.put("/app/{key}")
async def update_app_setting(key: str, body: SettingValue, services: ServicesDep) -> SettingView:
    """改一项设置；默认对话模型走模型页同一套检查（必须是网关里的对话模型）。"""
    if key == _DEFAULT_MODEL:
        if not isinstance(body.value, str):
            raise InvalidRequestError("取值不合规：默认对话模型应是模型名")
        await services.models.set_default_chat(body.value)
        return await services.app_settings.view(key)
    return await services.app_settings.update(key, body.value)


@settings_router.delete("/app/{key}")
async def reset_app_setting(key: str, services: ServicesDep) -> SettingView:
    """删掉页面上存的值，回到默认值（或环境变量指定的值）。"""
    view = await services.app_settings.view(key)
    if key == _DEFAULT_MODEL and view.source != "env":
        # 被环境变量指定时回到的是环境变量的值，不必查代码里的默认模型（积压小问题 F17）
        await services.models.require_chat(services.app_settings.default(key))
    return await services.app_settings.reset(key)


def _catalog(services: Services) -> SkillCatalog:
    catalog = services.agent.skill_catalog
    if catalog is None:
        raise NotFoundError("没有配置技能目录")
    return catalog


@settings_router.post("/reload")
async def reload(services: ServicesDep) -> ReloadResult:
    """重读 MCP 服务清单与审批规则、重连 MCP 服务、刷新模型信息。"""
    await services.integrations.reload()
    return ReloadResult(servers=_servers(services), approvals=_approvals(services))


def _servers(services: Services) -> McpServersView:
    return McpServersView(
        servers=services.integrations.server_views(),
        config_error=services.integrations.current_error(),
    )


def _approvals(services: Services) -> ApprovalSettingsView:
    rules = services.integrations.rules
    return ApprovalSettingsView(
        mcp_default=rules.mcp_default,
        rules=[ApprovalRuleView(tool=tool, action=action) for tool, action in rules.tools.items()],
        tools=services.agent.tool_approvals(),
    )
