"""agents 知识库文档登记表；文档片段随文档一起删除（设计文档 8.2、11.1）。

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 来源会话不设外键：删除会话不删除从它加入知识库的文档
    op.execute(
        """
        CREATE TABLE knowledge_documents (
            id               uuid PRIMARY KEY,
            user_id          text NOT NULL DEFAULT 'me',
            title            text NOT NULL,
            filename         text NOT NULL,
            media_type       text NOT NULL,
            size             bigint NOT NULL,
            blob_key         text NOT NULL,
            status           text NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'processing', 'done', 'failed')),
            error            text,
            chunk_total      integer NOT NULL DEFAULT 0,
            item_count       integer NOT NULL DEFAULT 0,
            source_thread_id uuid,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX knowledge_documents_created ON knowledge_documents (created_at)")
    op.execute(
        "ALTER TABLE knowledge_items ADD CONSTRAINT knowledge_items_document_fk "
        "FOREIGN KEY (document_id) REFERENCES knowledge_documents (id) ON DELETE CASCADE"
    )
    op.execute("CREATE INDEX knowledge_items_document_seq ON knowledge_items (document_id, seq)")


def downgrade() -> None:
    op.execute("DROP INDEX knowledge_items_document_seq")
    op.execute("ALTER TABLE knowledge_items DROP CONSTRAINT knowledge_items_document_fk")
    op.execute("DROP TABLE knowledge_documents")
