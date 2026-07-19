"""Generic hash-chain write + verify helpers for an append-only event table
with its own independent seq/prev_hash/row_hash chain (see app.audit_hash.
compute_event_hash) — guardrail_events, policy_events, and any future one.
Distinct from app.logging_hooks.write_audit_log, which is config_audit_log's
OWN chain with a different, fixed field shape (see audit_hash.compute_row_
hash's docstring for why that one is never generalized) — this is the
generic version for tables that don't share that exact shape.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_hash import compute_event_hash


async def next_chain_link(session: AsyncSession, model: Any, **hash_fields: object) -> tuple[int, str | None, str]:
    """Locks the chain's last row (`SELECT ... FOR UPDATE`, same
    concurrency-safety as `logging_hooks.write_audit_log` — serializes
    concurrent writers so two requests can't compute the same seq/prev_hash
    and silently fork the chain) and returns `(next_seq, prev_hash,
    row_hash)` for a new row about to be inserted with `hash_fields`.
    Model-agnostic on purpose: the caller constructs and adds the actual ORM
    row itself, since GuardrailEvent/PolicyEvent have different column
    shapes beyond the three chain fields this returns."""
    last_row = (
        await session.execute(
            select(model.seq, model.row_hash).order_by(model.seq.desc()).limit(1).with_for_update()
        )
    ).first()
    next_seq = (last_row.seq + 1) if last_row else 1
    prev_hash = last_row.row_hash if last_row else None
    row_hash = compute_event_hash(prev_hash=prev_hash, **hash_fields)
    return next_seq, prev_hash, row_hash


async def verify_event_chain(session: AsyncSession, model: Any, field_names: list[str]) -> dict:
    """Recomputes an event_chain-backed table's hash chain from scratch and
    confirms it matches what's stored — the same tamper-evidence proof
    `dashboards_api.audit.verify_audit_chain` gives config_audit_log,
    generalized. `field_names` must list EXACTLY the fields the table's
    writer passed to `next_chain_link` (see e.g.
    guardrails.service._record_event / tool_registry.policy_audit.
    record_policy_denial) — get this list wrong (missing or extra field)
    and every row will look tampered even though nothing's wrong; a UUID-
    typed field is stringified and a `created_at` field is ISO-formatted
    to match how each writer serializes it before hashing."""
    rows = (await session.execute(select(model).order_by(model.seq.asc()))).scalars().all()
    prev_hash = None
    for idx, row in enumerate(rows):
        fields: dict[str, Any] = {}
        for name in field_names:
            value = getattr(row, name)
            if name == "created_at":
                value = value.isoformat()
            elif isinstance(value, uuid.UUID):
                value = str(value)
            fields[name] = value
        expected = compute_event_hash(prev_hash=prev_hash, **fields)
        if row.prev_hash != prev_hash or row.row_hash != expected:
            return {
                "verified": False,
                "rows_checked": idx,
                "broken_at_seq": row.seq,
                "detail": "Hash mismatch — this row's stored hash doesn't match its recomputed hash, "
                "meaning it (or an earlier row) was altered after being written.",
            }
        prev_hash = row.row_hash
    return {"verified": True, "rows_checked": len(rows), "detail": "Every row's hash checks out."}
