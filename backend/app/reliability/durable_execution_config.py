"""Per-agent durable-execution config, read from `model_config.durable_
execution` — same shape/convention as `app.scil.runner.ScilConfig`/
`get_scil_config`: off by default, opt-in per agent, zero behavior change
for every agent that never sets this key.

    "durable_execution": {"enabled": true}

No further knobs yet (unlike SCIL's threshold/ttl/validators) — this pass
is a binary opt-in; failure_threshold/cooldown_seconds for the circuit
breaker are process-wide defaults (see app/reliability/circuit_breaker.py),
not per-agent, since they gate a downstream tool, not an agent's reasoning.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class DurableExecutionConfig:
    enabled: bool = False


def get_durable_execution_config(agent_row: Any) -> DurableExecutionConfig:
    raw = (agent_row.model_config_json or {}).get("durable_execution") or {}
    return DurableExecutionConfig(enabled=bool(raw.get("enabled", False)))
