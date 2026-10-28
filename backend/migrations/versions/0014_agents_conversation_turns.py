"""agents 会话索引表：每次运行一行，用户原文 + 主智能体的回答全文（设计 2026-10-23 6.1）。

不设外键（同 llm_usage）：会话、运行在 backend 的表里，删会话时由智能体模块显式删除。

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation_turns (
            run_id      uuid PRIMARY KEY,
            thread_id   uuid NOT NULL,
            title       text NOT NULL,
            started_at  timestamptz NOT NULL,
            user_text   text NOT NULL,
            answer_text text NOT NULL,
            search      tsvector NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX conversation_turns_search ON conversation_turns USING gin (search)")
    op.execute(
        "CREATE INDEX conversation_turns_thread ON conversation_turns (thread_id, started_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE conversation_turns")
