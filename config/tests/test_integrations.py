import re
from pathlib import Path

import pytest

from common.errors import InvalidConfigError
from config import (
    ApprovalRulesConfig,
    McpServerConfig,
    config_version,
    display_path,
    leading_comments,
    load_approval_rules,
    load_mcp_servers,
    read_config_yaml,
)
from config.settings import SEED_DIR

SEED_CONFIG = SEED_DIR / "files" / "config"


def _write(tmp_path: Path, text: str, name: str = "mcp_servers.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _servers(path: Path, env: dict[str, str]) -> list[McpServerConfig]:
    return load_mcp_servers(read_config_yaml(path), env, label=display_path(path))


def _rules(path: Path) -> ApprovalRulesConfig:
    return load_approval_rules(read_config_yaml(path), label=display_path(path))


def test_loads_servers_and_substitutes_env(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "servers:\n  files:\n    command: npx\n    args: ['-y', 'pkg@1.0.0', '${SHARED}']\n",
    )
    [server] = _servers(path, {"SHARED": "/shared"})
    assert (server.name, server.transport, server.args[-1], server.missing_env) == (
        "files",
        "stdio",
        "/shared",
        [],
    )


def test_missing_env_is_recorded_not_raised(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "servers:\n  github:\n    transport: streamable_http\n    url: https://example.com/mcp/\n"
        "    headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' }\n",
    )
    [server] = _servers(path, {})
    assert server.missing_env == ["GITHUB_TOKEN"]
    assert server.headers["Authorization"] == "Bearer ${GITHUB_TOKEN}"


def test_duplicated_bearer_is_collapsed(tmp_path: Path) -> None:
    """令牌变量里已经带了 Bearer：替换后成了"Bearer Bearer …"时去掉一个（设计 2026-10-23 5.8）。"""
    path = _write(
        tmp_path,
        "servers:\n  github:\n    transport: streamable_http\n    url: https://example.com/mcp/\n"
        "    headers: { Authorization: 'Bearer ${GITHUB_TOKEN}' }\n",
    )
    [server] = _servers(path, {"GITHUB_TOKEN": "Bearer abc"})
    assert server.headers["Authorization"] == "Bearer abc"
    [lower] = _servers(path, {"GITHUB_TOKEN": "bearer  abc"})
    assert lower.headers["Authorization"] == "Bearer abc"
    [plain] = _servers(path, {"GITHUB_TOKEN": "abc"})
    assert plain.headers["Authorization"] == "Bearer abc"


def test_stdio_without_command_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "servers:\n  files:\n    args: ['x']\n")
    with pytest.raises(InvalidConfigError, match="command"):
        _servers(path, {})


def test_http_without_url_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "servers:\n  remote:\n    transport: sse\n")
    with pytest.raises(InvalidConfigError, match="url"):
        _servers(path, {})


@pytest.mark.parametrize(
    "text", ["servers:\n  files:\n    comand: npx\n", "servers: [\n"], ids=["typo", "yaml"]
)
def test_unknown_field_and_bad_yaml_are_errors(tmp_path: Path, text: str) -> None:
    path = _write(tmp_path, text)
    with pytest.raises(InvalidConfigError, match=r"mcp_servers\.yaml"):
        _servers(path, {})


def test_bad_server_name_is_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "servers:\n  My Server:\n    command: npx\n")
    with pytest.raises(InvalidConfigError, match="My Server"):
        _servers(path, {})


def test_missing_files_mean_nothing_configured(tmp_path: Path) -> None:
    assert _servers(tmp_path / "none.yaml", {}) == []
    assert _rules(tmp_path / "none.yaml") == ApprovalRulesConfig()


def test_rules_keep_file_order(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "tools:\n  'files_*': auto\n  files_write_file: ask\n",
        name="approval_rules.yaml",
    )
    rules = _rules(path)
    assert list(rules.tools.items()) == [("files_*", "auto"), ("files_write_file", "ask")]
    assert rules.mcp_default == "ask"


def test_rule_values_are_auto_or_ask(tmp_path: Path) -> None:
    path = _write(tmp_path, "tools:\n  execute: 'yes'\n", name="approval_rules.yaml")
    with pytest.raises(InvalidConfigError, match=r"approval_rules\.yaml"):
        _rules(path)


def test_rules_file_may_carry_a_version() -> None:
    rules = load_approval_rules({"version": 1, "tools": {"a_*": "auto"}}, label="审批规则")
    assert rules.tools == {"a_*": "auto"}


def test_config_version_must_be_a_whole_number() -> None:
    assert (config_version({}), config_version({"version": 1})) == (0, 1)
    for bad in ("1", True, -1, 1.5):
        with pytest.raises(InvalidConfigError, match=re.escape("x.yaml 有误：version 应是整数")):
            config_version({"version": bad}, label="x.yaml")


