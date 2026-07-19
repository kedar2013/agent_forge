"""Model cascading: "cheap model first, escalate on low confidence" — the
model-selection half of the roadmap's "orchestration intelligence" item.
Wires the previously-dormant `model_config.scil.escalation_model` field
(declared in schemas/agents.py and scil/runner.ScilConfig since an earlier
phase, never actually consulted anywhere) into SCIL's EXISTING retry loop
(see playground_api/router.py's `_run_turn`): a SCIL validator failure is
already this platform's "low confidence" signal — a first attempt that a
deterministic check or the groundedness judge flagged as wrong. Rather than
inventing a second, parallel confidence heuristic, this reuses that one:
if `escalation_model` is configured, every retry after the first failure
runs on the bigger model instead of blindly retrying the same one.

Deliberately scoped to LEAF agents only (no sub_agents) — see
`build_escalated_agent`'s docstring for why an orchestrator is excluded
rather than partially/riskily supported.
"""

from google.adk.agents import Agent as AdkAgent


def is_escalation_over_budget(estimated_cost: float | None, max_cost: float | None) -> bool:
    """The "cost budget" half of cascading: True only when both a ceiling
    (`escalation_max_cost_usd`) and a real cost estimate are present AND
    the estimate exceeds it. Either being None (no ceiling configured, or
    nothing to estimate from — e.g. a turn with no token counts at all)
    means "not over budget", i.e. escalation proceeds — a missing budget
    signal should never itself become the reason a configured escalation
    silently never fires."""
    return max_cost is not None and estimated_cost is not None and estimated_cost > max_cost


def build_escalated_agent(adk_agent: AdkAgent, escalation_model: str) -> AdkAgent | None:
    """Returns a NEW agent instance with just `.model` swapped to
    `escalation_model` (via pydantic's `model_copy`, which never mutates
    the original — critical since `adk_agent` may be a published, CACHED
    instance shared across concurrent requests; mutating it in place would
    corrupt every other in-flight request using the same cached agent).

    Returns None (caller falls back to retrying on the original model) for
    an agent with any `sub_agents` — `model_copy` shallow-copies the
    `sub_agents` list rather than re-running ADK's own construction-time
    parent-agent wiring (see agent_runtime/builder.py's own comment on
    that mutable parent_agent assignment), so the safety of copying a
    multi-agent tree this way is unproven; a single leaf specialist (this
    platform's actual "escalate to a bigger model on a hard question" use
    case) has an empty sub_agents list and is unaffected by that concern
    at all.
    """
    if adk_agent.sub_agents:
        return None
    return adk_agent.model_copy(update={"model": _resolve_escalation_model(escalation_model)})


def _resolve_escalation_model(escalation_model: str):
    # Mirrors agent_runtime.builder._resolve_model's litellm-wrapping
    # convention (an "anthropic/<id>" string routes through ADK's LiteLlm
    # adapter; any other string, e.g. a gemini-* one, passes through as-is)
    # -- imported lazily to avoid a circular import (builder.py will import
    # THIS module for the reverse direction in a later pass, and even
    # today builder.py is the natural "owns model resolution" module this
    # defers to rather than duplicating that logic).
    from app.agent_runtime.builder import _resolve_model

    return _resolve_model(escalation_model)
