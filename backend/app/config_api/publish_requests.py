"""Admin review queue for agents a developer has asked to publish.

A developer's POST /agents/{id}/publish (see config_api.agents.publish_agent)
never makes an agent live by itself — it freezes the current config into an
AgentPublishRequest row (status=pending) and stops there. This router is the
other half: an admin lists pending requests, inspects the frozen snapshot,
and approves (publishes exactly that snapshot) or rejects (with an optional
note the developer can see).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_api.agents import _actor, _get_agent_or_404, _publish_now
from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.agents import Agent, AgentPublishRequest
from app.principal import Principal, require_role
from app.schemas.agents import AgentVersionRead, PublishRequestRead, ReviewPublishRequest

router = APIRouter(prefix="/agents/publish-requests", tags=["agents"])


async def _get_request_or_404(db: AsyncSession, request_id: uuid.UUID, workspace_id: uuid.UUID) -> AgentPublishRequest:
    req = await db.get(AgentPublishRequest, request_id)
    if req is None or req.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Publish request not found")
    return req


@router.get("", response_model=list[PublishRequestRead])
async def list_publish_requests(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> list[AgentPublishRequest]:
    query = select(AgentPublishRequest).where(AgentPublishRequest.workspace_id == principal.workspace_id)
    if status:
        query = query.where(AgentPublishRequest.status == status)
    else:
        query = query.where(AgentPublishRequest.status == "pending")
    result = await db.execute(query.order_by(AgentPublishRequest.created_at.desc()))
    return list(result.scalars().all())


@router.get("/mine", response_model=list[PublishRequestRead])
async def list_my_publish_requests(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("developer")),
) -> list[AgentPublishRequest]:
    """A developer's own view of what they've submitted and its outcome —
    there's no other way for them to see whether a rejection happened, since
    the agent itself just silently stays in "draft"."""
    result = await db.execute(
        select(AgentPublishRequest)
        .where(
            AgentPublishRequest.workspace_id == principal.workspace_id,
            AgentPublishRequest.requested_by_user_id == principal.user_id,
        )
        .order_by(AgentPublishRequest.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{request_id}/approve", response_model=PublishRequestRead)
async def approve_publish_request(
    request_id: uuid.UUID,
    payload: ReviewPublishRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AgentPublishRequest:
    req = await _get_request_or_404(db, request_id, principal.workspace_id)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request was already {req.status}")

    agent = await _get_agent_or_404(db, req.agent_id, principal.workspace_id)
    version_row = await _publish_now(
        db,
        agent,
        req.snapshot,
        req.requested_by or _actor(principal),
        principal,
        extra_diff={"via_publish_request": str(req.id)},
    )

    req.status = "approved"
    req.decided_by = _actor(principal)
    req.decided_at = datetime.now(timezone.utc)
    req.review_note = payload.review_note
    req.published_version = version_row.version

    await db.commit()
    await db.refresh(req)
    return req


@router.post("/{request_id}/reject", response_model=PublishRequestRead)
async def reject_publish_request(
    request_id: uuid.UUID,
    payload: ReviewPublishRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> AgentPublishRequest:
    req = await _get_request_or_404(db, request_id, principal.workspace_id)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request was already {req.status}")

    req.status = "rejected"
    req.decided_by = _actor(principal)
    req.decided_at = datetime.now(timezone.utc)
    req.review_note = payload.review_note

    await write_audit_log(
        db,
        entity_type="agent",
        entity_id=req.agent_id,
        action="update",
        actor=_actor(principal),
        diff={"publish_request_rejected": str(req.id), "review_note": payload.review_note},
        workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(req)
    return req
