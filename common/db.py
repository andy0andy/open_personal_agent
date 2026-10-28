"""PostgreSQL 连接池工厂（psycopg 3）。"""

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

type Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


def create_pool(dsn: str, *, max_size: int = 10) -> Pool:
    """创建连接池（未打开；调用方负责 `await pool.open()` 与 `await pool.close()`）。

    autocommit 与 dict_row 是 LangGraph Postgres 对话存档的要求；
    prepare_threshold=0 兼容连接池代理。
    """
    return AsyncConnectionPool(
        dsn,
        open=False,
        max_size=max_size,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
