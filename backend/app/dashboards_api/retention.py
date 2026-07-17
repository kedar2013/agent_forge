from fastapi import APIRouter, Depends
from google.adk.sessions import DatabaseSessionService
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.principal import Principal, require_role
from app.retention import purge_expired_data
from app.schemas.dashboards import RetentionPurgeRequest, RetentionPurgeResponse

router = APIRouter(prefix="/data-retention", tags=["dashboards"])

# Its own DatabaseSessionService instance rather than importing chat_api's
# _chat_sessions (module-private, and importing across API routers for
# internal state isn't this codebase's pattern) — DatabaseSessionService is
# a thin, cheap-to-construct wrapper over the same Postgres tables, not a
# stateful cache, so a second instance pointed at the same db_url is safe.
_session_service = DatabaseSessionService(db_url=get_settings().database_url)


@router.post("/purge", response_model=RetentionPurgeResponse)
async def purge_expired_conversation_data(
    payload: RetentionPurgeRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> RetentionPurgeResponse:
    """Deletes conversation/PII-bearing data older than the retention
    window, scoped to the caller's own workspace — see app/retention.py's
    module docstring for exactly which tables and why. Defaults to
    dry_run=True (count only) so an admin can see the blast radius before
    committing to it; pass dry_run=False to actually delete.

    Nothing calls this automatically — there's no scheduler in this app.
    Run it by hand, or point your hosting provider's own cron feature at
    it (see SECURITY.md)."""
    retention_days = payload.retention_days if payload.retention_days is not None else get_settings().data_retention_days
    result = await purge_expired_data(
        db,
        _session_service,
        workspace_id=principal.workspace_id,
        retention_days=retention_days,
        dry_run=payload.dry_run,
    )
    if not payload.dry_run:
        await db.commit()
    else:
        await db.rollback()

    return RetentionPurgeResponse(
        cutoff=result.cutoff,
        dry_run=result.dry_run,
        invocation_log_rows=result.invocation_log,
        scil_rows=result.scil_rows,
        chat_sessions=result.chat_sessions,
    )
