"""读取两个集成配置文件、交给智能体，并记下出错原因（设计文档 12.1 的设置接口）。

两个文件都在 .workdata/config/ 里（D22，只有这一份）。MCP 页的修改也在这里，流程统一为
"在内存里改 → 校验 → 在锁与"正在重连"里查有没有对话在进行 → 写文件 → 让智能体生效"，
不合规就在写文件之前拒绝，文件原样保留。
"""

import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import ValidationError

from agents.main_agent.integrations import McpProbeResult
from agents.main_agent.runtime import MainAgent
from backend.runs import RunRepo
from backend.settings.schemas import McpServerInput, McpServerView
from backend.settings.store import UserConfigFiles
from common.errors import (
    ConflictError,
    InvalidConfigError,
    InvalidRequestError,
    NotFoundError,
    UpstreamError,
)
from config import (
    ApprovalRulesConfig,
    McpServerConfig,
    Settings,
    blanked_hint,
    display_path,
    is_server_name,
    load_approval_rules,
    load_mcp_servers,
    raw_mcp_servers,
)
from config.integrations import ApprovalMode

logger = logging.getLogger(__name__)

SERVERS = "mcp_servers.yaml"
RULES = "approval_rules.yaml"
_SERVER_NAME_RULE = "只能用小写字母、数字和下划线，且以字母开头"

type Entries = dict[str, Any]


