import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.workspaces import DEFAULT_WORKSPACE_ID

USER_STATUSES = ("pending", "approved", "rejected")
# "developer" can onboard agents/sub-agents and use chat, but every agent they
# publish still needs an admin's sign-off (see AgentPublishRequest) — their own
# account approval (this table's `status`) is a separate, earlier gate.
USER_ROLES = ("admin", "viewer", "chat_user", "developer")
# Roles grantable via public self-registration (POST /auth/register). admin/
# viewer stay admin-only-creatable (see auth_api.create_named_user) since
# nobody should be able to self-serve their way into config/read access.
SELF_SERVE_ROLES = ("chat_user", "developer")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"status IN {USER_STATUSES}", name="users_status_check"),
        CheckConstraint(f"role IN {USER_ROLES}", name="users_role_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Corporate/employee id (e.g. "aa12345") — admin-assigned, optional. The
    # identity domain-owned data (persona/coverage tables) key their rows by,
    # via an access_policy's resolver_config["identity_state_key"], instead
    # of this account's own opaque `id` — lets an admin grant a real Agent Forge
    # user access to an existing domain dataset just by matching an id that
    # already means something outside this platform, rather than needing the
    # domain's own data reseeded per Agent Forge UUID.
    soeid: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default="chat_user")
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=DEFAULT_WORKSPACE_ID)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
