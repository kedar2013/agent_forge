import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.access_policies import AccessPolicy
from app.models.agents import Agent
from app.models.data_entities import DataEntity
from app.models.tools import Tool, ToolGrant, ToolVersion
from app.principal import Principal, require_role
from app.tenancy import require_tool_type_allowed
from app.schemas.tools import (
    ToolCreate,
    ToolGrantCreate,
    ToolGrantRead,
    ToolRead,
    ToolUpdate,
    ToolVersionRead,
)

router = APIRouter(prefix="/tools", tags=["tools"])

# Fields a new ToolVersion snapshot is taken over -- config/input_schema/
# output_schema/description are what actually changes a tool's behavior;
# name/access_scope changes go through config_audit_log (write_audit_log)
# like every other field, but don't warrant their own version snapshot.
_VERSIONED_FIELDS = ("config", "input_schema", "output_schema", "description")


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


async def _snapshot_tool_version(db: AsyncSession, tool: Tool, actor: str) -> None:
    tool.current_version += 1
    db.add(
        ToolVersion(
            tool_id=tool.id,
            version=tool.current_version,
            snapshot={
                "name": tool.name,
                "config": tool.config,
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
                "description": tool.description,
            },
            created_by=actor,
        )
    )


def _compose_schema_description(entity: DataEntity) -> str:
    """Turns a DataEntity's field list into the schema context an LLM needs
    to write correct SQL against it — this is what `data_query_tool`
    exposes instead of a hand-typed input_schema; see
    `app/tool_registry/data_query_tool.py`'s module docstring."""
    table = entity.source.get("table") or entity.source.get("collection") or "?"
    parts = [f"Table {table}."]
    if entity.description:
        parts.append(entity.description)
    columns = []
    for field in entity.fields:
        if field.get("visible", True) is False:
            continue
        bits = [field["name"], f"({field.get('type', 'string')}"]
        if field.get("label"):
            bits.append(f", {field['label']}")
        if field.get("format"):
            bits.append(f", {field['format']}")
        bits.append(")")
        columns.append("".join(bits))
    if columns:
        parts.append("Columns: " + ", ".join(columns) + ".")
    return " ".join(parts)


async def _hydrate_data_query_tool(db: AsyncSession, workspace_id: uuid.UUID | None, fields: dict) -> None:
    """Mutates `fields` (the dict about to become a Tool row) in place:
    resolves `config.entity_id`/`config.policy_id` into frozen snapshots (so
    `DataQueryTool.run_async` never needs a live DB session), and
    overwrites `description`/`input_schema` from the entity — an admin
    never hand-types either for this tool type. Re-run on every save, so a
    "Sync from entity" is just re-submitting the same entity_id/policy_id."""
    config = fields.get("config") or {}
    entity_id = config.get("entity_id")
    if not entity_id:
        raise HTTPException(status_code=422, detail="data_query_tool requires config.entity_id")

    entity = await db.get(DataEntity, uuid.UUID(str(entity_id)))
    if entity is None or entity.workspace_id != workspace_id:
        raise HTTPException(status_code=422, detail="config.entity_id does not reference a valid data entity")

    policy_field_names = None
    policy_id = config.get("policy_id")
    if policy_id:
        policy = await db.get(AccessPolicy, uuid.UUID(str(policy_id)))
        if policy is None or policy.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="config.policy_id does not reference a valid access policy")
        policy_field_names = policy.resolver_config.get("field_names")

    fields["config"] = {
        "entity_id": str(entity.id),
        "policy_id": str(policy_id) if policy_id else None,
        "entity": {
            "connection": entity.connection,
            "source": entity.source,
            "fields": entity.fields,
            "max_limit": entity.max_limit,
        },
        "policy_field_names": policy_field_names,
    }
    fields["description"] = _compose_schema_description(entity)
    table = entity.source.get("table") or entity.source.get("collection") or "the table"
    fields["input_schema"] = {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": f"A single SELECT statement against {table}."}},
        "required": ["sql"],
    }


@router.post("", response_model=ToolRead, status_code=201)
async def create_tool(
    payload: ToolCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> Tool:
    await require_tool_type_allowed(db, principal.workspace_id, payload.tool_type)
    fields = payload.model_dump(exclude={"workspace_id"})
    if payload.tool_type == "data_query_tool":
        await _hydrate_data_query_tool(db, principal.workspace_id, fields)
    tool = Tool(**fields, workspace_id=principal.workspace_id)
    db.add(tool)
    await db.flush()
    db.add(
        ToolVersion(
            tool_id=tool.id,
            version=1,
            snapshot={
                "name": tool.name,
                "config": tool.config,
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
                "description": tool.description,
            },
            created_by=_actor(principal),
        )
    )
    await write_audit_log(
        db,
        entity_type="tool",
        entity_id=tool.id,
        action="create",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolRead])
