"""add policy_events and hash chain to guardrail_events

Revision ID: c2b8e4a97f13
Revises: 9f1a2c7d4e6b
Create Date: 2026-07-19 14:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.audit_hash import compute_event_hash

revision = 'c2b8e4a97f13'
down_revision = '9f1a2c7d4e6b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- policy_events: brand-new, empty table -- no backfill needed -----
    op.create_table(
        'policy_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('seq', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=True),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('agent_name', sa.String(), nullable=True),
        sa.Column('adk_invocation_id', sa.String(), nullable=True),
        sa.Column('tool_name', sa.String(), nullable=False),
        sa.Column('policy_id', sa.UUID(), nullable=True),
        sa.Column('engine', sa.String(), nullable=False),
        sa.Column('persona', sa.String(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('prev_hash', sa.String(), nullable=True),
        sa.Column('row_hash', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agent_forge.agents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['policy_id'], ['agent_forge.access_policies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('seq', name='uq_policy_events_seq'),
        schema='agent_forge',
    )
    op.create_index(
        'ix_policy_events_workspace_id_created_at', 'policy_events', ['workspace_id', 'created_at'],
        unique=False, schema='agent_forge',
    )
    op.create_index(
        'ix_policy_events_agent_id_created_at', 'policy_events', ['agent_id', 'created_at'],
        unique=False, schema='agent_forge',
    )
    op.create_index(
        'ix_policy_events_adk_invocation_id', 'policy_events', ['adk_invocation_id'],
        unique=False, schema='agent_forge',
    )

    # --- guardrail_events: add the hash chain to a table that may already
    # have real rows (unlike policy_events above) -- same backfill approach
    # as b25478ebfb41's config_audit_log chain: assign seq by chronological
    # order, then compute each row's hash in that order.
    op.add_column('guardrail_events', sa.Column('seq', sa.BigInteger(), autoincrement=True, nullable=True), schema='agent_forge')
    op.add_column('guardrail_events', sa.Column('prev_hash', sa.String(), nullable=True), schema='agent_forge')
    op.add_column('guardrail_events', sa.Column('row_hash', sa.String(), nullable=True), schema='agent_forge')

    conn = op.get_bind()
    conn.execute(sa.text("""
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
            FROM agent_forge.guardrail_events
        )
        UPDATE agent_forge.guardrail_events t
        SET seq = ordered.rn
        FROM ordered WHERE t.id = ordered.id
    """))

    existing_rows = conn.execute(sa.text("""
        SELECT id, workspace_id, agent_id, agent_name, adk_invocation_id, direction, check_name, action,
               reason, matched_preview, created_at
        FROM agent_forge.guardrail_events ORDER BY seq
    """)).fetchall()
    prev_hash = None
    for row in existing_rows:
        row_hash = compute_event_hash(
            prev_hash=prev_hash,
            workspace_id=str(row.workspace_id) if row.workspace_id else None,
            agent_id=str(row.agent_id) if row.agent_id else None,
            agent_name=row.agent_name,
            adk_invocation_id=row.adk_invocation_id,
            direction=row.direction,
            check_name=row.check_name,
            action=row.action,
            reason=row.reason,
            matched_preview=row.matched_preview,
            created_at=row.created_at.isoformat(),
        )
        conn.execute(
            sa.text("UPDATE agent_forge.guardrail_events SET prev_hash = :prev, row_hash = :cur WHERE id = :id"),
            {"prev": prev_hash, "cur": row_hash, "id": row.id},
        )
        prev_hash = row_hash

    op.alter_column('guardrail_events', 'seq', nullable=False, schema='agent_forge')
    op.alter_column('guardrail_events', 'row_hash', nullable=False, schema='agent_forge')
    op.create_unique_constraint('uq_guardrail_events_seq', 'guardrail_events', ['seq'], schema='agent_forge')


def downgrade() -> None:
    op.drop_constraint('uq_guardrail_events_seq', 'guardrail_events', schema='agent_forge', type_='unique')
    op.drop_column('guardrail_events', 'row_hash', schema='agent_forge')
    op.drop_column('guardrail_events', 'prev_hash', schema='agent_forge')
    op.drop_column('guardrail_events', 'seq', schema='agent_forge')

    op.drop_index('ix_policy_events_adk_invocation_id', table_name='policy_events', schema='agent_forge')
    op.drop_index('ix_policy_events_agent_id_created_at', table_name='policy_events', schema='agent_forge')
    op.drop_index('ix_policy_events_workspace_id_created_at', table_name='policy_events', schema='agent_forge')
    op.drop_table('policy_events', schema='agent_forge')
