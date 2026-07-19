"""add guardrail_events

Revision ID: 9f1a2c7d4e6b
Revises: 52e3d6262e1b
Create Date: 2026-07-19 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '9f1a2c7d4e6b'
down_revision = '52e3d6262e1b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'guardrail_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=True),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('agent_name', sa.String(), nullable=True),
        sa.Column('adk_invocation_id', sa.String(), nullable=True),
        sa.Column('direction', sa.String(), nullable=False),
        sa.Column('check_name', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('matched_preview', sa.Text(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("direction IN ('input', 'output')", name='guardrail_events_direction_check'),
        sa.CheckConstraint("action IN ('block', 'redact')", name='guardrail_events_action_check'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_forge.agents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        schema='agent_forge',
    )
    op.create_index(
        'ix_guardrail_events_workspace_id_created_at',
        'guardrail_events',
        ['workspace_id', 'created_at'],
        unique=False,
        schema='agent_forge',
    )
    op.create_index(
        'ix_guardrail_events_agent_id_created_at',
        'guardrail_events',
        ['agent_id', 'created_at'],
        unique=False,
        schema='agent_forge',
    )
    op.create_index(
        'ix_guardrail_events_adk_invocation_id',
        'guardrail_events',
        ['adk_invocation_id'],
        unique=False,
        schema='agent_forge',
    )


def downgrade() -> None:
    op.drop_index('ix_guardrail_events_adk_invocation_id', table_name='guardrail_events', schema='agent_forge')
    op.drop_index('ix_guardrail_events_agent_id_created_at', table_name='guardrail_events', schema='agent_forge')
    op.drop_index('ix_guardrail_events_workspace_id_created_at', table_name='guardrail_events', schema='agent_forge')
    op.drop_table('guardrail_events', schema='agent_forge')