async def list_tools(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[Tool]:
    result = await db.execute(
        select(Tool).where(Tool.workspace_id == principal.workspace_id).order_by(Tool.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> Tool:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: uuid.UUID,
    payload: ToolUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> Tool:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    updates = payload.model_dump(exclude_unset=True)
    if tool.tool_type == "data_query_tool" and "config" in updates:
        await _hydrate_data_query_tool(db, principal.workspace_id, updates)
    touches_versioned_field = any(field in updates for field in _VERSIONED_FIELDS)
    for key, value in updates.items():
        setattr(tool, key, value)
    if touches_versioned_field:
        await _snapshot_tool_version(db, tool, _actor(principal))
    await write_audit_log(
        db,
        entity_type="tool",
        entity_id=tool.id,
        action="update",
        actor=_actor(principal),
        diff=updates,
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    await write_audit_log(
        db,
        entity_type="tool",
        entity_id=tool.id,
        action="delete",
        actor=_actor(principal),
        workspace_id=principal.workspace_id,
    )
    await db.delete(tool)
    await db.commit()


@router.get("/{tool_id}/versions", response_model=list[ToolVersionRead])
async def list_tool_versions(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[ToolVersion]:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    result = await db.execute(
        select(ToolVersion).where(ToolVersion.tool_id == tool_id).order_by(ToolVersion.version.desc())
    )
    return list(result.scalars().all())


@router.post("/{tool_id}/versions/{version}/rollback", response_model=ToolRead)
async def rollback_tool_version(
    tool_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> Tool:
    """Restores a past version's snapshot as the tool's current live
    config — itself recorded as a new version (current_version + 1), never
    by reusing the old version number, so the history stays linear and
    "what was live between t1 and t2" is always answerable from the
    version list alone."""
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    target = await db.scalar(
        select(ToolVersion).where(ToolVersion.tool_id == tool_id, ToolVersion.version == version)
    )
    if target is None:
        raise HTTPException(status_code=404, detail=f"Tool has no version {version}")

    snapshot = target.snapshot
    tool.name = snapshot["name"]
    tool.config = snapshot["config"]
    tool.input_schema = snapshot["input_schema"]
    tool.output_schema = snapshot.get("output_schema")
    tool.description = snapshot.get("description")
    await _snapshot_tool_version(db, tool, _actor(principal))
    await write_audit_log(
        db,
        entity_type="tool",
        entity_id=tool.id,
        action="update",
        actor=_actor(principal),
        diff={"rolled_back_to_version": version},
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("/{tool_id}/grants", response_model=list[ToolGrantRead])
async def list_tool_grants(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> list[ToolGrantRead]:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    result = await db.execute(
        select(ToolGrant, Agent.name).outerjoin(Agent, Agent.id == ToolGrant.agent_id).where(ToolGrant.tool_id == tool_id)
    )
    return [
        ToolGrantRead(
            tool_id=grant.tool_id,
            agent_id=grant.agent_id,
            agent_name=agent_name,
            granted_by=grant.granted_by,
            created_at=grant.created_at,
        )
        for grant, agent_name in result
    ]


@router.post("/{tool_id}/grants", response_model=ToolGrantRead, status_code=201)
async def create_tool_grant(
    tool_id: uuid.UUID,
    payload: ToolGrantCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> ToolGrantRead:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or agent.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    grant = await db.get(ToolGrant, {"tool_id": tool_id, "agent_id": payload.agent_id})
    if grant is None:
        grant = ToolGrant(tool_id=tool_id, agent_id=payload.agent_id, granted_by=_actor(principal))
        db.add(grant)
        await write_audit_log(
            db,
            entity_type="tool",
            entity_id=tool.id,
            action="update",
            actor=_actor(principal),
            diff={"grant_agent": str(payload.agent_id)},
            workspace_id=principal.workspace_id,
        )
        await db.commit()
        await db.refresh(grant)
    return ToolGrantRead(
        tool_id=grant.tool_id,
        agent_id=grant.agent_id,
        agent_name=agent.name,
        granted_by=grant.granted_by,
        created_at=grant.created_at,
    )


@router.delete("/{tool_id}/grants/{agent_id}", status_code=204)
async def delete_tool_grant(
    tool_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    tool = await db.get(Tool, tool_id)
    if tool is None or tool.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Tool not found")
    grant = await db.get(ToolGrant, {"tool_id": tool_id, "agent_id": agent_id})
    if grant is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await db.delete(grant)
    await write_audit_log(
        db,
        entity_type="tool",
        entity_id=tool.id,
        action="update",
        actor=_actor(principal),
        diff={"revoke_agent": str(agent_id)},
        workspace_id=principal.workspace_id,
    )
    await db.commit()
