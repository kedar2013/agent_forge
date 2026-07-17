"""add developer role, agent publish requests, trace correlation columns

Revision ID: a1c3e9d4f210
Revises: f6f4910b0d9c
Create Date: 2026-07-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a1c3e9d4f210'
down_revision = 'f6f4910b0d9c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- developer role ---------------------------------------------------
    op.drop_constraint("users_role_check", "users", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "users_role_check",
        "users",
        "role IN ('admin', 'viewer', 'chat_user', 'developer')",
        schema="agent_forge",
    )

    # --- agent publish requests (developer publish -> admin approval) -----
    op.create_table(
        "agent_publish_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="agent_publish_requests_status_check"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_agent_publish_requests_agent_id_status",
        "agent_publish_requests",
        ["agent_id", "status"],
        schema="agent_forge",
    )

    # --- trace correlation columns (debug console / OpenTelemetry) --------
    op.add_column("invocation_log", sa.Column("otel_trace_id", sa.String(), nullable=True), schema="agent_forge")
    op.add_column("tool_call_log", sa.Column("agent_name", sa.String(), nullable=True), schema="agent_forge")
    op.add_column("tool_call_log", sa.Column("otel_span_id", sa.String(), nullable=True), schema="agent_forge")


def downgrade() -> None:
    op.drop_column("tool_call_log", "otel_span_id", schema="agent_forge")
    op.drop_column("tool_call_log", "agent_name", schema="agent_forge")
    op.drop_column("invocation_log", "otel_trace_id", schema="agent_forge")

    op.drop_index("ix_agent_publish_requests_agent_id_status", table_name="agent_publish_requests", schema="agent_forge")
    op.drop_table("agent_publish_requests", schema="agent_forge")

    op.drop_constraint("users_role_check", "users", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "users_role_check",
        "users",
        "role IN ('admin', 'viewer', 'chat_user')",
        schema="agent_forge",
    )
