"""add self_healing_sql_tool and read_scratchpad_tool types

Revision ID: 1c434e403b77
Revises: a1c3e6f9d204
Create Date: 2026-07-16 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '1c434e403b77'
down_revision = 'a1c3e6f9d204'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool', 'data_query_tool', "
        "'self_healing_sql_tool', 'read_scratchpad_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool', 'data_query_tool')",
        schema="agent_forge",
    )
