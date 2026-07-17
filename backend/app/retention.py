"""Age-based purge of conversation/PII-bearing data, scoped to one
workspace. Admin-triggered only (see app/dashboards_api/retention.py) —
this app has no scheduler anywhere, so there's no automatic timer; run it
by hand, or point your hosting provider's own cron feature at the endpoint.

Tables covered, and why:
  - InvocationLog.transcript is the actual chat transcript. Deleting it
    cascades (ON DELETE CASCADE, see app/models/logs.py) to its
    ToolCallLog/AgentEventLog rows, so those never need a direct delete.
  - The SCIL tables hold real user input/output text (cached answers,
    correction pairs, sampled groundedness input, eval-run responses) —
    see app/models/scil.py's docstrings. All are workspace-scoped via a
    join to Agent.workspace_id (they only carry agent_id directly).
  - ADK's own `sessions`/`events` tables (google.adk.sessions.
    DatabaseSessionService) hold the live orchestration session for
    app_name="agent_forge_chat" and are purged through ADK's own
    list_sessions/delete_session API, not raw SQL against a schema this
    app doesn't own. Correctly workspace-scoped: chat sessions' ADK
    user_id is always str(User.id) (see chat_api._principal_key), so this
    resolves the workspace's User rows first and only touches sessions
    belonging to one of them.

Deliberately NOT covered:
  - ConfigAuditLog: hash-chained and append-only (see its docstring) —
    deleting any row breaks every hash after it. Never a purge target.
  - ScilEvalCase: curated regression-test questions, not user data.
  - app_name="agent_forge_invoke" ADK sessions: caller-supplied user_id
    (payload.user_id, defaults to "external-caller") has no relationship
    to this app's own User table, so there's no reliable way to attribute
    one of these sessions to a workspace via ADK's public session API —
    left out rather than guessed at or purged unscoped across tenants.
  - generated_files/generated_images on disk: not covered by this pass;
    see SECURITY.md.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from google.adk.sessions import DatabaseSessionService
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.models.logs import InvocationLog
from app.models.scil import (
    ScilCorrectionMemory,
    ScilEntityMemory,
    ScilEvalRun,
    ScilGroundednessSample,
    ScilMetrics,
    ScilSemanticCache,
)
from app.models.users import User

CHAT_APP_NAME = "agent_forge_chat"

# Every SCIL table that's keyed by agent_id (not workspace_id directly) and
# has a created_at column to filter on.
_SCIL_TABLES = (
    ScilSemanticCache,
    ScilCorrectionMemory,
    ScilEntityMemory,
    ScilGroundednessSample,
    ScilEvalRun,
    ScilMetrics,
)


@dataclass
class PurgeResult:
    cutoff: datetime
    dry_run: bool
    invocation_log: int = 0
    scil_rows: dict[str, int] = field(default_factory=dict)
    chat_sessions: int = 0


async def _workspace_agent_ids(db: AsyncSession, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(select(Agent.id).where(Agent.workspace_id == workspace_id))
    return [row[0] for row in result.all()]


async def _purge_invocation_log(
    db: AsyncSession, workspace_id: uuid.UUID, cutoff: datetime, dry_run: bool
) -> int:
    if dry_run:
        result = await db.execute(
            select(InvocationLog.id).where(
                InvocationLog.workspace_id == workspace_id, InvocationLog.created_at < cutoff
            )
        )
        return len(result.all())
    result = await db.execute(
        delete(InvocationLog)
        .where(InvocationLog.workspace_id == workspace_id, InvocationLog.created_at < cutoff)
        .returning(InvocationLog.id)
    )
    return len(result.all())


async def _purge_scil_table(db: AsyncSession, model, agent_ids: list[uuid.UUID], cutoff: datetime, dry_run: bool) -> int:
    if not agent_ids:
        return 0
    if dry_run:
        result = await db.execute(
            select(model.id).where(model.agent_id.in_(agent_ids), model.created_at < cutoff)
        )
        return len(result.all())
    result = await db.execute(
        delete(model).where(model.agent_id.in_(agent_ids), model.created_at < cutoff).returning(model.id)
    )
    return len(result.all())


async def _purge_chat_sessions(
    db: AsyncSession,
    session_service: DatabaseSessionService,
    workspace_id: uuid.UUID,
    cutoff: datetime,
    dry_run: bool,
) -> int:
    user_ids = (await db.execute(select(User.id).where(User.workspace_id == workspace_id))).scalars().all()
    purged = 0
    for user_id in user_ids:
        response = await session_service.list_sessions(app_name=CHAT_APP_NAME, user_id=str(user_id))
        for session in response.sessions:
            last_update = datetime.fromtimestamp(session.last_update_time, tz=timezone.utc)
            if last_update < cutoff:
                purged += 1
                if not dry_run:
                    await session_service.delete_session(
                        app_name=CHAT_APP_NAME, user_id=str(user_id), session_id=session.id
                    )
    return purged


async def purge_expired_data(
    db: AsyncSession,
    session_service: DatabaseSessionService,
    *,
    workspace_id: uuid.UUID,
    retention_days: int,
    dry_run: bool = True,
) -> PurgeResult:
    """Deletes (or, if dry_run, just counts) every row older than
    `retention_days` in the tables listed in this module's docstring, for
    one workspace only. Caller (app/dashboards_api/retention.py) is
    responsible for the admin auth check and for committing/rolling back —
    this function issues the deletes but doesn't commit, so a caller can
    still abort the whole batch on an unexpected error."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = PurgeResult(cutoff=cutoff, dry_run=dry_run)

    result.invocation_log = await _purge_invocation_log(db, workspace_id, cutoff, dry_run)

    agent_ids = await _workspace_agent_ids(db, workspace_id)
    for model in _SCIL_TABLES:
        result.scil_rows[model.__tablename__] = await _purge_scil_table(db, model, agent_ids, cutoff, dry_run)

    result.chat_sessions = await _purge_chat_sessions(db, session_service, workspace_id, cutoff, dry_run)

    return result
