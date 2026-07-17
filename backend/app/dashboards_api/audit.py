import csv
import io
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit_hash import compute_row_hash
from app.db import get_db
from app.models.agents import Agent
from app.models.logs import ConfigAuditLog, InvocationLog
from app.principal import Principal, require_role
from app.schemas.dashboards import (
    ConfigAuditRow,
    ConfigChangeListResponse,
    InvocationAuditRow,
    InvocationDetail,
    InvocationListResponse,
)

router = APIRouter(prefix="/dashboards/audit", tags=["dashboards"])


def _invocation_filters(
    query,
    agent_id: uuid.UUID | None,
    status: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
):
    if agent_id:
        query = query.where(InvocationLog.agent_id == agent_id)
    if status:
        query = query.where(InvocationLog.status == status)
    if from_date:
        query = query.where(InvocationLog.created_at >= from_date)
    if to_date:
        query = query.where(InvocationLog.created_at <= to_date)
    return query


async def _fetch_invocations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    status: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[InvocationAuditRow], int]:
    base = (
        select(InvocationLog, Agent.name)
        .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
        .where(InvocationLog.workspace_id == workspace_id)
    )
    base = _invocation_filters(base, agent_id, status, from_date, to_date)

    count_query = select(func.count()).select_from(base.with_only_columns(InvocationLog.id).subquery())
    total = (await db.execute(count_query)).scalar_one()

    result = await db.execute(
        base.order_by(InvocationLog.created_at.desc()).limit(limit).offset(offset)
    )
    rows = [
        InvocationAuditRow(
            id=inv.id,
            agent_id=inv.agent_id,
            agent_name=agent_name,
            agent_version=inv.agent_version,
            status=inv.status,
            latency_ms=inv.latency_ms,
            input_tokens=inv.input_tokens,
            output_tokens=inv.output_tokens,
            estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
            invoked_by=inv.invoked_by,
            trace_id=inv.trace_id,
            created_at=inv.created_at,
        )
        for inv, agent_name in result
    ]
    return rows, total


@router.get("/invocations", response_model=InvocationListResponse)
async def list_invocations(
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> InvocationListResponse:
    rows, total = await _fetch_invocations(
        db,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return InvocationListResponse(items=rows, total=total, limit=limit, offset=offset)


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


# Registered before /invocations/{invocation_id} — Starlette matches routes in
# registration order, and a path-param route would otherwise swallow "export"
# as if it were a UUID.
@router.get("/invocations/export")
async def export_invocations(
    format: Literal["csv", "json"] = "csv",
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> StreamingResponse:
    rows, _ = await _fetch_invocations(
        db,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=10_000,
        offset=0,
    )
    data = [r.model_dump(mode="json") for r in rows]

    if format == "json":
        import json

        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=invocations.json"},
        )

    return StreamingResponse(
        iter([_to_csv(data)]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invocations.csv"},
    )


@router.get("/invocations/{invocation_id}", response_model=InvocationDetail)
async def get_invocation(
    invocation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> InvocationDetail:
    result = await db.execute(
        select(InvocationLog, Agent.name)
        .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
        .where(InvocationLog.id == invocation_id, InvocationLog.workspace_id == principal.workspace_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Invocation not found")
    inv, agent_name = row
    return InvocationDetail(
        id=inv.id,
        agent_id=inv.agent_id,
        agent_name=agent_name,
        agent_version=inv.agent_version,
        status=inv.status,
        latency_ms=inv.latency_ms,
        input_tokens=inv.input_tokens,
        output_tokens=inv.output_tokens,
        estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
        invoked_by=inv.invoked_by,
        trace_id=inv.trace_id,
        created_at=inv.created_at,
        transcript=inv.transcript,
        error_message=inv.error_message,
    )


async def _fetch_config_changes(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[ConfigAuditRow], int]:
    base = select(ConfigAuditLog).where(ConfigAuditLog.workspace_id == workspace_id)
    if entity_type:
        base = base.where(ConfigAuditLog.entity_type == entity_type)
    if entity_id:
        base = base.where(ConfigAuditLog.entity_id == entity_id)
    if from_date:
        base = base.where(ConfigAuditLog.created_at >= from_date)
    if to_date:
        base = base.where(ConfigAuditLog.created_at <= to_date)

    count_query = select(func.count()).select_from(base.with_only_columns(ConfigAuditLog.id).subquery())
    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(base.order_by(ConfigAuditLog.created_at.desc()).limit(limit).offset(offset))
    rows = [
        ConfigAuditRow(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            action=row.action,
            actor=row.actor,
            diff=row.diff,
            created_at=row.created_at,
        )
        for (row,) in result
    ]
    return rows, total


@router.get("/config-changes", response_model=ConfigChangeListResponse)
async def list_config_changes(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> ConfigChangeListResponse:
    rows, total = await _fetch_config_changes(
        db,
        workspace_id=principal.workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return ConfigChangeListResponse(items=rows, total=total, limit=limit, offset=offset)


@router.get("/config-changes/export")
async def export_config_changes(
    format: Literal["csv", "json"] = "csv",
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> StreamingResponse:
    rows, _ = await _fetch_config_changes(
        db,
        workspace_id=principal.workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        from_date=from_date,
        to_date=to_date,
        limit=10_000,
        offset=0,
    )
    data = [r.model_dump(mode="json") for r in rows]

    if format == "json":
        import json

        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=config_changes.json"},
        )

    return StreamingResponse(
        iter([_to_csv(data)]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=config_changes.csv"},
    )


@router.get("/verify-chain")
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    """Recomputes the config_audit_log hash chain from scratch and confirms it
    matches what's stored — proof the append-only audit trail hasn't been
    edited or had rows deleted out from under it."""
    result = await db.execute(select(ConfigAuditLog).order_by(ConfigAuditLog.seq.asc()))
    rows = result.scalars().all()

    prev_hash = None
    for row in rows:
        expected = compute_row_hash(
            prev_hash=prev_hash,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id),
            action=row.action,
            actor=row.actor,
            diff=row.diff,
            created_at_iso=row.created_at.isoformat(),
        )
        if row.prev_hash != prev_hash or row.row_hash != expected:
            return {
                "verified": False,
                "rows_checked": rows.index(row),
                "broken_at_seq": row.seq,
                "detail": "Hash mismatch — this row's stored hash doesn't match its recomputed hash, "
                "meaning it (or an earlier row) was altered after being written.",
            }
        prev_hash = row.row_hash

    return {"verified": True, "rows_checked": len(rows), "detail": "Every row's hash checks out."}
