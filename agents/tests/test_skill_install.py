"""对话里装技能（D29）：install_skill 把会话目录里的技能包装进技能目录。

和技能页上传走同一套检查；审批跟着执行命令走（前两档先问，"跳过所有审批"直接装）；
子智能体没有这个工具。
"""

import io
import uuid
import zipfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.main_agent.integrations import PermissionMode
from agents.main_agent.runtime import ApprovalRequired, MainAgent, ToolFinished
from agents.main_agent.runtime.skills import SkillCatalog, SkillPackage
from agents.main_agent.workspace import LocalWorkspace
from agents.tests.fakes import FakeGateway, FakeSandbox, ScriptedChatModel, call
from common.errors import ConflictError

SHORT = "c_000000c1"
SKILL = "---\nname: caveman\ndescription: 说话更省字\n---\n\n正文\n"


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _agent(model: ScriptedChatModel, tmp_path: Path, **options: object) -> MainAgent:
    return MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
        skills_dir=tmp_path / "skills",
        **options,  # type: ignore[arg-type]
    )


def _put(tmp_path: Path, name: str, data: bytes) -> None:
    target = tmp_path / "workspace" / SHORT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


async def _run(agent: MainAgent, permission: PermissionMode = "skip") -> list[object]:
    return [
        e
        async for e in agent.run(
            thread_id=str(uuid.UUID(int=1)),
            thread_short_id=SHORT,
            run_id=str(uuid.uuid4()),
            message="帮我装这个技能",
            model="m",
            permission=permission,
        )
    ]


def _finished(events: list[object]) -> ToolFinished:
    return next(e for e in events if isinstance(e, ToolFinished) and e.name == "install_skill")


def _model(path: str) -> ScriptedChatModel:
    return ScriptedChatModel(responses=[call("install_skill", {"path": path}), AIMessage("好")])


async def test_installs_a_zip_from_the_session_directory(tmp_path: Path) -> None:
    _put(tmp_path, "caveman.zip", _zip({"caveman/SKILL.md": SKILL, "caveman/rules.md": "少说"}))
    agent = _agent(_model("caveman.zip"), tmp_path)
    done = _finished(await _run(agent))
    assert done.status == "success"
    assert "caveman" in done.output
    assert "/skills/caveman/SKILL.md" in done.output  # 告诉模型现在就能去读
    installed = tmp_path / "skills" / "caveman"
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == SKILL
    assert (installed / "rules.md").read_text(encoding="utf-8") == "少说"
    assert [skill.name for skill in agent.skills()] == ["caveman"]


async def test_accepts_the_path_as_the_agent_sees_it(tmp_path: Path) -> None:
    # 智能体看到的路径是 /workspace/<会话>/…：照这个写法给也认
    _put(tmp_path, "dl/SKILL.md", SKILL.encode())
    done = _finished(await _run(_agent(_model(f"/workspace/{SHORT}/dl/SKILL.md"), tmp_path)))
    assert done.status == "success"
    assert (tmp_path / "skills" / "caveman" / "SKILL.md").is_file()


async def test_bad_package_is_reported_to_the_model(tmp_path: Path) -> None:
    _put(tmp_path, "x.zip", _zip({"readme.md": "没有技能说明"}))
    done = _finished(await _run(_agent(_model("x.zip"), tmp_path)))
    assert done.status == "error"
    assert "SKILL.md" in done.output
    assert not (tmp_path / "skills").exists() or not list((tmp_path / "skills").iterdir())


