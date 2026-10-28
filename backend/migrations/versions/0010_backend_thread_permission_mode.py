"""backend 会话的审批权限（D23）：每次先问 / 只问执行命令 / 跳过所有审批，新会话为每次先问。

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE threads ADD COLUMN permission_mode text NOT NULL DEFAULT 'ask' "
        "CHECK (permission_mode IN ('ask', 'ask_execute', 'skip'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE threads DROP COLUMN permission_mode")
