"""add workspace_config

Revision ID: e8a1c5f930b7
Revises: d4f7a2e819c6
Create Date: 2026-07-19 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e8a1c5f930b7'
down_revision = 'd4f7a2e819c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workspace_config',
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('allowed_models', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('allowed_tool_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('max_requests_per_minute', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['agent_forge.workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('workspace_id'),
        schema='agent_forge',
    )


def downgrade() -> None:
    op.drop_table('workspace_config', schema='agent_forge')
