"""Hash-chain functions for this platform's append-only audit tables — used
both at write time and by any migration that backfills existing rows, so
neither ever computes a hash differently than the other. Kept dependency-
free (stdlib only) so Alembic can import it without pulling in the whole app.
"""

import hashlib
import json


def compute_row_hash(
    *,
    prev_hash: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str | None,
    diff: dict | None,
    created_at_iso: str,
) -> str:
    """config_audit_log's hash function specifically — fixed field shape,
    deliberately NOT touched/generalized for reuse by newer chains (see
    compute_event_hash below): every already-written config_audit_log row's
    hash depends on this exact field set/ordering/key-naming, and
    GET /dashboards/audit/verify-chain recomputes it over real historical
    data, so any change here — even a refactor that's supposed to be
    behavior-preserving — risks silently breaking verification for every
    row ever written. Not worth the DRY gain against that risk."""
    payload = json.dumps(
        {
            "prev_hash": prev_hash,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor": actor,
            "diff": diff,
            "created_at": created_at_iso,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def compute_event_hash(*, prev_hash: str | None, **fields: object) -> str:
    """Generic hash-chain link for any OTHER append-only, hash-chained
    table (guardrail_events, policy_events, ...) — each row's hash covers
    its own fields plus the previous row's hash, so altering or deleting
    any past row breaks every hash after it, same tamper-evidence property
    as config_audit_log's chain, just without that one's fixed field
    shape. `fields` should include every column that makes a row unique
    (a timestamp among them) so two rows can never accidentally hash
    identically."""
    payload = json.dumps({"prev_hash": prev_hash, **fields}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
