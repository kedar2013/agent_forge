"""Per-workspace config-write-time enforcement (see app.models.workspaces.
WorkspaceConfig) — "which models/tools apply to this tenant" is a
governance decision made when an agent/tool's config is AUTHORED, not a
per-invocation runtime gate, so this is called from config_api's create/
update endpoints, not agent_runtime.builder.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspaces import WorkspaceConfig


async def require_model_allowed(db: AsyncSession, workspace_id: uuid.UUID | None, model: str) -> None:
    if workspace_id is None:
        return
    config = await db.get(WorkspaceConfig, workspace_id)
    if config is None or config.allowed_models is None:
        return  # no row, or explicitly unrestricted -- every model permitted
    if model not in config.allowed_models:
        raise HTTPException(
            status_code=422,
            detail=f"Model {model!r} is not in this workspace's allowed_models list.",
        )


async def require_tool_type_allowed(db: AsyncSession, workspace_id: uuid.UUID | None, tool_type: str) -> None:
    if workspace_id is None:
        return
    config = await db.get(WorkspaceConfig, workspace_id)
    if config is None or config.allowed_tool_types is None:
        return
    if tool_type not in config.allowed_tool_types:
        raise HTTPException(
            status_code=422,
            detail=f"Tool type {tool_type!r} is not in this workspace's allowed_tool_types list.",
        )
