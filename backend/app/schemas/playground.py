import uuid
from typing import Any

from pydantic import BaseModel


class PlaygroundRunRequest(BaseModel):
    agent_id: uuid.UUID
    message: str
    user_id: str | None = None
    session_id: str | None = None
    state_delta: dict[str, Any] | None = None


class ToolCallTrace(BaseModel):
    name: str
    input: dict[str, Any]
    output: Any


class PlaygroundRunResponse(BaseModel):
    response_text: str
    tool_calls: list[ToolCallTrace]
    latency_ms: int
    session_id: str


class InvokeRequest(BaseModel):
    message: str
    user_id: str | None = None
    session_id: str | None = None
    state_delta: dict[str, Any] | None = None
