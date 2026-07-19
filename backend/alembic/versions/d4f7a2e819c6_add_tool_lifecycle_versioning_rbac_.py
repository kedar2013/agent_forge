"""add tool lifecycle: versioning, RBAC, output_schema

Revision ID: d4f7a2e819c6
Revises: c2b8e4a97f13
Create Date: 2026-07-19 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd4f7a2e819c6'
down_revision = 'c2b8e4a97f13'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tools', sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='agent_forge')
    op.add_column(
        'tools',
        sa.Column('access_scope', sa.String(), nullable=False, server_default='workspace'),
        schema='agent_forge',
    )
    op.add_column(
        'tools',
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        schema='agent_forge',
    )
    op.create_check_constraint(
        'tools_access_scope_check', 'tools', "access_scope IN ('workspace', 'restricted')", schema='agent_forge'
    )

    op.create_table(
        'tool_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tool_id'], ['agent_forge.tools.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tool_id', 'version', name='tool_versions_tool_id_version_key'),
        schema='agent_forge',
    )

    op.create_table(
        'tool_grants',
        sa.Column('tool_id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('granted_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tool_id'], ['agent_forge.tools.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_forge.agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tool_id', 'agent_id'),
        schema='agent_forge',
    )

    # Seed version 1 for every tool that already exists, so version history
    # is never empty for a pre-existing tool -- its current live config
    # becomes its own recorded starting point.
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO agent_forge.tool_versions (id, tool_id, version, snapshot, created_by, created_at)
        SELECT gen_random_uuid(), id, 1,
               jsonb_build_object(
                   'name', name, 'config', config, 'input_schema', input_schema,
                   'output_schema', output_schema, 'description', description
               ),
               created_by, created_at
        FROM agent_forge.tools
    """))


def downgrade() -> None:
    op.drop_table('tool_grants', schema='agent_forge')
    op.drop_table('tool_versions', schema='agent_forge')
    op.drop_constraint('tools_access_scope_check', 'tools', schema='agent_forge', type_='check')
    op.drop_column('tools', 'current_version', schema='agent_forge')
    op.drop_column('tools', 'access_scope', schema='agent_forge')
    op.drop_column('tools', 'output_schema', schema='agent_forge')
