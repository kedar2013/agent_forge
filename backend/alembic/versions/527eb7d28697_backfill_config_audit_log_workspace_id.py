"""backfill config_audit_log workspace_id

Revision ID: 527eb7d28697
Revises: b25478ebfb41
Create Date: 2026-07-06 22:14:56.625799

"""
from alembic import op
import sqlalchemy as sa

revision = '527eb7d28697'
down_revision = 'b25478ebfb41'
branch_labels = None
depends_on = None

DEFAULT_WORKSPACE_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE agent_forge.config_audit_log SET workspace_id = :ws WHERE workspace_id IS NULL"
        ),
        {"ws": DEFAULT_WORKSPACE_ID},
    )


def downgrade() -> None:
    pass
