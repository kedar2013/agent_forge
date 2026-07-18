import uuid
from datetime import datetime

from pydantic import BaseModel


class DurableRunEntry(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None
    status: str
    adk_session_id: str | None
    adk_invocation_id: str | None
    error_category: str | None
    error_message: str | None
    invoked_by: str | None
    created_at: datetime
    age_seconds: float
    # True once a 'running' row has sat longer than the staleness threshold
    # the list endpoint was called with — a real in-flight request just
    # hasn't finished yet; a stale one almost certainly means the process
    # that owned it died before it could reach its final status update.
    is_stale: bool


class DurableRunListResponse(BaseModel):
    items: list[DurableRunEntry]
    total: int
    limit: int
    offset: int


class DurableRunResumeResponse(BaseModel):
    id: uuid.UUID
    status: str
    response_text: str | None
    error_message: str | None


class CircuitBreakerEntry(BaseModel):
    key: str
    state: str
    consecutive_failures: int
    cooldown_remaining_seconds: float | None
