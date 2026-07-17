import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from google.adk.sessions import DatabaseSessionService
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runtime.builder import get_or_build_agent
from app.agent_runtime.byok import required_providers, resolve_request_api_keys, use_api_keys
from app.chat_api.deps import require_chat_access
from app.config import get_settings
from app.db import get_db
from app.models.agents import Agent as AgentRow
from app.models.agents import AgentSubagent
from app.models.logs import InvocationLog
from app.playground_api.router import _run_turn, _stream_turn
from app.principal import Principal
from app.rate_limit import rate_limit_principal
from app.schemas.dashboards import MyUsageAgentRow, MyUsageDayPoint, MyUsageSummary
from app.schemas.playground import PlaygroundRunResponse

router = APIRouter(prefix="/chat", tags=["chat"])

# A real end-user conversation — backed by Postgres (not in-memory) so it
# survives a backend restart, same as /invoke.
_chat_sessions = DatabaseSessionService(db_url=get_settings().database_url)

# Fallback when a request doesn't name an orchestrator explicitly — keeps
# existing callers (and the pre-picker frontend) working unchanged. See
# list_chat_orchestrators() below for how a client discovers every bot it
# can actually pick.
CHATBOT_AGENT_NAME = "market_intelligence_orchestrator"


def _principal_key(principal: Principal) -> str:
    """invoked_by/history key — real users get their id; the static admin
    token (no user_id) gets a stable placeholder so its own chat history is
    still trackable rather than every static-token call sharing session 0."""
    return str(principal.user_id) if principal.user_id else "admin-static-token"


async def _resolve_chat_agent(db: AsyncSession, principal: Principal, agent_name: str | None) -> AgentRow:
    """Looks up the published root agent a chat request should run against —
    the one named in the request if given, else CHATBOT_AGENT_NAME. Any
    published, workspace-scoped agent is a valid target here, not just
    orchestrator-shaped ones: a standalone published agent is just as
    legitimate a chat target as a multi-specialist router."""
    agent_row = await db.scalar(
        select(AgentRow).where(
            AgentRow.name == (agent_name or CHATBOT_AGENT_NAME),
            AgentRow.status == "published",
            AgentRow.workspace_id == principal.workspace_id,
        )
    )
    if agent_row is None:
        raise HTTPException(
            status_code=503,
            detail="That chatbot isn't available right now — no matching published agent.",
        )
    return agent_row


class OrchestratorSummary(BaseModel):
    name: str
    description: str | None
    is_multi_specialist: bool


@router.get("/orchestrators", response_model=list[OrchestratorSummary])
async def list_chat_orchestrators(
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
) -> list[OrchestratorSummary]:
    """Every published, top-level agent in this workspace — i.e. every
    distinct bot a user could choose to talk to. "Top-level" means not
    itself a sub-agent of anything else: a multi-specialist orchestrator
    (market_intelligence, the StudyBuddy "orchestrator") and a standalone
    published agent both qualify equally; a specialist only ever reached via
    an internal transfer does not, since talking to it directly would skip
    its orchestrator's routing/guardrail instructions entirely."""
    child_ids = select(AgentSubagent.child_agent_id)
    rows = (
        await db.scalars(
            select(AgentRow)
            .where(
                AgentRow.status == "published",
                AgentRow.workspace_id == principal.workspace_id,
                AgentRow.id.not_in(child_ids),
            )
            .order_by(AgentRow.name)
        )
    ).all()
    if not rows:
        return []
    sub_counts = dict(
        (
            await db.execute(
                select(AgentSubagent.parent_agent_id, func.count())
                .where(AgentSubagent.parent_agent_id.in_([r.id for r in rows]))
                .group_by(AgentSubagent.parent_agent_id)
            )
        ).all()
    )
    return [
        OrchestratorSummary(
            name=r.name, description=r.description, is_multi_specialist=sub_counts.get(r.id, 0) > 0
        )
        for r in rows
    ]


