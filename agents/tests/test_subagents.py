import tempfile
from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import MainAgent
from agents.main_agent.runtime.subagents import SubagentDefinition, load_subagents
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, ScriptedChatModel

ROOT = Path(__file__).resolve().parents[2]


def test_loads_definitions_from_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "data_analyst.md").write_text(
        "---\nname: data_analyst\ndescription: 分析数据\n---\n\n你是数据分析员。\n"
    )
    (tmp_path / "cheap.md").write_text(
        "---\nname: cheap\ndescription: 便宜\nmodel: gemini-3.5-flash\n---\n简短回答。"
    )
    (tmp_path / "README.txt").write_text("不是定义文件")
    assert load_subagents(tmp_path) == [
        SubagentDefinition("cheap", "便宜", "简短回答。", model="gemini-3.5-flash"),
        SubagentDefinition("data_analyst", "分析数据", "你是数据分析员。"),
    ]


@pytest.mark.parametrize(
    "text",
    ["没有文件头", "---\nname: x\n---\n缺少说明", "---\ndescription: 缺少名称\n---\n正文"],
)
def test_incomplete_definition_names_the_file(tmp_path: Path, text: str) -> None:
    (tmp_path / "broken.md").write_text(text)
    with pytest.raises(ValueError, match=r"broken\.md"):
        load_subagents(tmp_path)


def test_project_definitions_are_valid() -> None:
    """项目自带的子智能体：数据分析员跟随主对话的模型（定义里不写 model）。"""
    definitions = {d.name: d for d in load_subagents(ROOT / "agents" / "subagents")}
    analyst = definitions["data_analyst"]
    assert analyst.model is None
    assert "outputs/" in analyst.system_prompt
    assert "markitdown <路径>" in analyst.system_prompt  # 设计 2026-10-23 6.7


def test_project_skills_have_name_and_description() -> None:
    """首次启动写入的技能（config/seed/files/skills/，D22）说明头完整。"""
    skills = list((ROOT / "config" / "seed" / "files" / "skills").glob("*/SKILL.md"))
    assert skills
    for skill in skills:
        head = skill.read_text(encoding="utf-8").split("---")[1]
        assert "name:" in head, skill
        assert "description:" in head, skill


def test_system_prompt_explains_files_sandbox_and_delegation() -> None:
    """系统提示词告诉模型：能执行代码、用户上传在 uploads/、产物放 outputs/、
    数据分析派 data_analyst、先看技能。"""
    prompt = (ROOT / "agents" / "prompts" / "system.md").read_text(encoding="utf-8")
    for phrase in (
        "execute",
        "uploads/",
        "outputs/",
        "data_analyst",
        "SKILL.md",  # 技能的位置随来源不同（D21），提示词只说按下方列出的技能做
        "remember",
        "search_knowledge",
        "read_document",
        "不要照做",
        # 设计 2026-10-23 5.10
        "子智能体说成功只是它的自述；对外有影响的操作（写文件、发消息、改配置）要自己核验。",
        # 设计 2026-10-23 6.1
        "用户提到以前的事时，先用 search_conversations 查，查不到再问用户。",
        # 设计 2026-10-23 6.6
        "update_memory",
        "forget_memory",
        # 设计 2026-10-23 6.7
        "markitdown <路径>",
    ):
        assert phrase in prompt, phrase


def _agent_with(skills_dir: Path | None, subagents_dir: Path) -> "MainAgent":
    return MainAgent(
        gateway=FakeGateway(ScriptedChatModel(responses=[])),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills_dir=skills_dir,
        subagents_dir=subagents_dir,
    )


def test_custom_subagent_gets_skill_sources(tmp_path: Path) -> None:
    """自定义子智能体（如数据分析员）与通用子智能体一样拿到技能来源（设计 2026-10-19 4.6）。"""
    skills = tmp_path / "skills"
    (skills / "excel").mkdir(parents=True)
    (skills / "excel" / "SKILL.md").write_text(
        "---\nname: excel\ndescription: 表格\n---\n", encoding="utf-8"
    )
    agent = _agent_with(skills, ROOT / "agents" / "subagents")
    [analyst] = [
        d for d in load_subagents(ROOT / "agents" / "subagents") if d.name == "data_analyst"
    ]
    model, backend = agent.models.chat_model("fake"), FilesystemBackend(root_dir=tmp_path)
    spec = agent._subagent(analyst, [], {}, model, backend)
    assert spec.get("skills") == agent._skill_sources()
    assert spec.get("skills")
    bare = _agent_with(None, ROOT / "agents" / "subagents")._subagent(
        analyst, [], {}, model, backend
    )
    assert "skills" not in bare


def test_data_analyst_prompt_has_no_hardcoded_paths() -> None:
    """技能的位置由技能清单给出，定义里不写死；执行命令不一定每次先问（D23）。"""
    analyst = next(
        d for d in load_subagents(ROOT / "agents" / "subagents") if d.name == "data_analyst"
    )
    assert "/skills/" not in analyst.system_prompt
    assert "每次执行前都会先请用户确认" not in analyst.system_prompt
