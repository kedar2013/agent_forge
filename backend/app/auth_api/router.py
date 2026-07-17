import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_users import hash_password, issue_user_token, verify_password
from app.config import get_settings
from app.db import get_db
from app.models.users import SELF_SERVE_ROLES, USER_ROLES, User
from app.models.workspaces import DEFAULT_WORKSPACE_ID
from app.principal import Principal, require_role
from app.rate_limit import rate_limit_by_ip
from app.schemas.users import (
    CreateNamedUserRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UpdateUserRequest,
    UserRead,
    VerifyAdminTokenRequest,
    VerifyAdminTokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201, dependencies=[Depends(rate_limit_by_ip)])
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    """Public self-registration — always creates a PENDING account, never
    auto-approved regardless of role. Self-serve is limited to chat_user
    (default) and developer (SELF_SERVE_ROLES); admin/viewer accounts are
    created directly by an admin via /auth/users, since those roles shouldn't
    be grantable by an anonymous signup form. A developer's account approval
    here is only the first gate — every agent they later try to publish goes
    through its own separate admin-approval queue (see AgentPublishRequest)."""
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if payload.role not in SELF_SERVE_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {', '.join(SELF_SERVE_ROLES)}")

    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        workspace_id=DEFAULT_WORKSPACE_ID,
        status="pending",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/verify-admin-token", response_model=VerifyAdminTokenResponse, dependencies=[Depends(rate_limit_by_ip)]
)
async def verify_admin_token(payload: VerifyAdminTokenRequest) -> VerifyAdminTokenResponse:
    """Server-side counterpart to the admin-token login tab (LoginPage.tsx's
    TokenLoginForm). The token itself must never be checked client-side —
    Vite bakes any VITE_* value into the shipped JS bundle verbatim, so a
    client-side comparison against the real AGENT_FORGE_API_TOKEN would leak
    it to anyone who views the bundle. Same comparison principal.py's
    get_current_principal already does for the Authorization header, just
    reachable as a dedicated pre-flight check the login form can call before
    treating the entered value as a valid credential."""
    if payload.token != get_settings().agent_forge_api_token:
        raise HTTPException(status_code=401, detail="Incorrect admin token")
    return VerifyAdminTokenResponse()


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(rate_limit_by_ip)])
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    email = payload.email.strip().lower()
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if user.status == "pending":
        raise HTTPException(status_code=403, detail="Your account is still waiting for admin approval")
    if user.status == "rejected":
        raise HTTPException(status_code=403, detail="Your account request was not approved")
    return LoginResponse(token=issue_user_token(str(user.id)), email=user.email, role=user.role)


@router.get("/pending", response_model=list[UserRead])
async def list_pending(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(require_role("admin"))
) -> list[User]:
    result = await db.scalars(
        select(User)
        .where(User.status == "pending", User.workspace_id == principal.workspace_id)
        .order_by(User.created_at)
    )
    return list(result)


@router.get("/users", response_model=list[UserRead])
async def list_all_users(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(require_role("admin"))
) -> list[User]:
    result = await db.scalars(
        select(User).where(User.workspace_id == principal.workspace_id).order_by(User.created_at.desc())
    )
    return list(result)


@router.post("/users", response_model=UserRead, status_code=201)
async def create_named_user(
    payload: CreateNamedUserRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> User:
    """An admin directly creates another admin, viewer, or chat_user account —
    pre-approved, no pending queue, since the admin is vouching for them."""
    if payload.role not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {', '.join(USER_ROLES)}")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        soeid=payload.soeid.strip() if payload.soeid else None,
        workspace_id=principal.workspace_id,
        status="approved",
        decided_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> User:
    """Edits an existing account — most commonly to assign/change a user's
    SOEID once it's known, so they can be granted access to whichever
    domain dataset already has a matching persona/coverage row."""
    user = await db.get(User, user_id)
    if user is None or user.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="User not found")
    updates = payload.model_dump(exclude_unset=True)
    if "role" in updates and updates["role"] not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {', '.join(USER_ROLES)}")
    if "soeid" in updates and updates["soeid"]:
        updates["soeid"] = updates["soeid"].strip()
        existing = await db.scalar(select(User).where(User.soeid == updates["soeid"], User.id != user_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"SOEID '{updates['soeid']}' is already assigned to another account")
    for key, value in updates.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/approve", response_model=UserRead)
async def approve_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> User:
    user = await db.get(User, user_id)
    if user is None or user.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = "approved"
    user.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reject", response_model=UserRead)
async def reject_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> User:
    user = await db.get(User, user_id)
    if user is None or user.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = "rejected"
    user.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user
