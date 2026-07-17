import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.agents import Agent
from app.models.logs import InvocationLog, ToolCallLog
from app.models.tools import Tool
from app.models.users import User
from app.principal import Principal, require_role
from app.schemas.dashboards import (
    AgentUsageRow,
    ToolUsageRow,
    UsageSummary,
    UsageTimeseriesPoint,
    UserUsageRow,
)

router = APIRouter(prefix="/dashboards/usage", tags=["dashboards"])


def _since(range_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=range_days)


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


@router.get("/summary", response_model=UsageSummary)
async def usage_summary(
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> UsageSummary:
    since = _since(range_days)
    query = select(
        func.count(InvocationLog.id),
        func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
        func.coalesce(
            func.sum(func.coalesce(InvocationLog.input_tokens, 0) + func.coalesce(InvocationLog.output_tokens, 0)),
            0,
        ),
        func.count(func.distinct(InvocationLog.agent_id)),
    ).where(
        InvocationLog.created_at >= since,
        InvocationLog.workspace_id == principal.workspace_id,
    )
    if principal.role == "developer":
        # Admin/viewer see the whole workspace; a developer sees costs
        # scoped to only the agents THEY created — this dashboard exists so
        # a developer can see what their own Playground/BYOK usage is
        # costing, not everyone else's.
        query = query.join(Agent, Agent.id == InvocationLog.agent_id).where(Agent.created_by == _actor(principal))
    row = (await db.execute(query)).one()
    total, total_cost, total_tokens, unique_agents = row
    return UsageSummary(
        total_invocations=total or 0,
        total_cost_usd=float(total_cost or 0),
        total_tokens=int(total_tokens or 0),
        unique_agents=unique_agents or 0,
    )


@router.get("/timeseries", response_model=list[UsageTimeseriesPoint])
async def usage_timeseries(
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[UsageTimeseriesPoint]:
    since = _since(range_days)
    day = func.date_trunc("day", InvocationLog.created_at).label("day")

    query = (
        select(
            day,
            InvocationLog.agent_id,
            Agent.name,
            func.count(InvocationLog.id),
            func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
        )
        .join(Agent, Agent.id == InvocationLog.agent_id)
        .where(
            InvocationLog.created_at >= since,
            InvocationLog.workspace_id == principal.workspace_id,
        )
    )
    if principal.role == "developer":
        query = query.where(Agent.created_by == _actor(principal))
    result = await db.execute(query.group_by(day, InvocationLog.agent_id, Agent.name).order_by(day))

    return [
        UsageTimeseriesPoint(
            date=d.strftime("%Y-%m-%d"),
            agent_id=agent_id,
            agent_name=name,
            invocations=count,
            cost_usd=float(cost),
        )
        for d, agent_id, name, count, cost in result
    ]


@router.get("/agents", response_model=list[AgentUsageRow])
async def agent_usage(
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[AgentUsageRow]:
    since = _since(range_days)

    query = (
        select(
            Agent.id,
            Agent.name,
            func.count(InvocationLog.id),
            func.coalesce(
                func.sum(func.coalesce(InvocationLog.input_tokens, 0) + func.coalesce(InvocationLog.output_tokens, 0)),
                0,
            ),
            func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
        )
        .join(InvocationLog, InvocationLog.agent_id == Agent.id)
        .where(
            InvocationLog.created_at >= since,
            Agent.workspace_id == principal.workspace_id,
        )
    )
    if principal.role == "developer":
        query = query.where(Agent.created_by == _actor(principal))
    result = await db.execute(query.group_by(Agent.id, Agent.name))

    rows = []
    for agent_id, name, count, tokens, cost in result:
        cost = float(cost)
        rows.append(
            AgentUsageRow(
                agent_id=agent_id,
                name=name,
                invocation_count=count,
                total_tokens=int(tokens),
                total_cost_usd=cost,
                avg_cost_per_invocation=(cost / count) if count else 0.0,
            )
        )
    rows.sort(key=lambda r: r.total_cost_usd, reverse=True)
    return rows


@router.get("/tools", response_model=list[ToolUsageRow])
async def tool_usage(
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[ToolUsageRow]:
    since = _since(range_days)

    query = (
        select(Tool.id, Tool.name, Agent.name)
        .select_from(ToolCallLog)
        .join(Tool, Tool.id == ToolCallLog.tool_id)
        .join(InvocationLog, InvocationLog.id == ToolCallLog.invocation_id)
        .outerjoin(Agent, Agent.id == InvocationLog.agent_id)
        .where(
            ToolCallLog.created_at >= since,
            Tool.workspace_id == principal.workspace_id,
        )
    )
    if principal.role == "developer":
        # The outerjoin means a tool call with no agent_id would otherwise
        # slip through unfiltered -- Agent.created_by is NULL for those, so
        # this condition correctly excludes them too (not attributable to
        # this developer either).
        query = query.where(Agent.created_by == _actor(principal))
    result = await db.execute(query)

    call_counts: dict = {}
    agent_names: dict = {}
    tool_names: dict = {}
    for tool_id, tool_name, agent_name in result:
        call_counts[tool_id] = call_counts.get(tool_id, 0) + 1
        tool_names[tool_id] = tool_name
        if agent_name:
            agent_names.setdefault(tool_id, set()).add(agent_name)

    rows = [
        ToolUsageRow(
            tool_id=tool_id,
            name=tool_names[tool_id],
            call_count=count,
            agent_names=sorted(agent_names.get(tool_id, [])),
        )
        for tool_id, count in call_counts.items()
    ]
    rows.sort(key=lambda r: r.call_count, reverse=True)
    return rows


@router.get("/users", response_model=list[UserUsageRow])
async def user_usage(
    range_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> list[UserUsageRow]:
    """Usage grouped by whoever triggered each run — `invoked_by` is a plain
    string (a real user's id for /chat callers, or a caller label like
    "playground-user" / "external-caller" for the admin-facing surfaces), so
    the join to `users` happens in Python rather than risking a SQL cast
    error on values that were never a UUID to begin with."""
    since = _since(range_days)

    result = await db.execute(
        select(
            InvocationLog.invoked_by,
            func.count(InvocationLog.id),
            func.coalesce(
                func.sum(func.coalesce(InvocationLog.input_tokens, 0) + func.coalesce(InvocationLog.output_tokens, 0)),
                0,
            ),
            func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
            func.sum(case((InvocationLog.status != "success", 1), else_=0)),
            func.max(InvocationLog.created_at),
        )
        .where(
            InvocationLog.created_at >= since,
            InvocationLog.workspace_id == principal.workspace_id,
            InvocationLog.invoked_by.is_not(None),
        )
        .group_by(InvocationLog.invoked_by)
    )
    grouped = result.all()

    user_ids: list[uuid.UUID] = []
    for invoked_by, *_ in grouped:
        try:
            user_ids.append(uuid.UUID(invoked_by))
        except (ValueError, AttributeError):
            continue

    users_by_id: dict[uuid.UUID, User] = {}
    if user_ids:
        user_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in user_result.scalars().all()}

    rows = []
    for invoked_by, count, tokens, cost, error_count, last_active in grouped:
        user = None
        try:
            user = users_by_id.get(uuid.UUID(invoked_by))
        except (ValueError, AttributeError):
            pass
        rows.append(
            UserUsageRow(
                user_key=invoked_by,
                email=user.email if user else None,
                role=user.role if user else None,
                invocation_count=count,
                total_tokens=int(tokens),
                total_cost_usd=float(cost),
                error_count=error_count or 0,
                last_active=last_active,
            )
        )
    rows.sort(key=lambda r: r.invocation_count, reverse=True)
    return rows