# Some agent trees (the StudyBuddy family, reachable via the "orchestrator"
# bot) reference {grade}/{language}/{subject} in their instructions via
# ADK's {state_key} templating — a holdover from when /chat had a dedicated
# settings panel for those. That panel was removed when /chat became a
# generic multi-orchestrator surface (see list_chat_orchestrators above),
# so nothing supplies these anymore; without a default, the very first turn
# with such an agent raises `KeyError: Context variable not found`. Seeded
# once at session creation (never repeated — see _ensure_session_state) so
# a hypothetical future per-conversation settings UI could still override
# them without being silently stomped on the next turn. A harmless no-op
# for agent trees that don't reference these keys (market_intelligence and
# its specialists never do).
_DEFAULT_CHAT_STATE = {"language": "English", "grade": "8th grade", "subject": "General"}


async def _ensure_session_state(app_name: str, user_id: str, session_id: str, principal: Principal) -> None:
    existing = await _chat_sessions.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    if existing is None:
        # `_principal_user_id`/`_principal_soeid` are trusted identity every
        # built agent's before_tool_callback can read off session state
        # (see agent_runtime/builder.py) to inject into, or authorize, a
        # tool call — the LLM never sees or controls these values. An
        # access_policy picks which one it matches on via
        # resolver_config["identity_state_key"] (defaults to the Eärendil
        # user id; set to "_principal_soeid" for domains keyed by a
        # corporate id instead). Harmless for agents/tools that don't use
        # either, same as _DEFAULT_CHAT_STATE.
        state = {
            **_DEFAULT_CHAT_STATE,
            "_principal_user_id": user_id,
            "_principal_soeid": principal.soeid,
            "_principal_role": principal.role,
        }
        await _chat_sessions.create_session(app_name=app_name, user_id=user_id, session_id=session_id, state=state)


class ChatMessageRequest(BaseModel):
    message: str
    session_id: str | None = None
    state_delta: dict[str, Any] | None = None
    agent_name: str | None = None


def _identity_state_delta(principal: Principal) -> dict[str, Any]:
    """Trusted identity, re-asserted on every single turn (not just once at
    session creation) — a session that was created before a user's SOEID was
    assigned, or before this platform even had the concept, would otherwise
    be stuck with whatever was frozen into its state at creation time
    forever. Any client-supplied state_delta value for these reserved keys
    is overridden by this, never merged with it."""
    return {
        "_principal_user_id": str(principal.user_id) if principal.user_id else "admin-static-token",
        "_principal_soeid": principal.soeid,
        "_principal_role": principal.role,
    }


@router.post("/message", response_model=PlaygroundRunResponse, dependencies=[Depends(rate_limit_principal)])
async def send_chat_message(
    payload: ChatMessageRequest,
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-Api-Key"),
    x_anthropic_api_key: str | None = Header(default=None, alias="X-Anthropic-Api-Key"),
) -> PlaygroundRunResponse:
    agent_row = await _resolve_chat_agent(db, principal, payload.agent_name)
    adk_agent = await get_or_build_agent(db, agent_row.id, version=agent_row.current_version)
    user_key = _principal_key(principal)
    session_id = payload.session_id or f"chat-{user_key}-{uuid.uuid4()}"
    await _ensure_session_state("agent_forge_chat", user_key, session_id, principal)

    # BYOK: real end-user chat never falls back to the operator's own key —
    # see byok.resolve_request_api_keys's docstring. Raises MissingApiKeyError
    # (a 400) before any Runner/LLM call if a required key is absent.
    gemini_key, anthropic_key = resolve_request_api_keys(
        required_providers(adk_agent), x_gemini_api_key, x_anthropic_api_key, allow_operator_fallback=False
    )

    with use_api_keys(gemini_key, anthropic_key):
        return await _run_turn(
            db=db,
            adk_agent=adk_agent,
            agent_row=agent_row,
            session_service=_chat_sessions,
            app_name="agent_forge_chat",
            user_id=user_key,
            session_id=session_id,
            message=payload.message,
            state_delta={**(payload.state_delta or {}), **_identity_state_delta(principal)},
        )


