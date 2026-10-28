"""工具与技能用量（设计 2026-10-23 6.8）：工具每真正执行一次记一行，读技能说明时另记技能名。

独立的表、不设外键（同 llm_usage）：删会话不影响统计。

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE tool_usage ("
        "id bigserial PRIMARY KEY, "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "thread_id uuid, "
        "run_id uuid, "
        "tool text NOT NULL, "
        "skill text)"
    )
    op.execute("CREATE INDEX tool_usage_created_at ON tool_usage (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE tool_usage")
