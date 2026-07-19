# Policy-as-code port of app.domains.credit_facility.policy_config.SEARCH_RULES
# -- applied to query_companies (search/browse), sibling to
# credit_facility_query_access.rego (applied to query_facility_data). Only
# difference from the query policy: CCB is denied outright here, since
# "exact reference only" has no meaningful browse/search mode to scope.
package credit_facility.search_access

import rego.v1

default result := {"allowed": false, "reason": "No matching persona rule for this request."}

# See credit_facility_query_access.rego's identical rule for why this is
# explicit "GLOBAL" rather than an empty filter.
result := {"allowed": true, "filter": {"_policy_mode": "GLOBAL"}} if {
	input.persona == "GCM"
}

result := {"allowed": true, "filter": {
	"_policy_mode": "ATTRIBUTE_SCOPED",
	"_attr_values": ["L3", "L4"],
}} if {
	input.persona == "GSG"
}

result := {"allowed": true, "filter": {
	"_policy_mode": "ID_SCOPED",
	"_id_values": input.scope.coverage,
}} if {
	input.persona == "NON_GSG"
}

# CCB can't browse at all -- browsing/search would defeat "exact reference
# only" (there's nothing to search for that isn't itself a form of browsing).
result := {"allowed": false, "reason": "CCB access requires an exact gfcid — browsing/search isn't permitted."} if {
	input.persona == "CCB"
}
