"""agents 用量不再存费用（设计 2026-10-19 4.11）：只算输入与输出，价格只是模型的资料。

旧的费用数字在 2026-10-19 的整体快照里（降级只加回空列，不恢复旧值）。

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE llm_usage DROP COLUMN cost")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_usage ADD COLUMN cost numeric(12, 6)")