@router.post("/message/stream", dependencies=[Depends(rate_limit_principal)])
async def send_chat_message_stream(
    payload: ChatMessageRequest,
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
    x_gemini_api_key: str | None = Header(default=None, alias="X-Gemini-Api-Key"),
    x_anthropic_api_key: str | None = Header(default=None, alias="X-Anthropic-Api-Key"),
) -> StreamingResponse:
    """Newline-delimited-JSON streaming twin of /chat/message — same auth,
    same routing, same agent — but yields live progress (transfers, tool
    calls starting/finishing) as the ADK Runner produces them, ending with a
    "done" event shaped like PlaygroundRunResponse. Lets the chat UI show
    what the agent is doing instead of a blank wait during multi-tool-call
    chains, which can genuinely take a while (a specialist calling 2-3 real
    external APIs in sequence)."""
    agent_row = await _resolve_chat_agent(db, principal, payload.agent_name)
    adk_agent = await get_or_build_agent(db, agent_row.id, version=agent_row.current_version)
    user_key = _principal_key(principal)
    session_id = payload.session_id or f"chat-{user_key}-{uuid.uuid4()}"
    await _ensure_session_state("agent_forge_chat", user_key, session_id, principal)

    # Resolved eagerly (before the StreamingResponse is even constructed) so
    # a missing key is a normal 400, never a mid-stream "error" event.
    gemini_key, anthropic_key = resolve_request_api_keys(
        required_providers(adk_agent), x_gemini_api_key, x_anthropic_api_key, allow_operator_fallback=False
    )

    async def event_stream():
        # use_api_keys MUST wrap this loop, not the `return
        # StreamingResponse(...)` below — this generator body only actually
        # runs once Starlette starts draining it, which happens AFTER
        # send_chat_message_stream has already returned. Scoping the
        # ContextVars outside this function would reset them to None before
        # a single token generates, silently breaking BYOK for the primary
        # chat path (see byok.use_api_keys's docstring).
        with use_api_keys(gemini_key, anthropic_key):
            async for event in _stream_turn(
                adk_agent=adk_agent,
                agent_row=agent_row,
                session_service=_chat_sessions,
                app_name="agent_forge_chat",
                user_id=user_key,
                session_id=session_id,
                message=payload.message,
                state_delta={**(payload.state_delta or {}), **_identity_state_delta(principal)},
            ):
                yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


class ChatHistoryTurn(BaseModel):
    message: str
    response_text: str
    created_at: str


@router.get("/history", response_model=list[ChatHistoryTurn])
async def get_chat_history(
    session_id: str,
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
) -> list[ChatHistoryTurn]:
    """Reconstructs one conversation's past turns from invocation_log — the
    durable record of every run — rather than from ADK's in-memory session
    state, which doesn't survive a backend restart."""
    user_key = _principal_key(principal)
    rows = await db.scalars(
        select(InvocationLog)
        .where(
            InvocationLog.invoked_by == user_key,
            InvocationLog.trace_id == session_id,
            InvocationLog.transcript.is_not(None),
        )
        .order_by(InvocationLog.created_at.asc())
    )
    turns = []
    for row in rows:
        transcript = row.transcript or {}
        if "message" not in transcript or "response_text" not in transcript:
            continue
        turns.append(
            ChatHistoryTurn(
                message=transcript["message"],
                response_text=transcript["response_text"],
                created_at=row.created_at.isoformat(),
            )
        )
    return turns


