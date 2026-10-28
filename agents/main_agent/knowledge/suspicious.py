"""记忆的可疑检查（设计 2026-10-23 6.6）：被诱导记下的"指令"不能每次都拼进提示词。

每次写入记忆（remember、自动提取、知识库页新增或修改）都过一遍；命中的条目标为可疑：
不进提示词，也不出现在检索结果里，知识库页上显示警告，你确认无害后恢复。

只认针对智能体的说法，正常的个人信息不算（审查 I1：被误标的记忆会悄悄失效）：
- 往外发信息：发的是聊天记录、密码这类东西，或者是对智能体说"请 / 你把……发到 <邮箱或网址>"；
  "用户每周五把周报发给 lead@example.com"不算。
- 冒充系统："【系统消息】""系统提示："、让"你"进入管理员模式；"我是系统管理员"
  "手机开着开发者模式""【系统设计面试】"不算。
- 执行命令：执行"以下 / 下面"的命令；"运行这个脚本备份照片"不算。

英文词的边界用"前后不是英文字母、数字"判断：汉字在正则里也算单词字符，用 \\b 时
"请ignore previous instructions"会漏掉（审查 Minor 11）。各段长度都有上限，
长文本也是线性时间（审查 Minor 12：原来 2 万字无标点的中文要 5 秒多）。
"""

import re

_START = r"(?<![A-Za-z0-9_])"  # 英文词的开头：前面不是英文字母、数字
_END = r"(?![A-Za-z0-9_])"  # 英文词的结尾
_EMAIL_OR_URL = r"(?:https?://|[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}\.[A-Za-z0-9.-]{1,200})"
_SENSITIVE_ZH = (
    r"(?:聊天记录|对话记录|对话内容|对话|密码|密钥|口令|令牌|私钥|隐私|个人信息|记忆|"
    r"token|api\s?key)"
)
_SENSITIVE_EN = (
    r"(?:conversations?|chat\s+(?:history|logs?)|history|memor(?:y|ies)|passwords?|"
    r"secrets?|api\s?keys?|tokens?|private\s+keys?|credentials?)"
)
_SEND_ZH = r"(?:发送|发给|发到|转发|上传|告诉|泄露)"

# 按顺序检查，返回第一个命中的那一类
_KINDS: list[tuple[str, re.Pattern[str]]] = [
    (
        "要求忽略之前的指令",
        re.compile(
            # 忽略……指令 / 提示词：这类词很少出现在个人信息里
            r"(?:忽略|无视|忘掉|忘记|不要理会|别管|抛开)[^。\n]{0,8}?"
            r"(?:指令|指示|提示词|系统提示)"
            # 无视之前的 / 你的 规则（"忽略之前的格式要求""用户常忘记之前的设定"不算）
            r"|(?:忽略|无视|忘掉|不要理会|别管|抛开)[^。\n]{0,6}?"
            r"(?:之前|以上|上面|前面|先前|原来|原有|所有|全部|一切|你的)[^。\n]{0,4}?"
            r"(?:规则|设定|约束|规定|限制)"
            rf"|{_START}(?:ignore|disregard|forget){_END}\s+"
            r"(?:(?:all|any|of|the|your|my|previous|prior|above|earlier|preceding|these|those)\s+)"
            rf"{{1,4}}(?:instructions?|rules|directions|prompts?|guidelines){_END}"
            rf"|{_START}(?:ignore|disregard|forget){_END}\s+(?:everything|anything|all)\s+"
            rf"(?:above|before|previously|prior){_END}",
            re.IGNORECASE,
        ),
    ),
    (
        "冒充系统",
        re.compile(
            r"【\s*系统\s*(?:消息|提示|指令|通知)?\s*】|系统(?:消息|提示|指令|通知)\s*[:：]"
            r"|以系统(?:身份|名义)|我是(?:系统(?!管理|设计|工程|分析|架构)|你的(?:开发者|创造者|主人|管理员))"
            r"|(?:进入|开启|切换到|切换为|启用)\s*(?:管理员|开发者|上帝|越狱)模式"
            r"|你(?:现在)?(?:处于|进入了?|在)\s*(?:管理员|开发者|上帝|越狱)模式"
            rf"|^\s*(?:system|admin|developer)\s*[:：]|\[\s*system\s*\]|<\s*/?\s*system\s*>"
            rf"|{_START}you\s+are\s+now\s+(?:in|a|an|the|my|dan|free|unrestricted|jailbroken)"
            rf"{_END}|{_START}new\s+system\s+prompt{_END}"
            rf"|你(?:现在)?(?:是|扮演){_START}\s*DAN{_END}"
            rf"|{_START}(?:enter|enable|activate|switch\s+to)\s+(?:developer|admin|god|dan)\s+mode{_END}",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "夹带下载后直接执行的命令",
        re.compile(
            rf"{_START}(?:curl|wget){_END}[^\n|;]{{0,300}}\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh{_END}"
            rf"|{_START}(?:iwr|irm|invoke-webrequest|invoke-restmethod){_END}[^\n|]{{0,300}}"
            rf"\|\s*iex{_END}",
            re.IGNORECASE,
        ),
    ),
    (
        "让你执行命令",
        re.compile(
            r"(?:执行|运行)\s*(?:一下)?\s*(?:以下|下面|下列|如下)的?\s*(?:命令|指令|脚本|代码)"
            # 让智能体跑危险命令（"用户曾经误用 rm -rf"没有"执行 / 运行"，不算）
            rf"|(?:执行|运行)[^。\n]{{0,6}}?{_START}(?:rm\s+-[A-Za-z]*[rf]|sudo|mkfs|dd\s+if=|"
            r"chmod\s+-R|shutdown|reboot)"
            rf"|{_START}(?:run|execute)\s+(?:the\s+)?(?:following|below)\s+(?:shell\s+)?"
            rf"(?:commands?|scripts?|code){_END}",
            re.IGNORECASE,
        ),
    ),
    (
        "往外发信息",
        re.compile(
            # 把聊天记录、密码这类东西发到邮箱、网址（"用户把密码告诉了家人"不算）
            rf"(?:把|将)[^。\n]{{0,30}}?{_SENSITIVE_ZH}[^。\n]{{0,10}}?{_SEND_ZH}"
            rf"[^。\n]{{0,20}}?{_EMAIL_OR_URL}"
            # 对智能体说"你 / 请把聊天记录……发出去"
            rf"|(?:你|请|务必|必须)[^。\n]{{0,30}}?{_SENSITIVE_ZH}[^。\n]{{0,10}}?{_SEND_ZH}"
            # 对智能体说"请 / 你把……发到 <邮箱或网址>"
            rf"|(?:你|请|务必|必须)[^。\n]{{0,20}}?{_SEND_ZH}[^。\n]{{0,20}}?{_EMAIL_OR_URL}"
            rf"|{_START}(?:send|post|upload|forward|transmit|exfiltrate|leak){_END}"
            rf"[^\n]{{0,60}}?{_SENSITIVE_EN}[^\n]{{0,40}}?\s(?:to|into)\s+{_EMAIL_OR_URL}",
            re.IGNORECASE,
        ),
    ),
]


# 零宽字符：夹在字中间（"忽\u200b略"）就能躲过关键词
_INVISIBLE = re.compile("[\u200b-\u200f\u2060-\u2064\ufeff]")


def suspicious_reason(text: str) -> str | None:
    """像是写给智能体的指令时，返回命中的那一类（中文名）；正常内容返回 None。"""
    visible = _INVISIBLE.sub("", text)
    for name, pattern in _KINDS:
        if pattern.search(visible):
            return name
    return None
