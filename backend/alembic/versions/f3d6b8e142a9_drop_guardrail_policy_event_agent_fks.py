"""drop guardrail/policy event agent/policy foreign keys

Revision ID: f3d6b8e142a9
Revises: e8a1c5f930b7
Create Date: 2026-07-19 16:10:00.000000

An agent/policy deletion's ON DELETE SET NULL was silently rewriting a
column that's already baked into an EARLIER row's row_hash -- turning a
legitimate config-cleanup cascade into what verify_event_chain correctly
reports as tampering (found live: cleaning up test-suite-generated agents
broke the policy_events chain by nulling out agent_id on rows whose hash
was computed with the real id). guardrail_events/policy_events.agent_id
and policy_events.policy_id become plain UUID columns, resolved at query
time only -- same soft-reference pattern config_audit_log.entity_id
already uses, for the same reason: an audit trail's rows must never be
mutated by something else's delete.
"""
from alembic import op

revision = 'f3d6b8e142a9'
down_revision = 'e8a1c5f930b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('guardrail_events_agent_id_fkey', 'guardrail_events', schema='agent_forge', type_='foreignkey')
    op.drop_constraint('policy_events_agent_id_fkey', 'policy_events', schema='agent_forge', type_='foreignkey')
    op.drop_constraint('policy_events_policy_id_fkey', 'policy_events', schema='agent_forge', type_='foreignkey')


def downgrade() -> None:
    op.create_foreign_key(
        'policy_events_policy_id_fkey', 'policy_events', 'access_policies', ['policy_id'], ['id'],
        source_schema='agent_forge', referent_schema='agent_forge', ondelete='SET NULL',
    )
    op.create_foreign_key(
        'policy_events_agent_id_fkey', 'policy_events', 'agents', ['agent_id'], ['id'],
        source_schema='agent_forge', referent_schema='agent_forge', ondelete='SET NULL',
    )
    op.create_foreign_key(
        'guardrail_events_agent_id_fkey', 'guardrail_events', 'agents', ['agent_id'], ['id'],
        source_schema='agent_forge', referent_schema='agent_forge', ondelete='SET NULL',
    )
