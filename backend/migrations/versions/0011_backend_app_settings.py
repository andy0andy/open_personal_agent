"""backend 设置页的设置（D22）：每个设置键一行，值是 JSON；没存的用代码默认值，同名环境变量优先。

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_settings (
            key         text PRIMARY KEY,
            value       jsonb NOT NULL,
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE app_settings")
