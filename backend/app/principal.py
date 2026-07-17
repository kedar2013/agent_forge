"""Unified identity for every authenticated request — either a named user
account (admin / viewer / chat_user, real password, real role) or the legacy
static bearer token (a break-glass credential, kept for bootstrap/recovery,
always resolves to admin in the default workspace).

Every router should depend on `require_role(...)` rather than reading
Authorization headers itself, so access control lives in one place.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_users import verify_user_token
from app.config import get_settings
from app.db import get_db
from app.models.users import User
from app.models.workspaces import DEFAULT_WORKSPACE_ID


@dataclass(frozen=True)
class Principal:
    role: str  # "admin" | "viewer" | "chat_user"
    user_id: uuid.UUID | None
    email: str | None
    workspace_id: uuid.UUID
    soeid: str | None = None


async def get_current_principal(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.removeprefix("Bearer ").strip()

    if token == get_settings().agent_forge_api_token:
        return Principal(role="admin", user_id=None, email=None, workspace_id=DEFAULT_WORKSPACE_ID)

    user_id = verify_user_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session — please log in again",
        )
    user = await db.get(User, user_id)
    if user is None or user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not approved")
    return Principal(
        role=user.role, user_id=user.id, email=user.email, workspace_id=user.workspace_id, soeid=user.soeid
    )


def require_role(*roles: str):
    """FastAPI dependency factory: 403s unless the caller's role is one of `roles`."""

    async def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(roles)}",
            )
        return principal

    return _check
