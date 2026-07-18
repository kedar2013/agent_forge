"""The fixed rubric the System Prompt Evaluator scores every instruction
against — half deterministic (cheap, regex/heuristic, no LLM call, always
run, see deterministic_checks.py), half judged (needs real reasoning about
meaning, see judge.py). Modeled on widely-used prompt-engineering guidance
(role/objective clarity, specificity, constraints, output-format contract,
tool-use guidance, consistency, edge-case handling, conciseness) PLUS three
criteria specific to how agents actually work on THIS platform:

  - tool_usage_guidance / tool_usage_guidance_quality — informed by which
    tools are ACTUALLY attached to the agent being evaluated (from
    `agent_tools`), not generic advice about tools in the abstract.
  - orchestrator_routing_discipline — an agent with sub_agents attached is
    "orchestrator-shaped" on this platform (see app/agent_runtime/
    orchestration_patterns.py) and is expected to route via
    transfer_to_agent rather than answer domain questions itself; failing
    to instruct that is a real, previously-seen failure mode here, not a
    hypothetical one.
  - platform_convention_alignment — checks the instruction doesn't fight
    RLS/tool-safety/durable-execution conventions this platform's runtime
    already enforces mechanically (e.g. an instruction that invites the
    model to fabricate data when a tool returns nothing, or to ignore an
    access-denied response instead of relaying it).

Every criterion is additive, not exclusive: a criterion CAN be marked
"not applicable" (e.g. tool_usage_guidance when an agent has zero tools)
without affecting the weighted score — see `service.py`'s aggregation.
"""

from dataclasses import dataclass
from typing import Literal

Method = Literal["deterministic", "judged"]
Category = Literal["structure", "clarity", "safety", "tooling", "output", "consistency", "platform"]


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    category: Category
    method: Method
    # Relative importance in the weighted overall score — bigger number,
    # more it moves the needle. Not a percentage; only relative to the
    # other weights in this same list.
    weight: int
    description: str


