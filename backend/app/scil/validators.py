"""Deterministic output validators for the SCIL self-correction loop — no
LLM calls anywhere in this module. Which validators run for an agent comes
from its `model_config.scil.validators` list (see ScilAgentConfig); an
empty list means a successful turn is accepted as-is, exactly the Phase-2
behavior.

Error-signature taxonomy (stable strings — scil_correction_memory rows and
the corrections admin API filter on them, so they are contract, not
free-text):

    SQL:Syntax             — response didn't parse as SQL at all
    SQL:NotSingleSelect    — parsed, but not exactly one read-only SELECT
    SQL:GuardrailViolation — contains INSERT/UPDATE/DELETE/DDL anywhere
    JSON:ParseError        — response isn't valid JSON
    JSON:SchemaMismatch    — valid JSON, but violates the agent's declared
                             output_schema
    Hallucination:NoToolCall — the agent has tools attached but answered
                             without calling any of them this turn; the
                             answer is very likely invented rather than
                             looked up. Deterministic, no LLM call.

The `citation` validator from the original SCIL spec is deliberately not
implemented: chat responses in this platform carry no structured citation
ids to check against a retrieved chunk set, so there is nothing
deterministic to validate yet.

`Hallucination:Ungrounded` is a second, LLM-judge-based hallucination
signature — it does NOT come from this module (which makes no LLM calls,
see the constraint below) but from app.scil.hallucination.check_groundedness,
called separately from playground_api._run_turn when
model_config.scil.hallucination_groundedness_check is set. Its
ValidationResult flows into the exact same retry loop as everything
validated here.

`Entity:NoMatch` is a third signature living outside this module, for the
same reason `Hallucination:Ungrounded` does: it needs a DB round-trip
(sentence-transformer embedding lookup against scil_entity_memory), which
this module's own docstring bans. See app.scil.entities.resolve_entity_mismatch,
enabled via `"entity_resolution"` in an agent's `validators` list — it
catches a failure class neither this module's SQL check nor the
zero-tool-call hallucination check can see: syntactically valid SQL, a real
tool call, zero rows back because the literal the model searched for
("Tesslla") was a near-miss of something this agent has successfully
resolved before ("Tesla Inc").
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import jsonschema
import sqlglot
from sqlglot import exp

from app.tool_registry.data_query_tool import validate_single_select

# ```sql ... ``` or plain ``` ... ``` fencing an agent commonly wraps a SQL
# answer in; the validator judges the SQL itself, not the markdown around it.
_CODE_FENCE_RE = re.compile(r"```(?:sql|json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool
    error_signature: str | None = None
    error_detail: str | None = None


_VALID = ValidationResult(ok=True)


def _strip_code_fence(text: str) -> str:
    match = _CODE_FENCE_RE.search(text)
    return (match.group(1) if match else text).strip()


def validate_sql(
    response_text: str, agent_row: Any, tool_calls: list[Any] | None = None, tools_attached: bool = False
) -> ValidationResult:
    sql = _strip_code_fence(response_text)
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="mysql") if s is not None]
    except Exception as exc:  # noqa: BLE001 — the parse error IS the finding
        return ValidationResult(ok=False, error_signature="SQL:Syntax", error_detail=f"SQL failed to parse: {exc}")

    # Distinguish guardrail hits from shape problems so the correction
    # feedback (and correction-memory grouping) says the right thing.
    for stmt in statements:
        for node in stmt.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable)):
                return ValidationResult(
                    ok=False,
                    error_signature="SQL:GuardrailViolation",
                    error_detail="Query contains a forbidden write/DDL operation.",
                )

    error = validate_single_select(sql, dialect="mysql")
    if error:
        return ValidationResult(ok=False, error_signature="SQL:NotSingleSelect", error_detail=error)
    return _VALID


def validate_json_schema(
    response_text: str, agent_row: Any, tool_calls: list[Any] | None = None, tools_attached: bool = False
) -> ValidationResult:
    schema = getattr(agent_row, "output_schema", None)
    if not schema:
        # Nothing declared to validate against — misconfiguration, not a
        # model failure; accept rather than retry-loop on an unfixable error.
        return _VALID
    raw = _strip_code_fence(response_text)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return ValidationResult(ok=False, error_signature="JSON:ParseError", error_detail=f"Response is not valid JSON: {exc}")

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        return ValidationResult(ok=False, error_signature="JSON:SchemaMismatch", error_detail=exc.message)
    except jsonschema.SchemaError:
        # The agent's own declared schema is malformed — again not something
        # a model retry can fix, so accept and leave it to config surfacing.
        return _VALID
    return _VALID


def validate_hallucination(
    response_text: str, agent_row: Any, tool_calls: list[Any] | None = None, tools_attached: bool = False
) -> ValidationResult:
    """Deterministic half of hallucination detection: an agent with tools
    attached that answers without calling ANY of them this turn is very
    likely inventing the answer rather than looking it up. Ported from the
    identical one-off check the onboarding wizard's smoke test already used
    client-side (frontend/src/pages/onboarding/useNewDomainWizard.ts) — this
    makes it run on every real turn, not just that one canned question.

    `response_text` is unused here (the check is purely about whether a tool
    was called, not what the text says) but kept for signature parity with
    the other validators dispatched through validate_output.
    """
    if tools_attached and not tool_calls:
        return ValidationResult(
            ok=False,
            error_signature="Hallucination:NoToolCall",
            error_detail=(
                "Answered without calling any available data tool — likely an invented answer. "
                "Call the appropriate tool to look up real data before responding."
            ),
        )
    return _VALID


_VALIDATORS = {
    "sql": validate_sql,
    "json_schema": validate_json_schema,
    "hallucination": validate_hallucination,
}


def validate_output(
    response_text: str,
    validator_names: list[str],
    agent_row: Any,
    tool_calls: list[Any] | None = None,
    tools_attached: bool = False,
) -> ValidationResult:
    """Runs the configured validators in order; first failure wins (matching
    the correction loop's one-error-at-a-time feedback). Unknown names are
    skipped rather than raised — a future phase's validator name appearing
    in an agent's stored config must not break turns on an older backend."""
    for name in validator_names:
        validator = _VALIDATORS.get(name)
        if validator is None:
            continue
        result = validator(response_text, agent_row, tool_calls, tools_attached)
        if not result.ok:
            return result
    return _VALID
