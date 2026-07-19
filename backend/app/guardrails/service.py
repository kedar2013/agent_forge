"""Orchestrates one guardrail direction's checks (deterministic first, since
they're free; LLM-judge escalation only when the deterministic pass came up
clean and the check is enabled) and durably records any finding. Consumed by
`agent_runtime.builder`'s before/after-model callbacks, which own translating
a `GuardrailVerdict` into an actual ADK `LlmResponse` — this module only
decides pass/fail/redact, never touches ADK types.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.db import async_session_factory
from app.event_chain import next_chain_link
from app.guardrails import judge, patterns
from app.guardrails.config import GuardrailsConfig
from app.guardrails.patterns import Finding
from app.models.guardrails import GuardrailEvent

logger = logging.getLogger(__name__)


@dataclass
class GuardrailVerdict:
    ok: bool = True
    action: str = "block"  # "block" | "redact" — only meaningful when ok=False
    check_name: str = ""
    reason: str = ""
    redacted_text: str | None = None
    matched_preview: str = ""


_OK = GuardrailVerdict(ok=True)


async def _record_event(
    *,
    workspace_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    agent_name: str | None,
    adk_invocation_id: str | None,
    direction: str,
    verdict: GuardrailVerdict,
) -> None:
    async with async_session_factory() as session:
        created_at = datetime.now(timezone.utc)
        next_seq, prev_hash, row_hash = await next_chain_link(
            session,
            GuardrailEvent,
            workspace_id=str(workspace_id) if workspace_id else None,
            agent_id=str(agent_id) if agent_id else None,
            agent_name=agent_name,
            adk_invocation_id=adk_invocation_id,
            direction=direction,
            check_name=verdict.check_name,
            action=verdict.action,
            reason=verdict.reason,
            matched_preview=verdict.matched_preview,
            created_at=created_at.isoformat(),
        )
        session.add(
            GuardrailEvent(
                seq=next_seq,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_name=agent_name,
                adk_invocation_id=adk_invocation_id,
                direction=direction,
                check_name=verdict.check_name,
                action=verdict.action,
                reason=verdict.reason,
                matched_preview=verdict.matched_preview,
                prev_hash=prev_hash,
                row_hash=row_hash,
                created_at=created_at,
            )
        )
        try:
            await session.commit()
        except Exception:
            # A logging failure must never be why a real guardrail
            # block/redact doesn't take effect — the caller already has the
            # verdict and enforces it regardless of whether this write
            # succeeded. Loud in the logs either way.
            logger.exception("guardrails: failed to persist GuardrailEvent (verdict still enforced)")
            await session.rollback()


def _finding_to_verdict(finding: Finding, action: str) -> GuardrailVerdict:
    return GuardrailVerdict(
        ok=False,
        action=action,
        check_name=finding.check_name,
        reason=finding.reason,
        redacted_text=finding.redacted_text,
        matched_preview=finding.matched_preview,
    )


async def check_input(text: str, config: GuardrailsConfig, agent_row: Any) -> GuardrailVerdict:
    """Input guardrails always act as a hard block — there's no partial-
    redact concept for a question the model should never have seen."""
    if not config.enabled or not text:
        return _OK

    if config.input.prompt_injection_check:
        finding = patterns.check_prompt_injection(text)
        if finding.matched:
            return _finding_to_verdict(finding, "block")

    if config.input.jailbreak_check:
        finding = patterns.check_jailbreak(text)
        if finding.matched:
            return _finding_to_verdict(finding, "block")

        if get_settings().guardrails_judge_enabled:
            finding = await judge.check_jailbreak_judge(text, agent_row)
            if finding.matched:
                return _finding_to_verdict(finding, "block")

    if config.input.topical_scope_check and config.input.topical_scope and get_settings().guardrails_judge_enabled:
        finding = await judge.check_topical_scope(text, config.input.topical_scope, agent_row)
        if finding.matched:
            return _finding_to_verdict(finding, "block")

    return _OK


async def check_output(text: str, config: GuardrailsConfig, agent_row: Any) -> GuardrailVerdict:
    if not config.enabled or not text:
        return _OK

    if config.output.pii_check:
        finding = patterns.check_pii(text)
        if finding.matched:
            return _finding_to_verdict(finding, config.output.action)

    if config.output.mnpi_check and config.output.mnpi_terms:
        finding = patterns.check_mnpi(text, config.output.mnpi_terms)
        if finding.matched:
            return _finding_to_verdict(finding, config.output.action)

    if config.output.toxicity_check and get_settings().guardrails_judge_enabled:
        finding = await judge.check_toxicity(text, agent_row)
        if finding.matched:
            # Toxicity has no safe partial redaction — always a hard block
            # regardless of this agent's configured output.action.
            return _finding_to_verdict(finding, "block")

    return _OK


async def enforce_input(
    text: str,
    config: GuardrailsConfig,
    agent_row: Any,
    *,
    workspace_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    agent_name: str | None,
    adk_invocation_id: str | None,
) -> GuardrailVerdict:
    verdict = await check_input(text, config, agent_row)
    if not verdict.ok:
        logger.warning(
            "guardrails: INPUT %s blocked agent=%s invocation=%s reason=%s",
            verdict.check_name,
            agent_name,
            adk_invocation_id,
            verdict.reason,
        )
        await _record_event(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_name=agent_name,
            adk_invocation_id=adk_invocation_id,
            direction="input",
            verdict=verdict,
        )
    return verdict


async def enforce_output(
    text: str,
    config: GuardrailsConfig,
    agent_row: Any,
    *,
    workspace_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    agent_name: str | None,
    adk_invocation_id: str | None,
) -> GuardrailVerdict:
    verdict = await check_output(text, config, agent_row)
    if not verdict.ok:
        logger.warning(
            "guardrails: OUTPUT %s (%s) agent=%s invocation=%s reason=%s",
            verdict.check_name,
            verdict.action,
            agent_name,
            adk_invocation_id,
            verdict.reason,
        )
        await _record_event(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_name=agent_name,
            adk_invocation_id=adk_invocation_id,
            direction="output",
            verdict=verdict,
        )
    return verdict
