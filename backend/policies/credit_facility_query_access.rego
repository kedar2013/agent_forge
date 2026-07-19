# Policy-as-code port of app.domains.credit_facility.policy_config.QUERY_RULES
# -- the exact same GCM/GSG/NON_GSG/CCB persona rule set the Python
# tool_registry.policy_engine.apply_policy() already enforces from that
# module's JSON dict, expressed here as versioned, independently testable
# Rego instead. Neither is "the" implementation platform-wide: an
# AccessPolicy row opts into THIS one specifically by setting
# resolver_config.engine = "opa" and resolver_config.opa_package =
# "credit_facility.query_access" (see scripts/migrate_policy_to_opa.py) --
# every other policy keeps using the Python engine untouched.
#
# Output shape is a deliberate, exact match for policy_engine.PolicyResult /
# app.tool_registry.data_query_tool's `_policy_mode`/`_attr_values`/
# `_id_values` contract, so swapping a policy's engine never requires
# touching the tool that consumes its decision.
#
# Run the regression suite in credit_facility_query_access_test.rego with:
#   opa test backend/policies/
package credit_facility.query_access

import rego.v1

default result := {"allowed": false, "reason": "No matching persona rule for this request."}

# GCM: global access to every company. data_query_tool.py treats a missing
# _policy_mode the same as "GLOBAL" (both mean "no predicate injected"), but
# this states it explicitly to match QUERY_RULES["GCM"] exactly rather than
# relying on that implicit equivalence.
result := {"allowed": true, "filter": {"_policy_mode": "GLOBAL"}} if {
	input.persona == "GCM"
}

# GSG: covers L3/L4 (sector-rollup) company_level only -- no L2.
result := {"allowed": true, "filter": {
	"_policy_mode": "ATTRIBUTE_SCOPED",
	"_attr_values": ["L3", "L4"],
}} if {
	input.persona == "GSG"
}

# NON_GSG: only the companies explicitly assigned to this user's coverage.
result := {"allowed": true, "filter": {
	"_policy_mode": "ID_SCOPED",
	"_id_values": input.scope.coverage,
}} if {
	input.persona == "NON_GSG"
}

# CCB: exact-reference lookup only -- the query must filter on a literal
# gfcid; no browsing/search, no hierarchy rollups.
result := {"allowed": true, "filter": {"_policy_mode": "EXACT"}} if {
	input.persona == "CCB"
}
