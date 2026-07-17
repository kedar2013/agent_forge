"""The hash-chain function for config_audit_log — used both at write time
(app/config_api/*) and by the migration that backfills existing rows, so the
two never compute a hash differently. Kept dependency-free (stdlib only) so
Alembic can import it without pulling in the whole app.
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
