"""SCIL: eval framework -- golden-question regression suite
(scil_eval_cases/scil_eval_runs) plus sampled live-traffic groundedness
scoring (scil_groundedness_samples). Adds the deterministic-ish, ongoing
correctness signal that scil_metrics/scil_correction_memory don't cover:
those two only ever see traffic that actually happened and only flag what
a configured validator can detect; this closes the gap for (a) known
questions that must keep working across a prompt/tool/config change, and
(b) passive sampling of real traffic for ungrounded answers on agents that
haven't opted into the blocking, retry-triggering
hallucination_groundedness_check.

Revision ID: a1c3e6f9d204
Revises: c9a4f1e08b3d
Create Date: 2026-07-14 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c3e6f9d204'
down_revision = 'c9a4f1e08b3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scil_eval_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_criteria", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_eval_cases_agent_id", "scil_eval_cases", ["agent_id"], schema="agent_forge"
    )

    op.create_table(
        "scil_eval_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("actual_response", sa.Text(), nullable=False),
        sa.Column("judge_reasoning", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["agent_forge.scil_eval_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_eval_runs_agent_id_batch_id", "scil_eval_runs", ["agent_id", "batch_id"], schema="agent_forge"
    )

    op.create_table(
        "scil_groundedness_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_groundedness_samples_agent_id_created_at",
        "scil_groundedness_samples", ["agent_id", "created_at"], schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_index("ix_scil_groundedness_samples_agent_id_created_at", table_name="scil_groundedness_samples", schema="agent_forge")
    op.drop_table("scil_groundedness_samples", schema="agent_forge")
    op.drop_index("ix_scil_eval_runs_agent_id_batch_id", table_name="scil_eval_runs", schema="agent_forge")
    op.drop_table("scil_eval_runs", schema="agent_forge")
    op.drop_index("ix_scil_eval_cases_agent_id", table_name="scil_eval_cases", schema="agent_forge")
    op.drop_table("scil_eval_cases", schema="agent_forge")