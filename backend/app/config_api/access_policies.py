import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.access_policies import AccessPolicy
from app.principal import Principal, require_role
from app.schemas.access_policies import AccessPolicyCreate, AccessPolicyRead, AccessPolicyUpdate

router = APIRouter(prefix="/access-policies", tags=["access-policies"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


@router.post("", response_model=AccessPolicyRead, status_code=201)
async def create_access_policy(
    payload: AccessPolicyCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AccessPolicy:
    existing = await db.scalar(
        select(AccessPolicy).where(AccessPolicy.name == payload.name, AccessPolicy.workspace_id == principal.workspace_id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"An access policy named '{payload.name}' already exists")
    policy = AccessPolicy(**payload.model_dump(exclude={"workspace_id"}), workspace_id=principal.workspace_id)
    db.add(policy)
    await db.flush()
    await write_audit_log(
        db,
        entity_type="access_policy",
        entity_id=policy.id,
        action="create",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@router.get("", response_model=list[AccessPolicyRead])
async def list_access_policies(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> list[AccessPolicy]:
    result = await db.execute(
        select(AccessPolicy)
        .where(AccessPolicy.workspace_id == principal.workspace_id)
        .order_by(AccessPolicy.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{policy_id}", response_model=AccessPolicyRead)
async def get_access_policy(
    policy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> AccessPolicy:
    policy = await db.get(AccessPolicy, policy_id)
    if policy is None or policy.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Access policy not found")
    return policy


@router.patch("/{policy_id}", response_model=AccessPolicyRead)
async def update_access_policy(
    policy_id: uuid.UUID,
    payload: AccessPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AccessPolicy:
    policy = await db.get(AccessPolicy, policy_id)
    if policy is None or policy.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Access policy not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(policy, key, value)
    await write_audit_log(
        db,
        entity_type="access_policy",
        entity_id=policy.id,
        action="update",
        actor=_actor(principal),
        diff=updates,
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/{policy_id}", status_code=204)
async def delete_access_policy(
    policy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    policy = await db.get(AccessPolicy, policy_id)
    if policy is None or policy.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Access policy not found")
    await write_audit_log(
        db,
        entity_type="access_policy",
        entity_id=policy.id,
        action="delete",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.delete(policy)
    await db.commit()