class IntegrationSettings:
    def __init__(self, settings: Settings, agent: MainAgent, runs: RunRepo) -> None:
        self._settings = settings
        self._agent = agent
        self._runs = runs
        self._user = UserConfigFiles(settings.config_dir)
        # 启动时的连接与"重新加载"不能同时进行（MCP 客户端一次只换一套连接）
        self._lock = asyncio.Lock()
        self.rules = ApprovalRulesConfig()
        self.servers: list[McpServerConfig] = []
        self.config_error: str | None = None  # 配置文件写错的原因，设置页显示

    async def load(self) -> None:
        """启动时调用：读配置文件、连接 MCP 服务。配置文件写错时记下原因，用空配置，不抛出。"""
        async with self._lock:
            try:
                servers, rules = self._read()
                self.config_error = None
            except InvalidConfigError as exc:
                logger.warning("集成配置有误，先不接入 MCP 服务：%s", exc)
                servers, rules = [], ApprovalRulesConfig()
                self.config_error = str(exc)
            try:
                await self._agent.reload_integrations(servers, rules)
            except Exception:  # 后台任务边界：连接出意外也不能影响服务本身
                logger.exception("启动时接入 MCP 服务失败")
            self.servers, self.rules = servers, rules

    async def reload(self) -> None:
        """MCP 页的"重新加载"：重读两个文件、重连 MCP 服务、刷新模型信息。

        有运行正在进行时拒绝（重连会关掉它正在用的 MCP 连接）；文件写错时抛出，旧配置继续生效。
        """
        # 在锁与"正在重连"里先查有没有对话在进行：查完之后发起的运行等重连完再开始（积压小问题 E10）
        async with self._lock, self._agent.reconnecting():
            if await self._runs.count_running():
                raise ConflictError("有对话正在进行，等它结束或停止后再重新加载")
            # 在锁里读：等前一个修改连完再读，拿到的是最新的文件
            servers, rules = self._read()
            await self._agent.reload_integrations(servers, rules)
            self.servers, self.rules = servers, rules
            self.config_error = None
        try:
            await self._agent.models.list_models()
        except UpstreamError:
            logger.warning("重新加载时模型网关不可用，模型信息沿用之前的")

    # ---- MCP 页的修改 ----

    async def add_servers(self, inputs: list[McpServerInput]) -> None:
        """一次加入多个服务（粘贴 JSON 时）：有一个不行就一个都不加。"""
        existing = set(self._raw_servers())
        for item in inputs:
            _check_name(item.name)
            if item.name in existing:
                raise ConflictError(f"已有同名服务：{item.name}")
            existing.add(item.name)

        def change(servers: Entries, rules: Entries) -> None:
            for item in inputs:
                servers[item.name] = item.entry()

        await self._change(change)

    async def update_server(self, name: str, item: McpServerInput) -> None:
        """改一个服务：表单里的字段写进条目，表单里没有的字段（如超时）保留。"""
        if item.name != name:
            raise InvalidRequestError("服务名不能改：它也是工具名的前缀，审批规则按它对应")
        self._require(name)

        def change(servers: Entries, rules: Entries) -> None:
            servers[name] = {**(servers.get(name) or {}), **item.entry()}

        await self._change(change)

    async def set_server_enabled(self, name: str, enabled: bool) -> None:
        """停用 = 断开连接、配置保留；启用时去掉 enabled 字段（默认就是启用）。"""
        self._require(name)

        def change(servers: Entries, rules: Entries) -> None:
            entry = {**(servers.get(name) or {}), "enabled": enabled}
            if enabled:
                entry.pop("enabled")
            servers[name] = entry

        await self._change(change)

    async def remove_server(self, name: str) -> None:
        """删除一个服务（任何服务都能删，D22），连同它的工具的审批规则。"""
        self._require(name)

        def change(servers: Entries, rules: Entries) -> None:
            servers.pop(name, None)
            # 名字更长的服务（删 files 时的 files_backup）的工具也以"files_"开头：它们的规则留着
            # （积压小问题 E14）
            longer = [other for other in servers if other.startswith(f"{name}_")]
            for tool in [tool for tool in rules if _owned_by(tool, name, longer)]:
                del rules[tool]

        await self._change(change)

    async def set_tool_action(self, tool: str, action: ApprovalMode) -> None:
        """改一个工具的"自动 / 先问"：只换审批规则、不重连，有对话在进行也可以改。

        也要拿锁：重连进行中改了规则，重连结束时不能被它手里那份旧规则盖回去（审查 Important 5）。
        """
        if tool == "execute":
            raise InvalidRequestError("执行命令固定先问，不能改")
        async with self._lock:
            user = self._user.read(RULES)
            candidate = {**user, "tools": {**(user.get("tools") or {}), tool: action}}
            rules = load_approval_rules(candidate, label=self._label(RULES))
            self._user.write(RULES, candidate)
            self._agent.update_rules(rules)
            self.rules = rules

    async def probe(self, item: McpServerInput) -> McpProbeResult:
        """测试连接（不保存）；缺环境变量时不去连，直接说清楚要设置哪个。"""
        _check_name(item.name)
        [config] = load_mcp_servers(
            {"servers": {item.name: item.entry()}}, os.environ, label="表单"
        )
        if config.missing_env:
            names = "、".join(config.missing_env)
            return McpProbeResult(
                ok=False,
                error=f"缺少环境变量 {names}：在 .env 里设置后执行 make restart"
                f"（重建后端容器才会读到）{blanked_hint(config.missing_env, os.environ)}",
            )
        return await self._agent.probe_mcp(config)

    def server_views(self) -> list[McpServerView]:
        """智能体那边的连接状态，加上编辑用的原文（未替换 ${变量}）。"""
        try:
            raw = self._raw_servers()
        except InvalidConfigError:
            raw = {}  # 文件写坏时只显示状态，原因在 config_error 里
        configs = {server.name: server for server in self.servers}
        views: list[McpServerView] = []
        for status in self._agent.mcp_servers():
            config = configs.get(status.name)
            try:
                form = McpServerInput.from_raw(status.name, raw.get(status.name, {}))
            except ValidationError:
                form = McpServerInput(name=status.name)  # 手改写错了：原因在 config_error 里
            views.append(
                McpServerView(
                    **status.model_dump(),
                    missing_env=config.missing_env if config else [],
                    config=form,
                )
            )
        return views

    def current_error(self) -> str | None:
        """现读一次两份配置文件：启动后才手改坏的也能在页面上看到原因。"""
        try:
            self._read()
        except InvalidConfigError as exc:
            return str(exc)
        if self.config_error:
            return f"{self.config_error}（文件已改好，点“重新加载”生效）"
        return None

    # ---- 内部 ----

    def _label(self, name: str) -> str:
        return display_path(self._user.path(name))

    def _raw_servers(self) -> dict[str, Entries]:
        return raw_mcp_servers(self._user.read(SERVERS), label=self._label(SERVERS))

    def _require(self, name: str) -> None:
        if name not in self._raw_servers():
            raise NotFoundError(f"没有这个服务：{name}")

    async def _change(self, change: Callable[[Entries, Entries], None]) -> None:
        """要重连的修改：先在内存里改两份文件、校验，再看有没有对话在进行，然后写入、重连。"""
        user_servers, user_rules = self._user.read(SERVERS), self._user.read(RULES)
        servers = dict(user_servers.get("servers") or {})
        rules = dict(user_rules.get("tools") or {})
        change(servers, rules)
        rules_changed = rules != (user_rules.get("tools") or {})
        new_servers = {**user_servers, "servers": servers}
        new_rules = {**user_rules, "tools": rules}
        configs = load_mcp_servers(new_servers, os.environ, label=self._label(SERVERS))
        new_rule_config = load_approval_rules(new_rules, label=self._label(RULES))
        # 在锁与"正在重连"里查运行数：查完之后发起的运行等重连完再开始（积压小问题 E10）
        async with self._lock, self._agent.reconnecting():
            if await self._runs.count_running():
                raise ConflictError("有对话正在进行，等它结束或停止后再改")
            self._user.write(SERVERS, new_servers)
            if rules_changed:
                self._user.write(RULES, new_rules)
            # 锁里重读规则文件：校验之后、拿到锁之前别的请求可能改过它
            new_rule_config = self._read()[1]
            await self._agent.reload_integrations(configs, new_rule_config)
            self.servers, self.rules = configs, new_rule_config
            self.config_error = None

    def _read(self) -> tuple[list[McpServerConfig], ApprovalRulesConfig]:
        servers = load_mcp_servers(self._user.read(SERVERS), os.environ, label=self._label(SERVERS))
        rules = load_approval_rules(self._user.read(RULES), label=self._label(RULES))
        return servers, rules


def _owned_by(tool: str, server: str, longer: Sequence[str]) -> bool:
    """工具名（规则的键）是不是这个服务的：以"服务名_"开头、又不属于名字更长的服务。"""
    if not tool.startswith(f"{server}_"):
        return False
    return not any(tool.startswith(f"{other}_") for other in longer)


def _check_name(name: str) -> None:
    if not is_server_name(name):
        raise InvalidRequestError(f"服务名“{name}”{_SERVER_NAME_RULE}")
