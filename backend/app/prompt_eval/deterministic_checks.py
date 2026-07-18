"""Deterministic (no-LLM-call) half of the System Prompt Evaluator's rubric
— same "cheap, code-only, always run" philosophy as app/scil/validators.py.
Every function here is a pure function over plain primitives (strings,
lists of name/description tuples) so it's trivially unit-testable and never
needs a live DB session or model call — mirrors validate_sql/
validate_json_schema's own shape in that file.

Each check returns exactly one CriterionResult (see types.py) whose `id`
matches a Criterion in rubric.py — service.py asserts this at merge time,
so a typo here fails loudly (a silently-dropped criterion is worse than an
import-time error).
"""

import re
from dataclasses import dataclass

from app.prompt_eval.types import CriterionResult

_WORD_RE = re.compile(r"\S+")

_ROLE_PATTERNS = [
    re.compile(r"\byou\s+are\b", re.IGNORECASE),
    re.compile(r"\byour\s+role\s+is\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\b", re.IGNORECASE),
    re.compile(r"\byou'?re\s+(?:an?|the)\b", re.IGNORECASE),
]

_FORMAT_PATTERNS = [
    re.compile(r"\bjson\b", re.IGNORECASE),
    re.compile(r"\bmarkdown\b", re.IGNORECASE),
    re.compile(r"\brespond\s+with\b", re.IGNORECASE),
    re.compile(r"\bformat\s+your\b", re.IGNORECASE),
    re.compile(r"\b(output|response)\s+format\b", re.IGNORECASE),
    re.compile(r"\bschema\b", re.IGNORECASE),
    re.compile(r"\bbullet\s*points?\b", re.IGNORECASE),
    re.compile(r"\btable\b", re.IGNORECASE),
    re.compile(r"\bstructure\s+your\s+(answer|response)\b", re.IGNORECASE),
]

_HEDGE_PHRASES = [
    "try to", "if possible", "generally", "usually", "should probably",
    "maybe", "perhaps", "as much as possible", "when appropriate", "ideally",
    "ought to", "in most cases", "where feasible", "tend to",
]

_PLACEHOLDER_PATTERNS = [
    re.compile(r"\bTODO\b"),
    re.compile(r"\bFIXME\b"),
    re.compile(r"\{\{.*?\}\}"),
    re.compile(r"\[insert[^\]]*\]", re.IGNORECASE),
    re.compile(r"\bXXX\b"),
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"<\s*(your|agent|domain)[\w\s]*>", re.IGNORECASE),
]

_GENERIC_TOOL_GUIDANCE_PATTERNS = [
    re.compile(r"\buse\s+the\s+(following\s+)?tools?\b", re.IGNORECASE),
    re.compile(r"\bcall\s+the\s+(appropriate\s+)?tool\b", re.IGNORECASE),
    re.compile(r"\byou\s+have\s+access\s+to\b", re.IGNORECASE),
    re.compile(r"\balways\s+call\b", re.IGNORECASE),
]

_ROUTING_DISCIPLINE_PATTERNS = [
    re.compile(r"transfer_to_agent", re.IGNORECASE),
    re.compile(r"\btransfer\s+to\b", re.IGNORECASE),
    re.compile(r"\bnever\s+answer\b", re.IGNORECASE),
    re.compile(r"\brout(e|ing)\b", re.IGNORECASE),
    re.compile(r"router-peer-clause", re.IGNORECASE),
]

_EXAMPLE_PATTERNS = [
    re.compile(r"\bfor\s+example\b", re.IGNORECASE),
    re.compile(r"\be\.g\.", re.IGNORECASE),
    re.compile(r"\bfor\s+instance\b", re.IGNORECASE),
    re.compile(r"\bexample:", re.IGNORECASE),
]


