"""代码、部署与在用的文档里不再出现已经过时的说法（积压小问题 I14）。

扫描范围同 test_paths（docs/ 里的历史计划、决策记录、审视文档保留原样）；测试跳过（各处 tests/
目录、前端的 *.test.* 与 e2e 的 *.spec.*）：测试里写"原 config/app.yaml"是在讲历史。
"""

import re
from pathlib import Path

from deploy.tests.test_paths import ROOT, _files

# 旧说法 → 为什么过时
_STALE: dict[str, str] = {
    r"config/app\.yaml": "设置已进数据库与设置页，没有 app.yaml 了（D22）",
    r"docker-compose\.yml 里传给": "后端整份读入 .env，不再逐项传（D22）",
    r"backend\.security": "这个模块已删除（D23）",
    r"向量模型写在 config/models\.yaml": "模型都在网关数据库里，在模型页管理（D22 第 6 条）",
    r"不超过\s*50\s*MB": "上传上限可在设置页改（max_upload_mb），不能写死",
    r"max_document_mb": "上传上限只有 max_upload_mb 一项，附件、知识库文档、技能包共用",
    r"config/models\.yaml\s*(?:里的|的|增加|中)[^。\n]{0,10}条目": (
        "模型都在网关数据库里（默认清单是 config/seed/models.yaml），"
        "config/models.yaml 只剩网关自身的设置（D22）"
    ),
}


def _stale(line: str) -> list[str]:
    return [reason for pattern, reason in _STALE.items() if re.search(pattern, line)]


def _scanned(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return "tests" not in relative.parts and not any(
        mark in relative.name for mark in (".test.", ".spec.")
    )


def test_tests_are_skipped() -> None:
    """测试里讲历史的文字不算：后端的 tests/ 目录、前端与源码放在一起的测试、端到端测试都跳过。"""
    assert not _scanned(ROOT / "backend" / "tests" / "test_x.py")
    assert not _scanned(ROOT / "frontend" / "src" / "a" / "b.test.tsx")
    assert not _scanned(ROOT / "frontend" / "e2e" / "chat.spec.ts")
    assert _scanned(ROOT / "frontend" / "src" / "a" / "b.tsx")


def test_env_is_never_scanned() -> None:
    """扫描不读 .env（含 deploy/.env 链接）：里面是密钥。"""
    assert not [path for path in _files() if path.name == ".env"]


def test_rules_catch_stale_wording() -> None:
    """规则本身：认得出旧说法；正常提到 config/models.yaml（网关自己的设置）不算。"""
    assert _stale("见 config/app.yaml 的 agent 段") == [_STALE[r"config/app\.yaml"]]
    assert _stale("上传的文件不超过 50 MB") == [_STALE[r"不超过\s*50\s*MB"]]
    assert _stale("uv run python -m backend.security") == [_STALE[r"backend\.security"]]
    assert _stale("网关自己的设置在 config/models.yaml") == []
    assert _stale("# 与 config/models.yaml 里的向量模型条目一致") != []
    assert _stale("写在 config/models.yaml 里的模型没有编号，页面上不能改") == []


def test_no_stale_wording() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{number} → {reason}"
        for path in _files()
        if _scanned(path)
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        )
        for reason in _stale(line)
    ]
    assert found == []
