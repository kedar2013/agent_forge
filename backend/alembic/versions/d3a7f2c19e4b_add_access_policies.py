"""add access_policies

Revision ID: d3a7f2c19e4b
Revises: c4e8f1a2b930
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd3a7f2c19e4b'
down_revision = 'c4e8f1a2b930'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'access_policies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resolver_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        schema='agent_forge',
    )
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool')",
        schema="agent_forge",
    )
    op.drop_table('access_policies', schema='agent_forge')
