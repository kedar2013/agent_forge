"""SCIL (Self-Correcting Intelligence Layer): pgvector extension +
scil_semantic_cache, scil_correction_memory, scil_metrics tables

Revision ID: e2f9a6c1b8d4
Revises: d8e1b4c7f302
Create Date: 2026-07-11 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = 'e2f9a6c1b8d4'
down_revision = 'd8e1b4c7f302'
branch_labels = None
depends_on = None

# Matches app/embeddings.py's EMBEDDING_DIM (sentence-transformers/all-MiniLM-L6-v2).
# No other migration in this repo has enabled pgvector before -- the existing
# RAG feature (retrieval_tool.py) points at an externally-provisioned database
# that already has it, so this is the first CREATE EXTENSION for it here.
_EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "scil_semantic_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("input_embedding", Vector(_EMBEDDING_DIM), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_type", sa.String(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ttl_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_semantic_cache_agent_id_input_hash",
        "scil_semantic_cache", ["agent_id", "input_hash"], schema="agent_forge",
        # unique: exact-match cache key -- also lets cache.write() upsert via
        # ON CONFLICT (agent_id, input_hash) instead of risking duplicate
        # rows from two concurrent cache misses on the same input.
        unique=True,
    )
    op.execute(
        "CREATE INDEX ix_scil_semantic_cache_embedding_hnsw ON agent_forge.scil_semantic_cache "
        "USING hnsw (input_embedding vector_cosine_ops)"
    )

    op.create_table(
        "scil_correction_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("input_embedding", Vector(_EMBEDDING_DIM), nullable=False),
        sa.Column("failed_output", postgresql.JSONB(), nullable=False),
        sa.Column("error_signature", sa.String(), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("corrected_output", postgresql.JSONB(), nullable=False),
        sa.Column("correction_source", sa.String(), nullable=False),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "correction_source IN ('auto_retry', 'hitl', 'user_feedback')",
            name="scil_correction_memory_source_check",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agent_forge.agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.execute(
        "CREATE INDEX ix_scil_correction_memory_embedding_hnsw ON agent_forge.scil_correction_memory "
        "USING hnsw (input_embedding vector_cosine_ops)"
    )
    op.create_index(
        "ix_scil_correction_memory_agent_id_error_signature",
        "scil_correction_memory", ["agent_id", "error_signature"], schema="agent_forge",
    )

    op.create_table(
        "scil_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="agent_forge",
    )
    op.create_index(
        "ix_scil_metrics_agent_id_created_at", "scil_metrics", ["agent_id", "created_at"], schema="agent_forge",
    )


def downgrade() -> None:
    op.drop_index("ix_scil_metrics_agent_id_created_at", table_name="scil_metrics", schema="agent_forge")
    op.drop_table("scil_metrics", schema="agent_forge")

    op.drop_index(
        "ix_scil_correction_memory_agent_id_error_signature", table_name="scil_correction_memory", schema="agent_forge"
    )
    op.execute("DROP INDEX IF EXISTS agent_forge.ix_scil_correction_memory_embedding_hnsw")
    op.drop_table("scil_correction_memory", schema="agent_forge")

    op.execute("DROP INDEX IF EXISTS agent_forge.ix_scil_semantic_cache_embedding_hnsw")
    op.drop_index(
        "ix_scil_semantic_cache_agent_id_input_hash", table_name="scil_semantic_cache", schema="agent_forge"
    )
    op.drop_table("scil_semantic_cache", schema="agent_forge")

    # Extension isn't dropped -- other objects/sessions may depend on it, and
    # CREATE EXTENSION IF NOT EXISTS on a future upgrade is a safe no-op either way.
