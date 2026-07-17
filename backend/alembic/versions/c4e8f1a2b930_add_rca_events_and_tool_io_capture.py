"""debug console RCA: agent_event_log, error_category, tool call I/O capture

Revision ID: c4e8f1a2b930
Revises: b7d2f4a8e315
Create Date: 2026-07-08 00:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c4e8f1a2b930'
down_revision = 'b7d2f4a8e315'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invocation_log", sa.Column("error_category", sa.String(), nullable=True), schema="agent_forge")
    op.add_column("tool_call_log", sa.Column("input", postgresql.JSONB(), nullable=True), schema="agent_forge")
    op.add_column("tool_call_log", sa.Column("output", postgresql.JSONB(), nullable=True), schema="agent_forge")

    op.create_table(
        "agent_event_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invocation_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_agent", sa.String(), nullable=True),
        sa.Column("to_agent", sa.String(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("offset_ms", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('transfer', 'orchestrator_hallucination_retry', 'stale_session_retry')",
            name="agent_event_log_event_type_check",
        ),
        sa.ForeignKeyConstraint(["invocation_id"], ["agent_forge.invocation_log.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_agent_event_log_invocation_id", "agent_event_log", ["invocation_id"], schema="agent_forge"
    )


def downgrade() -> None:
    op.drop_index("ix_agent_event_log_invocation_id", table_name="agent_event_log", schema="agent_forge")
    op.drop_table("agent_event_log", schema="agent_forge")
    op.drop_column("tool_call_log", "output", schema="agent_forge")
    op.drop_column("tool_call_log", "input", schema="agent_forge")
    op.drop_column("invocation_log", "error_category", schema="agent_forge")
