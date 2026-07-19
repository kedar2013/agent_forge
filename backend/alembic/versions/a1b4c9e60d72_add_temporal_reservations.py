"""add temporal_reservations

Revision ID: a1b4c9e60d72
Revises: f3d6b8e142a9
Create Date: 2026-07-19 16:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b4c9e60d72'
down_revision = 'f3d6b8e142a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'temporal_reservations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('item', sa.String(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('reserved', 'confirmed', 'released')", name='temporal_reservations_status_check'),
        sa.PrimaryKeyConstraint('id'),
        schema='agent_forge',
    )


def downgrade() -> None:
    op.drop_table('temporal_reservations', schema='agent_forge')
