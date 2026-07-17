import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MonitoringSummary(BaseModel):
    total_invocations: int
    error_rate: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    active_agents_count: int


class AgentHealthRow(BaseModel):
    agent_id: uuid.UUID
    name: str
    status: str
    invocation_count: int
    error_rate: float
    p95_latency_ms: float | None
    last_invocation_at: datetime | None


class ToolHealthRow(BaseModel):
    tool_id: uuid.UUID | None
    name: str
    tool_type: str
    call_count: int
    error_rate: float
    avg_latency_ms: float | None


class UsageSummary(BaseModel):
    total_invocations: int
    total_cost_usd: float
    total_tokens: int
    unique_agents: int


class UsageTimeseriesPoint(BaseModel):
    date: str
    agent_id: uuid.UUID
    agent_name: str
    invocations: int
    cost_usd: float


class AgentUsageRow(BaseModel):
    agent_id: uuid.UUID
    name: str
    invocation_count: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_per_invocation: float


class ToolUsageRow(BaseModel):
    tool_id: uuid.UUID | None
    name: str
    call_count: int
    agent_names: list[str]


class UserUsageRow(BaseModel):
    user_key: str
    email: str | None
    role: str | None
    invocation_count: int
    total_tokens: int
    total_cost_usd: float
    error_count: int
    last_active: datetime | None


class MyUsageDayPoint(BaseModel):
    date: str
    invocations: int
    cost_usd: float


class MyUsageAgentRow(BaseModel):
    agent_name: str
    invocation_count: int
    total_tokens: int
    total_cost_usd: float


class MyUsageSummary(BaseModel):
    total_invocations: int
    total_tokens: int
    total_cost_usd: float
    error_count: int
    last_active: datetime | None
    by_day: list[MyUsageDayPoint]
    by_agent: list[MyUsageAgentRow]


class InvocationAuditRow(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    agent_version: int
    status: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    invoked_by: str | None
    trace_id: str | None
    created_at: datetime


class InvocationDetail(InvocationAuditRow):
    transcript: dict[str, Any] | None
    error_message: str | None


class ConfigAuditRow(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor: str | None
    diff: dict[str, Any] | None
    created_at: datetime


class InvocationListResponse(BaseModel):
    items: list[InvocationAuditRow]
    total: int
    limit: int
    offset: int


class ConfigChangeListResponse(BaseModel):
    items: list[ConfigAuditRow]
    total: int
    limit: int
    offset: int


class RetentionPurgeRequest(BaseModel):
    # None -> settings.data_retention_days. Explicit override lets an admin
    # preview/run a different window without changing the app-wide default.
    retention_days: int | None = None
    # True by default: an admin must deliberately pass dry_run=False to
    # actually delete anything — see app/retention.py's module docstring for
    # why this needs to default to "count only, delete nothing."
    dry_run: bool = True


class RetentionPurgeResponse(BaseModel):
    cutoff: datetime
    dry_run: bool
    invocation_log_rows: int
    scil_rows: dict[str, int]
    chat_sessions: int
