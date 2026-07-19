"""Read-only visibility into guardrail_events (see app/guardrails/) — the
audit trail an admin/compliance reviewer needs to answer "what did the
guardrails actually catch, and did any of it look like a real attack vs
noise." Deliberately list-only for now: there is no "override/allow this
verdict" action here, since a guardrail verdict is already enforced and
recorded at the moment it happened (see guardrails.service._record_event) —
this endpoint only ever reads it back.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.event_chain import verify_event_chain
from app.models.guardrails import GuardrailEvent
from app.principal import Principal, require_role
from app.schemas.dashboards import GuardrailEventListResponse, GuardrailEventRow

router = APIRouter(prefix="/dashboards/guardrails", tags=["dashboards"])

# Must exactly match the fields guardrails.service._record_event passes to
# next_chain_link (and the c2b8e4a97f13 migration's backfill) — see
# app.event_chain.verify_event_chain's docstring for why this list has to
# be exact, not just "close enough".
_HASH_FIELDS = [
    "workspace_id",
    "agent_id",
    "agent_name",
    "adk_invocation_id",
    "direction",
    "check_name",
    "action",
    "reason",
    "matched_preview",
    "created_at",
]


@router.get("/events", response_model=GuardrailEventListResponse)
async def list_guardrail_events(
    agent_id: uuid.UUID | None = None,
    direction: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> GuardrailEventListResponse:
    query = select(GuardrailEvent).where(GuardrailEvent.workspace_id == principal.workspace_id)
    if agent_id:
        query = query.where(GuardrailEvent.agent_id == agent_id)
    if direction:
        query = query.where(GuardrailEvent.direction == direction)
    if from_date:
        query = query.where(GuardrailEvent.created_at >= from_date)
    if to_date:
        query = query.where(GuardrailEvent.created_at <= to_date)

    count_query = select(func.count()).select_from(query.with_only_columns(GuardrailEvent.id).subquery())
    total = (await db.execute(count_query)).scalar_one()

    result = await db.execute(query.order_by(GuardrailEvent.created_at.desc()).limit(limit).offset(offset))
    items = [
        GuardrailEventRow(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            adk_invocation_id=row.adk_invocation_id,
            direction=row.direction,
            check_name=row.check_name,
            action=row.action,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]
    return GuardrailEventListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/verify-chain")
async def verify_guardrail_events_chain(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    """Same tamper-evidence proof as GET /dashboards/audit/verify-chain,
    for guardrail_events' own independent hash chain (see
    app.event_chain.verify_event_chain)."""
    return await verify_event_chain(db, GuardrailEvent, _HASH_FIELDS)
