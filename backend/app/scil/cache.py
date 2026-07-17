"""Semantic cache read/write -- exact-hash fast path, then pgvector cosine
similarity fallback. Only ever reads/writes rows with validated=True; there
is no real output validator yet (that's a later phase), so "validated" for
this phase means "the call that produced this returned status=success"
(enforced by the caller, app/scil/runner.py, before calling `write`)."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings import embed_text
from app.models.scil import ScilSemanticCache
from app.scil.normalizer import NormalizedRequest

# The app's runtime engine locks search_path to the agent_forge schema only
# (app/db.py) so agent_forge's own tables never collide with StudyBuddy's in
# the same database -- but `CREATE EXTENSION vector` installed the `vector`
# type AND its `<=>` operator into `public` (the extension's default, and
# deliberately left untouched here rather than relocated, since other
# consumers on the same Postgres server may already depend on it living in
# `public`). With `public` excluded from search_path, both need explicit
# qualification: the type via `CAST(x AS public.vector)`, and the operator
# -- which Postgres does NOT resolve just because both operand types are
# qualified -- via `OPERATOR(public.<=>)` syntax. Public (not underscored):
# app/scil/corrector.py's similarity lookup shares these.
VECTOR_CAST_TYPE = "public.vector"
COSINE_DISTANCE_OP = "OPERATOR(public.<=>)"

OUTPUT_TYPE_AGENT_TURN = "agent_turn"


@dataclass
class CacheHit:
    id: int
    output_payload: dict[str, Any]


async def lookup(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    normalized: NormalizedRequest,
    similarity_threshold: float,
    scope_key: str = "",
) -> CacheHit | None:
    now = datetime.now(timezone.utc)
    exact = (
        await session.execute(
            select(ScilSemanticCache)
            .where(
                ScilSemanticCache.agent_id == agent_id,
                ScilSemanticCache.scope_key == scope_key,
                ScilSemanticCache.input_hash == normalized.input_hash,
                ScilSemanticCache.validated.is_(True),
                # Expired rows are simply invisible (not deleted here — the
                # upsert in write() will overwrite them in place on the next
                # validated answer for the same input).
                (ScilSemanticCache.ttl_expires_at.is_(None)) | (ScilSemanticCache.ttl_expires_at > now),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if exact is not None:
        await _record_hit(session, exact)
        return CacheHit(id=exact.id, output_payload=exact.output_payload)

    embedding = embed_text(normalized.normalized_text)
    embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"
    distance_expr = f"input_embedding {COSINE_DISTANCE_OP} CAST(:embedding AS {VECTOR_CAST_TYPE})"
    row = (
        await session.execute(
            text(
                f"""
                SELECT id, output_payload, 1 - ({distance_expr}) AS similarity
                FROM scil_semantic_cache
                WHERE agent_id = :agent_id AND scope_key = :scope_key AND validated IS TRUE
                  AND (ttl_expires_at IS NULL OR ttl_expires_at > now())
                ORDER BY {distance_expr}
                LIMIT 1
                """
            ),
            {"embedding": embedding_literal, "agent_id": agent_id, "scope_key": scope_key},
        )
    ).first()
    if row is None or row.similarity < similarity_threshold:
        return None
    candidate = await session.get(ScilSemanticCache, row.id)
    await _record_hit(session, candidate)
    return CacheHit(id=candidate.id, output_payload=candidate.output_payload)


async def _record_hit(session: AsyncSession, row: ScilSemanticCache) -> None:
    row.hit_count += 1
    row.last_hit_at = datetime.now(timezone.utc)
    await session.commit()


async def write(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    normalized: NormalizedRequest,
    output_payload: dict[str, Any],
    output_type: str = OUTPUT_TYPE_AGENT_TURN,
    ttl_hours: int | None = None,
    scope_key: str = "",
) -> None:
    embedding = embed_text(normalized.normalized_text)
    ttl_expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours) if ttl_hours else None
    stmt = pg_insert(ScilSemanticCache).values(
        agent_id=agent_id,
        scope_key=scope_key,
        input_hash=normalized.input_hash,
        input_text=normalized.raw,
        input_embedding=embedding,
        output_payload=output_payload,
        output_type=output_type,
        ttl_expires_at=ttl_expires_at,
    )
    # Replaces the payload on a repeat cache-miss for the same exact input
    # (e.g. the agent's config changed since the last cached answer, or the
    # previous entry's TTL lapsed) rather than duplicating rows -- matches
    # the unique index on (agent_id, scope_key, input_hash).
    stmt = stmt.on_conflict_do_update(
        index_elements=["agent_id", "scope_key", "input_hash"],
        set_={
            "output_payload": stmt.excluded.output_payload,
            "output_type": stmt.excluded.output_type,
            "input_embedding": stmt.excluded.input_embedding,
            "ttl_expires_at": stmt.excluded.ttl_expires_at,
            "validated": True,
        },
    )
    await session.execute(stmt)
    await session.commit()
