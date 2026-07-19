# opa test backend/policies/
package credit_facility.query_access_test

import rego.v1
import data.credit_facility.query_access

test_gcm_gets_global_access if {
	result := query_access.result with input as {"persona": "GCM", "scope": {}, "args": {}}
	result.allowed
	result.filter._policy_mode == "GLOBAL"
}

test_gsg_is_scoped_to_l3_l4_only if {
	result := query_access.result with input as {"persona": "GSG", "scope": {}, "args": {}}
	result.allowed
	result.filter._policy_mode == "ATTRIBUTE_SCOPED"
	result.filter._attr_values == ["L3", "L4"]
}

test_non_gsg_is_scoped_to_own_coverage_list if {
	result := query_access.result with input as {
		"persona": "NON_GSG",
		"scope": {"coverage": ["C001", "C002"]},
		"args": {},
	}
	result.allowed
	result.filter._policy_mode == "ID_SCOPED"
	result.filter._id_values == ["C001", "C002"]
}

test_ccb_gets_exact_reference_mode if {
	result := query_access.result with input as {"persona": "CCB", "scope": {}, "args": {}}
	result.allowed
	result.filter._policy_mode == "EXACT"
}

test_unknown_persona_is_denied_by_default if {
	result := query_access.result with input as {"persona": "SOMETHING_UNRECOGNIZED", "scope": {}, "args": {}}
	not result.allowed
}

test_missing_persona_is_denied_by_default if {
	result := query_access.result with input as {"scope": {}, "args": {}}
	not result.allowed
}
