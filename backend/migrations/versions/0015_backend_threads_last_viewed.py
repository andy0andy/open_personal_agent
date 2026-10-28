"""会话的最后查看时间（设计 2026-10-23 6.5）："有新回答"按它判断。

已有会话填升级时的时间：升级后不会所有会话都亮绿点。

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE threads ADD COLUMN last_viewed_at timestamptz NOT NULL DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE threads DROP COLUMN last_viewed_at")
