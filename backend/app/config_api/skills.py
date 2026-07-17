import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.skills import Skill
from app.principal import Principal, require_role
from app.schemas.skills import SkillCreate, SkillRead, SkillUpdate

router = APIRouter(prefix="/skills", tags=["skills"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


def _dump(payload: SkillCreate | SkillUpdate) -> dict:
    data = payload.model_dump(exclude_unset=isinstance(payload, SkillUpdate))
    if data.get("few_shot_examples") is not None:
        data["few_shot_examples"] = [ex if isinstance(ex, dict) else ex.model_dump() for ex in data["few_shot_examples"]]
    return data


@router.post("", response_model=SkillRead, status_code=201)
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> Skill:
    skill_data = _dump(payload)
    skill_data.pop("workspace_id", None)
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
