"""运行记下"重试的是哪一次"（D26，设计 2026-10-23 4.5）：界面把失败的那一轮收成一行。

原运行被删除（随会话一起）时置空。

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN retry_of uuid REFERENCES runs(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN retry_of")
