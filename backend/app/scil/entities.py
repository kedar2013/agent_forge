"""Entity resolution: the SCIL failure class neither validators.py nor
hallucination.py can see. A data_query_tool call can be perfectly valid SQL
(the SQL validator passes it) and call a real tool (the zero-tool-call
hallucination check passes it too) and STILL be wrong, because the literal
value the model searched for was misspelled ("Tesslla" instead of "Tesla")
and the query legitimately returned zero rows. Closes the gap
app/scil/normalizer.py's docstring names explicitly: "no entity
canonicalization here ... a real entity-canonicalization pass is future
work."

Self-correcting, not a fixed dictionary: `scil_entity_memory` starts empty
per agent and is populated organically from literal values seen in
SUCCESSFUL (>=1 row) data_query_tool calls (remember_entities_fire_and_forget,
called from the same place cache/metrics writes fire from in
playground_api._run_turn). The first time any agent's "Tesla Inc" lookup
succeeds, that string is remembered; every later near-miss for that agent
can be corrected against it. Cold-start (nothing remembered yet) resolves
to no match on purpose -- the agent's own "never guess" instruction (see
e.g. app/domains/credit_facility/seed_agent.py) is exactly the right
fallback until memory exists, which is why this validator only ever fires a
retry when it has a genuine candidate, never on a bare "found nothing".

Matching is a blend of two signals, not sentence-transformer cosine alone.
Measured live against this repo's actual embedder
(sentence-transformers/all-MiniLM-L6-v2):

    cosine("Tesla Inc", "Tesslla")        = 0.135   <- WORSE than...
    cosine("Tesla Inc", "Microsoft Corp") = 0.420   <- ...an unrelated company
    cosine("Tesla Inc", "HDFC Bank Ltd" vs "hdfc bank ltd") = 1.000
    cosine("HDFC Bank Ltd", "HDFC")       = 0.729

MiniLM embeds MEANING, not spelling -- a garbled single token like
"Tesslla" just doesn't land near "Tesla Inc" in embedding space, while it's
exactly right for legitimate semantic/casing variants (abbreviations, case,
suffixes). difflib's character-level ratio is the mirror image: strong on
typos ("Tesla Inc" vs "Tesslla" = 0.625, "Apple Inc" vs "Aple Inc" = 0.941),
weak on abbreviations ("HDFC Bank Ltd" vs "HDFC" = 0.471, worse than
cosine's 0.729). Taking max(cosine, lexical) per candidate is what actually
covers both failure modes; either signal alone misses one of them.
"""

import asyncio
import difflib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.embeddings import embed_text
from app.models.scil import ScilEntityMemory
from app.scil.cache import COSINE_DISTANCE_OP, VECTOR_CAST_TYPE
from app.scil.validators import ValidationResult

logger = logging.getLogger(__name__)

_VALID = ValidationResult(ok=True)

# Below this, "best candidate" is still noise -- a bare zero-row result with
# no confident memory match falls through to the agent's own "ask the user"
# behavior rather than force a retry on a guess.
_MATCH_THRESHOLD = 0.6
# How many nearest-by-cosine candidates to pull from Postgres before
# re-ranking by the blended score in Python -- keeps the lexical pass (which
# can't run in SQL) cheap regardless of how large one agent's memory grows.
_CANDIDATE_LIMIT = 20
_MIN_LITERAL_LEN = 3


@dataclass
class EntityMatch:
    text: str
    score: float


def extract_literal_values(sql: str, dialect: str = "mysql") -> list[str]:
    """String literals anywhere in the query's WHERE clause, '%'-wildcards
    stripped -- deliberately not scoped to a specific column or comparison
    operator (`=` vs `LIKE`) so this works the same for any data_query_tool
    agent regardless of its domain's schema."""
    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return []
    where = parsed.args.get("where") if hasattr(parsed, "args") else None
    if where is None:
        return []
    values: list[str] = []
    for lit in where.find_all(exp.Literal):
        if not lit.is_string:
            continue
        value = lit.this.strip("%").strip()
        if len(value) >= _MIN_LITERAL_LEN:
            values.append(value)
    return values


