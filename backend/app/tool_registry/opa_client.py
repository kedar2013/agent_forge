"""Thin HTTP client for OPA's REST Data API (`POST /v1/data/<package-path>`)
— the policy-as-code alternative to `policy_engine.apply_policy`'s
in-process Python rule evaluation. See `backend/policies/*.rego` for a
worked example (credit_facility's persona-based RLS, the same rule set
`app.domains.credit_facility.policy_config` already expresses as JSON,
ported to Rego) and `backend/policies/*_test.rego` for its `opa test`
regression suite — the auditable, versioned control surface the rules
JSON alone doesn't give you (a `.rego` file is checked-in, diffable,
independently testable code; a JSONB `rules` column is neither).

An `AccessPolicy` opts into OPA per-policy, not platform-wide: setting
`resolver_config["engine"] = "opa"` and `resolver_config["opa_package"]`
(the dotted Rego package path, e.g. `"credit_facility.query_access"`)
routes that ONE policy's phase-2 decision through here; every policy that
doesn't set `engine` keeps using `apply_policy` exactly as before. See
`agent_runtime/builder.py`'s `_before_tool` for where this branch happens.
"""

import logging

import httpx

from app.config import get_settings
from app.tool_registry.policy_engine import PolicyResult

logger = logging.getLogger(__name__)


async def evaluate_opa_policy(opa_package: str, input_doc: dict) -> PolicyResult:
    """Always returns a `PolicyResult` — never raises. `input_doc` becomes
    OPA's `input` document verbatim (typically `{"persona":..., "scope":...,
    "args":...}` — see the call site in builder.py); the Rego policy's own
    `result.allowed`/`result.filter`/`result.reason` fields map straight
    onto `PolicyResult`, so a Rego policy is a drop-in replacement for
    `apply_policy` producing the exact same output shape
    `tool_registry.data_query_tool` already knows how to consume."""
    settings = get_settings()
    if not settings.opa_enabled:
        logger.error(
            "AccessPolicy references OPA package %r but OPA_ENABLED=false — denying (fail-closed).", opa_package
        )
        return PolicyResult(allowed=False, reason="Policy engine misconfigured: OPA is not enabled on this server.")

    url = f"{settings.opa_url.rstrip('/')}/v1/data/{opa_package.replace('.', '/')}"
    try:
        async with httpx.AsyncClient(timeout=settings.opa_timeout_seconds) as client:
            response = await client.post(url, json={"input": input_doc})
            response.raise_for_status()
            body = response.json()
        result = body.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"OPA package {opa_package!r} returned no 'result' document: {body!r}")
    except (httpx.HTTPError, ValueError) as exc:
        if settings.opa_fail_closed:
            logger.error("OPA policy evaluation failed for package %r (failing closed): %s", opa_package, exc)
            return PolicyResult(allowed=False, reason="Policy evaluation unavailable — access denied.")
        logger.warning(
            "OPA policy evaluation failed for package %r — OPA_FAIL_CLOSED=false, ALLOWING THROUGH UNFILTERED: %s",
            opa_package,
            exc,
        )
        return PolicyResult(allowed=True, filter={})

    if not result.get("allowed", False):
        return PolicyResult(allowed=False, reason=result.get("reason") or "Denied by policy.")
    return PolicyResult(allowed=True, filter=result.get("filter") or {})
