"""向量列改为 768 维、可空（D28）：向量化改在后端进程里跑 EmbeddingGemma，输出 768 维。

旧向量是另一个模型算的，和新模型的不能比：一律置空，后端启动后在后台用新模型补算
（没有向量的条目只是暂时按意思搜不到，按关键词照常能搜到）。降级改回 1024 维，向量仍为空。

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def _resize(dimensions: int) -> None:
    # 索引建在旧维度上，改类型前要先删；改完再建（空向量不进索引）
    op.execute("DROP INDEX knowledge_items_embedding")
    op.execute("ALTER TABLE knowledge_items ALTER COLUMN embedding DROP NOT NULL")
    op.execute("UPDATE knowledge_items SET embedding = NULL")
    op.execute(f"ALTER TABLE knowledge_items ALTER COLUMN embedding TYPE vector({dimensions})")
    op.execute(
        "CREATE INDEX knowledge_items_embedding ON knowledge_items "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def upgrade() -> None:
    _resize(768)


def downgrade() -> None:
    _resize(1024)
    # 旧代码要求每条都有向量：只有表里没有条目时才能恢复这个约束；有条目时留着可空，
    # 退回旧版本要靠恢复升级前的备份（D28）
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM knowledge_items) THEN "
        "ALTER TABLE knowledge_items ALTER COLUMN embedding SET NOT NULL; END IF; END $$"
    )
