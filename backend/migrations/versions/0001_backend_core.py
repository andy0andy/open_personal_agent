"""backend 核心表：会话、运行、运行事件（界面历史）。

Revision ID: 0001
Revises:
"""

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE threads (
            id          uuid PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'me',
            short_id    text NOT NULL UNIQUE,
            title       text NOT NULL DEFAULT '',
            model       text NOT NULL,
            agent_name  text NOT NULL DEFAULT 'main_agent',
            archived    boolean NOT NULL DEFAULT false,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE runs (
            id           uuid PRIMARY KEY,
            user_id      text NOT NULL DEFAULT 'me',
            thread_id    uuid NOT NULL REFERENCES threads (id) ON DELETE CASCADE,
            status       text NOT NULL CHECK (status IN (
                             'queued', 'running', 'interrupted',
                             'completed', 'failed', 'cancelled')),
            model        text NOT NULL,
            input        jsonb NOT NULL,
            error        text,
            usage        jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz
        )
        """
    )
    # 同一会话同一时间只能有一个进行中的运行（设计文档 10.9 替换点①）
    op.execute(
        "CREATE UNIQUE INDEX runs_one_active_per_thread ON runs (thread_id) "
        "WHERE status IN ('queued', 'running', 'interrupted')"
    )
    op.execute("CREATE INDEX runs_thread_created ON runs (thread_id, created_at)")
    op.execute(
        """
        CREATE TABLE run_events (
            run_id      uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
            seq         integer NOT NULL,
            type        text NOT NULL,
            payload     jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (run_id, seq)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE run_events")
    op.execute("DROP TABLE runs")
    op.execute("DROP TABLE threads")
