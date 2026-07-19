"""Audit trail for DENIED access_policy decisions — the runtime counterpart
to app.guardrails.service's GuardrailEvent recording, same "only the
exception is interesting" convention (an ALLOWED decision writes nothing;
only a denial is a governance event worth a row) and same independent hash
chain (see app.event_chain.next_chain_link / app.audit_hash.compute_event_
hash). Called from agent_runtime.builder's before_tool_callback the moment
either policy engine (policy_engine.apply_policy or opa_client.
evaluate_opa_policy) returns allowed=False.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.db import async_session_factory
from app.event_chain import next_chain_link
from app.models.guardrails import PolicyEvent

logger = logging.getLogger(__name__)


async def record_policy_denial(
    *,
    workspace_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    agent_name: str | None,
    adk_invocation_id: str | None,
    tool_name: str,
    policy_id: uuid.UUID | None,
    engine: str,
    persona: str | None,
    reason: str | None,
) -> None:
    async with async_session_factory() as session:
        created_at = datetime.now(timezone.utc)
        next_seq, prev_hash, row_hash = await next_chain_link(
            session,
            PolicyEvent,
            workspace_id=str(workspace_id) if workspace_id else None,
            agent_id=str(agent_id) if agent_id else None,
            agent_name=agent_name,
            adk_invocation_id=adk_invocation_id,
            tool_name=tool_name,
            policy_id=str(policy_id) if policy_id else None,
            engine=engine,
            persona=persona,
            reason=reason,
            created_at=created_at.isoformat(),
        )
        session.add(
            PolicyEvent(
                seq=next_seq,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_name=agent_name,
                adk_invocation_id=adk_invocation_id,
                tool_name=tool_name,
                policy_id=policy_id,
                engine=engine,
                persona=persona,
                reason=reason,
                prev_hash=prev_hash,
                row_hash=row_hash,
                created_at=created_at,
            )
        )
        try:
            await session.commit()
        except Exception:
            # Same fail-safe reasoning as guardrails.service._record_event:
            # a logging failure must never be why a real policy denial
            # doesn't take effect -- the caller already has the verdict and
            # enforces it regardless of whether this write succeeded.
            logger.exception("policy_audit: failed to persist PolicyEvent (denial still enforced)")
            await session.rollback()
