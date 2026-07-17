"""scil: add hallucination_unresolved to agent_event_log event_type check

Revision ID: b3f7c9d2e841
Revises: a7c5e3f1d926
Create Date: 2026-07-12 21:00:00.000000

"""
from alembic import op

revision = 'b3f7c9d2e841'
down_revision = 'a7c5e3f1d926'
branch_labels = None
depends_on = None

OLD_CHECK = "event_type IN ('transfer', 'orchestrator_hallucination_retry', 'stale_session_retry', 'model_text')"
NEW_CHECK = (
    "event_type IN ('transfer', 'orchestrator_hallucination_retry', 'stale_session_retry', "
    "'model_text', 'hallucination_unresolved')"
)


def upgrade() -> None:
    op.drop_constraint("agent_event_log_event_type_check", "agent_event_log", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "agent_event_log_event_type_check", "agent_event_log", NEW_CHECK, schema="agent_forge"
    )


def downgrade() -> None:
    op.drop_constraint("agent_event_log_event_type_check", "agent_event_log", schema="agent_forge", type_="check")
    op.create_check_constraint(
        "agent_event_log_event_type_check", "agent_event_log", OLD_CHECK, schema="agent_forge"
    )
