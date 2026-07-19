"""Two-level configuration for the guardrails plugin, same convention as
`app.reliability.durable_execution_config`/`app.scil.runner.get_scil_config`:
a platform-wide default (Settings, env-driven — see app/config.py) that
every agent inherits unless it opts out, layered under a per-agent override
read from `model_config.guardrails` (same free-form JSONB key convention as
`durable_execution`/`scil`).

Deliberately defaults to ENABLED platform-wide (unlike durable_execution/
SCIL, which default OFF): those two are opt-in performance/correctness
features an agent author chooses; guardrails are a safety control this
platform's operator (not each individual agent author) is responsible for,
so the safe default is "on for everyone" with an explicit, auditable
per-agent opt-out rather than the reverse. `GUARDRAILS_ENABLED=false` is
still there as a platform-wide kill switch (e.g. local dev, or a staging
env with no judge-model budget).

    "guardrails": {
      "enabled": true,
      "input": {
        "prompt_injection_check": true,
        "jailbreak_check": true,
        "topical_scope": "credit facility and lending questions only",
        "topical_scope_check": false
      },
      "output": {
        "pii_check": true,
        "mnpi_check": true,
        "toxicity_check": true,
        "mnpi_terms": ["project falcon", "unannounced merger"],
        "action": "block"
      },
      "block_message": "..."
    }

Every key is optional; an agent that sets none of them gets the platform
default for each one individually (per-field merge, not "any override
replaces the whole block") so a config that only sets
`output.mnpi_terms` doesn't accidentally disable pii_check.
"""

from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

_DEFAULT_BLOCK_MESSAGE = (
    "I can't help with that request — it was flagged by an automated policy "
    "check. If you believe this is a mistake, please rephrase or contact your "
    "platform administrator."
)


@dataclass
class InputGuardrailConfig:
    prompt_injection_check: bool = True
    jailbreak_check: bool = True
    # Free-text description of what this agent should answer, e.g. "credit
    # facility and lending questions only" — judged by an LLM call, so off
    # by default (extra cost/latency per turn) even when guardrails overall
    # are on; an agent opts in by setting both a topical_scope string AND
    # topical_scope_check=true.
    topical_scope: str | None = None
    topical_scope_check: bool = False


@dataclass
class OutputGuardrailConfig:
    pii_check: bool = True
    mnpi_check: bool = True
    toxicity_check: bool = True
    # Merged with settings.guardrails_mnpi_terms (platform list), not a
    # replacement — a domain agent adds its own confidential terms on top
    # of whatever the operator already flags platform-wide.
    mnpi_terms: list[str] = field(default_factory=list)
    # "block" replaces the whole response with the refusal message;
    # "redact" masks only the flagged span(s) and lets the rest through —
    # only meaningful for pii_check/mnpi_check (regex-locatable spans);
    # toxicity_check always blocks regardless of this setting, since a
    # toxic response has no "safe partial" to redact down to.
    action: str = "block"


@dataclass
class GuardrailsConfig:
    enabled: bool = True
    input: InputGuardrailConfig = field(default_factory=InputGuardrailConfig)
    output: OutputGuardrailConfig = field(default_factory=OutputGuardrailConfig)
    block_message: str = _DEFAULT_BLOCK_MESSAGE


def get_guardrails_config(agent_row: Any) -> GuardrailsConfig:
    settings = get_settings()
    raw: dict = (getattr(agent_row, "model_config_json", None) or {}).get("guardrails") or {}
    raw_input: dict = raw.get("input") or {}
    raw_output: dict = raw.get("output") or {}

    return GuardrailsConfig(
        enabled=bool(raw.get("enabled", settings.guardrails_enabled)),
        input=InputGuardrailConfig(
            prompt_injection_check=bool(raw_input.get("prompt_injection_check", True)),
            jailbreak_check=bool(raw_input.get("jailbreak_check", True)),
            topical_scope=raw_input.get("topical_scope"),
            topical_scope_check=bool(raw_input.get("topical_scope_check", False)),
        ),
        output=OutputGuardrailConfig(
            pii_check=bool(raw_output.get("pii_check", True)),
            mnpi_check=bool(raw_output.get("mnpi_check", True)),
            toxicity_check=bool(raw_output.get("toxicity_check", True)),
            mnpi_terms=[*settings.guardrails_mnpi_terms, *raw_output.get("mnpi_terms", [])],
            action=raw_output.get("action", "block"),
        ),
        block_message=raw.get("block_message") or _DEFAULT_BLOCK_MESSAGE,
    )
