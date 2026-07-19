"""The orchestration glue playground_api._run_turn/_stream_turn call into.
Kept agnostic of PlaygroundRunResponse/ToolCallTrace on purpose -- the
router owns turning its own response shape into a plain JSON-able dict for
`output_payload` and back, so this module doesn't need to import
playground-specific schemas.

Session handling: cache lookup is awaited inline (it gates whether the LLM
call happens at all, so it can't be fire-and-forget) using its own short
-lived session. Cache writes and metrics are fire-and-forget, matching
app/logging_hooks.py's existing pattern for the same reason -- neither
_run_turn's `db` param (unused today) nor _stream_turn (which has no `db`
param at all, and runs after its endpoint has already returned as a
StreamingResponse generator) can be relied on to still have a live
request-scoped session by the time these run.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.db import async_session_factory
from app.scil import cache, metrics
from app.scil.exemplars import apply_exemplars, fetch_exemplars, format_exemplar_block
from app.scil.normalizer import NormalizedRequest, normalize
from app.scil.templates import match_template

logger = logging.getLogger(__name__)


@dataclass
class ScilConfig:
    enabled: bool = False
    cache_similarity_threshold: float = 0.80
    cache_ttl_hours: int | None = None
    # "global": one cached answer per (agent, question), shared across all
    # callers. "user": per (agent, USER, question) -- required for agents
    # whose answers depend on who's asking (row-level security domains),
    # where a shared cache would leak one persona's data to another.
    cache_scope: str = "global"
    max_retries: int = 2
    exemplar_top_k: int = 3
    # Model cascading (see app/agent_runtime/cascade.py): once a validator
    # flags a low-confidence first attempt, every retry this turn runs on
    # `escalation_model` instead of blindly retrying the same one — the
    # "escalate on low confidence" half of cheap-model-first cascading.
    # None (default) = no cascading, retries stay on the original model,
    # exactly today's behavior.
    escalation_model: str | None = None
    # The "cost budget" half: if set, an escalation whose ESTIMATED cost
    # (using the failed attempt's own token counts as a same-turn proxy for
    # what the bigger model would likely cost) would exceed this ceiling is
    # skipped — the turn keeps its low-confidence answer rather than
    # silently blowing a per-turn budget to chase a fix. None (default) =
    # no ceiling, escalate whenever escalation_model is set.
    escalation_max_cost_usd: float | None = None
    validators: list[str] = field(default_factory=list)
    templates_enabled: bool = False
    templates: list[dict] = field(default_factory=list)
    # Only meaningful when "hallucination" is in `validators` — the always-
    # free zero-tool-call check runs regardless; this opts into a second,
    # LLM-judge groundedness pass (see app/scil/hallucination.check_groundedness).
    hallucination_groundedness_check: bool = False
    # "entity_resolution" in `validators` opts into app/scil/entities.py —
    # see ScilAgentConfig's docstring in app/schemas/agents.py.
    # Fraction of SUCCESSFUL turns (0.0-1.0) sampled for out-of-band, fire-
    # and-forget groundedness scoring (app/scil/eval_runner.py), independent
    # of hallucination_groundedness_check above -- that flag blocks the turn
    # and triggers a retry; this only ever observes and logs, never retries
    # or delays the response. 0.0 (default) = no sampling.
    eval_sample_rate: float = 0.0

    def scope_key(self, user_id: str | None) -> str:
        return (user_id or "") if self.cache_scope == "user" else ""


def get_scil_config(agent_row: Any) -> ScilConfig:
    raw = (agent_row.model_config_json or {}).get("scil") or {}
    return ScilConfig(
        enabled=bool(raw.get("enabled", False)),
        cache_similarity_threshold=float(raw.get("cache_similarity_threshold", 0.80)),
        cache_ttl_hours=raw.get("cache_ttl_hours"),
        cache_scope=str(raw.get("cache_scope", "global")),
        max_retries=int(raw.get("max_retries", 2)),
        exemplar_top_k=int(raw.get("exemplar_top_k", 3)),
        escalation_model=raw.get("escalation_model"),
        escalation_max_cost_usd=raw.get("escalation_max_cost_usd"),
        validators=list(raw.get("validators", [])),
        templates_enabled=bool(raw.get("templates_enabled", False)),
        templates=list(raw.get("templates", [])),
        hallucination_groundedness_check=bool(raw.get("hallucination_groundedness_check", False)),
        eval_sample_rate=float(raw.get("eval_sample_rate", 0.0)),
    )


def check_template(normalized: NormalizedRequest, config: ScilConfig) -> str | None:
    """Deterministic template answer (route='deterministic', zero LLM calls),
    or None to fall through to cache/LLM. Checked FIRST — it's pure regex,
    cheaper than even the cache's exact-hash DB roundtrip."""
    if not (config.enabled and config.templates_enabled and config.templates):
        return None
    return match_template(normalized.normalized_text, config.templates)


async def build_exemplar_message(agent_id: uuid.UUID, message: str, normalized: NormalizedRequest, config: ScilConfig) -> str:
    """The message to actually send to the model: the original request,
    prepended with a compact block of this agent's most-similar past
    corrections (if any). Only the outbound prompt changes — transcript,
    cache key, and correction-memory writes all keep the original message."""
    if not config.enabled:
        return message
    exemplars = await fetch_exemplars(agent_id, normalized, config.exemplar_top_k)
    return apply_exemplars(message, format_exemplar_block(exemplars))


async def check_cache(
    agent_id: uuid.UUID, message: str, config: ScilConfig, user_id: str | None = None
) -> tuple[cache.CacheHit | None, NormalizedRequest]:
    normalized = normalize(message)
    if not config.enabled:
        return None, normalized
    async with async_session_factory() as session:
        hit = await cache.lookup(
            session,
            agent_id=agent_id,
            normalized=normalized,
            similarity_threshold=config.cache_similarity_threshold,
            scope_key=config.scope_key(user_id),
        )
    return hit, normalized


def save_cache_entry_fire_and_forget(
    agent_id: uuid.UUID,
    normalized: NormalizedRequest,
    output_payload: dict,
    ttl_hours: int | None = None,
    scope_key: str = "",
) -> None:
    asyncio.create_task(_write_cache_entry(agent_id, normalized, output_payload, ttl_hours, scope_key))


async def _write_cache_entry(
    agent_id: uuid.UUID, normalized: NormalizedRequest, output_payload: dict, ttl_hours: int | None, scope_key: str
) -> None:
    try:
        async with async_session_factory() as session:
            await cache.write(
                session,
                agent_id=agent_id,
                normalized=normalized,
                output_payload=output_payload,
                ttl_hours=ttl_hours,
                scope_key=scope_key,
            )
    except Exception:
        logger.exception("SCIL: failed to write cache entry")


def log_metrics_fire_and_forget(
    *,
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    route: str,
    llm_calls: int,
    retries: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
) -> None:
    asyncio.create_task(
        _write_metrics(
            agent_id=agent_id,
            request_id=request_id,
            route=route,
            llm_calls=llm_calls,
            retries=retries,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
    )


async def _write_metrics(**kwargs: Any) -> None:
    try:
        async with async_session_factory() as session:
            await metrics.record(session, **kwargs)
    except Exception:
        logger.exception("SCIL: failed to write metrics")
