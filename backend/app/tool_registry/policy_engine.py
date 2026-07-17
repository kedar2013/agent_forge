"""Generic row-level-security engine consumed by `agent_runtime/builder.py`'s
`before_tool_callback` for any tool whose config carries a `policy_id`.

Two-phase on purpose:
  1. `resolve_scope(policy, user_id)` — the expensive part (a lookup for
     persona + coverage-style scope lists, against whichever backend
     `resolver_config["type"]` names). Pure function of `(policy_id,
     user_id)`, so callers cache the `ScopeResolution` per session and only
     re-run this once per conversation, not once per tool call.
  2. `apply_policy(policy, scope, requested_args)` — cheap, synchronous,
     no I/O. Turns a cached `ScopeResolution` plus this specific call's
     LLM-supplied args into a `PolicyResult` (a dict of reserved keys for
     the calling tool to merge into its own args, or a denial). Safe to
     call on every single tool invocation. Entirely backend-agnostic: it
     only ever manipulates the `rules` JSON, never talks to a database.

No domain-specific knowledge lives here — everything domain-specific (where
persona/coverage data lives, what the rules are, what shape a resolved
filter needs to be for a given tool type) comes from the `AccessPolicy`
row's declarative `resolver_config`/`rules` JSON.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from app.models.access_policies import AccessPolicy
from app.tool_registry._templating import bind_template

# A resolver_config's connection_env(_prefix) may name env vars app/config.py
# never bridges into os.environ (it only bridges its own known Settings
# fields) — load .env directly, same pattern as mcp_servers/_db.py /
# mysql_tool.py. Idempotent, never overrides a real env var already set.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _assert_safe_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Unsafe identifier in access_policy resolver_config: {value!r}")
    return value


@dataclass
class ScopeResolution:
    """The result of phase 1 — cacheable per (policy, user_id)."""

    found: bool
    discriminator: Any = None
    scope: dict[str, Any] = field(default_factory=dict)  # e.g. {"coverage": ["C001", "C002"]}

    def to_state(self) -> dict[str, Any]:
        return {"found": self.found, "discriminator": self.discriminator, "scope": self.scope}

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> "ScopeResolution":
        return cls(found=data["found"], discriminator=data.get("discriminator"), scope=data.get("scope", {}))


@dataclass
class PolicyResult:
    allowed: bool
    filter: dict[str, Any] | None = None
    reason: str | None = None


async def resolve_scope(policy: AccessPolicy, user_id: str) -> ScopeResolution:
    resolver_type = policy.resolver_config.get("type", "mongo")
    if resolver_type == "mongo":
        return await _resolve_scope_mongo(policy, user_id)
    if resolver_type == "mysql":
        return await _resolve_scope_mysql(policy, user_id)
    raise ValueError(f"Unsupported access_policy resolver type: {resolver_type!r}")


async def _resolve_scope_mongo(policy: AccessPolicy, user_id: str) -> ScopeResolution:
    from motor.motor_asyncio import AsyncIOMotorClient

    resolver = policy.resolver_config
    client = AsyncIOMotorClient(os.environ[resolver["connection_env"]])
    db = client[resolver["database"]]

    persona_cfg = resolver["persona_lookup"]
    persona_doc = await db[persona_cfg["source"]].find_one({persona_cfg["match_field"]: user_id})
    if persona_doc is None:
        return ScopeResolution(found=False)
    discriminator = persona_doc.get(persona_cfg["project"])

    rule = policy.rules.get(discriminator, {})
    scope: dict[str, Any] = {}
    for scope_name, scope_cfg in resolver.get("scope_lookups", {}).items():
        if not _rule_references_scope(rule, scope_name):
            continue
        coll = db[scope_cfg["source"]]
        proj_field = scope_cfg["project"]
        if scope_cfg.get("many", True):
            docs = await coll.find({scope_cfg["match_field"]: user_id}, {proj_field: 1}).to_list(length=None)
            scope[scope_name] = [d[proj_field] for d in docs if proj_field in d]
        else:
            doc = await coll.find_one({scope_cfg["match_field"]: user_id}, {proj_field: 1})
            scope[scope_name] = doc.get(proj_field) if doc else None

    return ScopeResolution(found=True, discriminator=discriminator, scope=scope)


async def _resolve_scope_mysql(policy: AccessPolicy, user_id: str) -> ScopeResolution:
    import asyncio

    import pymysql

    resolver = policy.resolver_config
    prefix = resolver["connection_env_prefix"]

    def _query() -> ScopeResolution:
        conn = pymysql.connect(
            host=os.environ.get(f"{prefix}_HOST", "localhost"),
            port=int(os.environ.get(f"{prefix}_PORT", "3306")),
            user=os.environ.get(f"{prefix}_USER", "root"),
            password=os.environ.get(f"{prefix}_PASSWORD", ""),
            database=os.environ[f"{prefix}_DATABASE"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                persona_cfg = resolver["persona_lookup"]
                table = _assert_safe_identifier(persona_cfg["source"])
                match_col = _assert_safe_identifier(persona_cfg["match_field"])
                project_col = _assert_safe_identifier(persona_cfg["project"])
                cur.execute(f"SELECT {project_col} AS v FROM {table} WHERE {match_col} = %s LIMIT 1", (user_id,))
                row = cur.fetchone()
                if row is None:
                    return ScopeResolution(found=False)
                discriminator = row["v"]

                rule = policy.rules.get(discriminator, {})
                scope: dict[str, Any] = {}
                for scope_name, scope_cfg in resolver.get("scope_lookups", {}).items():
                    if not _rule_references_scope(rule, scope_name):
                        continue
                    s_table = _assert_safe_identifier(scope_cfg["source"])
                    s_match_col = _assert_safe_identifier(scope_cfg["match_field"])
                    s_project_col = _assert_safe_identifier(scope_cfg["project"])
                    cur.execute(f"SELECT {s_project_col} AS v FROM {s_table} WHERE {s_match_col} = %s", (user_id,))
                    scope[scope_name] = [r["v"] for r in cur.fetchall()]
                return ScopeResolution(found=True, discriminator=discriminator, scope=scope)
        finally:
            conn.close()

    return await asyncio.to_thread(_query)


def apply_policy(policy: AccessPolicy, scope: ScopeResolution, requested_args: dict[str, Any]) -> PolicyResult:
    if not scope.found:
        return PolicyResult(allowed=False, reason="No access profile found for this user.")

    rule = policy.rules.get(scope.discriminator)
    if rule is None:
        return PolicyResult(allowed=False, reason=f"No access rule configured for '{scope.discriminator}'.")
    if rule.get("__deny"):
        return PolicyResult(allowed=False, reason=rule.get("reason", "Not permitted at this access level."))

    if "__require_arg" in rule:
        arg_name = rule["__require_arg"]
        if not requested_args.get(arg_name):
            return PolicyResult(
                allowed=False, reason=f"This access level requires an exact '{arg_name}' — no browsing/search."
            )
        return PolicyResult(allowed=True, filter=bind_template(rule.get("filter", {}), requested_args))

    resolved = _resolve_scope_refs(rule, scope.scope)
    return PolicyResult(allowed=True, filter=resolved)


def _rule_references_scope(node: Any, scope_name: str) -> bool:
    token = f"${scope_name}"
    if isinstance(node, str):
        return node == token or node.startswith(f"{token}.")
    if isinstance(node, dict):
        return any(_rule_references_scope(v, scope_name) for v in node.values())
    if isinstance(node, list):
        return any(_rule_references_scope(v, scope_name) for v in node)
    return False


def _resolve_scope_refs(node: Any, scope: dict[str, Any]) -> Any:
    if isinstance(node, str) and node.startswith("$") and not node.startswith("{{"):
        scope_name, _, sub_field = node[1:].partition(".")
        if scope_name not in scope:
            return node  # not actually a scope reference (e.g. a literal '$'-prefixed value) — pass through
        value = scope[scope_name]
        if sub_field and isinstance(value, list):
            return [v.get(sub_field) if isinstance(v, dict) else v for v in value]
        if sub_field and isinstance(value, dict):
            return value.get(sub_field)
        return value
    if isinstance(node, dict):
        return {k: _resolve_scope_refs(v, scope) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_scope_refs(v, scope) for v in node]
    return node
