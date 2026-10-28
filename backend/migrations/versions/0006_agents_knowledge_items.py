"""agents 知识条目表：记忆、文档片段等统一存放（设计文档 8.1、11.1）。

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # document_id 指向文档表（M3b 新建）；来源会话、运行不设外键：删除会话不删它记住的事
    op.execute(
        """
        CREATE TABLE knowledge_items (
            id               uuid PRIMARY KEY,
            user_id          text NOT NULL DEFAULT 'me',
            kind             text NOT NULL CHECK (kind IN ('memory', 'document_chunk')),
            tags             text[] NOT NULL DEFAULT '{}',
            pinned           boolean NOT NULL DEFAULT false,
            content          text NOT NULL,
            document_id      uuid,
            seq              integer,
            section_path     text,
            page             integer,
            source           text NOT NULL CHECK (source IN ('conversation', 'document', 'manual')),
            source_thread_id uuid,
            source_run_id    uuid,
            token_count      integer NOT NULL,
            embedding        vector(1024) NOT NULL,
            embedding_model  text NOT NULL,
            search           tsvector NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),
            updated_at       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX knowledge_items_embedding ON knowledge_items "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX knowledge_items_search ON knowledge_items USING gin (search)")
    op.execute("CREATE INDEX knowledge_items_kind_pinned ON knowledge_items (kind, pinned)")
    op.execute("CREATE INDEX knowledge_items_tags ON knowledge_items USING gin (tags)")


def downgrade() -> None:
    op.execute("DROP TABLE knowledge_items")