@dataclass
class ToolInfo:
    name: str
    description: str


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def check_length_appropriateness(text: str) -> CriterionResult:
    words = _word_count(text)
    if words < 15:
        return CriterionResult(
            id="length_appropriateness", score=1, applicable=True, severity="critical",
            rationale=f"Only {words} words — almost certainly under-specified for a real agent instruction.",
            suggestion="Expand with an explicit role, task scope, constraints, and expected output shape.",
        )
    if words < 40:
        return CriterionResult(
            id="length_appropriateness", score=3, applicable=True, severity="warning",
            rationale=f"{words} words — quite short; check nothing essential (scope, constraints, format) was left implicit.",
        )
    if words <= 1200:
        return CriterionResult(
            id="length_appropriateness", score=5, applicable=True, severity="info",
            rationale=f"{words} words — a reasonable length for a single agent instruction.",
        )
    if words <= 2000:
        return CriterionResult(
            id="length_appropriateness", score=3, applicable=True, severity="warning",
            rationale=f"{words} words — on the long side; important guidance may be getting buried.",
            suggestion="Consider moving reusable, non-core guidance into an attached Skill instead of the base instruction.",
        )
    return CriterionResult(
        id="length_appropriateness", score=2, applicable=True, severity="warning",
        rationale=f"{words} words — very long. This costs tokens on every single turn and likely buries key rules.",
        suggestion="Split into a tighter base instruction plus one or more attached Skills for domain-specific detail.",
    )


def check_role_definition_present(text: str) -> CriterionResult:
    if any(p.search(text) for p in _ROLE_PATTERNS):
        return CriterionResult(
            id="role_definition_present", score=5, applicable=True, severity="info",
            rationale="An explicit role/persona statement is present.",
        )
    return CriterionResult(
        id="role_definition_present", score=2, applicable=True, severity="warning",
        rationale="No explicit role/persona framing found (e.g. \"You are...\").",
        suggestion='Open with a one-sentence role statement, e.g. "You are the <domain> specialist responsible for <task>."',
    )


def check_output_format_specified(text: str, has_output_schema: bool) -> CriterionResult:
    if has_output_schema:
        return CriterionResult(
            id="output_format_specified", score=5, applicable=True, severity="info",
            rationale="This agent has a declared output_schema, which mechanically enforces response structure.",
        )
    if any(p.search(text) for p in _FORMAT_PATTERNS):
        return CriterionResult(
            id="output_format_specified", score=4, applicable=True, severity="info",
            rationale="The instruction references an expected output format/structure.",
        )
    return CriterionResult(
        id="output_format_specified", score=2, applicable=True, severity="warning",
        rationale="No output format/structure guidance found, and no output_schema is set.",
        suggestion="State the expected shape of a good answer — length, tone, headings/bullets, or a JSON contract if this feeds another system.",
    )


def check_hedging_language_density(text: str) -> CriterionResult:
    words = max(_word_count(text), 1)
    lowered = text.lower()
    count = sum(lowered.count(phrase) for phrase in _HEDGE_PHRASES)
    ratio = count / words
    if ratio > 0.02:
        return CriterionResult(
            id="hedging_language_density", score=2, applicable=True, severity="warning",
            rationale=f"{count} hedge phrase(s) found — instructions phrased as soft suggestions are easy for a model to skip.",
            suggestion='Replace hedges ("try to", "if possible") with direct, enforceable statements ("always", "never", "do X").',
        )
    if ratio > 0.005:
        return CriterionResult(
            id="hedging_language_density", score=4, applicable=True, severity="info",
            rationale=f"{count} hedge phrase(s) found — a minor amount, likely fine.",
        )
    return CriterionResult(
        id="hedging_language_density", score=5, applicable=True, severity="info",
        rationale="Little to no vague hedge language detected.",
    )


def check_placeholder_or_todo_leftover(text: str) -> CriterionResult:
    hits = [p.pattern for p in _PLACEHOLDER_PATTERNS if p.search(text)]
    if hits:
        return CriterionResult(
            id="placeholder_or_todo_leftover", score=1, applicable=True, severity="critical",
            rationale=f"Found leftover placeholder/TODO-style text matching: {', '.join(hits)}.",
            suggestion="Remove or fill in every placeholder before this agent is published.",
        )
    return CriterionResult(
        id="placeholder_or_todo_leftover", score=5, applicable=True, severity="info",
        rationale="No leftover placeholders or TODO markers found.",
    )


