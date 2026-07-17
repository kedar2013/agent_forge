"""The LLM-judge half of SCIL hallucination detection — sibling to
corrector.py, not part of validators.py (whose docstring bans LLM calls
outright). Called from playground_api._run_turn only when an agent has
"hallucination" in model_config.scil.validators AND has opted into
model_config.scil.hallucination_groundedness_check (it costs an extra
model call per turn, so it's opt-in on top of the always-free
zero-tool-call check in validators.validate_hallucination).

Its ValidationResult flows into the exact same retry loop every other
SCIL validator failure does — this module only decides pass/fail, the
corrector/retry mechanics are unchanged.
"""

import logging
from typing import Any

from app.observability.rca import cap_payload
from app.scil.validators import ValidationResult

logger = logging.getLogger(__name__)

_VALID = ValidationResult(ok=True)

_JUDGE_PROMPT_TEMPLATE = """You are a strict fact-checker reviewing one AI agent turn.

The agent had access to ONLY the following tool call results as its source of factual data:

{tool_calls_block}

The agent's final answer to the user was:
{response_text}

Does every factual claim in the answer (numbers, names, dates, values) come directly from the \
tool output data above, with no invented, unsupported, or embellished detail? Cosmetic formatting \
of a value that IS present in the tool output — adding a currency symbol, thousands separator, \
percent sign, unit label, or rounding to a reasonable precision — is NOT a hallucination; only flag \
a claim as ungrounded if its underlying value or fact does not appear in the tool output at all. \
Reply with exactly one line: "GROUNDED" if yes, or "UNGROUNDED: <brief reason>" if the answer \
contains any claim not supported by the tool output."""


def _format_tool_calls(tool_calls: list[Any]) -> str:
    if not tool_calls:
        return "(no tool calls were made this turn)"
    blocks = []
    for call in tool_calls:
        name = getattr(call, "name", None) or (call.get("name") if isinstance(call, dict) else None)
        tool_input = getattr(call, "input", None) if not isinstance(call, dict) else call.get("input")
        output = getattr(call, "output", None) if not isinstance(call, dict) else call.get("output")
        blocks.append(f"Tool: {name}\nInput: {cap_payload(tool_input)}\nOutput: {cap_payload(output)}")
    return "\n\n".join(blocks)


async def check_groundedness(response_text: str, tool_calls: list[Any], agent_row: Any) -> ValidationResult:
    """Reference-free groundedness check: does the answer's content trace
    back to the tool outputs it actually received this turn? Fails open
    (returns ok=True) on any judge-call error — a broken judge must never
    block a real answer from reaching the user."""
    if not tool_calls:
        # Nothing to ground against — the zero-tool-call check in
        # validators.py already covers this case deterministically and for
        # free; don't spend a second LLM call restating the same finding.
        return _VALID

    try:
        model = (agent_row.model_config_json or {}).get("model", "gemini-2.5-flash")
        prompt = _JUDGE_PROMPT_TEMPLATE.format(
            tool_calls_block=_format_tool_calls(tool_calls), response_text=response_text
        )
        # Judge runs on whatever provider the agent itself is configured
        # for — same "anthropic/<model-id>" convention the model dropdown
        # stores and agent_runtime/builder.py._resolve_model reads.
        if model.startswith("anthropic/"):
            import anthropic

            client = anthropic.AsyncAnthropic()
            response = await client.messages.create(
                model=model.removeprefix("anthropic/"),
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            verdict = "".join(block.text for block in response.content if block.type == "text").strip()
        else:
            from google import genai

            client = genai.Client()
            result = await client.aio.models.generate_content(model=model, contents=prompt)
            verdict = (result.text or "").strip()
    except Exception:
        logger.exception("SCIL: groundedness judge call failed — failing open (accepting the answer)")
        return _VALID

    if verdict.upper().startswith("GROUNDED"):
        return _VALID

    reason = verdict.split(":", 1)[1].strip() if ":" in verdict else verdict or "Judge flagged this answer as ungrounded."
    return ValidationResult(ok=False, error_signature="Hallucination:Ungrounded", error_detail=reason)
