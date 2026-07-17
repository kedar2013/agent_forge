"""debug console: add model_text to agent_event_log event_type check

Revision ID: d8e1b4c7f302
Revises: c7d4a1f9e6b2
Create Date: 2026-07-11 15:10:00.000000

"""
from alembic import op

revision = 'd8e1b4c7f302'
down_revision = 'c7d4a1f9e6b2'
branch_labels = None
depends_on = None

OLD_CHECK = "event_type IN ('transfer', 'orchestrator_hallucination_retry', 'stale_session_retry')"
NEW_CHECK = "event_type IN ('transfer', 'orchestrator_hallucination_retry', 'stale_session_retry', 'model_text')"


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