from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select, within_group
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agents import Agent
from app.models.logs import InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.principal import Principal, require_role
from app.schemas.dashboards import AgentHealthRow, MonitoringSummary, ToolHealthRow

router = APIRouter(prefix="/dashboards/monitoring", tags=["dashboards"])


def _since(window_hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=window_hours)


@router.get("/summary", response_model=MonitoringSummary)
async def monitoring_summary(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> MonitoringSummary:
    since = _since(window_hours)

    row = (
        await db.execute(
            select(
                func.count(InvocationLog.id),
                func.sum(case((InvocationLog.status != "success", 1), else_=0)),
                within_group(func.percentile_cont(0.5), InvocationLog.latency_ms.asc()),
                within_group(func.percentile_cont(0.95), InvocationLog.latency_ms.asc()),
                within_group(func.percentile_cont(0.99), InvocationLog.latency_ms.asc()),
            ).where(
                InvocationLog.created_at >= since,
                InvocationLog.workspace_id == principal.workspace_id,
            )
        )
    ).one()
    total, error_count, p50, p95, p99 = row

    active_agents_count = (
        await db.execute(
            select(func.count(Agent.id)).where(
                Agent.status == "published", Agent.workspace_id == principal.workspace_id
            )
        )
    ).scalar_one()

    return MonitoringSummary(
        total_invocations=total or 0,
        error_rate=(error_count / total) if total else 0.0,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        p99_latency_ms=p99,
        active_agents_count=active_agents_count,
    )


@router.get("/agents", response_model=list[AgentHealthRow])
async def agent_health(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> list[AgentHealthRow]:
    since = _since(window_hours)

    stats_subq = (
        select(
            InvocationLog.agent_id.label("agent_id"),
            func.count(InvocationLog.id).label("invocation_count"),
            func.sum(case((InvocationLog.status != "success", 1), else_=0)).label("error_count"),
            within_group(func.percentile_cont(0.95), InvocationLog.latency_ms.asc()).label("p95_latency_ms"),
            func.max(InvocationLog.created_at).label("last_invocation_at"),
        )
        .where(
            InvocationLog.created_at >= since,
            InvocationLog.workspace_id == principal.workspace_id,
        )
        .group_by(InvocationLog.agent_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.status,
            func.coalesce(stats_subq.c.invocation_count, 0),
            stats_subq.c.error_count,
            stats_subq.c.p95_latency_ms,
            stats_subq.c.last_invocation_at,
        )
        .outerjoin(stats_subq, stats_subq.c.agent_id == Agent.id)
        .where(Agent.workspace_id == principal.workspace_id)
    )

    rows = []
    for agent_id, name, status, invocation_count, error_count, p95, last_invocation_at in result:
        rows.append(
            AgentHealthRow(
                agent_id=agent_id,
                name=name,
                status=status,
                invocation_count=invocation_count,
                error_rate=(error_count / invocation_count) if invocation_count else 0.0,
                p95_latency_ms=p95,
                last_invocation_at=last_invocation_at,
            )
        )

    rows.sort(key=lambda r: (r.error_rate, r.p95_latency_ms or 0), reverse=True)
    return rows


@router.get("/tools", response_model=list[ToolHealthRow])
async def tool_health(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> list[ToolHealthRow]:
    since = _since(window_hours)

    stats_subq = (
        select(
            ToolCallLog.tool_id.label("tool_id"),
            func.count(ToolCallLog.id).label("call_count"),
            func.sum(case((ToolCallLog.status != "success", 1), else_=0)).label("error_count"),
            func.avg(ToolCallLog.latency_ms).label("avg_latency_ms"),
        )
        .where(ToolCallLog.created_at >= since)
        .group_by(ToolCallLog.tool_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Tool.id,
            Tool.name,
            Tool.tool_type,
            func.coalesce(stats_subq.c.call_count, 0),
            stats_subq.c.error_count,
            stats_subq.c.avg_latency_ms,
        )
        .outerjoin(stats_subq, stats_subq.c.tool_id == Tool.id)
        .where(Tool.workspace_id == principal.workspace_id)
    )

    rows = []
    for tool_id, name, tool_type, call_count, error_count, avg_latency in result:
        rows.append(
            ToolHealthRow(
                tool_id=tool_id,
                name=name,
                tool_type=tool_type,
                call_count=call_count,
                error_rate=(error_count / call_count) if call_count else 0.0,
                avg_latency_ms=avg_latency,
            )
        )

    rows.sort(key=lambda r: (r.error_rate, r.avg_latency_ms or 0), reverse=True)
    return rows
