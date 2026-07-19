import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, PrimaryKeyConstraint, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# "workspace" (default): any agent in this tool's own workspace may attach
# and invoke it — exactly today's behavior, zero change for every existing
# tool. "restricted": only an agent with an explicit ToolGrant row may
# attach or invoke it, checked both at attach time (config_api.agents.
# attach_tool) and at runtime (agent_runtime.builder._before_tool_callback,
# defense in depth against a grant revoked after attachment, or a stale
# published snapshot).
TOOL_ACCESS_SCOPES = ("workspace", "restricted")

TOOL_TYPES = (
    "http_tool",
    "sql_tool",
    "mcp_tool",
    "retrieval_tool",
    "image_gen_tool",
    "db_schema_tool",
    "nl2sql_query_tool",
    "mongo_query_tool",
    "mysql_query_tool",
    "data_query_tool",
    # Self-healing execution loop (error reflection): catches a SQL
    # execution/validation error and feeds the raw error text back to the
    # model as the tool's own result, capped at a configurable retry count
    # — see app/tool_registry/self_healing_sql_tool.py.
    "self_healing_sql_tool",
    # Query decomposition: a stateless read of the scratchpad slots
    # self_healing_sql_tool writes to when called with `scratchpad_slot` —
    # see app/tool_registry/read_scratchpad_tool.py.
    "read_scratchpad_tool",
    # Saga/compensation worked example (reserve/release/confirm modes over a
    # tiny demo inventory table) — see app/tool_registry/reservation_demo_tool.py
    # and scripts/seed_reliability_demo.py.
    "reservation_demo_tool",
)


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (
        CheckConstraint(f"tool_type IN {TOOL_TYPES}", name="tools_tool_type_check"),
        CheckConstraint(f"access_scope IN {TOOL_ACCESS_SCOPES}", name="tools_access_scope_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tool_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Optional — validated against on every real tool response (see
    # agent_runtime/builder.py's _build_after_tool_callback); a response
    # that fails validation is replaced with an error rather than passed
    # through, so a malformed/misbehaving tool (or MCP server) can't feed
    # unvalidated shape into the model's context. NULL (the default) is a
    # no-op, same as every other opt-in knob in this codebase.
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    access_scope: Mapped[str] = mapped_column(String, nullable=False, default="workspace")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ToolVersion(Base):
    """Append-only snapshot history for a Tool — one row per meaningful
    change (create, and every update that touches config/input_schema/
    output_schema/description), mirroring AgentVersion's shape/purpose.
    Unlike agents, tools have no separate draft/published state — a Tool
    row IS always "live" — so this is pure history/rollback material, not
    a staging mechanism: `POST /tools/{id}/versions/{version}/rollback`
    restores a past snapshot as the tool's current live config, itself
    recorded as a NEW version rather than reusing the old version number
    (so version numbers are never reused and the history stays linear)."""

    __tablename__ = "tool_versions"
    __table_args__ = (UniqueConstraint("tool_id", "version", name="tool_versions_tool_id_version_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolGrant(Base):
    """Explicit per-agent RBAC grant for a `access_scope="restricted"`
    tool — the tool is invisible to (can't be attached by, and can't be
    invoked by, even if already attached before being restricted) any
    agent without a row here. No-op for the default `access_scope=
    "workspace"` tools, which every agent in the tool's own workspace can
    already use — restricting a tool is what makes these rows start
    mattering."""

    __tablename__ = "tool_grants"
    __table_args__ = (PrimaryKeyConstraint("tool_id", "agent_id"),)

    tool_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    granted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