class ConversationSummary(BaseModel):
    session_id: str
    title: str
    last_message_at: str
    message_count: int
    agent_name: str | None = None


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    """One row per distinct conversation (ADK session/trace_id) this user has
    ever had, newest first — titled from that conversation's first message.
    Also reports which bot each conversation was with (agent_name), so a
    multi-orchestrator chat UI can restore the right bot selection when a
    past conversation is reopened rather than always defaulting to one."""
    user_key = _principal_key(principal)
    grouped = (
        await db.execute(
            select(
                InvocationLog.trace_id,
                func.max(InvocationLog.created_at).label("last_message_at"),
                func.count().label("message_count"),
            )
            .where(InvocationLog.invoked_by == user_key, InvocationLog.transcript.is_not(None))
            .group_by(InvocationLog.trace_id)
            .order_by(func.max(InvocationLog.created_at).desc())
        )
    ).all()

    conversations = []
    for trace_id, last_message_at, message_count in grouped:
        first_row = await db.scalar(
            select(InvocationLog)
            .where(InvocationLog.invoked_by == user_key, InvocationLog.trace_id == trace_id)
            .order_by(InvocationLog.created_at.asc())
            .limit(1)
        )
        title = "New conversation"
        agent_name = None
        if first_row and first_row.transcript and first_row.transcript.get("message"):
            raw = first_row.transcript["message"].strip()
            title = raw[:60] + ("…" if len(raw) > 60 else "")
        if first_row and first_row.agent_id:
            agent_name = await db.scalar(select(AgentRow.name).where(AgentRow.id == first_row.agent_id))
        conversations.append(
            ConversationSummary(
                session_id=trace_id,
                title=title,
                last_message_at=last_message_at.isoformat(),
                message_count=message_count,
                agent_name=agent_name,
            )
        )
    return conversations


@router.get("/usage", response_model=MyUsageSummary)
async def get_my_usage(
    range_days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(require_chat_access),
    db: AsyncSession = Depends(get_db),
) -> MyUsageSummary:
    """Self-service usage for the calling user only — chat_user accounts can't
    see the admin usage dashboard, but they can see their own numbers."""
    user_key = _principal_key(principal)
    since = datetime.now(timezone.utc) - timedelta(days=range_days)
    base_filter = (
        InvocationLog.invoked_by == user_key,
        InvocationLog.created_at >= since,
        InvocationLog.workspace_id == principal.workspace_id,
    )

    summary_row = (
        await db.execute(
            select(
                func.count(InvocationLog.id),
                func.coalesce(
                    func.sum(func.coalesce(InvocationLog.input_tokens, 0) + func.coalesce(InvocationLog.output_tokens, 0)),
                    0,
                ),
                func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
                func.sum(case((InvocationLog.status != "success", 1), else_=0)),
                func.max(InvocationLog.created_at),
            ).where(*base_filter)
        )
    ).one()
    total_invocations, total_tokens, total_cost, error_count, last_active = summary_row

    day = func.date_trunc("day", InvocationLog.created_at).label("day")
    day_rows = await db.execute(
        select(day, func.count(InvocationLog.id), func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0))
        .where(*base_filter)
        .group_by(day)
        .order_by(day)
    )
    by_day = [
        MyUsageDayPoint(date=d.date().isoformat(), invocations=count, cost_usd=float(cost))
        for d, count, cost in day_rows
    ]

    agent_rows = await db.execute(
        select(
            AgentRow.name,
            func.count(InvocationLog.id),
            func.coalesce(
                func.sum(func.coalesce(InvocationLog.input_tokens, 0) + func.coalesce(InvocationLog.output_tokens, 0)),
                0,
            ),
            func.coalesce(func.sum(InvocationLog.estimated_cost_usd), 0),
        )
        .join(AgentRow, AgentRow.id == InvocationLog.agent_id)
        .where(*base_filter)
        .group_by(AgentRow.name)
        .order_by(func.count(InvocationLog.id).desc())
    )
    by_agent = [
        MyUsageAgentRow(agent_name=name, invocation_count=count, total_tokens=int(tokens), total_cost_usd=float(cost))
        for name, count, tokens, cost in agent_rows
    ]

    return MyUsageSummary(
        total_invocations=total_invocations or 0,
        total_tokens=int(total_tokens or 0),
        total_cost_usd=float(total_cost or 0),
        error_count=error_count or 0,
        last_active=last_active,
        by_day=by_day,
        by_agent=by_agent,
    )
