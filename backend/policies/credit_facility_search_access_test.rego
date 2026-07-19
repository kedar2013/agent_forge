# opa test backend/policies/
package credit_facility.search_access_test

import rego.v1
import data.credit_facility.search_access

test_gcm_gets_global_access if {
	result := search_access.result with input as {"persona": "GCM", "scope": {}, "args": {}}
	result.allowed
	result.filter._policy_mode == "GLOBAL"
}

test_gsg_is_scoped_to_l3_l4_only if {
	result := search_access.result with input as {"persona": "GSG", "scope": {}, "args": {}}
	result.allowed
	result.filter._attr_values == ["L3", "L4"]
}

test_non_gsg_is_scoped_to_own_coverage_list if {
	result := search_access.result with input as {
		"persona": "NON_GSG",
		"scope": {"coverage": ["C001"]},
		"args": {},
	}
	result.allowed
	result.filter._id_values == ["C001"]
}

# The one behavioral difference from query_access: CCB is denied outright
# here rather than getting an EXACT-mode filter, since search/browse has no
# meaningful "exact reference only" mode.
test_ccb_is_denied_outright_for_search if {
	result := search_access.result with input as {"persona": "CCB", "scope": {}, "args": {}}
	not result.allowed
	result.reason == "CCB access requires an exact gfcid — browsing/search isn't permitted."
}

test_unknown_persona_is_denied_by_default if {
	result := search_access.result with input as {"persona": "SOMETHING_UNRECOGNIZED", "scope": {}, "args": {}}
	not result.allowed
}