def _is_empty_data_query_result(tool_call: Any) -> str | None:
    """Returns the tool call's `sql` input if it's a data_query_tool-shaped
    call that executed cleanly but matched zero rows, else None. Structural,
    same convention as validators.py: no knowledge of any specific domain's
    schema, just the {row_count, columns, data, ...} / {"error": ...} shape
    DataQueryTool.run_async always returns."""
    output = getattr(tool_call, "output", None) if not isinstance(tool_call, dict) else tool_call.get("output")
    tool_input = getattr(tool_call, "input", None) if not isinstance(tool_call, dict) else tool_call.get("input")
    if not isinstance(output, dict) or not isinstance(tool_input, dict):
        return None
    if "error" in output or "row_count" not in output:
        return None
    if output.get("row_count") != 0:
        return None
    sql = tool_input.get("sql")
    return sql if isinstance(sql, str) and sql.strip() else None


def _is_nonempty_data_query_result(tool_call: Any) -> str | None:
    output = getattr(tool_call, "output", None) if not isinstance(tool_call, dict) else tool_call.get("output")
    tool_input = getattr(tool_call, "input", None) if not isinstance(tool_call, dict) else tool_call.get("input")
    if not isinstance(output, dict) or not isinstance(tool_input, dict):
        return None
    if "error" in output or "row_count" not in output:
        return None
    if not output.get("row_count"):
        return None
    sql = tool_input.get("sql")
    return sql if isinstance(sql, str) and sql.strip() else None


async def _candidates(session: AsyncSession, agent_id: uuid.UUID, literal: str) -> list[EntityMatch]:
    embedding_literal = "[" + ",".join(str(v) for v in embed_text(literal)) + "]"
    distance_expr = f"entity_embedding {COSINE_DISTANCE_OP} CAST(:embedding AS {VECTOR_CAST_TYPE})"
    rows = (
        await session.execute(
            text(
                f"""
                SELECT entity_text, 1 - ({distance_expr}) AS cosine_similarity
                FROM scil_entity_memory
                WHERE agent_id = :agent_id
                ORDER BY {distance_expr}
                LIMIT :limit
                """
            ),
            {"embedding": embedding_literal, "agent_id": agent_id, "limit": _CANDIDATE_LIMIT},
        )
    ).all()
    out = []
    for row in rows:
        lexical = difflib.SequenceMatcher(None, literal.lower(), row.entity_text.lower()).ratio()
        out.append(EntityMatch(text=row.entity_text, score=max(float(row.cosine_similarity), lexical)))
    out.sort(key=lambda m: m.score, reverse=True)
    return out


async def resolve_entity_mismatch(agent_id: uuid.UUID, tool_calls: list[Any]) -> ValidationResult:
    """Only ever a retry SIGNAL, never a guess itself: fails this attempt
    only when a specific, scored candidate exists in memory for this agent.
    A cold-start zero-row result (nothing remembered yet) passes through
    unflagged -- the agent's own "ask the user to confirm" fallback is
    correct until there's something to correct against. Fails open on any
    lookup error, same posture as every other SCIL I/O path."""
    try:
        async with async_session_factory() as session:
            for call in tool_calls:
                sql = _is_empty_data_query_result(call)
                if sql is None:
                    continue
                for literal in extract_literal_values(sql):
                    candidates = await _candidates(session, agent_id, literal)
                    if not candidates:
                        continue
                    best = candidates[0]
                    if best.score < _MATCH_THRESHOLD or best.text.lower() == literal.lower():
                        continue
                    return ValidationResult(
                        ok=False,
                        error_signature="Entity:NoMatch",
                        error_detail=(
                            f"'{literal}' didn't match any row, but '{best.text}' is a known value for this "
                            f"agent ({best.score:.0%} similar) — retry the lookup using '{best.text}' instead "
                            "of asking the user to confirm, unless the two are clearly different entities."
                        ),
                    )
    except Exception:
        logger.exception("SCIL: entity resolution lookup failed — failing open (leaving the turn unflagged)")
    return _VALID


def remember_entities_fire_and_forget(agent_id: uuid.UUID, tool_calls: list[Any]) -> None:
    asyncio.create_task(_remember_entities(agent_id, tool_calls))


async def _remember_entities(agent_id: uuid.UUID, tool_calls: list[Any]) -> None:
    try:
        literals: set[str] = set()
        for call in tool_calls:
            sql = _is_nonempty_data_query_result(call)
            if sql is None:
                continue
            literals.update(extract_literal_values(sql))
        if not literals:
            return
        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            for literal in literals:
                stmt = pg_insert(ScilEntityMemory).values(
                    agent_id=agent_id,
                    entity_text=literal,
                    entity_embedding=embed_text(literal),
                    use_count=1,
                    last_used_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["agent_id", "entity_text"],
                    set_={"use_count": ScilEntityMemory.use_count + 1, "last_used_at": now},
                )
                await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.exception("SCIL: failed to write entity memory")