"""记忆的可疑标记（设计 2026-10-23 6.6）：像是写给智能体的指令的记忆不进提示词、不进检索。

suspicious：命中的那一类（没命中为空）；trusted：你在知识库页点过"确认无害"。
旧条目都没有标记、未确认，照常可用。

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_items ADD COLUMN suspicious text, "
        "ADD COLUMN trusted boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_items DROP COLUMN suspicious, DROP COLUMN trusted")
