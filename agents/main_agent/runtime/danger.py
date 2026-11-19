"""硬底线（设计 2026-10-23 5.2，D25）：执行的命令命中任何一条，任何档位（含跳过所有审批）都要先问。

按文字判断，挡的是模型一时糊涂，不是恶意（绕得过去，见 D25）。做法：
- 引号外的换行当作命令分隔；用 shlex 切词（去掉引号），再按 ; && || | & 切成一段段命令，
  逐段看命令名与参数：`echo rm -rf /`、`grep "rm -rf /"` 不算，`rm -rf build ~` 算；
- `cd` 进了 .workdata 之后的写操作也算改写 .workdata；
- 改到本会话目录之外（D29）：命令的当前目录是 /workspace/<会话>/，跟着 `cd` 记下走到了哪里，
  删改的目标出了本会话目录（`../别的会话`、`../../config`、`/workspace/*`）就算。只按路径的
  写法推，不看磁盘；写明 /workspace/<某个会话>/ 的绝对路径当作本会话（分不出是不是别人的）；
- `bash -c '…'` 里的命令再判断一遍；
- "下载后直接执行"看整条命令（管道、$(…)、<(…) 几种写法）。
只看命令文字：恢复审批时会再判断一次，两次结果必须一样。
"""

import posixpath
import re
import shlex
from collections.abc import Iterator
from pathlib import PurePosixPath

ROOT_OR_HOME = "删除根目录或家目录"
WORKDATA = "删除或改写 .workdata"
OUTSIDE = "删除或改写本会话目录之外的数据"
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
_WORKSPACE = "/workspace"  # 智能体看到的工作区根目录；它下面一层是各个会话
_HERE = f"{_WORKSPACE}/c_current"  # 命令开始时的当前目录：本会话目录（名字只是占位）
_GLOB = re.compile(r"[*?\[]")


def danger_reason(command: str) -> str | None:
    """命令命中的硬底线（名字）；没命中时为 None。"""
    if _DOWNLOAD_EXEC.search(command):
        return DOWNLOAD_EXEC
    in_workdata = False
    where = _Where()
    for words in _segments(command):
        name, args = _command(words)
        if name == "cd":
            in_workdata = bool(args) and ".workdata" in args[0]
            where.cd(args[0] if args else "")
            continue
        if reason := _check(name, args, words, in_workdata=in_workdata, where=where):
            return reason
    return None


class _Where:
    """跟着 `cd` 记下当前目录（只按写法推）：用来看删改的目标有没有出本会话目录。"""

    def __init__(self) -> None:
        self.cwd: str | None = _HERE  # None：不知道在哪（cd 到了变量、~ 一类）
        self.home = _HERE  # 当作本会话目录的那一个

    def cd(self, target: str) -> None:
        if not target or target[0] in "~$-":
            self.cwd = None
        elif target.startswith("/"):
            self.cwd = posixpath.normpath(target)
            if _is_session_path(self.cwd):  # 写明了某个会话：当作本会话
                self.home = "/".join(self.cwd.split("/")[:3])
        elif self.cwd is not None:
            moved = posixpath.normpath(posixpath.join(self.cwd, target))
            # 从会话里用 .. 走出去了：/workspace 是个链接，再往上按写法推不准，统一记成工作区根
            escaped = _within(self.cwd, _WORKSPACE) and not _within(moved, self.home)
            self.cwd = _WORKSPACE if escaped else moved

    def outside(self, path: str) -> bool:
        """这个路径是不是数据目录里、本会话目录之外的东西。"""
        if not path or path[0] in "~$":
            return False
        if path.startswith("/"):
            normal = posixpath.normpath(path)
            named = _within(path.rstrip("/") or "/", _WORKSPACE) or _within(normal, _WORKSPACE)
            return named and not _is_session_path(normal)
        if self.cwd is None:
            return False
        absolute = posixpath.normpath(posixpath.join(self.cwd, path))
        if _within(self.cwd, _WORKSPACE):
            return not _within(absolute, self.home)
        return _within(absolute, _WORKSPACE) and not _is_session_path(absolute)  # 从别处绕回来


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _is_session_path(path: str) -> bool:
    """/workspace/<某个会话>[/…]：会话那一层不能是通配符。"""
    parts = path.split("/")
    return path.startswith(_WORKSPACE + "/") and bool(parts[2]) and not _GLOB.search(parts[2])


def _check(
    name: str, args: list[str], words: list[str], *, in_workdata: bool, where: _Where
) -> str | None:
    paths = [arg for arg in args if not arg.startswith("-")]
    if name == "rm" and any(_ROOT_OR_HOME.fullmatch(path) for path in paths):
        return ROOT_OR_HOME
    if _writes_workdata(name, args, paths, words, in_workdata=in_workdata):
        return WORKDATA
    if any(where.outside(path) for path in _changed(name, args, paths, words)):
        return OUTSIDE
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
    targets = _targets(name, args, paths)
    return (in_workdata and bool(targets)) or any(".workdata" in path for path in targets)


def _targets(name: str, args: list[str], paths: list[str]) -> list[str]:
    """这条命令会改动的路径（没有时为空）。"""
    if (
        name == "sed" and any(a.startswith(("-i", "--in-place")) for a in args)
    ) or name in _CHANGES_ALL:
        return paths
    if name in _CHANGES_TARGET:
        return paths[-1:]
    return []


def _changed(name: str, args: list[str], paths: list[str], words: list[str]) -> list[str]:
    """同上，再加上重定向写入的文件、find 带 -delete / -exec 时的起点目录。"""
    redirected = [
        words[i + 1] for i, word in enumerate(words) if word in (">", ">>") and i + 1 < len(words)
    ]
    roots: list[str] = []
    if name == "find" and any(arg in ("-delete", "-exec", "-execdir") for arg in args):
        for arg in args:
            if arg.startswith(("-", "(", "!")):
                break
            roots.append(arg)
    return [*_targets(name, args, paths), *redirected, *roots]


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
