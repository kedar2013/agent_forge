"""The self-correction side of SCIL: turning a validation failure into a
structured retry prompt, remembering what fixed it, and recalling that
memory the next time the same class of mistake shows up on a similar
request — so the platform stops paying (in tokens and latency) for the
same error twice.

Used only by playground_api._run_turn's retry loop (the streaming path
deliberately has no retry — same precedent as the existing stale-session /
hallucination self-heals, which also live on the non-streaming path only).
"""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.embeddings import embed_text
from app.models.scil import ScilCorrectionMemory
from app.scil.cache import COSINE_DISTANCE_OP, VECTOR_CAST_TYPE
from app.scil.normalizer import NormalizedRequest

logger = logging.getLogger(__name__)

# Looser than the response cache's 0.80: a correction exemplar is advisory
# context for the retry prompt, not a returned answer, so a near-miss is
# still useful and a false positive costs a few prompt tokens, not a wrong
# answer served to the user.
_KNOWN_CORRECTION_MIN_SIMILARITY = 0.85


async def find_known_correction(
    session: AsyncSession, *, agent_id: uuid.UUID, error_signature: str, normalized: NormalizedRequest
) -> dict[str, Any] | None:
    """Top-1 past correction for the same agent + error class with input
    cosine similarity >= 0.85. Increments reuse_count on a hit, which is
    what the corrections admin API sorts curation decisions by."""
    embedding_literal = "[" + ",".join(str(v) for v in embed_text(normalized.normalized_text)) + "]"
    distance_expr = f"input_embedding {COSINE_DISTANCE_OP} CAST(:embedding AS {VECTOR_CAST_TYPE})"
    row = (
        await session.execute(
            text(
                f"""
                SELECT id, corrected_output, 1 - ({distance_expr}) AS similarity
                FROM scil_correction_memory
                WHERE agent_id = :agent_id AND error_signature = :error_signature
                ORDER BY {distance_expr}
                LIMIT 1
                """
            ),
            {"embedding": embedding_literal, "agent_id": agent_id, "error_signature": error_signature},
        )
    ).first()
    if row is None or row.similarity < _KNOWN_CORRECTION_MIN_SIMILARITY:
        return None
    memory = await session.get(ScilCorrectionMemory, row.id)
    memory.reuse_count += 1
    await session.commit()
    return memory.corrected_output


def build_correction_message(
    *,
    original_message: str,
    failed_output: str,
    error_signature: str,
    error_detail: str,
    known_correction: dict[str, Any] | None = None,
) -> str:
    """The structured feedback sent back to the SAME model as a follow-up
    user turn (the session already contains the original request and the
    failed answer, so this only needs to carry what was wrong and what a
    known-good fix looked like — not re-state the whole task)."""
    parts = [
        "Your previous response failed automated validation and was not delivered to the user.",
        f"Validation error [{error_signature}]: {error_detail}",
        f"Your response was:\n{failed_output}",
    ]
    if known_correction is not None:
        example = known_correction.get("response_text") if isinstance(known_correction, dict) else None
        if example:
            parts.append(
                "A previous, similar request with this same error was successfully corrected to:\n" + str(example)
            )
    parts.append(
        "Produce a corrected response to the original request that fixes this exact error. "
        f"Original request: {original_message}"
    )
    return "\n\n".join(parts)


def save_correction_fire_and_forget(
    *,
    agent_id: uuid.UUID,
    normalized: NormalizedRequest,
    failed_output: dict[str, Any],
    error_signature: str,
    error_detail: str,
    corrected_output: dict[str, Any],
) -> None:
    asyncio.create_task(
        _write_correction(
            agent_id=agent_id,
            normalized=normalized,
            failed_output=failed_output,
            error_signature=error_signature,
            error_detail=error_detail,
            corrected_output=corrected_output,
        )
    )


async def _write_correction(
    *,
    agent_id: uuid.UUID,
    normalized: NormalizedRequest,
    failed_output: dict[str, Any],
    error_signature: str,
    error_detail: str,
    corrected_output: dict[str, Any],
) -> None:
    try:
        async with async_session_factory() as session:
            session.add(
                ScilCorrectionMemory(
                    agent_id=agent_id,
                    input_text=normalized.raw,
                    input_embedding=embed_text(normalized.normalized_text),
                    failed_output=failed_output,
                    error_signature=error_signature,
                    error_detail=error_detail,
                    corrected_output=corrected_output,
                    correction_source="auto_retry",
                )
            )
            await session.commit()
    except Exception:
        logger.exception("SCIL: failed to write correction memory")


async def lookup_known_correction(
    agent_id: uuid.UUID, error_signature: str, normalized: NormalizedRequest
) -> dict[str, Any] | None:
    """Session-owning wrapper for the retry loop (which, like all SCIL I/O
    in playground_api, must not lean on the request-scoped db session)."""
    try:
        async with async_session_factory() as session:
            return await find_known_correction(
                session, agent_id=agent_id, error_signature=error_signature, normalized=normalized
            )
    except Exception:
        logger.exception("SCIL: known-correction lookup failed")
        return None
