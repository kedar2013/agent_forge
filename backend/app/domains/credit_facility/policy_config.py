"""The declarative persona -> access rule table for Credit Facility Analysis.
This is *data* consumed by the generic `app.tool_registry.policy_engine`
(persona/scope resolution) and `app.tool_registry.data_query_tool` (turning
a resolved rule into an AST-injected SQL predicate) — adjusting a rule here
never requires touching either. See `app.models.access_policies.AccessPolicy`
for the resolver/rule shape and `data_query_tool.py`'s module docstring for
exactly how `_policy_mode`/`_attr_values`/`_id_values` get consumed.

Persona rules (as given in the requirement, GCM/GSG/Non-GSG/CCB):
  - GCM: global access to every company.
  - GSG: covers L3/L4 only — no L2 (sector-rollup) visibility.
  - NON_GSG: only the companies explicitly assigned to that user in
    cf_user_company_coverage.
  - CCB: exact-reference lookup only — must write a query whose WHERE
    clause literally filters on `gfcid`; no browsing/search, no hierarchy
    rollups. `query_companies` denies CCB outright since browsing by name
    would defeat "exact reference only" (there's nothing to search for
    that isn't itself a form of browsing).
"""

QUERY_POLICY_NAME = "credit_facility_query_access"
SEARCH_POLICY_NAME = "credit_facility_search_access"

RESOLVER_CONFIG = {
    "type": "mysql",
    "connection_env_prefix": "CREDIT_FACILITY_MYSQL",
    # Match on the logged-in user's SOEID (corporate id), not Agent Forge's own
    # opaque account id — an admin grants access by setting a user's SOEID
    # (Users page) to one already present in cf_user_persona, rather than
    # needing this domain's own data reseeded per Agent Forge account.
    "identity_state_key": "_principal_soeid",
    "persona_lookup": {
        "source": "cf_user_persona",
        "match_field": "user_id",
        "project": "persona",
    },
    "scope_lookups": {
        "coverage": {
            "source": "cf_user_company_coverage",
            "match_field": "user_id",
            "project": "company_id",
        },
    },
    # Which column each rule mode below enforces against — the same three
    # columns exist on both cf_company_master and cf_company_facility_monthly,
    # so one field_names mapping covers both query_companies and
    # query_facility_data.
    "field_names": {"attribute": "company_level", "id": "company_id", "exact": "gfcid"},
}

# Applied to `query_facility_data`.
QUERY_RULES = {
    "GCM": {"_policy_mode": "GLOBAL"},
    "GSG": {"_policy_mode": "ATTRIBUTE_SCOPED", "_attr_values": ["L3", "L4"]},
    "NON_GSG": {"_policy_mode": "ID_SCOPED", "_id_values": "$coverage"},
    "CCB": {"_policy_mode": "EXACT"},
}

# Applied to `query_companies` (search/browse) — CCB can't browse at all,
# everyone else browses within their normal query scope.
SEARCH_RULES = {
    "GCM": {"_policy_mode": "GLOBAL"},
    "GSG": {"_policy_mode": "ATTRIBUTE_SCOPED", "_attr_values": ["L3", "L4"]},
    "NON_GSG": {"_policy_mode": "ID_SCOPED", "_id_values": "$coverage"},
    "CCB": {"__deny": True, "reason": "CCB access requires an exact gfcid — browsing/search isn't permitted."},
}
