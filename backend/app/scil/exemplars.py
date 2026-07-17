"""Correction-memory-augmented prompting: before an agent's FIRST attempt,
fetch its most-similar past corrections and prepend them as a compact
few-shot block — so a mistake the platform has already paid to discover is
avoided up front instead of recovered from via the (more expensive) retry
loop in app/scil/corrector.py.

Only the message SENT TO THE MODEL carries the block; the transcript,
cache key, and correction-memory embeddings all keep the user's original
message, so exemplar availability never changes what gets cached or how
future similarity lookups behave.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.db import async_session_factory
from app.embeddings import embed_text
from app.scil.cache import COSINE_DISTANCE_OP, VECTOR_CAST_TYPE
from app.scil.normalizer import NormalizedRequest

logger = logging.getLogger(__name__)

_MIN_SIMILARITY = 0.85
# The spec's compact-block budget. Counted in approximate tokens (chars/4)
# — close enough for a cap whose only job is keeping the few-shot block
# from crowding out the actual request.
_DEFAULT_BUDGET_TOKENS = 800


@dataclass
class Exemplar:
    id: int
    input_text: str
    error_signature: str
    error_detail: str
    corrected_text: str
    similarity: float


def _corrected_text(corrected_output: Any) -> str:
    if isinstance(corrected_output, dict):
        text_value = corrected_output.get("response_text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value
    return json.dumps(corrected_output, default=str)


async def fetch_exemplars(
    agent_id: uuid.UUID, normalized: NormalizedRequest, top_k: int
) -> list[Exemplar]:
    """Top-k past corrections for this agent with input cosine similarity
    >= 0.85, most similar first. Increments reuse_count on every returned
    row (the corrections admin API surfaces reuse_count as the curation
    signal for which memories actually earn their keep)."""
    if top_k <= 0:
        return []
    embedding_literal = "[" + ",".join(str(v) for v in embed_text(normalized.normalized_text)) + "]"
    distance_expr = f"input_embedding {COSINE_DISTANCE_OP} CAST(:embedding AS {VECTOR_CAST_TYPE})"
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT id, input_text, error_signature, error_detail, corrected_output,
                               1 - ({distance_expr}) AS similarity
                        FROM scil_correction_memory
                        WHERE agent_id = :agent_id
                        ORDER BY {distance_expr}
                        LIMIT :top_k
                        """
                    ),
                    {"embedding": embedding_literal, "agent_id": agent_id, "top_k": top_k},
                )
            ).fetchall()
            exemplars = [
                Exemplar(
                    id=r.id,
                    input_text=r.input_text,
                    error_signature=r.error_signature,
                    error_detail=r.error_detail,
                    corrected_text=_corrected_text(r.corrected_output),
                    similarity=float(r.similarity),
                )
                for r in rows
                if r.similarity >= _MIN_SIMILARITY
            ]
            if exemplars:
                await session.execute(
                    text("UPDATE scil_correction_memory SET reuse_count = reuse_count + 1 WHERE id = ANY(:ids)"),
                    {"ids": [e.id for e in exemplars]},
                )
                await session.commit()
            return exemplars
    except Exception:
        # Exemplars are an optimization — a lookup failure must never take
        # down the turn it was trying to improve.
        logger.exception("SCIL: exemplar lookup failed")
        return []


def format_exemplar_block(exemplars: list[Exemplar], budget_tokens: int = _DEFAULT_BUDGET_TOKENS) -> str | None:
    """Compact few-shot block, highest-similarity exemplars kept first when
    the budget forces truncation (spec: truncate lowest-similarity first)."""
    if not exemplars:
        return None
    budget_chars = budget_tokens * 4
    parts: list[str] = []
    used = 0
    for ex in sorted(exemplars, key=lambda e: e.similarity, reverse=True):
        entry = (
            f"- Request: {ex.input_text}\n"
            f"  Mistake to avoid [{ex.error_signature}]: {ex.error_detail}\n"
            f"  Correct response: {ex.corrected_text}"
        )
        if used + len(entry) > budget_chars and parts:
            break
        parts.append(entry[: budget_chars - used])
        used += len(entry)
    return (
        "Known corrections from similar past requests — avoid repeating these mistakes:\n"
        + "\n".join(parts)
    )


def apply_exemplars(message: str, block: str | None) -> str:
    if not block:
        return message
    return f"{block}\n\n---\n\n{message}"
