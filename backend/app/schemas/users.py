import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    email: str
    password: str
    # Self-serve roles only — "chat_user" (default, chat-only) or "developer"
    # (agent onboarding + chat, every publish still admin-reviewed). admin/
    # viewer are never grantable through public registration.
    role: str = "chat_user"


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str
    role: str


class VerifyAdminTokenRequest(BaseModel):
    token: str


class VerifyAdminTokenResponse(BaseModel):
    role: str = "admin"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    soeid: str | None = None
    role: str
    status: str
    created_at: datetime


class CreateNamedUserRequest(BaseModel):
    """Admin-created account — admin/viewer accounts skip the pending-approval
    queue since an admin is directly vouching for them (unlike public
    self-registration, which is chat_user-only and always starts pending)."""

    email: str
    password: str
    role: str
    soeid: str | None = None


class UpdateUserRequest(BaseModel):
    """Admin edits an existing account after creation — most commonly to
    assign/change the SOEID once it's known, since that's often decided
    after approval rather than at signup."""

    soeid: str | None = None
    role: str | None = None
