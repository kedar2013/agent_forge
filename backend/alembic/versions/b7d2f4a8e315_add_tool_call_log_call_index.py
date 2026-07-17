"""add call_index to tool_call_log for debug-console waterfall ordering

Revision ID: b7d2f4a8e315
Revises: a1c3e9d4f210
Create Date: 2026-07-08 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b7d2f4a8e315'
down_revision = 'a1c3e9d4f210'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_call_log", sa.Column("call_index", sa.Integer(), nullable=True), schema="agent_forge")


def downgrade() -> None:
    op.drop_column("tool_call_log", "call_index", schema="agent_forge")
