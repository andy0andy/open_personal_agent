"""中文分词（jieba）：PostgreSQL 自带的全文检索不会给中文分词，先在 Python 里分好再存。"""

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)  # 第一次分词时加载词典，默认会打印几行调试信息

_WORD = re.compile(r"\w")


def warm_up() -> None:
    """预先加载词典（约 1 秒，同步）：启动时在线程里调用，免得第一次分词时卡住服务。"""
    jieba.initialize()


def search_tokens(text: str) -> list[str]:
    """搜索引擎模式分词（长词再切出短词，便于部分匹配），统一小写，去掉标点与空白。"""
    return [word.lower() for word in jieba.cut_for_search(text) if _WORD.search(word)]
