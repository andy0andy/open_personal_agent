"""测试不靠固定等待保证先后顺序（设计 2026-10-23 7.6）：sleep(非 0) 要在同一行注明理由。

允许的情形：替身里模拟慢的延迟、有次数上限的轮询；写成"允许等待：原因"。
"""

import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SLEEP = re.compile(r"\b(?:asyncio|time|anyio|trio)\.sleep\((?!\s*0\s*\))")
_ALLOWED = "允许等待："


def test_rule_catches_every_sleep() -> None:
    """规则本身：asyncio、time、anyio、trio 的 sleep(非 0) 都认得出，sleep(0) 放过
    （积压小问题 I17）。"""
    for line in (
        "await asyncio.sleep(1)",
        "time.sleep(0.5)",
        "await anyio.sleep(1)",
        "trio.sleep(2)",
    ):
        assert _SLEEP.search(line), line
    assert not _SLEEP.search("await asyncio.sleep(0)")


def test_no_fixed_sleeps_in_tests() -> None:
    found = []
    for folder in ("agents/tests", "backend/tests", "common/tests", "config/tests", "deploy/tests"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if path == Path(__file__).resolve():
                continue  # 规则自测里的例子
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _SLEEP.search(line) and _ALLOWED not in line:
                    found.append(f"{path.relative_to(ROOT)}:{number}")
    assert found == [], (
        "这些地方靠固定等待：改成等条件，或在同一行注明“允许等待：原因”\n" + "\n".join(found)
    )


def test_temp_dirs_go_under_pytest_basetemp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """测试里（连同被测代码）用 tempfile 建的临时目录都落在 pytest 的临时目录下，
    随它只留最近 3 次，不在系统临时目录里越积越多（R45）。"""
    made = Path(tempfile.mkdtemp())
    assert made.is_relative_to(tmp_path_factory.getbasetemp())
