"""打码：日志、报错文字、长期记忆里不出现密钥（设计 2026-10-23 5.12；记忆脱敏 R48）。

两种办法一起用：
- 已知密钥的值：环境变量里名字像密钥（以 _KEY、_TOKEN、_SECRET、_PASSWORD 结尾）、值又不太短的，
  原样出现就换成 ***；太短的值会误伤普通文字，不当密钥；
- 常见格式：私钥块、sk- 开头的密钥、Bearer 令牌、各家令牌的固定前缀（GitHub、AWS、Google、
  Slack、npm、Hugging Face、Stripe）、api_key=… / "token": "…" 一类、网址里的口令。

英文词的开头用"前面不是英文字母、数字、下划线"判断：汉字在正则里也算单词字符，用 \\b 时
"密钥是sk-…"（中间没有空格）会漏掉。
"""

import os
import re
from collections.abc import Callable, Iterable, Mapping

MASK = "***"
_MIN_SECRET = 8
_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def _keep_prefix(found: re.Match[str]) -> str:
    """留下认得出是哪家令牌的前缀（几个写法里只有一个分组有值），后面换成 ***。"""
    return next(group for group in found.groups() if group) + MASK


_START = r"(?<![A-Za-z0-9_])"  # 英文词的开头：前面不是英文字母、数字、下划线
_PATTERNS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    # 私钥块：整段换掉；只贴了前半截（没有结束行）时连同后面成行的 base64 一起换
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
            r"(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|(?:\s+[A-Za-z0-9+/=]{16,})*)"
        ),
        MASK,
    ),
    # Bearer 令牌（排在 sk- 前面：令牌本身也可能是 sk- 开头的）
    (re.compile(rf"(?i){_START}(bearer)\s+[A-Za-z0-9._~+/=\-]{{8,}}"), r"\1 " + MASK),
    # 各家令牌的固定前缀：GitHub（细粒度、经典）、Slack、npm、Hugging Face、Stripe、Google
    (
        re.compile(
            rf"{_START}(github_pat_|gh[pousr]_)[A-Za-z0-9_]{{16,}}"
            rf"|{_START}(xox[baprs]-)[A-Za-z0-9\-]{{10,}}"
            rf"|{_START}(npm_|hf_|[sr]k_live_)[A-Za-z0-9]{{16,}}"
            rf"|{_START}(AIza)[A-Za-z0-9_\-]{{30,}}"
        ),
        _keep_prefix,
    ),
    # AWS 访问密钥：AKIA / ASIA 加 16 位大写字母、数字，前后都不能再连着字母、数字
    (re.compile(r"(?<![A-Za-z0-9])(AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])"), r"\1" + MASK),
    # sk- 开头的密钥（中间可能有连字符，如 sk-ant-api03-…）
    (re.compile(rf"{_START}sk-[A-Za-z0-9][A-Za-z0-9_\-]{{7,}}"), "sk-" + MASK),
    # api_key=…、"token": "…"、password=… 一类：保留名字和分隔符
    (
        re.compile(
            rf"(?i){_START}(api[_-]?key|access[_-]?token|token|secret|password)"
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
