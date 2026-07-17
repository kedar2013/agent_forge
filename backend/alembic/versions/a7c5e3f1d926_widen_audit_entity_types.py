"""Widen config_audit_log entity_type check: access_policy + data_entity.

config_api/access_policies.py and config_api/data_entities.py have been
writing audit rows with entity_type="access_policy"/"data_entity" since
they were added, but the CHECK constraint still only allowed
('agent','tool','skill') — so every create/update/delete of an access
policy or data entity through the API failed its COMMIT with a
CheckViolationError (surfacing in the admin UI as "Failed to fetch",
since the unhandled-500 path also lacked CORS headers). Seed scripts
bypass the API, which is why Credit Facility onboarding worked anyway.

Revision ID: a7c5e3f1d926
Revises: f4b8d2e9a713
Create Date: 2026-07-12 10:00:00.000000

"""
from alembic import op

revision = 'a7c5e3f1d926'
down_revision = 'f4b8d2e9a713'
branch_labels = None
depends_on = None

OLD = "entity_type IN ('agent', 'tool', 'skill')"
NEW = "entity_type IN ('agent', 'tool', 'skill', 'access_policy', 'data_entity')"


def upgrade() -> None:
    op.drop_constraint("config_audit_log_entity_type_check", "config_audit_log", schema="agent_forge", type_="check")
    op.create_check_constraint("config_audit_log_entity_type_check", "config_audit_log", NEW, schema="agent_forge")


def downgrade() -> None:
    op.drop_constraint("config_audit_log_entity_type_check", "config_audit_log", schema="agent_forge", type_="check")
    op.create_check_constraint("config_audit_log_entity_type_check", "config_audit_log", OLD, schema="agent_forge")
