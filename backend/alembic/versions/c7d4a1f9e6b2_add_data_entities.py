"""add data_entities and data_query_tool type

Revision ID: c7d4a1f9e6b2
Revises: b6f3e08c2a51
Create Date: 2026-07-11 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c7d4a1f9e6b2'
down_revision = 'b6f3e08c2a51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'data_entities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('connection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('source', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('default_sort', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_limit', sa.Integer(), nullable=False),
        sa.Column('max_limit', sa.Integer(), nullable=False),
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
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool', 'data_query_tool')",
        schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_constraint("tools_tool_type_check", "tools", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "tools_tool_type_check",
        "tools",
        "tool_type IN ('http_tool', 'sql_tool', 'mcp_tool', 'retrieval_tool', 'image_gen_tool', "
        "'db_schema_tool', 'nl2sql_query_tool', 'mongo_query_tool', 'mysql_query_tool')",
        schema="agent_forge",
    )
    op.drop_table('data_entities', schema='agent_forge')
