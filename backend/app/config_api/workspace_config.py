"""Self-service per-tenant config: an admin manages THEIR OWN workspace's
restrictions (see app.models.workspaces.WorkspaceConfig) — there's no
cross-tenant listing/editing here, deliberately: `principal.workspace_id`
is always the target, never a path param, so there's no cross-tenant
access check to get wrong in the first place.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.workspaces import WorkspaceConfig
from app.principal import Principal, require_role
from app.schemas.workspace_config import WorkspaceConfigRead, WorkspaceConfigUpdate

router = APIRouter(prefix="/workspace-config", tags=["workspace-config"])


@router.get("", response_model=WorkspaceConfigRead)
async def get_workspace_config(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer", "developer")),
) -> WorkspaceConfigRead:
    if principal.workspace_id is None:
        return WorkspaceConfigRead(allowed_models=None, allowed_tool_types=None, max_requests_per_minute=None)
    config = await db.get(WorkspaceConfig, principal.workspace_id)
    if config is None:
        return WorkspaceConfigRead(allowed_models=None, allowed_tool_types=None, max_requests_per_minute=None)
    return WorkspaceConfigRead.model_validate(config)


@router.put("", response_model=WorkspaceConfigRead)
async def update_workspace_config(
    payload: WorkspaceConfigUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> WorkspaceConfigRead:
    if principal.workspace_id is None:
        raise HTTPException(status_code=422, detail="No workspace associated with this principal.")
    config = await db.get(WorkspaceConfig, principal.workspace_id)
    if config is None:
        config = WorkspaceConfig(workspace_id=principal.workspace_id)
        db.add(config)
    config.allowed_models = payload.allowed_models
    config.allowed_tool_types = payload.allowed_tool_types
    config.max_requests_per_minute = payload.max_requests_per_minute
    await db.commit()
    await db.refresh(config)
    return WorkspaceConfigRead.model_validate(config)
