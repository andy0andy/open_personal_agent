"""知识库文档的内容哈希（积压小问题 C12）：同一内容（SHA-256）不再重复加入，改了名也认得出。

旧文档在这里先为空，之后每次启动在后台给还没有的从原文件补算（从升级前的备份恢复的也补得上）；
原文件读不出来的记个占位（空字符串），不影响别的文档。

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_documents ADD COLUMN content_hash text")
    op.execute(
        "CREATE INDEX knowledge_documents_content_hash ON knowledge_documents (content_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX knowledge_documents_content_hash")
    op.execute("ALTER TABLE knowledge_documents DROP COLUMN content_hash")
