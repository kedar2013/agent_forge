"""add mysql_query_tool type

Revision ID: a9e21c6b4f7d
Revises: d3a7f2c19e4b
Create Date: 2026-07-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a9e21c6b4f7d'
down_revision = 'd3a7f2c19e4b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool')",
        schema="agent_forge",
    )
