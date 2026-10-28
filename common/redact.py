"""打码：日志、报错文字里不出现密钥（设计 2026-10-23 5.12）。

两种办法一起用：
- 已知密钥的值：环境变量里名字像密钥（以 _KEY、_TOKEN、_SECRET、_PASSWORD 结尾）、值又不太短的，
  原样出现就换成 ***；太短的值会误伤普通文字，不当密钥；
- 常见格式：sk- 开头的密钥、Bearer 令牌、api_key=… / "token": "…" 一类、网址里的口令。
"""

import os
import re
from collections.abc import Iterable, Mapping

MASK = "***"
_MIN_SECRET = 8
_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer 令牌（排在 sk- 前面：令牌本身也可能是 sk- 开头的）
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 " + MASK),
    # sk- 开头的密钥（中间可能有连字符，如 sk-ant-api03-…）
    (re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{7,}"), "sk-" + MASK),
    # api_key=…、"token": "…"、password=… 一类：保留名字和分隔符
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)"
            r"(\"?\s*[:=]\s*\"?)[^\s\"',;&]{4,}"
        ),
        r"\1\2" + MASK,
    ),
    # 网址里的口令：scheme://user:pass@host
    (re.compile(r"(://[^:/\s@]+:)[^@\s/]+@"), r"\1" + MASK + "@"),
)


def secret_values(env: Mapping[str, str] | None = None) -> list[str]:
    """环境变量里的密钥值（默认取当前进程的），长的在前：一个是另一个的一部分时先换长的。"""
    source = os.environ if env is None else env
    values = {
        value
        for name, value in source.items()
        if name.upper().endswith(_SECRET_SUFFIXES) and len(value) >= _MIN_SECRET
    }
    return sorted(values, key=len, reverse=True)


def redact(text: str, secrets: Iterable[str] | None = None) -> str:
    """把文字里的密钥换成 ***：已知的值（不给时取当前环境变量）与常见格式。"""
    for value in secret_values() if secrets is None else secrets:
        text = text.replace(value, MASK)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
