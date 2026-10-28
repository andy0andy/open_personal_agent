"""backend：会话的自定义顺序（左侧拖拽排序）。数字小的在上面；现有会话按最近使用的顺序初始化。

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE threads ADD COLUMN position integer")
    op.execute(
        """
        UPDATE threads t SET position = o.rn
        FROM (SELECT id, row_number() OVER (ORDER BY updated_at DESC) AS rn FROM threads) o
        WHERE t.id = o.id
        """
    )
    op.execute("ALTER TABLE threads ALTER COLUMN position SET DEFAULT 0")
    op.execute("ALTER TABLE threads ALTER COLUMN position SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE threads DROP COLUMN position")
