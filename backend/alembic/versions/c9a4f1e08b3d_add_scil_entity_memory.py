"""SCIL: scil_entity_memory — closes the "entity canonicalization is
stubbed" gap (see app/scil/normalizer.py's docstring and the SCIL tech
doc's Known Limitations). Neither the SQL validator nor the zero-tool-call
hallucination check can see "valid SQL, tool executed cleanly, zero rows
because the literal the model searched for was misspelled" — this table is
what app/scil/entities.py reads/writes to catch and self-correct that case.

Revision ID: c9a4f1e08b3d
Revises: b3f7c9d2e841
Create Date: 2026-07-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = 'c9a4f1e08b3d'
down_revision = 'b3f7c9d2e841'
branch_labels = None
depends_on = None

# Matches app/embeddings.py's EMBEDDING_DIM (sentence-transformers/all-MiniLM-L6-v2).
_EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "scil_entity_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # The resolved, canonical string as it appeared in a WHERE-clause
        # literal of a data_query_tool call that returned >=1 row -- e.g.
        # "Tesla Inc", not the misspelled input that failed to match it.
        sa.Column("entity_text", sa.Text(), nullable=False),
        sa.Column("entity_embedding", Vector(_EMBEDDING_DIM), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_entity_memory_agent_id_entity_text",
        "scil_entity_memory", ["agent_id", "entity_text"], schema="agent_forge",
        # One remembered row per (agent, canonical string) -- repeats bump
        # use_count via ON CONFLICT DO UPDATE instead of duplicating rows.
        unique=True,
    )
    op.execute(
        "CREATE INDEX ix_scil_entity_memory_embedding_hnsw ON agent_forge.scil_entity_memory "
        "USING hnsw (entity_embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_forge.ix_scil_entity_memory_embedding_hnsw")
    op.drop_index(
        "ix_scil_entity_memory_agent_id_entity_text", table_name="scil_entity_memory", schema="agent_forge"
    )
    op.drop_table("scil_entity_memory", schema="agent_forge")