"""外部集成的配置文件（设计文档 7.2、7.5）：MCP 服务清单与工具审批规则。

两个文件都在 .workdata/config/ 里（D22，只有这一份，不再叠加 config/ 里的），可以在 MCP 页上改，
也可以手改后点"重新加载"，所以不放进 Settings。读取出错时抛 InvalidConfigError，消息直接给用户看。
加载是纯函数（参数是文件读出的内容）：页面修改前先在内存里改好、校验，合规才写文件。
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from common.errors import InvalidConfigError
from config.settings import ROOT_DIR

type ApprovalMode = Literal["auto", "ask"]

_SERVER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DOUBLE_BEARER = re.compile(r"^\s*bearer\s+bearer\s+", re.IGNORECASE)
# 由加载函数填写、不能出现在配置文件里的字段
_LOADER_FIELDS = ("name", "missing_env")

# .workdata/config 里各配置文件的当前格式版本（设计 2026-10-23 7.3）：没写 version 的当作 0，
# 启动时逐步迁移到这里的版本；改了某个文件的格式就加一，并在 backend/settings/seed.py 补迁移步骤
CONFIG_VERSIONS = {"mcp_servers.yaml": 1, "approval_rules.yaml": 1, "skills.yaml": 1}


class McpServerConfig(BaseModel):
    """一个 MCP 服务。

    name 同时是它的工具名前缀：files 服务的 write_file 工具叫 files_write_file。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_SERVER_NAME.pattern)
    description: str = ""
    enabled: bool = True
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    # 本地进程型（标准输入输出方式）
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    # 网络型
    url: str | None = None
    headers: dict[str, str] = {}
    connect_timeout: float = Field(default=60, gt=0)  # 首次 npx 要下载服务包，较慢
    call_timeout: float = Field(default=60, gt=0)  # 一次工具调用最多等多久
    missing_env: list[str] = []  # 引用了但没有设置的环境变量：这个服务不启动，设置页显示原因

    @model_validator(mode="after")
    def _connection_is_complete(self) -> "McpServerConfig":
        if self.transport == "stdio" and not self.command:
            raise ValueError("command 必填（标准输入输出方式要写启动命令）")
        if self.transport != "stdio" and not self.url:
            raise ValueError("url 必填（网络方式要写服务地址）")
        return self


class ApprovalRulesConfig(BaseModel):
    """工具审批规则：tools 按文件里的顺序匹配（支持 * 通配），第一条匹配的为准。"""

    model_config = ConfigDict(extra="forbid")

    tools: dict[str, ApprovalMode] = {}
    mcp_default: ApprovalMode = "ask"


def load_mcp_servers(
    data: dict[str, Any], env: Mapping[str, str], *, label: str
) -> list[McpServerConfig]:
    """服务清单文件的内容 → 服务列表，按 env 替换 ${名字}；label 是文件在报错里的显示名。"""
    result: list[McpServerConfig] = []
    for name, raw in raw_mcp_servers(data, label=label).items():
        missing: list[str] = []
        # 说明只给页面看：里面的 ${X} 原样留着，不当成要的变量、也不把密钥填进去（积压小问题 E12）
        described = {key: value for key, value in raw.items() if key != "description"}
        substituted = {**_substitute(described, env, missing), **_description(raw)}
        if isinstance(headers := substituted.get("headers"), dict):
            substituted["headers"] = {
                key: dedupe_bearer(value) if isinstance(value, str) else value
                for key, value in headers.items()
            }
        result.append(
            _validate(McpServerConfig, {**substituted, "name": name, "missing_env": missing}, label)
        )
    return result


def blanked_hint(names: Sequence[str], env: Mapping[str, str]) -> str:
    """缺的变量其实设了、只是空值（网关专用的密钥在后端被置空）时补的一句（积压小问题 E17）。"""
    if any(name in env and not env[name] for name in names):
        return "；也可能是网关专用、在后端被置空的变量，给 MCP 用请在 .env 另起一个名字"
    return ""


