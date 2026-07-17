import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_api.agents import _actor, _assemble_agent_read, _get_agent_or_404
from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool
from app.models.skills import Skill
from app.models.tools import Tool
from app.principal import Principal, require_role
from app.schemas.agent_transfer import (
    EXPORT_FORMAT,
    AgentExport,
    AgentImportResult,
    ExportedAgentCore,
    ExportedSkill,
    ExportedTool,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/{agent_id}/export", response_model=AgentExport)
async def export_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AgentExport:
    """A self-contained JSON snapshot of one agent: its own config, the *full
    definitions* of every tool/skill it uses (not just references — so the
    file is portable to an environment where those ids don't exist), and its
    sub-agents by name only (importing re-links by name match, or skips)."""
    agent = await _get_agent_or_404(db, agent_id, principal.workspace_id)
    agent_read = await _assemble_agent_read(db, agent)

    tools = []
    for t in agent_read.tools:
        tool_row = await db.get(Tool, t.id)
        if tool_row is not None:
            tools.append(
                ExportedTool(
                    name=tool_row.name,
                    tool_type=tool_row.tool_type,
                    config=tool_row.config,
                    input_schema=tool_row.input_schema,
                    description=tool_row.description,
                )
            )

    skills = []
    for s in agent_read.skills:
        skill_row = await db.get(Skill, s.id)
        if skill_row is not None:
            skills.append(
                ExportedSkill(
                    name=skill_row.name,
                    instruction_text=skill_row.instruction_text,
                    few_shot_examples=skill_row.few_shot_examples,
                    tags=skill_row.tags,
                )
            )

    return AgentExport(
        format=EXPORT_FORMAT,
        agent=ExportedAgentCore(
            name=agent_read.name,
            description=agent_read.description,
            base_instruction=agent_read.base_instruction,
            model_settings=agent_read.model_settings,
            output_schema=agent_read.output_schema,
            output_key=agent_read.output_key,
        ),
        tools=tools,
        skills=skills,
        sub_agent_names=[a.name for a in agent_read.sub_agents],
    )


async def _unique_name(db: AsyncSession, base_name: str, workspace_id: uuid.UUID, model) -> str:
    name = base_name
    suffix = 2
    while (await db.scalar(select(model).where(model.name == name, model.workspace_id == workspace_id))) is not None:
        name = f"{base_name} ({suffix})"
        suffix += 1
    return name


@router.post("/import", response_model=AgentImportResult, status_code=201)
async def import_agent(
    payload: AgentExport,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AgentImportResult:
    """Recreates an agent from an export file. A tool or skill whose *name*
    already matches one in this workspace is reused rather than duplicated;
    otherwise it's created fresh. Sub-agents are matched by name and linked
    if found — if not, they're reported back as missing rather than failing
    the whole import, since the agent is still usable without them."""
    if payload.format != EXPORT_FORMAT:
        raise HTTPException(status_code=422, detail=f"Unrecognized export format: {payload.format}")

    tools_created, tools_reused = [], []
    tool_ids: list[uuid.UUID] = []
    for exported in payload.tools:
        existing = await db.scalar(
            select(Tool).where(Tool.name == exported.name, Tool.workspace_id == principal.workspace_id)
        )
        if existing is not None:
            tool_ids.append(existing.id)
            tools_reused.append(exported.name)
            continue
        tool = Tool(
            name=exported.name,
            tool_type=exported.tool_type,
            config=exported.config,
            input_schema=exported.input_schema,
            description=exported.description,
            created_by=_actor(principal),
            workspace_id=principal.workspace_id,
        )
        db.add(tool)
        await db.flush()
        tool_ids.append(tool.id)
        tools_created.append(exported.name)

    skills_created, skills_reused = [], []
    skill_ids: list[uuid.UUID] = []
    for exported in payload.skills:
        existing = await db.scalar(
            select(Skill).where(Skill.name == exported.name, Skill.workspace_id == principal.workspace_id)
        )
        if existing is not None:
            skill_ids.append(existing.id)
            skills_reused.append(exported.name)
            continue
        skill = Skill(
            name=exported.name,
            instruction_text=exported.instruction_text,
            few_shot_examples=[e.model_dump() for e in exported.few_shot_examples] if exported.few_shot_examples else None,
            tags=exported.tags,
            created_by=_actor(principal),
            workspace_id=principal.workspace_id,
        )
        db.add(skill)
        await db.flush()
        skill_ids.append(skill.id)
        skills_created.append(exported.name)

    sub_agents_linked, sub_agents_missing = [], []
    sub_agent_ids: list[uuid.UUID] = []
    for name in payload.sub_agent_names:
        match = await db.scalar(
            select(Agent).where(Agent.name == name, Agent.workspace_id == principal.workspace_id)
        )
        if match is not None:
            sub_agent_ids.append(match.id)
            sub_agents_linked.append(name)
        else:
            sub_agents_missing.append(name)

    name = await _unique_name(db, payload.agent.name, principal.workspace_id, Agent)
    agent = Agent(
        name=name,
        description=payload.agent.description,
        base_instruction=payload.agent.base_instruction,
        model_config_json=payload.agent.model_settings,
        output_schema=payload.agent.output_schema,
        output_key=payload.agent.output_key,
        created_by=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    db.add(agent)
    await db.flush()

    for tool_id in tool_ids:
        db.add(AgentTool(agent_id=agent.id, tool_id=tool_id))
    for order, skill_id in enumerate(skill_ids):
        db.add(AgentSkill(agent_id=agent.id, skill_id=skill_id, attach_order=order))
    for child_id in sub_agent_ids:
        db.add(AgentSubagent(parent_agent_id=agent.id, child_agent_id=child_id))

    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=agent.id,
        action="create",
        actor=_actor(principal),
        diff={"imported": True, "original_name": payload.agent.name},
        workspace_id=principal.workspace_id,
    )
    await db.commit()

    return AgentImportResult(
        agent_id=str(agent.id),
        agent_name=name,
        tools_created=tools_created,
        tools_reused=tools_reused,
        skills_created=skills_created,
        skills_reused=skills_reused,
        sub_agents_linked=sub_agents_linked,
        sub_agents_missing=sub_agents_missing,
    )