CRITERIA: list[Criterion] = [
    # --- Deterministic (deterministic_checks.py) ---------------------------
    Criterion(
        id="length_appropriateness",
        label="Length is appropriate",
        category="structure",
        method="deterministic",
        weight=2,
        description=(
            "Flags an instruction that's likely under-specified (very short) or so long it risks "
            "burying key guidance / wasting context budget on every single turn."
        ),
    ),
    Criterion(
        id="role_definition_present",
        label="Role / persona is explicitly stated",
        category="clarity",
        method="deterministic",
        weight=3,
        description='Checks for an explicit framing of who the agent is and what it\'s for ("You are...", "Your role is...").',
    ),
    Criterion(
        id="output_format_specified",
        label="Output format / structure is specified",
        category="output",
        method="deterministic",
        weight=3,
        description=(
            "Checks whether the instruction (or the agent's own declared output_schema) tells the "
            "model what shape/format its answer should take."
        ),
    ),
    Criterion(
        id="hedging_language_density",
        label="Avoids vague, unenforceable hedge language",
        category="clarity",
        method="deterministic",
        weight=2,
        description=(
            'Flags a high density of hedge phrases ("try to", "if possible", "generally", "usually") '
            "relative to length — instructions phrased as soft suggestions are easy for a model to skip."
        ),
    ),
    Criterion(
        id="placeholder_or_todo_leftover",
        label="No leftover placeholders / TODOs",
        category="structure",
        method="deterministic",
        weight=4,
        description='Flags stray "TODO", "FIXME", "{{...}}", "[insert ...]", lorem-ipsum-style filler that should never ship.',
    ),
    Criterion(
        id="tool_usage_guidance",
        label="Attached tools have usage guidance",
        category="tooling",
        method="deterministic",
        weight=3,
        description=(
            "For an agent with tools attached: checks the instruction actually says something about "
            "when/how to use them, rather than leaving tool-calling entirely implicit."
        ),
    ),
    Criterion(
        id="orchestrator_routing_discipline",
        label="Orchestrator-shaped agents instruct routing, not answering",
        category="platform",
        method="deterministic",
        weight=4,
        description=(
            "For an agent with sub_agents attached (an orchestrator on this platform): checks the "
            "instruction tells it to transfer to a specialist rather than answer domain questions itself "
            "— the pattern app/agent_runtime/orchestration_patterns.py's build_router_instruction encodes."
        ),
    ),
    Criterion(
        id="redundancy_check",
        label="No near-duplicate, redundant sentences",
        category="structure",
        method="deterministic",
        weight=1,
        description="Flags repeated or near-duplicate sentences that pad length without adding guidance.",
    ),
    Criterion(
        id="examples_present",
        label="Examples / few-shot demonstrations",
        category="clarity",
        method="deterministic",
        weight=1,
        description=(
            "Advisory, not a hard requirement: notes whether the instruction or an attached skill's "
            "few_shot_examples gives the model a concrete worked example."
        ),
    ),
    # --- Judged (judge.py, needs real reasoning) ---------------------------
    Criterion(
        id="role_and_objective_clarity",
        label="Role and objective are unambiguous",
        category="clarity",
        method="judged",
        weight=4,
        description="Is it clear WHO the agent is, WHAT it's for, and what's out of scope for it?",
    ),
    Criterion(
        id="specificity_and_actionability",
        label="Instructions are specific and actionable",
        category="clarity",
        method="judged",
        weight=4,
        description="Are instructions concrete enough to act on consistently, or vague aspirations open to many interpretations?",
    ),
    Criterion(
        id="constraints_and_guardrails",
        label="Constraints and guardrails are stated",
        category="safety",
        method="judged",
        weight=4,
        description="Does it say what the agent must NOT do, and how to handle requests outside its scope?",
    ),
    Criterion(
        id="output_structure_quality",
        label="Output guidance is complete and usable",
        category="output",
        method="judged",
        weight=3,
        description="Beyond just specifying SOME format: is the expected tone/length/structure clear enough to produce consistent answers?",
    ),
    Criterion(
        id="tool_usage_guidance_quality",
        label="Tool usage guidance is correct and sufficient",
        category="tooling",
        method="judged",
        weight=3,
        description=(
            "Given the agent's ACTUAL attached tools (name + description), does the instruction correctly "
            "guide when/how each should be used, without misdescribing what a tool does?"
        ),
    ),
    Criterion(
        id="consistency_no_contradictions",
        label="Internally consistent, no contradictions",
        category="consistency",
        method="judged",
        weight=4,
        description="Do any two instructions conflict (e.g. one clause requires X, another forbids it)?",
    ),
    Criterion(
        id="edge_case_and_failure_handling",
        label="Edge cases and failures are covered",
        category="safety",
        method="judged",
        weight=3,
        description="Does it say what to do when data is missing, a tool errors, or the request is ambiguous/out of scope?",
    ),
    Criterion(
        id="conciseness_vs_completeness",
        label="Balances conciseness with completeness",
        category="structure",
        method="judged",
        weight=2,
        description="Is it appropriately tight without dropping necessary guidance, or bloated with filler that dilutes the important parts?",
    ),
    Criterion(
        id="platform_convention_alignment",
        label="Aligned with this platform's own conventions",
        category="platform",
        method="judged",
        weight=3,
        description=(
            "Given this agent's real context (RLS-scoped tools, sub-agents, planning/durable-execution "
            "flags), does the instruction avoid fighting mechanisms the runtime already enforces — e.g. "
            "inviting the model to fabricate data, or to route around an access-denied response?"
        ),
    ),
]

CRITERIA_BY_ID: dict[str, Criterion] = {c.id: c for c in CRITERIA}

# A criterion scoring at or below this (on the 1-5 scale every criterion is
# normalized to before weighting) is "weak enough to call out a suggested
# rewrite for" — see judge.py/service.py. 3 = "adequate but not solid."
REWRITE_TRIGGER_THRESHOLD = 3
