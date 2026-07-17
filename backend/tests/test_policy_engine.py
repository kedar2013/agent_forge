"""Pure-function tests for the generic RLS engine (`apply_policy`), using the
real Credit Facility persona rules as the worked example — no live DB
required, since `apply_policy` never does I/O itself (that's `resolve_scope`,
whose MySQL lookups are exercised end-to-end via /chat instead, see the
implementation plan's manual verification steps).

Note: CCB's "must supply an exact gfcid" requirement is no longer enforced
here — `apply_policy` just resolves CCB to `{_policy_mode: 'EXACT'}`
unconditionally now that the query itself is LLM-written SQL, not a
structured arg to gate on before execution. The actual enforcement (the
query's WHERE clause must contain a literal gfcid equality) is tested in
`test_data_query_tool.py::test_exact_mode_*`, against the parsed SQL."""

from types import SimpleNamespace

from app.domains.credit_facility.policy_config import QUERY_RULES, SEARCH_RULES
from app.tool_registry.policy_engine import ScopeResolution, apply_policy


def _policy(rules: dict):
    return SimpleNamespace(rules=rules)


def test_gcm_is_global():
    scope = ScopeResolution(found=True, discriminator="GCM", scope={})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert result.allowed
    assert result.filter["_policy_mode"] == "GLOBAL"


def test_gsg_excludes_l2():
    scope = ScopeResolution(found=True, discriminator="GSG", scope={})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert result.allowed
    assert result.filter["_policy_mode"] == "ATTRIBUTE_SCOPED"
    assert result.filter["_attr_values"] == ["L3", "L4"]


def test_non_gsg_restricted_to_coverage_list():
    scope = ScopeResolution(found=True, discriminator="NON_GSG", scope={"coverage": ["C0007", "C0012"]})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert result.allowed
    assert result.filter["_policy_mode"] == "ID_SCOPED"
    assert result.filter["_id_values"] == ["C0007", "C0012"]


def test_non_gsg_with_empty_coverage_matches_nothing():
    """No coverage rows for this user -> an empty list, not an unfiltered
    query -- the failure mode for a misconfigured coverage list must be
    "sees nothing", never "sees everything". data_query_tool renders an
    empty IN-list as a real (always-false) SQL IN expression."""
    scope = ScopeResolution(found=True, discriminator="NON_GSG", scope={"coverage": []})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert result.allowed
    assert result.filter["_id_values"] == []


def test_ccb_resolves_to_exact_mode():
    """No structured arg to gate on anymore (the only tool arg is `sql`) --
    apply_policy always resolves CCB to EXACT; data_query_tool is what
    refuses to execute a query lacking a literal gfcid filter."""
    scope = ScopeResolution(found=True, discriminator="CCB", scope={})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert result.allowed
    assert result.filter["_policy_mode"] == "EXACT"


def test_ccb_denied_from_browsing():
    """query_companies uses SEARCH_RULES, where CCB is denied outright --
    exact-reference-only means no browsing by name at all."""
    scope = ScopeResolution(found=True, discriminator="CCB", scope={})
    result = apply_policy(_policy(SEARCH_RULES), scope, {})
    assert not result.allowed


def test_unknown_persona_denied():
    scope = ScopeResolution(found=True, discriminator="SOME_OTHER_ROLE", scope={})
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert not result.allowed


def test_no_access_profile_denied():
    scope = ScopeResolution(found=False)
    result = apply_policy(_policy(QUERY_RULES), scope, {})
    assert not result.allowed
    assert "access profile" in result.reason.lower()


def test_a_crafted_arg_cannot_bypass_non_gsg_scope():
    """A NON_GSG user's resolved scope is independent of whatever args the
    LLM happened to pass -- apply_policy never reads `requested_args` for
    ID_SCOPED/ATTRIBUTE_SCOPED/GLOBAL, so there's nothing for a crafted
    arg to influence in the first place."""
    scope = ScopeResolution(found=True, discriminator="NON_GSG", scope={"coverage": ["C0007"]})
    result = apply_policy(_policy(QUERY_RULES), scope, {"company_id": "C9999", "sql": "SELECT * FROM t"})
    assert result.allowed
    assert result.filter["_id_values"] == ["C0007"]
