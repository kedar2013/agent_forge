"""The LLM-judge half of the System Prompt Evaluator — scores the "judged"
criteria in rubric.py (the ones that need real reasoning about MEANING, not
just regex) and drafts a suggested rewrite. Sibling to
app/scil/hallucination.py and app/scil/eval_runner.judge_regression_case:
same provider-selection-by-model-prefix pattern (a bare model string routes
to Gemini via google-genai, an "anthropic/<model>" string routes to Claude
via the official SDK), same "this is a judge call, not a tool call, so it
runs outside ADK's Runner entirely" reasoning.

Deliberately does NOT fail open the way hallucination.check_groundedness
does: that function protects a live user-facing turn (a broken judge must
never block a real answer), but this one IS the feature a caller explicitly
asked for — silently returning fabricated/empty scores on a judge error
would misinform exactly the person trying to improve their prompt. On
failure this raises JudgeError; service.py catches it and returns the
deterministic-only results with the error surfaced plainly instead.
"""

import json
import re
from dataclasses import dataclass

from app.prompt_eval.rubric import CRITERIA, CRITERIA_BY_ID
from app.prompt_eval.types import CriterionResult

DEFAULT_JUDGE_MODEL = "gemini-3.5-flash"

_JUDGED_CRITERIA = [c for c in CRITERIA if c.method == "judged"]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class JudgeError(Exception):
    pass


@dataclass
class JudgeOutput:
    criteria: list[CriterionResult]
    summary: str
    suggested_rewrite: str | None
    model_used: str


def _criteria_directory() -> str:
    return "\n".join(f'- id="{c.id}" ({c.label}): {c.description}' for c in _JUDGED_CRITERIA)


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": [c.id for c in _JUDGED_CRITERIA]},
                    "score": {"type": "integer", "description": "1 (poor) to 5 (excellent)."},
                    "rationale": {"type": "string", "description": "One or two sentences, specific to THIS prompt."},
                    "suggestion": {
                        "type": "string",
                        "description": "Concrete fix if score <= 3; empty string if score >= 4.",
                    },
                },
                "required": ["id", "score", "rationale", "suggestion"],
            },
        },
        "summary": {"type": "string", "description": "2-3 sentence overall assessment."},
        "suggested_rewrite": {
            "type": "string",
            "description": (
                "A full rewritten version of the instruction addressing every criterion scored <= 3. "
                "Empty string if no criterion scored that low."
            ),
        },
    },
    "required": ["criteria", "summary", "suggested_rewrite"],
}

_PROMPT_TEMPLATE = """You are a senior prompt engineer reviewing ONE AI agent's system instruction \
against a fixed rubric, for a platform where agents are built by composing instructions, tools, and \
sub-agents (not hand-written code).

{context_block}

THE INSTRUCTION TEXT BEING REVIEWED (verbatim, this is the "{scope}" version — {scope_note}):
---
{instruction_text}
---

Score EACH of the following criteria from 1 (poor) to 5 (excellent), with a specific one-or-two \
sentence rationale grounded in what this exact instruction actually says or fails to say (never generic \
advice that could apply to any prompt). For any criterion scoring 3 or below, give one concrete, \
actionable suggestion for what to add or change. For a criterion scoring 4 or 5, leave suggestion as an \
empty string.

Criteria to score:
{criteria_directory}

Also write a 2-3 sentence overall summary, and — ONLY if at least one criterion above scored 3 or \
below — a full suggested_rewrite: a complete, ready-to-use rewritten version of the instruction that \
fixes every weak criterion while preserving everything that already works well and keeping the agent's \
actual purpose intact. If every criterion scored 4 or 5, leave suggested_rewrite as an empty string \
rather than rewriting a prompt that isn't meaningfully broken.

Respond with ONLY the JSON object described, no other text."""


def _build_context_block(
    *,
    agent_name: str | None,
    tools: list[tuple[str, str]],
    sub_agent_names: list[str],
    has_output_schema: bool,
    scil_enabled: bool,
    durable_execution_enabled: bool,
    planning_enabled: bool,
) -> str:
    lines = [f"Agent being evaluated: {agent_name or '(unnamed / pasted prompt text)'}"]
    if tools:
        tool_lines = "\n".join(f"  - {name}: {desc or '(no description)'}" for name, desc in tools)
        lines.append(f"Tools actually attached to this agent:\n{tool_lines}")
    else:
        lines.append("Tools actually attached to this agent: none.")
    if sub_agent_names:
        lines.append(
            f"Sub-agents attached (this makes it an ORCHESTRATOR on this platform, expected to route "
            f"via transfer_to_agent rather than answer domain questions itself): {', '.join(sub_agent_names)}"
        )
    else:
        lines.append("Sub-agents attached: none (this is a leaf specialist, not an orchestrator).")
    if has_output_schema:
        lines.append("This agent has a declared structured output_schema (strict JSON output is enforced separately).")
    flags = []
    if scil_enabled:
        flags.append("SCIL (semantic caching / self-correction) is enabled")
    if durable_execution_enabled:
        flags.append("durable execution (crash-safe checkpointing) is enabled")
    if planning_enabled:
        flags.append("Planner/ReAct reasoning mode is enabled")
    if flags:
        lines.append("Runtime flags: " + "; ".join(flags) + ".")
    return "\n".join(lines)