def _description(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {"description": raw["description"]} if "description" in raw else {}


def dedupe_bearer(value: str) -> str:
    """令牌变量里已经带了 Bearer、模板里又写了一个：去掉重复的那个（设计 2026-10-23 5.8）。"""
    return _DOUBLE_BEARER.sub("Bearer ", value)


def raw_mcp_servers(data: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    """替换 ${变量} 之前的原文：页面编辑时用它，密钥引用不会变成真实的值。"""
    servers = _servers_section(data, label)
    return {name: dict(_server_entry(name, raw, label)) for name, raw in servers.items()}


def is_server_name(name: str) -> bool:
    """服务名规则：小写字母开头，只用小写字母、数字和下划线（也是工具名前缀）。"""
    return bool(_SERVER_NAME.match(name))


def display_path(path: Path) -> str:
    """文件在项目里的位置（如 .workdata/config/mcp_servers.yaml），报错时给用户看。"""
    return _display(path)


def read_config_yaml(path: Path) -> dict[str, Any]:
    """读一份配置文件的原文（不存在时为空）；写错时抛 InvalidConfigError。"""
    return _read_yaml(path)


def leading_comments(text: str) -> str:
    """开头连续的注释、空行与 "---"（含换行）：页面保存配置文件时原样留着（积压小问题 F8）；
    遇到第一行内容就停，行尾的注释与正文里的注释不算。"""
    lines = text.splitlines(keepends=True)
    head = 0
    while head < len(lines) and is_preamble_line(lines[head]):
        head += 1
    return "".join(lines[:head])


def is_preamble_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#") or stripped == "---"


def config_version(data: Mapping[str, Any], *, label: str = "配置文件") -> int:
    """配置文件内容的格式版本：没写 version 的是 0；写的不是非负整数时抛 InvalidConfigError。"""
    version = data.get("version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise InvalidConfigError(f"{label} 有误：version 应是整数")
    return version


def _servers_section(data: dict[str, Any], label: str) -> dict[Any, Any]:
    servers = data.get("servers") or {}
    if not isinstance(servers, dict):
        raise InvalidConfigError(f"{label} 有误：servers 下应是“服务名: 配置”的列表")
    for name in servers:
        if not isinstance(name, str) or not _SERVER_NAME.match(name):
            raise InvalidConfigError(
                f"{label} 有误：服务名“{name}”只能用小写字母、数字和下划线，且以字母开头"
            )
    return servers


def _server_entry(name: str, raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidConfigError(f"{label} 有误：{name} 的配置应是一组“字段: 值”")
    for field in _LOADER_FIELDS:
        if field in raw:
            raise InvalidConfigError(f"{label} 有误：{name}.{field} 不认识的字段")
    return raw


def load_approval_rules(data: dict[str, Any], *, label: str) -> ApprovalRulesConfig:
    """审批规则文件的内容 → 规则；文件不存在（内容为空）时用默认规则。"""
    return _validate(ApprovalRulesConfig, _rules_data(data), label)


def _rules_data(data: dict[str, Any]) -> dict[str, Any]:
    # 格式版本只给启动时的迁移看；"tools:" 下面只有注释时当作没有规则
    return {k: v for k, v in data.items() if k != "version" and not (k == "tools" and v is None)}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise InvalidConfigError(f"{_display(path)} 有误：不是 UTF-8 文字，请另存为 UTF-8") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"第 {mark.line + 1} 行" if mark is not None else "格式"
        raise InvalidConfigError(f"{_display(path)} 有误：{where}不是合法的 YAML") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise InvalidConfigError(f"{_display(path)} 有误：最外层应是一组“字段: 值”")
    return data


def _substitute(value: Any, env: Mapping[str, str], missing: list[str]) -> Any:
    """替换字符串里的 ${名字}；没有的名字原样保留并记下（去重、按出现顺序）。"""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if env.get(name):  # 空值算没设置（积压小问题 E17：网关专用的密钥在后端被置空）
                return env[name]
            if name not in missing:
                missing.append(name)
            return match.group(0)

        return _ENV_REFERENCE.sub(replace, value)
    if isinstance(value, list):
        return [_substitute(item, env, missing) for item in value]
    if isinstance(value, dict):
        return {k: _substitute(v, env, missing) for k, v in value.items()}
    return value


_MESSAGES = {
    "extra_forbidden": "不认识的字段",
    "missing": "必填",
    "literal_error": "取值不对",
    "string_type": "应是文字",
    "bool_type": "应是 true 或 false",
    "list_type": "应是列表",
    "dict_type": "应是一组“名字: 值”",
    "greater_than": "应大于 0",
    "float_parsing": "应是数字",
}


def _validate[T: BaseModel](model: type[T], data: dict[str, Any], label: str) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        if isinstance(data.get("name"), str):
            where = ".".join(part for part in (data["name"], where) if part)
        message = _MESSAGES.get(error["type"]) or str(error["msg"]).removeprefix("Value error, ")
        if error["type"] == "literal_error":
            choices = str(error["ctx"]["expected"]).replace(" or ", "、").replace(", ", "、")
            message = f"{message}（只能是 {choices}）"
        raise InvalidConfigError(f"{label} 有误：{where}：{message}") from exc


def _display(path: Path) -> str:
    """出错的文件在项目里的位置（如 config/mcp_servers.yaml）。"""
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)
