from pydantic import BaseModel, ConfigDict


class WorkspaceConfigUpdate(BaseModel):
    """All fields optional and independently nullable — sending a field as
    explicit `null` clears that restriction back to unrestricted/platform-
    default; omitting a field leaves it untouched. There is no separate
    "unset" vs "set to null" distinction here on purpose: for this specific
    resource (one row per workspace, PUT-only, no partial-field semantics
    like AgentUpdate/ToolUpdate need) every PUT is a full replace of the
    row's restriction state."""

    allowed_models: list[str] | None = None
    allowed_tool_types: list[str] | None = None
    max_requests_per_minute: int | None = None


class WorkspaceConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed_models: list[str] | None
    allowed_tool_types: list[str] | None
    max_requests_per_minute: int | None
