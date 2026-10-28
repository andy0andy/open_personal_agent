"""数据目录改名为 .workdata（D22）：代码、部署与在用的文档里不再写不带点的 workdata 路径。

docs/ 里的历史计划、决策记录、审视文档保留原样，只查在用的几份。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 只认路径写法：workdata/、"workdata"、../workdata:/app、行尾的 /app/workdata、整行的 workdata
# （忽略清单）、WORKDATA=workdata（shell 变量）；
# 不误伤变量名 workdata: Path、关键字参数 workdata_dir=workdata、临时目录前缀 e2e-workdata-、
# 环境变量名 WORKDATA_DIR
_PLAIN = re.compile(
    r"""(?<![.\w-])workdata(?=/|:/|["'`])|(?:^|(?<=/))workdata$|(?<=[A-Z_]=)workdata\b""",
    re.MULTILINE,
)
_DIRS = ("agents", "backend", "common", "config", "deploy", "frontend/src", "frontend/e2e")
_FILES = (
    "Makefile",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "README.md",
    "CLAUDE.md",
    "docs/usage.md",
)
_SUFFIXES = {".py", ".ts", ".tsx", ".yaml", ".yml", ".sh", ".md", ".json", ".toml", ""}


def _files() -> list[Path]:
    found = [ROOT / name for name in _FILES]
    found += sorted((ROOT / "docs" / "development").glob("*.md"))
    for folder in _DIRS:
        for path in (ROOT / folder).rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()  # deploy/.env 链到真正的 .env：密钥不读
                and path.name != ".env"
                and path.suffix in _SUFFIXES | {".Dockerfile"}
                and "node_modules" not in path.parts
                and "__pycache__" not in path.parts
                and path != Path(__file__)
            ):
                found.append(path)
    return found


def test_no_plain_workdata_left() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{text[: match.start()].count(chr(10)) + 1}"
        for path in _files()
        for text in [path.read_text(encoding="utf-8", errors="replace")]
        for match in _PLAIN.finditer(text)
    ]
    assert offenders == []