def _extract_json_object(raw: str) -> dict:
    raw = raw.strip()
    fence_match = _JSON_FENCE_RE.search(raw)
    candidate = fence_match.group(1).strip() if fence_match else raw
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        pass
    # Last resort: the first balanced-looking {...} block in the text.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except (TypeError, ValueError) as exc:
            raise JudgeError(f"Judge response was not valid JSON: {exc}") from exc
    raise JudgeError("Judge response contained no JSON object.")


def _parse_judge_payload(payload: dict) -> tuple[list[CriterionResult], str, str | None]:
    results: list[CriterionResult] = []
    seen_ids: set[str] = set()
    for item in payload.get("criteria", []):
        criterion_id = item.get("id")
        criterion = CRITERIA_BY_ID.get(criterion_id)
        if criterion is None or criterion.method != "judged":
            continue  # unknown/hallucinated id — skip rather than trust it
        seen_ids.add(criterion_id)
        try:
            score = max(1, min(5, int(item.get("score", 3))))
        except (TypeError, ValueError):
            score = 3
        suggestion = (item.get("suggestion") or "").strip() or None
        results.append(
            CriterionResult(
                id=criterion_id,
                score=score,
                applicable=True,
                severity="critical" if score <= 2 else ("warning" if score == 3 else "info"),
                rationale=str(item.get("rationale") or "").strip() or "(no rationale given)",
                suggestion=suggestion,
            )
        )
    # Any judged criterion the model didn't return gets a neutral, clearly-
    # marked placeholder rather than silently vanishing from the report.
    for criterion in _JUDGED_CRITERIA:
        if criterion.id not in seen_ids:
            results.append(
                CriterionResult(
                    id=criterion.id, score=3, applicable=True, severity="warning",
                    rationale="The judge model did not return a score for this criterion.",
                )
            )
    summary = str(payload.get("summary") or "").strip()
    suggested_rewrite = (payload.get("suggested_rewrite") or "").strip() or None
    return results, summary, suggested_rewrite


async def run_judge(
    *,
    instruction_text: str,
    scope: str,
    agent_name: str | None,
    tools: list[tuple[str, str]],
    sub_agent_names: list[str],
    has_output_schema: bool,
    scil_enabled: bool,
    durable_execution_enabled: bool,
    planning_enabled: bool,
    model: str = DEFAULT_JUDGE_MODEL,
) -> JudgeOutput:
    scope_note = (
        "base_instruction alone"
        if scope == "static"
        else "base_instruction plus every attached skill's instruction text, composed exactly as the runtime sends it"
    )
    context_block = _build_context_block(
        agent_name=agent_name,
        tools=tools,
        sub_agent_names=sub_agent_names,
        has_output_schema=has_output_schema,
        scil_enabled=scil_enabled,
        durable_execution_enabled=durable_execution_enabled,
        planning_enabled=planning_enabled,
    )
    prompt = _PROMPT_TEMPLATE.format(
        context_block=context_block,
        scope=scope,
        scope_note=scope_note,
        instruction_text=instruction_text,
        criteria_directory=_criteria_directory(),
    )

    try:
        if model.startswith("anthropic/"):
            import anthropic

            client = anthropic.AsyncAnthropic()
            response = await client.messages.create(
                model=model.removeprefix("anthropic/"),
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = "".join(block.text for block in response.content if block.type == "text")
        else:
            from google import genai
            from google.genai import types

            client = genai.Client()
            result = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                    temperature=0.2,
                ),
            )
            raw_text = result.text or ""
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller, not swallowed
        raise JudgeError(f"Judge model call failed: {exc}") from exc

    payload = _extract_json_object(raw_text)
    criteria_results, summary, suggested_rewrite = _parse_judge_payload(payload)
    return JudgeOutput(criteria=criteria_results, summary=summary, suggested_rewrite=suggested_rewrite, model_used=model)
