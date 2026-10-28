"""智能体技能（设计文档 7.4）：列出技能；新加的技能在老会话里也能用上。"""

import re
import stat
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.runtime import MainAgent, SkillCatalog, SkillPackage, list_skills
from agents.main_agent.runtime.files import SkillsFilesystem
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, ScriptedChatModel
from common.errors import ConflictError, InvalidConfigError, NotFoundError

SHORT = "c_000000b1"


def _skill(root: Path, folder: str, head: str) -> None:
    (root / folder).mkdir(parents=True)
    (root / folder / "SKILL.md").write_text(f"---\n{head}\n---\n\n正文\n", encoding="utf-8")


def test_lists_skills_with_name_and_description(tmp_path: Path) -> None:
    _skill(tmp_path, "b", "name: beta\ndescription: 第二个")
    _skill(tmp_path, "a", "name: alpha\ndescription: 第一个")
    skills = list_skills(tmp_path)
    assert [(s.name, s.description, s.error) for s in skills] == [
        ("alpha", "第一个", None),
        ("beta", "第二个", None),
    ]


@pytest.mark.parametrize(
    ("length", "notice"),
    [
        (300, None),
        (301, "说明有 301 字，说明尽量短：每次对话智能体都要读一遍所有技能的说明"),
        (1024, "说明有 1024 字，说明尽量短：每次对话智能体都要读一遍所有技能的说明"),
        (1025, "说明有 1025 字，超过 1024 字的部分会被截断：智能体只读前 1024 字"),
    ],
)
def test_long_description_gets_a_notice(tmp_path: Path, length: int, notice: str | None) -> None:
    _skill(tmp_path, "long", f"name: long\ndescription: {'字' * length}")
    [skill] = list_skills(tmp_path)
    assert skill.notice == notice


def test_uploaded_skill_comes_back_with_its_notice(tmp_path: Path) -> None:
    text = f"---\nname: long\ndescription: {'字' * 400}\n---\n正文\n"
    package = SkillPackage(name="long", description="字" * 400, files={"SKILL.md": text.encode()})
    info = SkillCatalog(tmp_path).install(package)
    assert info.notice == "说明有 400 字，说明尽量短：每次对话智能体都要读一遍所有技能的说明"


def test_broken_skill_is_listed_with_reason(tmp_path: Path) -> None:
    _skill(tmp_path, "half", "name: half")
    [skill] = list_skills(tmp_path)
    assert skill.name == "half"
    assert "说明头不完整" in (skill.error or "")


def test_no_skills_dir_means_no_skills(tmp_path: Path) -> None:
    assert list_skills(None) == []
    assert list_skills(tmp_path / "none") == []


async def test_new_skill_is_seen_by_existing_thread(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _skill(skills, "excel", "name: excel\ndescription: 处理表格")
    model = ScriptedChatModel(responses=[AIMessage(content="一"), AIMessage(content="二")])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills_dir=skills,
    )
    for run_id, message in (("r1", "你好"), ("r2", "再来")):
        if run_id == "r2":
            _skill(skills, "slides", "name: slides\ndescription: 做幻灯片")
        async for _ in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id=run_id, message=message, model="fake"
        ):
            pass
    system = str(model.received[-1][0].content)
    assert "slides" in system


def test_skill_without_closing_marker_or_not_utf8_is_listed_with_reason(tmp_path: Path) -> None:
    """说明头少了结束的 ---、文件不是 UTF-8：照样列出并写明原因，不让设置页报错（审查 Minor 4）。"""
    (tmp_path / "open").mkdir()
    (tmp_path / "open" / "SKILL.md").write_text("---\nname: open\n", encoding="utf-8")
    (tmp_path / "gbk").mkdir()
    (tmp_path / "gbk" / "SKILL.md").write_bytes("---\nname: 表格\n---\n".encode("gbk"))
    skills = list_skills(tmp_path)
    assert [(s.name, bool(s.error)) for s in skills] == [("gbk", True), ("open", True)]
    assert "UTF-8" in (skills[0].error or "")