async def test_same_name_is_refused(tmp_path: Path) -> None:
    (tmp_path / "skills" / "caveman").mkdir(parents=True)
    (tmp_path / "skills" / "caveman" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    _put(tmp_path, "caveman.zip", _zip({"SKILL.md": SKILL.replace("省字", "别的")}))
    done = _finished(await _run(_agent(_model("caveman.zip"), tmp_path)))
    assert done.status == "error"
    assert "已有同名技能" in done.output
    assert "省字" in (tmp_path / "skills" / "caveman" / "SKILL.md").read_text(encoding="utf-8")


async def test_missing_file_and_folder_are_explained(tmp_path: Path) -> None:
    done = _finished(await _run(_agent(_model("nope.zip"), tmp_path)))
    assert done.status == "error"
    assert "不存在" in done.output
    (tmp_path / "workspace" / SHORT / "folder").mkdir(parents=True)
    _put(tmp_path, "folder/SKILL.md", SKILL.encode())
    done = _finished(await _run(_agent(_model("folder"), tmp_path)))
    assert done.status == "error"
    assert "zip -r" in done.output  # 给的是文件夹：告诉模型先打包


async def test_cannot_read_outside_the_session_directory(tmp_path: Path) -> None:
    (tmp_path / "secret.zip").write_bytes(_zip({"SKILL.md": SKILL}))
    done = _finished(await _run(_agent(_model("../../secret.zip"), tmp_path)))
    assert done.status == "error"
    assert not (tmp_path / "skills" / "caveman").exists()


async def test_oversized_package_is_refused_before_reading(tmp_path: Path) -> None:
    _put(tmp_path, "big.zip", b"0" * 2048)
    done = _finished(await _run(_agent(_model("big.zip"), tmp_path, max_upload_bytes=1024)))
    assert done.status == "error"
    assert "太大" in done.output


async def test_asks_first_unless_the_session_skips_approvals(tmp_path: Path) -> None:
    _put(tmp_path, "caveman.zip", _zip({"SKILL.md": SKILL}))
    modes: tuple[PermissionMode, ...] = ("ask", "ask_execute")
    for mode in modes:
        paused = (await _run(_agent(_model("caveman.zip"), tmp_path), mode))[-1]
        assert isinstance(paused, ApprovalRequired), mode
        [request] = paused.requests
        [action] = request.actions
        assert action.name == "install_skill"
        # 确认卡上写清楚后果，不是只显示工具的英文名
        assert action.description == "装上后以后所有会话都能用；可以在技能页停用、删除"
        assert not (tmp_path / "skills" / "caveman").exists()


def test_install_skill_is_a_side_effect_tool_only_with_a_skills_dir(tmp_path: Path) -> None:
    model = ScriptedChatModel(responses=[AIMessage("好")])
    with_skills = _agent(model, tmp_path)
    assert "install_skill" in [row.name for row in with_skills.tool_approvals()]
    assert with_skills.has_side_effects(["install_skill"])  # 调过它的一轮不能"重试这一轮"
    without = MainAgent(
        gateway=FakeGateway(model),
        checkpointer=InMemorySaver(),
        system_prompt="测试助手",
        workspace=LocalWorkspace(tmp_path, FakeSandbox()),
    )
    assert "install_skill" not in [row.name for row in without.tool_approvals()]


async def test_unexpected_file_errors_do_not_fail_the_run(tmp_path: Path) -> None:
    # 会话目录里的怪东西（自己指自己的链接、带空字符的路径）不能让整轮对话失败，
    # 报错里也不带真实路径
    session = tmp_path / "workspace" / SHORT
    session.mkdir(parents=True)
    (session / "loop.zip").symlink_to("loop.zip")
    for path in ("loop.zip", "a\x00b.zip", "x" * 300 + ".zip"):
        events = await _run(_agent(_model(path), tmp_path))
        done = _finished(events)
        assert done.status == "error", path
        assert "没有装上" in done.output
        assert str(tmp_path) not in done.output
        assert events[-1].status == "completed"  # type: ignore[attr-defined]


async def test_git_folder_is_left_out_of_the_package(tmp_path: Path) -> None:
    # 仓库根目录就是技能时，照着"zip -r ../名字.zip ."打包会带上 .git/：不算进技能里
    files = {"SKILL.md": SKILL, ".git/HEAD": "ref: refs/heads/main", ".git/objects/ab/cd": "x"}
    _put(tmp_path, "caveman.zip", _zip(files))
    done = _finished(await _run(_agent(_model("caveman.zip"), tmp_path)))
    assert done.status == "success"
    assert not (tmp_path / "skills" / "caveman" / ".git").exists()


async def test_wrong_kind_of_file_is_explained_for_the_conversation(tmp_path: Path) -> None:
    _put(tmp_path, "notes.txt", b"hello")
    done = _finished(await _run(_agent(_model("notes.txt"), tmp_path)))
    assert done.status == "error"
    assert ".zip" in done.output
    assert "SKILL.md" in done.output
    assert "上传" not in done.output  # 这里不是上传


def test_losing_a_race_for_the_same_name_is_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两处同时装同名技能：后到的那个在改名时才发现已经有了，要说"已有同名技能"，不是系统错误。"""
    catalog = SkillCatalog(tmp_path / "skills")
    package = SkillPackage(
        name="caveman", description="说话更省字", files={"SKILL.md": SKILL.encode()}
    )
    real_rename = Path.rename

    def rename_after_someone_else(self: Path, target: Path) -> Path:
        target.mkdir()
        (target / "SKILL.md").write_text(SKILL, encoding="utf-8")  # 别人先装好了
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename_after_someone_else)
    with pytest.raises(ConflictError, match="已有同名技能"):
        catalog.install(package)
    assert [p.name for p in (tmp_path / "skills").iterdir()] == ["caveman"]  # 没留下临时文件夹