def test_file_not_in_utf8_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "skills.yaml"
    path.write_bytes("disabled:\n- 表格\n".encode("gbk"))
    with pytest.raises(
        InvalidConfigError, match=re.escape("有误：不是 UTF-8 文字，请另存为 UTF-8")
    ):
        read_config_yaml(path)


def test_seed_config_files_load() -> None:
    """首次启动写入的默认文件（D22）：files 服务、默认先问。"""
    servers = _servers(SEED_CONFIG / "mcp_servers.yaml", {})
    assert [server.name for server in servers] == ["files"]
    assert servers[0].args[-1] == "/shared"
    rules = _rules(SEED_CONFIG / "approval_rules.yaml")
    assert (rules.mcp_default, rules.tools) == ("ask", {})


def test_seed_rule_examples_work_when_uncommented(tmp_path: Path) -> None:
    """按文件开头的例子在 tools 下加那一行就能用（审查 Minor 11：原来的例子去掉 # 后与
    tools: {} 冲突；例子挪到开头见积压小问题 F8）。"""
    text = (SEED_CONFIG / "approval_rules.yaml").read_text(encoding="utf-8")
    example = re.search(r"加一行 (\S+: \w+)", text)
    assert example is not None
    added = text.replace("tools:\n", f"tools:\n  {example.group(1)}\n")
    path = _write(tmp_path, added, name="approval_rules.yaml")
    assert list(_rules(path).tools) == ["files_write_file"]


def test_seed_server_example_works_when_moved_under_servers(tmp_path: Path) -> None:
    """MCP 服务的例子去掉行首的 # 放到 servers 下就能用（积压小问题 F8：例子挪到了开头）。"""
    text = (SEED_CONFIG / "mcp_servers.yaml").read_text(encoding="utf-8")
    example = [line[2:] for line in text.splitlines() if line.startswith("#   ")]
    added = text.replace("servers:\n", "servers:\n" + "\n".join(example) + "\n")
    servers = _servers(_write(tmp_path, added), {"GITHUB_TOKEN": "t"})
    assert [server.name for server in servers] == ["github", "files"]


def test_mcp_servers_come_only_from_workdata() -> None:
    """只有 .workdata 里的一份（D22）：不再有"自带"，写了 builtin 字段就是不认识的字段。"""
    [memo] = load_mcp_servers({"servers": {"memo": {"command": "echo"}}}, {}, label="x")
    assert memo.name == "memo"
    assert "builtin" not in type(memo).model_fields
    with pytest.raises(InvalidConfigError, match="不认识的字段"):
        load_mcp_servers({"servers": {"memo": {"command": "echo", "builtin": True}}}, {}, label="x")


@pytest.mark.parametrize("name", ["mcp_servers.yaml", "approval_rules.yaml"])
def test_seed_examples_are_in_the_header(name: str) -> None:
    """默认文件里的说明与示例都写在开头的注释段（积压小问题 F8）：页面保存时只保留开头的注释，
    写在正文里的会丢。"""
    lines = (SEED_CONFIG / name).read_text(encoding="utf-8").splitlines()
    head = len(leading_comments("\n".join(lines)).splitlines())
    assert head > 0
    assert [line for line in lines[head:] if "#" in line] == []


def test_leading_comments_stop_at_the_first_yaml_line() -> None:
    text = "# 说明一\n\n# 说明二\nversion: 1  # 行尾的不算\n# 正文里的\nservers: {}\n"
    assert leading_comments(text) == "# 说明一\n\n# 说明二\n"
    assert leading_comments("version: 1\n") == ""


def test_description_is_not_substituted(tmp_path: Path) -> None:
    """说明里写的 ${X} 原样保留（积压小问题 E12）：不当成要的环境变量，
    也不把密钥填进页面上的说明。"""
    text = "servers:\n  gh:\n    command: npx\n    description: 用 ${GH_TOKEN} 登录的 GitHub\n"
    [server] = _servers(_write(tmp_path, text), {"GH_TOKEN": "ghp_secret"})
    assert server.description == "用 ${GH_TOKEN} 登录的 GitHub"
    assert server.missing_env == []


def test_empty_variable_counts_as_missing(tmp_path: Path) -> None:
    """设成空值的变量算没设置（积压小问题 E17：网关专用的密钥在后端被置成空，
    服务照常启动却用不了）。"""
    text = "servers:\n  oa:\n    command: npx\n    env:\n      KEY: ${OPENAI_API_KEY}\n"
    [server] = _servers(_write(tmp_path, text), {"OPENAI_API_KEY": ""})
    assert server.missing_env == ["OPENAI_API_KEY"]
