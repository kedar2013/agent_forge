import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The fixed id of the workspace every pre-existing row (created before
# multi-tenancy was enforced) is backfilled into — a real deployment would
# create additional workspaces through the API as new tenants onboard.
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceConfig(Base):
    """Per-tenant configuration and quotas — one optional row per
    workspace (no row = every field falls back to its platform-wide
    Settings default, exactly today's unrestricted behavior; every
    existing workspace needs zero migration work to keep working
    unchanged). `allowed_models`/`allowed_tool_types` NULL means
    unrestricted (any model/tool type); an empty list is a real, different
    state (nothing allowed) from NULL, not a shorthand for it — a caller
    that wants "restrict to nothing" has to say so explicitly.

    Enforced at CONFIG-WRITE time (config_api/agents.py checks
    allowed_models when an agent's model_config.model is set;
    config_api/tools.py checks allowed_tool_types when a tool is created)
    — not at agent-build/runtime, since a workspace's own admin choosing
    which models/tools their agents may use is a governance decision made
    when the config is authored, not a per-invocation gate."""

    __tablename__ = "workspace_config"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    allowed_models: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    allowed_tool_types: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Overrides Settings.workspace_max_requests_per_minute for just this
    # workspace when set (see app/rate_limit.rate_limit_workspace).
    max_requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
