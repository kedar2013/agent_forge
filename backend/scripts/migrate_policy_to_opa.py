"""Switches one named AccessPolicy's phase-2 decision engine between the
in-process Python `apply_policy` (default) and OPA/Rego (see
app/tool_registry/opa_client.py, backend/policies/*.rego). Idempotent and
reversible -- a policy's scope RESOLUTION (persona/coverage lookup) is
completely unaffected either way, only which code decides allow/deny/filter
for a given resolved scope + tool args.

    python scripts/migrate_policy_to_opa.py credit_facility_query_access credit_facility.query_access
    python scripts/migrate_policy_to_opa.py credit_facility_query_access --revert

Requires a reachable OPA loaded with backend/policies/ (`docker compose up
-d opa`) and OPA_ENABLED=true in .env before the switched-over policy will
actually authorize anything -- this script only flips the AccessPolicy row;
it doesn't start or check OPA itself.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models.access_policies import AccessPolicy  # noqa: E402


async def migrate(policy_name: str, opa_package: str | None, revert: bool) -> bool:
    async with async_session_factory() as session:
        policy = await session.scalar(select(AccessPolicy).where(AccessPolicy.name == policy_name))
        if policy is None:
            print(f"MISS {policy_name}: no access_policy with this name found")
            return False

        resolver_config = dict(policy.resolver_config)
        if revert:
            resolver_config.pop("engine", None)
            resolver_config.pop("opa_package", None)
            print(f"OK   {policy_name}: reverted to the in-process Python policy engine")
        else:
            if not opa_package:
                print(f"FAIL {policy_name}: an opa_package argument is required unless --revert is passed")
                return False
            resolver_config["engine"] = "opa"
            resolver_config["opa_package"] = opa_package
            print(f"OK   {policy_name}: now evaluated via OPA package {opa_package!r}")

        policy.resolver_config = resolver_config
        await session.commit()
        return True


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--revert"]
    revert = "--revert" in sys.argv
    if not args or (not revert and len(args) < 2):
        print(__doc__)
        sys.exit(2)

    policy_name = args[0]
    opa_package = args[1] if len(args) > 1 else None
    ok = asyncio.run(migrate(policy_name, opa_package, revert))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
