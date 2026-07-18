"""add prompt_eval_runs

Revision ID: 52e3d6262e1b
Revises: 7b2e4f91a3c8
Create Date: 2026-07-18 15:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '52e3d6262e1b'
down_revision = '7b2e4f91a3c8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prompt_eval_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=True),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('agent_name', sa.String(), nullable=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('criteria_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('overall_score', sa.Numeric(5, 1), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('suggested_rewrite', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(), nullable=True),
        sa.Column('judge_error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("scope IN ('static', 'effective')", name='prompt_eval_runs_scope_check'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_forge.agents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        schema='agent_forge',
    )
    op.create_index(
        'ix_prompt_eval_runs_agent_id_created_at',
        'prompt_eval_runs',
        ['agent_id', 'created_at'],
        unique=False,
        schema='agent_forge',
    )


def downgrade() -> None:
    op.drop_index('ix_prompt_eval_runs_agent_id_created_at', table_name='prompt_eval_runs', schema='agent_forge')
    op.drop_table('prompt_eval_runs', schema='agent_forge')
