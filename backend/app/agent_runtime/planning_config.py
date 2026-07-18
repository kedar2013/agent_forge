"""Per-agent Planner/ReAct opt-in, read from `model_config.planning` — same
shape/convention as `app.scil.runner.ScilConfig`/`get_scil_config` and
`app.reliability.durable_execution_config`: off by default, opt-in per
agent, zero behavior change for every agent that never sets this key.

    "planning": {"enabled": true}

Wired into `google.adk.agents.Agent(planner=...)` in
`agent_runtime/builder.py` — ADK's own `flows/llm_flows/_nl_planning.py`
does the rest (building the planning instruction, splitting a response into
plan/reasoning/action vs. final-answer parts) whenever `agent.planner` is
set; nothing else in this codebase needs to know the planner exists except
for `playground_api/router.py`'s response-part filtering (see
`_execute_run`/`_stream_turn`), which keeps `part.thought`-marked
reasoning text out of the user-facing answer regardless of which agent
produced it.

Deliberately NOT set on any agent whose `output_schema` requires strict JSON
output (`PlanReActPlanner` forces free-text `/*PLANNING*/.../*ACTION*/...`
formatting, which cannot coexist with a schema-constrained response) — see
`scripts/consolidate_orchestrators.py` for which agents are excluded and why.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class PlanningConfig:
    enabled: bool = False


def get_planning_config(agent_row: Any) -> PlanningConfig:
    raw = (agent_row.model_config_json or {}).get("planning") or {}
    return PlanningConfig(enabled=bool(raw.get("enabled", False)))
