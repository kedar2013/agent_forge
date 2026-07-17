import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

AGENT_STATUSES = ("draft", "published", "archived")
PUBLISH_REQUEST_STATUSES = ("pending", "approved", "rejected")


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(f"status IN {AGENT_STATUSES}", name="agents_status_check"),
        Index("ix_agents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    model_config_json: Mapped[dict] = mapped_column("model_config", JSONB, nullable=False)
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_key: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="agent_versions_agent_id_version_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_by: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTool(Base):
    __tablename__ = "agent_tools"
    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "tool_id"),
        Index("ix_agent_tools_tool_id", "tool_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE")
    )


class AgentSkill(Base):
    __tablename__ = "agent_skills"
    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "skill_id"),
        Index("ix_agent_skills_skill_id", "skill_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE")
    )
    attach_order: Mapped[int] = mapped_column(Integer, default=0)


class AgentSubagent(Base):
    __tablename__ = "agent_subagents"
    __table_args__ = (
        PrimaryKeyConstraint("parent_agent_id", "child_agent_id"),
        CheckConstraint("parent_agent_id != child_agent_id", name="agent_subagents_no_self_ref"),
    )

    parent_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    child_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )


class AgentPublishRequest(Base):
    """A developer's request to publish an agent. Unlike an admin (who
    publishes immediately — see config_api.agents.publish_agent), a developer's
    publish attempt freezes the current live config into `snapshot` right here
    and waits for an admin to approve/reject it. Approving publishes EXACTLY
    this snapshot (not whatever the live draft has drifted to by review time),
    so what the admin reviewed is what goes live."""

    __tablename__ = "agent_publish_requests"
    __table_args__ = (
        CheckConstraint(f"status IN {PUBLISH_REQUEST_STATUSES}", name="agent_publish_requests_status_check"),
        Index("ix_agent_publish_requests_agent_id_status", "agent_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
