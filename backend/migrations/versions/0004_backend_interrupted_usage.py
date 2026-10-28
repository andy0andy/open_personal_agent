"""backend：结束事件（run.finished）的 interrupted 改名为 interrupted_usage，避免与运行状态
interrupted（等待审批，M4）混淆；M1b 之前存下的结束事件补齐 usage / interrupted_usage（值为空）。

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE run_events SET payload = jsonb_set(
            payload,
            '{data}',
            ((payload -> 'data') - 'interrupted') || jsonb_build_object(
                'usage', coalesce(payload -> 'data' -> 'usage', 'null'::jsonb),
                'interrupted_usage', coalesce(payload -> 'data' -> 'interrupted', 'null'::jsonb)
            )
        )
        WHERE type = 'run.finished'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE run_events SET payload = jsonb_set(
            payload,
            '{data}',
            ((payload -> 'data') - 'interrupted_usage') || jsonb_build_object(
                'interrupted', coalesce(payload -> 'data' -> 'interrupted_usage', 'null'::jsonb)
            )
        )
        WHERE type = 'run.finished'
        """
    )
