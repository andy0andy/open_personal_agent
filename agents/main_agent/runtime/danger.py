"""硬底线（设计 2026-10-23 5.2，D25）：执行的命令命中任何一条，任何档位（含跳过所有审批）都要先问。

按文字判断，挡的是模型一时糊涂，不是恶意（绕得过去，见 D25）。做法：
- 引号外的换行当作命令分隔；用 shlex 切词（去掉引号），再按 ; && || | & 切成一段段命令，
  逐段看命令名与参数：`echo rm -rf /`、`grep "rm -rf /"` 不算，`rm -rf build ~` 算；
- `cd` 进了 .workdata 之后的写操作也算改写 .workdata；
- `bash -c '…'` 里的命令再判断一遍；
- "下载后直接执行"看整条命令（管道、$(…)、<(…) 几种写法）。
只看命令文字：恢复审批时会再判断一次，两次结果必须一样。
"""

import re
import shlex
from collections.abc import Iterator
from pathlib import PurePosixPath

ROOT_OR_HOME = "删除根目录或家目录"
WORKDATA = "删除或改写 .workdata"
MKFS = "格式化磁盘（mkfs）"
DD = "直接写磁盘设备（dd of=/dev/…）"
POWER = "关机或重启"
DOWNLOAD_EXEC = "下载后直接执行（curl … | sh）"
CHMOD_ROOT = "把根目录权限改成 777"

_FETCH = r"(?:curl|wget)\b"
_RUNNER = r"(?:(?:ba|z|da|k)?sh|python3?|perl|ruby|node)\b"
# 管道给解释器、且它从标准输入读脚本（不带参数，或 -s、-）才算；curl … | python3 -m json.tool 不算
_FROM_STDIN = r"(?:\s+-s\b[^\n;&|]*|\s+-(?=\s|$))?(?=\s*(?:$|[\n;&|)<>]|\d>))"
_DOWNLOAD_EXEC = re.compile(
    rf"\b{_FETCH}[^|\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?{_RUNNER}{_FROM_STDIN}"  # curl … | sh
    rf"|\b(?:ba|z|da|k)?sh\s+-c\s+[\"']?\$\(\s*{_FETCH}"  # sh -c "$(curl …)"
    rf"|(?:\b(?:ba|z|da|k)?sh|\bsource|^\.|[;&|]\s*\.)\s+<\(\s*{_FETCH}"  # bash <(curl …)
    rf"|\beval\s+[\"']?\$\(\s*{_FETCH}"
)
_ROOT_OR_HOME = re.compile(r"(?:/|~/?|\$HOME/?|\$\{HOME\}/?)\*?")
_OPERATOR = re.compile(r"[;&|]+")  # shlex 切出来的命令分隔
_PREFIXES = frozenset({"sudo", "doas", "env", "nohup", "time", "command", "exec", "nice"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_POWER = frozenset({"shutdown", "reboot", "poweroff", "halt"})
# 改动参数里所有路径的命令；cp 一类只改目标（最后一个参数）
_CHANGES_ALL = frozenset(
    {"rm", "rmdir", "unlink", "shred", "mv", "chmod", "chown", "truncate", "tee"}
)
_CHANGES_TARGET = frozenset({"cp", "rsync", "install", "ln"})


def danger_reason(command: str) -> str | None:
    """命令命中的硬底线（名字）；没命中时为 None。"""
    if _DOWNLOAD_EXEC.search(command):
        return DOWNLOAD_EXEC
    in_workdata = False
    for words in _segments(command):
        name, args = _command(words)
        if name == "cd":
            in_workdata = bool(args) and ".workdata" in args[0]
            continue
        if reason := _check(name, args, words, in_workdata=in_workdata):
            return reason
    return None


def _check(name: str, args: list[str], words: list[str], *, in_workdata: bool) -> str | None:
    paths = [arg for arg in args if not arg.startswith("-")]
    if name == "rm" and any(_ROOT_OR_HOME.fullmatch(path) for path in paths):
        return ROOT_OR_HOME
    if _writes_workdata(name, args, paths, words, in_workdata=in_workdata):
        return WORKDATA
    if name.startswith("mkfs"):
        return MKFS
    if name == "dd" and any(a.startswith("of=/dev/") and a != "of=/dev/null" for a in args):
        return DD
    if name in _POWER or (name == "systemctl" and any(a in _POWER for a in args)):
        return POWER
    if name == "chmod" and _chmod_root_777(args, paths):
        return CHMOD_ROOT
    if name in _SHELLS and "-c" in args:
        script = args[args.index("-c") + 1] if args.index("-c") + 1 < len(args) else ""
        return danger_reason(script) if script else None
    return None


def _writes_workdata(
    name: str, args: list[str], paths: list[str], words: list[str], *, in_workdata: bool
) -> bool:
    redirected = any(
        word in (">", ">>") and i + 1 < len(words) and ".workdata" in words[i + 1]
        for i, word in enumerate(words)
    )
    if redirected:
        return True
    if (
        name == "sed" and any(a.startswith(("-i", "--in-place")) for a in args)
    ) or name in _CHANGES_ALL:
        targets = paths
    elif name in _CHANGES_TARGET:
        targets = paths[-1:]
    else:
        return False
    return (in_workdata and bool(targets)) or any(".workdata" in path for path in targets)


def _chmod_root_777(args: list[str], paths: list[str]) -> bool:
    recursive = any(re.fullmatch(r"-[a-zA-Z]*R[a-zA-Z]*|--recursive", a) for a in args)
    return recursive and any(re.fullmatch(r"0?777", a) for a in paths) and "/" in paths


def _command(words: list[str]) -> tuple[str, list[str]]:
    """一段命令的命令名（去掉目录）与参数：跳过开头的 sudo、env、变量赋值一类。"""
    rest = [word for word in words if word not in (">", ">>", "<", "<(", ")")]
    while rest and (rest[0] in _PREFIXES or "=" in rest[0] or rest[0].startswith("-")):
        rest = rest[1:]
    if not rest:
        return "", []
    return PurePosixPath(rest[0]).name, rest[1:]


def _segments(command: str) -> Iterator[list[str]]:
    words = _words(_unquoted_newlines_to_semicolons(command))
    segment: list[str] = []
    for word in words:
        if _OPERATOR.fullmatch(word):
            if segment:
                yield segment
            segment = []
        else:
            segment.append(word)
    if segment:
        yield segment


def _words(command: str) -> list[str]:
    """切词并去掉引号；引号没配对时退回按空白与分隔符切（不去引号）。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return re.findall(r"[;&|]+|<\(|>>?|<|[^\s;&|<>]+", command)


def _unquoted_newlines_to_semicolons(command: str) -> str:
    """多行脚本：引号外的换行就是命令分隔（shlex 把换行当成普通空白）。"""
    out: list[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "\n":
            char = ";"
        out.append(char)
    return "".join(out)
