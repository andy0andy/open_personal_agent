"""backend 后台任务表：记忆提取、标题生成等（设计文档 10.9、11.2）。

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
            id          uuid PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'me',
            kind        text NOT NULL,
            payload     jsonb NOT NULL DEFAULT '{}',
            status      text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'done', 'failed')),
            attempts    integer NOT NULL DEFAULT 0,
            last_error  text,
            run_at      timestamptz NOT NULL DEFAULT now(),
            locked_at   timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX jobs_due ON jobs (run_at) WHERE status = 'queued'")


def downgrade() -> None:
    op.execute("DROP TABLE jobs")
