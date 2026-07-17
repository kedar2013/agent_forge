import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.cache import agent_cache
from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.agents import (
    Agent,
    AgentCollaborator,
    AgentPublishRequest,
    AgentSkill,
    AgentSubagent,
    AgentTool,
    AgentVersion,
)
from app.models.skills import Skill
from app.models.tools import Tool
from app.models.users import User
from app.principal import Principal, require_role
from app.schemas.agents import (
    AddCollaboratorRequest,
    AgentCreate,
    AgentRead,
    AgentUpdate,
    AgentVersionRead,
    AttachSkillRequest,
    AttachSubagentRequest,
    AttachToolRequest,
    CollaboratorEntry,
    PublishRequest,
    PublishRequestRead,
    PublishResult,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


async def _require_can_modify(agent: Agent, principal: Principal, db: AsyncSession) -> None:
    """admin can modify any agent in the workspace. A developer can modify
    agents THEY created, or any agent whose creator has explicitly added
    them as a collaborator (AgentCollaborator) — keeps one developer's
    edits from clobbering another's by default, while still letting an
    author deliberately share edit access with a specific colleague.
    Routes that call this already gated entry with require_role("admin",
    "developer"), so anything reaching here is one of those two roles."""
    if principal.role != "developer" or agent.created_by == _actor(principal):
        return
    is_collaborator = await db.scalar(
        select(AgentCollaborator).where(
            AgentCollaborator.agent_id == agent.id,
            AgentCollaborator.user_email == _actor(principal),
        )
    )
    if is_collaborator is None:
        raise HTTPException(
            status_code=403,
            detail="You can only modify agents you created or were added to as a collaborator",
        )


async def _require_is_owner(agent: Agent, principal: Principal) -> None:
    """Managing WHO can collaborate on an agent is the creator's call alone
    (or an admin's) — a collaborator granted edit access by _require_can_modify
    above must not be able to grant that same access to someone else without
    the author's say-so."""
    if principal.role == "developer" and agent.created_by != _actor(principal):
        raise HTTPException(
            status_code=403, detail="Only this agent's creator can manage its collaborators"
        )


def _build_publish_snapshot(agent_read: AgentRead) -> dict:
    return {
        "name": agent_read.name,
        "description": agent_read.description,
        "base_instruction": agent_read.base_instruction,
        "model_config": agent_read.model_settings,
        "output_schema": agent_read.output_schema,
        "output_key": agent_read.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in agent_read.tools],
        "skills": [
            {"id": str(s.id), "name": s.name, "attach_order": s.attach_order} for s in agent_read.skills
        ],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in agent_read.sub_agents],
    }


async def _assemble_agent_read(db: AsyncSession, agent: Agent) -> AgentRead:
    tools_result = await db.execute(
        select(Tool.id, Tool.name, Tool.tool_type)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(AgentTool.agent_id == agent.id)
    )
    skills_result = await db.execute(
        select(Skill.id, Skill.name, Skill.instruction_text, AgentSkill.attach_order)
        .join(AgentSkill, AgentSkill.skill_id == Skill.id)
        .where(AgentSkill.agent_id == agent.id)
        .order_by(AgentSkill.attach_order)
    )
    subagents_result = await db.execute(
        select(Agent.id, Agent.name)
        .join(AgentSubagent, AgentSubagent.child_agent_id == Agent.id)
        .where(AgentSubagent.parent_agent_id == agent.id)
    )

    return AgentRead(
        id=agent.id,
        workspace_id=agent.workspace_id,
        name=agent.name,
        description=agent.description,
        base_instruction=agent.base_instruction,
        model_config=agent.model_config_json,
        output_schema=agent.output_schema,
        output_key=agent.output_key,
        status=agent.status,
        current_version=agent.current_version,
        created_by=agent.created_by,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        tools=[{"id": r.id, "name": r.name, "tool_type": r.tool_type} for r in tools_result],
        skills=[
            {
                "id": r.id,
                "name": r.name,
                "instruction_text": r.instruction_text,
                "attach_order": r.attach_order,
            }
            for r in skills_result
        ],
        sub_agents=[{"id": r.id, "name": r.name} for r in subagents_result],
    )


