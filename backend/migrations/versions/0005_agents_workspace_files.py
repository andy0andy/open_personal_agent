"""agents 工作区文件表：会话里的上传与产物（设计文档 9.3、11.1）。

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 会话不设外键（threads 归 backend 所有）：删除会话时由运行管理一并删除这些记录
    op.execute(
        """
        CREATE TABLE workspace_files (
            id          uuid PRIMARY KEY,
            user_id     text NOT NULL DEFAULT 'me',
            thread_id   uuid NOT NULL,
            path        text NOT NULL,
            source      text NOT NULL CHECK (source IN ('upload', 'output')),
            media_type  text NOT NULL,
            size        bigint NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (thread_id, path)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_files")
