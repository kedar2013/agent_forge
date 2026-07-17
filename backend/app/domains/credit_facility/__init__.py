"""Credit Facility Analysis — a worked example of a Mongo-backed, identity-
scoped domain plugged into Agent Forge's generic tool/policy framework (see
`app.tool_registry.mongo_tool`, `app.tool_registry.policy_engine`, and
`app.models.access_policies`). Nothing in this package is imported by the
platform itself — it is purely a producer of config (Postgres `tools`/
`agents`/`access_policies` rows) and of the Mongo data those rows query.
A different domain would be its own sibling package here, reusing the same
generic framework without touching it.
"""
