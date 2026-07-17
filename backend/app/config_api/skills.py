import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.skills import Skill, SkillCollaborator
from app.models.users import User
from app.principal import Principal, require_role
from app.schemas.skills import (
    AddCollaboratorRequest,
    CollaboratorEntry,
    SkillCreate,
    SkillRead,
    SkillUpdate,
)

router = APIRouter(prefix="/skills", tags=["skills"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


def _dump(payload: SkillCreate | SkillUpdate) -> dict:
    data = payload.model_dump(exclude_unset=isinstance(payload, SkillUpdate))
    if data.get("few_shot_examples") is not None:
        data["few_shot_examples"] = [ex if isinstance(ex, dict) else ex.model_dump() for ex in data["few_shot_examples"]]
    return data


async def _require_can_modify(skill: Skill, principal: Principal, db: AsyncSession) -> None:
    """Same rule as config_api.agents._require_can_modify: admin can modify
    any skill in the workspace; a developer can modify skills THEY created,
    or one whose creator explicitly added them as a collaborator."""
    if principal.role != "developer" or skill.created_by == _actor(principal):
        return
    is_collaborator = await db.scalar(
        select(SkillCollaborator).where(
            SkillCollaborator.skill_id == skill.id,
            SkillCollaborator.user_email == _actor(principal),
        )
    )
    if is_collaborator is None:
        raise HTTPException(
            status_code=403,
            detail="You can only modify skills you created or were added to as a collaborator",
        )


async def _require_is_owner(skill: Skill, principal: Principal) -> None:
    if principal.role == "developer" and skill.created_by != _actor(principal):
        raise HTTPException(
            status_code=403, detail="Only this skill's creator can manage its collaborators"
        )


@router.post("", response_model=SkillRead, status_code=201)
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> Skill:
    skill_data = _dump(payload)
    skill_data.pop("workspace_id", None)
    # A developer's created_by is always their own identity (never the
    # payload's free-form value) — same anti-spoofing rule as
    # config_api.agents.create_agent, and what _require_can_modify keys off.
    if principal.role == "developer":
        skill_data["created_by"] = _actor(principal)
    skill = Skill(**skill_data, workspace_id=principal.workspace_id)
    db.add(skill)
    await db.flush()
    await write_audit_log(
        db,
        entity_type="skill",
        entity_id=skill.id,
        action="create",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(skill)
    return skill


@router.get("", response_model=list[SkillRead])
async def list_skills(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[Skill]:
    result = await db.execute(
        select(Skill).where(Skill.workspace_id == principal.workspace_id).order_by(Skill.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.patch("/{skill_id}", response_model=SkillRead)
async def update_skill(
    skill_id: uuid.UUID,
    payload: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    await _require_can_modify(skill, principal, db)
    updates = _dump(payload)
    for key, value in updates.items():
        setattr(skill, key, value)
    await write_audit_log(
        db,
        entity_type="skill",
        entity_id=skill.id,
        action="update",
        actor=_actor(principal),
        diff=updates,
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    await _require_can_modify(skill, principal, db)
    await write_audit_log(
        db,
        entity_type="skill",
        entity_id=skill.id,
        action="delete",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.delete(skill)
    await db.commit()


# --- Collaborators: author-managed edit-access sharing ----------------------


@router.get("/{skill_id}/collaborators", response_model=list[CollaboratorEntry])
async def list_skill_collaborators(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> list[SkillCollaborator]:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    if principal.role == "developer" and skill.created_by != _actor(principal):
        await _require_can_modify(skill, principal, db)
    result = await db.execute(
        select(SkillCollaborator)
        .where(SkillCollaborator.skill_id == skill_id)
        .order_by(SkillCollaborator.created_at)
    )
    return list(result.scalars().all())


@router.post("/{skill_id}/collaborators", status_code=204)
async def add_skill_collaborator(
    skill_id: uuid.UUID,
    payload: AddCollaboratorRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    await _require_is_owner(skill, principal)

    target = await db.scalar(
        select(User).where(User.email == payload.user_email, User.workspace_id == principal.workspace_id)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="No user with that email in this workspace")
    if target.role != "developer":
        raise HTTPException(
            status_code=422,
            detail="Only a developer-role user can be added as a collaborator "
            "(admins already have full access; other roles can't edit skills at all)",
        )
    if payload.user_email == skill.created_by:
        raise HTTPException(status_code=422, detail="This skill's creator already has full access")

    existing = await db.get(SkillCollaborator, {"skill_id": skill_id, "user_email": payload.user_email})
    if existing is None:
        db.add(SkillCollaborator(skill_id=skill_id, user_email=payload.user_email, added_by=_actor(principal)))
        await write_audit_log(
            db,
            entity_type="skill",
            entity_id=skill_id,
            action="update",
            actor=_actor(principal),
            diff={"add_collaborator": payload.user_email},
            workspace_id=principal.workspace_id,
        )
        await db.commit()


@router.delete("/{skill_id}/collaborators/{user_email}", status_code=204)
async def remove_skill_collaborator(
    skill_id: uuid.UUID,
    user_email: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    await _require_is_owner(skill, principal)

    row = await db.get(SkillCollaborator, {"skill_id": skill_id, "user_email": user_email})
    if row is not None:
        await db.delete(row)
        await write_audit_log(
            db,
            entity_type="skill",
            entity_id=skill_id,
            action="update",
            actor=_actor(principal),
            diff={"remove_collaborator": user_email},
            workspace_id=principal.workspace_id,
        )
        await db.commit()
