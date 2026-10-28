"""agents 用量表：每次模型调用一行（设计文档 7.7、11.1）。

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 会话、运行不设外键：删除会话后用量记录仍保留，费用统计不受影响
    op.execute(
        """
        CREATE TABLE llm_usage (
            id                  uuid PRIMARY KEY,
            user_id             text NOT NULL DEFAULT 'me',
            thread_id           uuid,
            run_id              uuid,
            caller              text NOT NULL,
            requested_model     text NOT NULL,
            actual_model        text NOT NULL,
            input_tokens        integer NOT NULL,
            output_tokens       integer NOT NULL,
            cache_read_tokens   integer NOT NULL DEFAULT 0,
            cache_write_tokens  integer NOT NULL DEFAULT 0,
            reasoning_tokens    integer NOT NULL DEFAULT 0,
            cost                numeric(12, 6),
            duration_ms         integer NOT NULL DEFAULT 0,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX llm_usage_thread ON llm_usage (thread_id)")
    op.execute("CREATE INDEX llm_usage_run ON llm_usage (run_id)")
    op.execute("CREATE INDEX llm_usage_created ON llm_usage (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE llm_usage")
