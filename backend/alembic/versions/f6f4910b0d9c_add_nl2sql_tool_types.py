"""add nl2sql tool types

Revision ID: f6f4910b0d9c
Revises: 527eb7d28697
Create Date: 2026-07-06 23:18:15.706153

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6f4910b0d9c'
down_revision = '527eb7d28697'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool')",
        schema="agent_forge",
    )
