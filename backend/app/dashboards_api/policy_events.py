"""Read-only visibility into policy_events (see app/tool_registry/policy_
audit.py) — every DENIED access_policy decision, from either the Python
engine or OPA. Sibling to dashboards_api/guardrails.py in every respect
(same "only the exception is interesting" — an allow writes nothing here —
same independent hash chain)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.event_chain import verify_event_chain
from app.models.guardrails import PolicyEvent
from app.principal import Principal, require_role
from app.schemas.dashboards import PolicyEventListResponse, PolicyEventRow

router = APIRouter(prefix="/dashboards/policy-events", tags=["dashboards"])

# Must exactly match the fields tool_registry.policy_audit.record_policy_
# denial passes to next_chain_link — see app.event_chain.verify_event_
# chain's docstring for why this list has to be exact.
_HASH_FIELDS = [
    "workspace_id",
    "agent_id",
    "agent_name",
    "adk_invocation_id",
    "tool_name",
    "policy_id",
    "engine",
    "persona",
    "reason",
    "created_at",
]


@router.get("", response_model=PolicyEventListResponse)
async def list_policy_events(
    agent_id: uuid.UUID | None = None,
    engine: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> PolicyEventListResponse:
    query = select(PolicyEvent).where(PolicyEvent.workspace_id == principal.workspace_id)
    if agent_id:
        query = query.where(PolicyEvent.agent_id == agent_id)
    if engine:
        query = query.where(PolicyEvent.engine == engine)
    if from_date:
        query = query.where(PolicyEvent.created_at >= from_date)
    if to_date:
        query = query.where(PolicyEvent.created_at <= to_date)

    count_query = select(func.count()).select_from(query.with_only_columns(PolicyEvent.id).subquery())
    total = (await db.execute(count_query)).scalar_one()

    result = await db.execute(query.order_by(PolicyEvent.created_at.desc()).limit(limit).offset(offset))
    items = [
        PolicyEventRow(
            id=row.id,
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            adk_invocation_id=row.adk_invocation_id,
            tool_name=row.tool_name,
            policy_id=row.policy_id,
            engine=row.engine,
            persona=row.persona,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]
    return PolicyEventListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/verify-chain")
async def verify_policy_events_chain(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    return await verify_event_chain(db, PolicyEvent, _HASH_FIELDS)
