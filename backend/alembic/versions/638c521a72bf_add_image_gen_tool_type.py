"""add image_gen_tool type

Revision ID: 638c521a72bf
Revises: 106c23bffdaf
Create Date: 2026-07-06 15:54:41.289083

"""
from alembic import op
import sqlalchemy as sa


revision = '638c521a72bf'
down_revision = '106c23bffdaf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool')",
        schema="agent_forge",
    )