async def _get_agent_or_404(db: AsyncSession, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _would_create_cycle(db: AsyncSession, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
    """True if attaching child_id as a sub-agent of parent_id would create a cycle.

    Walks the sub-agent graph starting at child_id: if parent_id is reachable
    (i.e. parent_id is already a descendant of child_id), attaching would close a loop.
    """
    if parent_id == child_id:
        return True

    visited: set[uuid.UUID] = set()
    frontier = [child_id]
    while frontier:
        result = await db.execute(
            select(AgentSubagent.child_agent_id).where(AgentSubagent.parent_agent_id.in_(frontier))
        )
        next_frontier = []
        for (node,) in result:
            if node == parent_id:
                return True
            if node not in visited:
                visited.add(node)
                next_frontier.append(node)
        frontier = next_frontier
    return False


async def _find_ancestor_ids(db: AsyncSession, agent_id: uuid.UUID) -> set[uuid.UUID]:
    """Every agent that has `agent_id` as a descendant, at any depth.

    A published agent's build is cached as a fully-materialized tree — a
    parent's cache entry has its children baked in at build time and isn't
    keyed on the children's versions. Publishing a *child* therefore leaves
    any already-cached *parent* silently serving the old child until the
    parent's own cache entry is separately invalidated too.
    """
    ancestors: set[uuid.UUID] = set()
    frontier = [agent_id]
    while frontier:
        result = await db.execute(
            select(AgentSubagent.parent_agent_id).where(AgentSubagent.child_agent_id.in_(frontier))
        )
        next_frontier = []
        for (node,) in result:
            if node not in ancestors:
                ancestors.add(node)
                next_frontier.append(node)
        frontier = next_frontier
    return ancestors


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> AgentRead:
    # A developer's created_by is always their own identity (never the
    # payload's free-form value) — this is what ownership scoping in
    # _require_can_modify keys off of, so it can't be spoofed at create time.
    created_by = _actor(principal) if principal.role == "developer" else payload.created_by
    agent = Agent(
        name=payload.name,
        description=payload.description,
        base_instruction=payload.base_instruction,
        model_config_json=payload.model_settings.model_dump(),
        output_schema=payload.output_schema,
        output_key=payload.output_key,
        created_by=created_by,
        workspace_id=principal.workspace_id,
    )
    db.add(agent)
    await db.flush()
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent.id,
        action="create",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(agent)
    return await _assemble_agent_read(db, agent)


@router.post("/{agent_id}/clone", response_model=AgentRead, status_code=201)
async def clone_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> AgentRead:
    """Copies an agent's instruction, model settings, and every tool/skill/
    sub-agent attachment into a brand-new draft — a fast starting point for
    building a variant instead of retyping everything. The copy shares the
    same underlying tools/skills/sub-agents (those are reusable by design),
    it just starts as its own independent, unpublished agent."""
    source = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    source_read = await _assemble_agent_read(db, source)

    base_name = f"{source.name} (copy)"
    name = base_name
    suffix = 2
    while (await db.scalar(select(Agent).where(Agent.name == name, Agent.workspace_id == principal.workspace_id))) is not None:
        name = f"{base_name} {suffix}"
        suffix += 1

    clone = Agent(
        name=name,
        description=source.description,
        base_instruction=source.base_instruction,
        model_config_json=source.model_config_json,
        output_schema=source.output_schema,
        output_key=source.output_key,
        created_by=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    db.add(clone)
    await db.flush()

    for tool in source_read.tools:
        db.add(AgentTool(agent_id=clone.id, tool_id=tool.id))
    for skill in source_read.skills:
        db.add(AgentSkill(agent_id=clone.id, skill_id=skill.id, attach_order=skill.attach_order))
    for sub in source_read.sub_agents:
        db.add(AgentSubagent(parent_agent_id=clone.id, child_agent_id=sub.id))

    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=clone.id,
        action="create",
        actor=_actor(principal),
        diff={"cloned_from": str(agent_id)},
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(clone)
    return await _assemble_agent_read(db, clone)


@router.get("", response_model=list[AgentRead])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[AgentRead]:
    result = await db.execute(
        select(Agent).where(Agent.workspace_id == principal.workspace_id).order_by(Agent.created_at.desc())
    )
    agents = result.scalars().all()
    return [await _assemble_agent_read(db, a) for a in agents]


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> AgentRead:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    return await _assemble_agent_read(db, agent)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> AgentRead:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    await _require_can_modify(agent, principal, db)
    updates = payload.model_dump(exclude_unset=True, by_alias=False)
    model_settings = updates.pop("model_settings", None)
    if model_settings is not None:
        agent.model_config_json = model_settings
    for key, value in updates.items():
        setattr(agent, key, value)
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent.id,
        action="update",
        actor=_actor(principal),
        diff=updates,
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(agent)
    return await _assemble_agent_read(db, agent)


@router.post("/{agent_id}/archive", response_model=AgentRead)
async def archive_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> AgentRead:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    await _require_can_modify(agent, principal, db)
    agent.status = "archived"
    agent_cache.invalidate(agent.id)
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent.id,
        action="archive",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(agent)
    return await _assemble_agent_read(db, agent)


@router.post("/{agent_id}/tools", status_code=204)
async def attach_tool(
    agent_id: uuid.UUID,
    payload: AttachToolRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    tool = await db.get(Tool, payload.tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    existing = await db.get(AgentTool, {"agent_id": agent_id, "tool_id": payload.tool_id})
    if existing is None:
        db.add(AgentTool(agent_id=agent_id, tool_id=payload.tool_id))
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent_id,
        action="update",
        actor=_actor(principal),
        diff={"attach_tool": str(payload.tool_id)},
        workspace_id=principal.workspace_id,
    )
    await db.commit()


@router.delete("/{agent_id}/tools/{tool_id}", status_code=204)
async def detach_tool(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    link = await db.get(AgentTool, {"agent_id": agent_id, "tool_id": tool_id})
    if link is not None:
        await db.delete(link)
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent_id,
            action="update",
            actor=_actor(principal),
            diff={"detach_tool": str(tool_id)},
            workspace_id=principal.workspace_id,
        )
        await db.commit()


@router.post("/{agent_id}/skills", status_code=204)
async def attach_skill(
    agent_id: uuid.UUID,
    payload: AttachSkillRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    skill = await db.get(Skill, payload.skill_id)
    if skill is None or skill.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Skill not found")
    existing = await db.get(AgentSkill, {"agent_id": agent_id, "skill_id": payload.skill_id})
    if existing is not None:
        existing.attach_order = payload.attach_order
    else:
        db.add(
            AgentSkill(agent_id=agent_id, skill_id=payload.skill_id, attach_order=payload.attach_order)
        )
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent_id,
        action="update",
        actor=_actor(principal),
        diff={"attach_skill": str(payload.skill_id), "attach_order": payload.attach_order},
        workspace_id=principal.workspace_id,
    )
    await db.commit()


@router.delete("/{agent_id}/skills/{skill_id}", status_code=204)
async def detach_skill(
    agent_id: uuid.UUID,
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    link = await db.get(AgentSkill, {"agent_id": agent_id, "skill_id": skill_id})
    if link is not None:
        await db.delete(link)
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent_id,
            action="update",
            actor=_actor(principal),
            diff={"detach_skill": str(skill_id)},
            workspace_id=principal.workspace_id,
        )
        await db.commit()


@router.post("/{agent_id}/subagents", status_code=204)
async def attach_subagent(
    agent_id: uuid.UUID,
    payload: AttachSubagentRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    child = await db.get(Agent, payload.child_agent_id)
    if child is None or child.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Sub-agent not found")

    if await _would_create_cycle(db, agent_id, payload.child_agent_id):
        raise HTTPException(
            status_code=400,
            detail="Attaching this agent as a sub-agent would create a circular reference",
        )

    existing = await db.get(
        AgentSubagent, {"parent_agent_id": agent_id, "child_agent_id": payload.child_agent_id}
    )
    if existing is None:
        db.add(AgentSubagent(parent_agent_id=agent_id, child_agent_id=payload.child_agent_id))
    agent_cache.invalidate(agent_id)
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent_id,
        action="update",
        actor=_actor(principal),
        diff={"attach_subagent": str(payload.child_agent_id)},
        workspace_id=principal.workspace_id,
    )
    await db.commit()


@router.delete("/{agent_id}/subagents/{child_agent_id}", status_code=204)
async def detach_subagent(
    agent_id: uuid.UUID,
    child_agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    await _require_can_modify(await _get_agent_or_404(db, agent_id, principal.workspace_id), principal, db)
    link = await db.get(
        AgentSubagent, {"parent_agent_id": agent_id, "child_agent_id": child_agent_id}
    )
    if link is not None:
        await db.delete(link)
        agent_cache.invalidate(agent_id)
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent_id,
            action="update",
            actor=_actor(principal),
            diff={"detach_subagent": str(child_agent_id)},
            workspace_id=principal.workspace_id,
        )
        await db.commit()


async def _publish_now(
    db: AsyncSession,
    agent: Agent,
    snapshot: dict,
    published_by: str,
    principal: Principal,
    *,
    extra_diff: dict | None = None,
) -> AgentVersion:
    """The actual "make this version live" step, shared by an admin's direct
    publish, an admin's approval of a developer's publish request, and
    rollback (publishing an old snapshot again)."""
    new_version = agent.current_version if agent.status == "draft" else agent.current_version + 1
    version_row = AgentVersion(
        agent_id=agent.id,
        version=new_version,
        snapshot=snapshot,
        published_by=published_by,
    )
    db.add(version_row)
    agent.current_version = new_version
    agent.status = "published"

    agent_cache.invalidate(agent.id)
    for ancestor_id in await _find_ancestor_ids(db, agent.id):
        agent_cache.invalidate(ancestor_id)

    diff: dict = {"version": new_version, **(extra_diff or {})}
    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent.id,
        action="publish",
        actor=_actor(principal),
        diff=diff,
        workspace_id=principal.workspace_id,
    )
    await db.flush()
    await db.refresh(version_row)
    return version_row


@router.post("/{agent_id}/publish", response_model=PublishResult)
async def publish_agent(
    agent_id: uuid.UUID,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> PublishResult:
    """admin: publishes immediately, exactly like before.
    developer: never publishes directly — instead freezes the current live
    config into a new AgentPublishRequest (status=pending) for an admin to
    review at /agents/publish-requests. See config_api.publish_requests for
    the approve/reject side of this."""
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    await _require_can_modify(agent, principal, db)
    agent_read = await _assemble_agent_read(db, agent)
    snapshot = _build_publish_snapshot(agent_read)

    if principal.role == "developer":
        existing_pending = await db.scalar(
            select(AgentPublishRequest).where(
                AgentPublishRequest.agent_id == agent.id, AgentPublishRequest.status == "pending"
            )
        )
        if existing_pending is not None:
            raise HTTPException(
                status_code=409,
                detail="This agent already has a publish request awaiting admin review",
            )
        request_row = AgentPublishRequest(
            agent_id=agent.id,
            workspace_id=principal.workspace_id,
            snapshot=snapshot,
            status="pending",
            requested_by=_actor(principal),
            requested_by_user_id=principal.user_id,
        )
        db.add(request_row)
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent.id,
            action="update",
            actor=_actor(principal),
            diff={"publish_requested": True},
            workspace_id=principal.workspace_id,
        )
        await db.commit()
        await db.refresh(request_row)
        return PublishResult(status="pending_approval", publish_request=PublishRequestRead.model_validate(request_row))

    version_row = await _publish_now(db, agent, snapshot, payload.published_by or _actor(principal), principal)
    await db.commit()
    return PublishResult(status="published", version=AgentVersionRead.model_validate(version_row))


@router.get("/{agent_id}/versions", response_model=list[AgentVersionRead])
async def list_agent_versions(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[AgentVersion]:
    await _get_agent_or_404(db, agent_id, principal.workspace_id)
    result = await db.execute(
        select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc())
    )
    return list(result.scalars().all())


@router.post("/{agent_id}/versions/{version}/rollback", response_model=AgentVersionRead)
async def rollback_agent(
    agent_id: uuid.UUID,
    version: int,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AgentVersion:
    """Restores the live draft to look like an older published version, then
    publishes that as a brand-new version — history is never overwritten or
    deleted, "rolling back" just means "publish the old thing again." Tools,
    skills, or sub-agents that snapshot referenced but have since been
    deleted are silently skipped rather than failing the whole rollback.

    Deliberately admin-only, unlike the rest of this router's developer
    access: rollback republishes immediately, with no review step — letting
    a developer trigger that would be a way around the publish-approval
    queue entirely."""
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)

    target = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version == version)
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"No version {version} exists for this agent")

    snapshot = target.snapshot
    agent.name = snapshot["name"]
    agent.description = snapshot.get("description")
    agent.base_instruction = snapshot["base_instruction"]
    agent.model_config_json = snapshot["model_config"]
    agent.output_schema = snapshot.get("output_schema")
    agent.output_key = snapshot.get("output_key")

    await db.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
    await db.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent_id))
    await db.execute(delete(AgentSubagent).where(AgentSubagent.parent_agent_id == agent_id))

    tool_ids = [uuid.UUID(t["id"]) for t in snapshot.get("tools", [])]
    if tool_ids:
        existing_tool_ids = (await db.execute(select(Tool.id).where(Tool.id.in_(tool_ids)))).scalars().all()
        for tool_id in existing_tool_ids:
            db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))

    for s in snapshot.get("skills", []):
        skill_id = uuid.UUID(s["id"])
        if await db.get(Skill, skill_id) is not None:
            db.add(AgentSkill(agent_id=agent_id, skill_id=skill_id, attach_order=s["attach_order"]))

    for sub in snapshot.get("sub_agents", []):
        child_id = uuid.UUID(sub["id"])
        if await db.get(Agent, child_id) is not None:
            db.add(AgentSubagent(parent_agent_id=agent_id, child_agent_id=child_id))

    await db.flush()
    await db.refresh(agent)

    agent_read = await _assemble_agent_read(db, agent)
    new_snapshot = _build_publish_snapshot(agent_read)
    version_row = await _publish_now(
        db,
        agent,
        new_snapshot,
        payload.published_by or _actor(principal),
        principal,
        extra_diff={"rolled_back_to_version": version},
    )
    await db.commit()
    return version_row


