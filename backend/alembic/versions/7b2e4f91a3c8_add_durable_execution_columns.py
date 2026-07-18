"""add durable execution columns

Revision ID: 7b2e4f91a3c8
Revises: 60a63e1accd8
Create Date: 2026-07-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7b2e4f91a3c8'
down_revision = '60a63e1accd8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("invocation_log_status_check", "invocation_log", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "invocation_log_status_check",
        "invocation_log",
        "status IN ('success', 'error', 'timeout', 'running')",
        schema="agent_forge",
    )
    op.add_column(
        "invocation_log",
        sa.Column("adk_invocation_id", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.add_column(
        "invocation_log",
        sa.Column("adk_session_id", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.add_column(
        "invocation_log",
        sa.Column("adk_user_id", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.add_column(
        "invocation_log",
        sa.Column("adk_app_name", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.create_index(
        "ix_invocation_log_adk_invocation_id",
        "invocation_log",
        ["adk_invocation_id"],
        unique=True,
        schema="agent_forge",
    )

    op.add_column(
        "tool_call_log",
        sa.Column("idempotency_key", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.add_column(
        "tool_call_log",
        sa.Column("replayed", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="agent_forge",
    )
    op.add_column(
        "tool_call_log",
        sa.Column("compensation_status", sa.String(), nullable=True),
        schema="agent_forge",
    )
    op.create_check_constraint(
        "tool_call_log_compensation_status_check",
        "tool_call_log",
        "compensation_status IS NULL OR compensation_status IN ('pending', 'compensated', 'failed')",
        schema="agent_forge",
    )
    op.create_unique_constraint(
        "uq_tool_call_log_invocation_idempotency_key",
        "tool_call_log",
        ["invocation_id", "idempotency_key"],
        schema="agent_forge",
    )

    # Saga/compensation worked example (see app/tool_registry/
    # reservation_demo_tool.py, scripts/seed_reliability_demo.py).
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool', "
        "'data_query_tool', 'self_healing_sql_tool', 'read_scratchpad_tool', 'reservation_demo_tool')",
        schema="agent_forge",
    )
    op.create_table(
        "reliability_demo_inventory",
        sa.Column("item", sa.String(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("item"),
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_table("reliability_demo_inventory", schema="agent_forge")
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool', "
        "'data_query_tool', 'self_healing_sql_tool', 'read_scratchpad_tool')",
        schema="agent_forge",
    )
    op.drop_constraint(
        "uq_tool_call_log_invocation_idempotency_key", "tool_call_log", schema="agent_forge", type_="unique"
    )
    op.drop_constraint(
        "tool_call_log_compensation_status_check", "tool_call_log", schema="agent_forge", type_="check"
    )
    op.drop_column("tool_call_log", "compensation_status", schema="agent_forge")
    op.drop_column("tool_call_log", "replayed", schema="agent_forge")
    op.drop_column("tool_call_log", "idempotency_key", schema="agent_forge")

    op.drop_index("ix_invocation_log_adk_invocation_id", table_name="invocation_log", schema="agent_forge")
    op.drop_column("invocation_log", "adk_app_name", schema="agent_forge")
    op.drop_column("invocation_log", "adk_user_id", schema="agent_forge")
    op.drop_column("invocation_log", "adk_session_id", schema="agent_forge")
    op.drop_column("invocation_log", "adk_invocation_id", schema="agent_forge")
    op.drop_constraint("invocation_log_status_check", "invocation_log", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "invocation_log_status_check",
        "invocation_log",
        "status IN ('success', 'error', 'timeout')",
        schema="agent_forge",
    )
