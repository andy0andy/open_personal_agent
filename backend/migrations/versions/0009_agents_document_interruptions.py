"""agents 知识库文档：处理时服务中断的次数（连续中断两次就标为失败，不在每次启动时重做）。

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_documents ADD COLUMN interruptions integer NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_documents DROP COLUMN interruptions")