# --- Collaborators: author-managed edit-access sharing ----------------------


@router.get("/{agent_id}/collaborators", response_model=list[CollaboratorEntry])
async def list_agent_collaborators(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> list[AgentCollaborator]:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    # Visible to admin, the creator, or an existing collaborator (so someone
    # who's been granted access can see who else has it) -- not to every
    # other developer in the workspace.
    if principal.role == "developer" and agent.created_by != _actor(principal):
        await _require_can_modify(agent, principal, db)
    result = await db.execute(
        select(AgentCollaborator)
        .where(AgentCollaborator.agent_id == agent_id)
        .order_by(AgentCollaborator.created_at)
    )
    return list(result.scalars().all())


@router.post("/{agent_id}/collaborators", status_code=204)
async def add_agent_collaborator(
    agent_id: uuid.UUID,
    payload: AddCollaboratorRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    await _require_is_owner(agent, principal)

    target = await db.scalar(
        select(User).where(User.email == payload.user_email, User.workspace_id == principal.workspace_id)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="No user with that email in this workspace")
    if target.role != "developer":
        raise HTTPException(
            status_code=422,
            detail="Only a developer-role user can be added as a collaborator "
            "(admins already have full access; other roles can't edit agents at all)",
        )
    if payload.user_email == agent.created_by:
        raise HTTPException(status_code=422, detail="This agent's creator already has full access")

    existing = await db.get(AgentCollaborator, {"agent_id": agent_id, "user_email": payload.user_email})
    if existing is None:
        db.add(AgentCollaborator(agent_id=agent_id, user_email=payload.user_email, added_by=_actor(principal)))
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent_id,
            action="update",
            actor=_actor(principal),
            diff={"add_collaborator": payload.user_email},
            workspace_id=principal.workspace_id,
        )
        await db.commit()


@router.delete("/{agent_id}/collaborators/{user_email}", status_code=204)
async def remove_agent_collaborator(
    agent_id: uuid.UUID,
    user_email: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "developer")),
) -> None:
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    await _require_is_owner(agent, principal)

    row = await db.get(AgentCollaborator, {"agent_id": agent_id, "user_email": user_email})
    if row is not None:
        await db.delete(row)
        await write_audit_log(
            db,
            entity_type="agent",
            entity_id=agent_id,
            action="update",
            actor=_actor(principal),
            diff={"remove_collaborator": user_email},
            workspace_id=principal.workspace_id,
        )
        await db.commit()