# ---- 管理页面：一个技能目录、停用清单（D22） ----


def _catalog(tmp_path: Path) -> SkillCatalog:
    skills = tmp_path / "skills"
    _skill(skills, "excel", "name: excel\ndescription: 处理表格")
    _skill(skills, "memo", "name: memo\ndescription: 记笔记")
    return SkillCatalog(skills, tmp_path / "config" / "skills.yaml")


def test_catalog_lists_one_directory(tmp_path: Path) -> None:
    """只有一个技能目录（D22）：首次写入的与上传的放在一起，按文件夹名排序。"""
    skills = _catalog(tmp_path).list()
    assert [(s.id, s.enabled) for s in skills] == [("excel", True), ("memo", True)]
    assert skills[0].location.endswith("skills/excel/")
    assert all(s.added_at is not None for s in skills)
    assert "origin" not in type(skills[0]).model_fields


def test_disabled_skill_is_hidden_from_the_agent_files(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    files = SkillsFilesystem(tmp_path / "skills", catalog.hidden)
    catalog.set_enabled("excel", False)
    assert "disabled" in (tmp_path / "config" / "skills.yaml").read_text(encoding="utf-8")
    assert all("excel" not in (entry["path"]) for entry in files.ls("/").entries or [])
    assert files.read("/excel/SKILL.md").error is not None
    assert [r.error is not None for r in files.download_files(["/excel/SKILL.md"])] == [True]
    catalog.set_enabled("excel", True)
    assert any("excel" in entry["path"] for entry in files.ls("/").entries or [])


async def test_disabled_skill_is_not_listed_for_the_agent(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog.set_enabled("memo", False)
    model = ScriptedChatModel(responses=[AIMessage(content="好")])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills=catalog,
    )
    async for _ in agent.run(
        thread_id="t1", thread_short_id=SHORT, run_id="r1", message="你好", model="fake"
    ):
        pass
    system = str(model.received[0][0].content)
    assert "处理表格" in system
    assert "记笔记" not in system


def test_install_rejects_same_name_ignoring_case(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    package = SkillPackage(name="Excel", description="x", files={"SKILL.md": b"---\n"})
    with pytest.raises(ConflictError, match="已有同名技能：Excel"):
        catalog.install(package)
    assert sorted(p.name for p in (tmp_path / "skills").iterdir()) == ["excel", "memo"]


def test_install_writes_folder_named_after_skill(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    text = b"---\nname: \xe5\x91\xa8\xe6\x8a\xa5\ndescription: d\n---\n"
    info = catalog.install(
        SkillPackage(name="周报", description="d", files={"SKILL.md": text, "a/b.py": b"x"})
    )
    assert info.id == "周报"
    assert (tmp_path / "skills" / "周报" / "a" / "b.py").read_bytes() == b"x"
    assert not [p for p in (tmp_path / "skills").iterdir() if p.name.startswith(".")]
    detail = catalog.detail("周报")
    assert detail.files == ["SKILL.md", "a/b.py"]


def test_remove_deletes_folder_and_state(tmp_path: Path) -> None:
    """任何技能都能删（D22），连同它在停用清单里的那一行。"""
    catalog = _catalog(tmp_path)
    catalog.set_enabled("excel", False)
    catalog.remove("excel")
    assert not (tmp_path / "skills" / "excel").exists()
    assert "excel" not in catalog.hidden()


def test_detail_has_body_without_front_matter(tmp_path: Path) -> None:
    detail = _catalog(tmp_path).detail("excel")
    assert (detail.body, detail.files) == ("正文", ["SKILL.md"])
    with pytest.raises(NotFoundError):
        _catalog(tmp_path / "again").detail("nope")


@pytest.mark.parametrize("text", ["disabled: [\n", "disabled: excel\n", "disabled: 5\n"])
async def test_broken_state_file_hides_nothing_and_agent_keeps_running(
    tmp_path: Path, text: str
) -> None:
    """skills.yaml 手改写坏了：什么都不隐藏、对话照常；改开关时才报原因（审查 Important 3）。"""
    catalog = _catalog(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "skills.yaml").write_text(text, encoding="utf-8")
    assert catalog.hidden() == frozenset()
    assert "skills.yaml" in (catalog.state_error() or "")
    model = ScriptedChatModel(responses=[AIMessage(content="好")])
    agent = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(Path(tempfile.mkdtemp()), FakeSandbox()),
        skills=catalog,
    )
    events = [
        e
        async for e in agent.run(
            thread_id="t1", thread_short_id=SHORT, run_id="r1", message="你好", model="fake"
        )
    ]
    assert getattr(events[-1], "status", None) == "completed"
    with pytest.raises(InvalidConfigError, match=r"skills\.yaml"):
        catalog.set_enabled("excel", False)


def test_description_length_ignores_surrounding_blanks(tmp_path: Path) -> None:
    """竖线块写的说明末尾带换行：按 deepagents 的算法先去掉首尾空白再量
    （积压小问题 F2，原来 300 字算成 301）。"""
    _skill(tmp_path, "long", f"name: long\ndescription: |\n  {'字' * 300}")
    [skill] = list_skills(tmp_path)
    assert (skill.description, skill.notice) == ("字" * 300, None)


def test_blank_description_is_incomplete(tmp_path: Path) -> None:
    """只有空格的说明 deepagents 会跳过这个技能（积压小问题 F2）：这里也算说明头不完整。"""
    _skill(tmp_path, "blank", "name: blank\ndescription: '  '")
    [skill] = list_skills(tmp_path)
    assert skill.error is not None
    assert "说明头不完整" in skill.error


def test_install_refuses_folder_without_skill_md(tmp_path: Path) -> None:
    """技能目录里已有同名文件夹但没有 SKILL.md（积压小问题 F5，原来改名失败 500）：
    说清楚，原文件夹不动。"""
    catalog = _catalog(tmp_path)
    leftover = tmp_path / "skills" / "周报"
    leftover.mkdir()
    (leftover / "notes.txt").write_text("留着", encoding="utf-8")
    package = SkillPackage(name="周报", description="d", files={"SKILL.md": b"---\n"})
    refused = re.escape("技能目录里已有同名文件夹 周报（里面没有 SKILL.md）")
    with pytest.raises(ConflictError, match=refused):
        catalog.install(package)
    assert (leftover / "notes.txt").read_text(encoding="utf-8") == "留着"
    assert not [p for p in (tmp_path / "skills").iterdir() if p.name.startswith(".")]


def test_disabled_skill_is_hidden_regardless_of_case(tmp_path: Path) -> None:
    """停用 excel 后，换大小写的路径也读不到（积压小问题 F7：.workdata 在 Mac 上不分大小写）。"""
    catalog = _catalog(tmp_path)
    files = SkillsFilesystem(tmp_path / "skills", catalog.hidden)
    catalog.set_enabled("excel", False)
    assert files.read("/EXCEL/SKILL.md").error is not None
    assert [r.error is not None for r in files.download_files(["/Excel/SKILL.md"])] == [True]


def test_state_write_keeps_leading_comments(tmp_path: Path) -> None:
    """停用、启用写回停用清单时，保留你写在开头的注释（积压小问题 F8）。"""
    catalog = _catalog(tmp_path)
    state = tmp_path / "config" / "skills.yaml"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("# 我自己的说明\nversion: 1\ndisabled: []\n", encoding="utf-8")
    catalog.set_enabled("excel", False)
    text = state.read_text(encoding="utf-8")
    assert text.startswith("# 我自己的说明\nversion: 1\n")
    assert catalog.hidden() == frozenset({"excel"})


def test_state_write_keeps_file_mode(tmp_path: Path) -> None:
    """停用清单写回时保持原来的权限，新文件 0644：执行命令的普通用户也读得到（积压小问题 G10）。"""
    catalog = _catalog(tmp_path)
    state = tmp_path / "config" / "skills.yaml"
    catalog.set_enabled("excel", False)
    assert stat.S_IMODE(state.stat().st_mode) == 0o644
    state.chmod(0o600)
    catalog.set_enabled("excel", True)
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
