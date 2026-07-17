"""SCIL: user-scoped cache keys — scope_key on scil_semantic_cache.

For agents whose answers depend on WHO is asking (row-level security via
access_policies, e.g. credit_facility_analyst), a global (agent, question)
cache key would serve one persona's data to another. scope_key carries the
asking user's id when the agent's scil config says cache_scope="user"
(empty string for the default global scope), and joins the unique upsert key.

Revision ID: f4b8d2e9a713
Revises: e2f9a6c1b8d4
Create Date: 2026-07-11 18:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f4b8d2e9a713'
down_revision = 'e2f9a6c1b8d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scil_semantic_cache",
        sa.Column("scope_key", sa.String(), nullable=False, server_default=""),
        schema="agent_forge",
    )
    op.drop_index("ix_scil_semantic_cache_agent_id_input_hash", table_name="scil_semantic_cache", schema="agent_forge")
    op.create_index(
        "ix_scil_semantic_cache_agent_id_scope_input_hash",
        "scil_semantic_cache", ["agent_id", "scope_key", "input_hash"], schema="agent_forge", unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scil_semantic_cache_agent_id_scope_input_hash", table_name="scil_semantic_cache", schema="agent_forge"
    )
    op.create_index(
        "ix_scil_semantic_cache_agent_id_input_hash",
        "scil_semantic_cache", ["agent_id", "input_hash"], schema="agent_forge", unique=True,
    )
    op.drop_column("scil_semantic_cache", "scope_key", schema="agent_forge")