def check_tool_usage_guidance(text: str, tools: list[ToolInfo]) -> CriterionResult:
    if not tools:
        return CriterionResult.not_applicable(
            "tool_usage_guidance", "This agent has no tools attached — nothing to guide usage of."
        )
    lowered = text.lower()
    mentioned = sum(1 for t in tools if t.name.lower().replace("_", " ") in lowered or t.name.lower() in lowered)
    has_generic = any(p.search(text) for p in _GENERIC_TOOL_GUIDANCE_PATTERNS)
    ratio = mentioned / len(tools)
    if ratio >= 0.5 or has_generic:
        return CriterionResult(
            id="tool_usage_guidance", score=5, applicable=True, severity="info",
            rationale=f"{mentioned}/{len(tools)} attached tool(s) referenced by name, or generic tool-usage guidance is present.",
        )
    if ratio > 0:
        return CriterionResult(
            id="tool_usage_guidance", score=3, applicable=True, severity="warning",
            rationale=f"Only {mentioned}/{len(tools)} attached tool(s) are referenced in the instruction.",
            suggestion="Say explicitly when each remaining tool should be called.",
        )
    return CriterionResult(
        id="tool_usage_guidance", score=2, applicable=True, severity="warning",
        rationale=f"{len(tools)} tool(s) attached, but the instruction never explains when/how to use any of them.",
        suggestion="Add explicit guidance for each attached tool: what it's for and when to call it.",
    )


def check_orchestrator_routing_discipline(text: str, sub_agent_names: list[str]) -> CriterionResult:
    if not sub_agent_names:
        return CriterionResult.not_applicable(
            "orchestrator_routing_discipline", "This agent has no sub-agents attached — it isn't orchestrator-shaped."
        )
    if any(p.search(text) for p in _ROUTING_DISCIPLINE_PATTERNS):
        return CriterionResult(
            id="orchestrator_routing_discipline", score=5, applicable=True, severity="info",
            rationale="Instruction tells this orchestrator-shaped agent to route/transfer rather than answer itself.",
        )
    return CriterionResult(
        id="orchestrator_routing_discipline", score=1, applicable=True, severity="critical",
        rationale=(
            f"This agent has {len(sub_agent_names)} sub-agent(s) attached ({', '.join(sub_agent_names[:5])}"
            f"{'...' if len(sub_agent_names) > 5 else ''}) but nothing in its instruction tells it to route "
            "to them instead of answering domain questions itself."
        ),
        suggestion=(
            "Add explicit routing instructions, e.g. via "
            "app.agent_runtime.orchestration_patterns.build_router_instruction — never answer a domain "
            "question directly; always transfer_to_agent to the right specialist(s)."
        ),
    )


def check_redundancy(text: str) -> CriterionResult:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    normalized = [re.sub(r"\s+", " ", s.strip().lower()) for s in sentences]
    normalized = [s for s in normalized if len(s.split()) >= 6]
    seen: dict[str, int] = {}
    for s in normalized:
        seen[s] = seen.get(s, 0) + 1
    duplicates = {s: c for s, c in seen.items() if c > 1}
    if duplicates:
        return CriterionResult(
            id="redundancy_check", score=3, applicable=True, severity="warning",
            rationale=f"{len(duplicates)} sentence(s) appear to be repeated near-verbatim.",
            suggestion="Remove repeated sentences — redundant phrasing wastes tokens without adding guidance.",
        )
    return CriterionResult(
        id="redundancy_check", score=5, applicable=True, severity="info",
        rationale="No obviously repeated/redundant sentences found.",
    )


def check_examples_present(text: str, skills_have_few_shot: bool) -> CriterionResult:
    if skills_have_few_shot or any(p.search(text) for p in _EXAMPLE_PATTERNS):
        return CriterionResult(
            id="examples_present", score=5, applicable=True, severity="info",
            rationale="A worked example or few-shot demonstration is present (in the instruction or an attached skill).",
        )
    return CriterionResult(
        id="examples_present", score=3, applicable=True, severity="info",
        rationale="No worked example found. Not always necessary, but often helps for nuanced formatting/tone tasks.",
        suggestion="Consider adding one short example of an ideal input/output pair, especially if output formatting is nuanced.",
    )


def run_deterministic_checks(
    *,
    text: str,
    tools: list[ToolInfo],
    sub_agent_names: list[str],
    has_output_schema: bool,
    skills_have_few_shot: bool,
) -> list[CriterionResult]:
    """Runs every deterministic criterion in rubric.py order. Cheap enough
    (pure regex/string ops) to always run in full, even when the LLM judge
    call later fails — a caller should never be left with zero signal."""
    return [
        check_length_appropriateness(text),
        check_role_definition_present(text),
        check_output_format_specified(text, has_output_schema),
        check_hedging_language_density(text),
        check_placeholder_or_todo_leftover(text),
        check_tool_usage_guidance(text, tools),
        check_orchestrator_routing_discipline(text, sub_agent_names),
        check_redundancy(text),
        check_examples_present(text, skills_have_few_shot),
    ]
