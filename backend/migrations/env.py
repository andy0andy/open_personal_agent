"""Alembic 迁移环境：表结构变更一律用原生 SQL 编写（不使用 ORM 元数据）。"""

from alembic import context
from sqlalchemy import create_engine

from config import get_settings


def _database_url() -> str:
    # 测试通过 attributes 传入测试库地址；命令行运行时读取应用配置（没有 alembic.ini）
    url = context.config.attributes.get("database_url") or get_settings().database_url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
