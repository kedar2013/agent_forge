"""Generates synthetic Credit Facility Analysis data: a 3-level company
hierarchy (L2 sector -> L3 group -> L4 operating company), written once as
`cf_company_master` (name/id/gfcid/hierarchy/level — one row per company,
for resolve/list queries) and once as `cf_company_facility_monthly` (the
same key fields plus 6 months of numeric metrics per company, for the
actual credit data lookup). GSG's "no L2 visibility" rule gets real rows to
exclude this way, not a vacuous case. Also creates demo login accounts
spanning all four personas (GCM/GSG/NON_GSG/CCB) so the row-level-security
rules in `policy_config.py` are actually exercisable end-to-end through a
real `/chat` login.

User identity is the join key between Postgres (who can log in) and MySQL
(who can see what), so this script writes both: `users` rows in the
platform's Postgres DB (chat_user role, pre-approved) and matching
`cf_user_persona`/`cf_user_company_coverage` rows in MySQL keyed by that
same user's UUID. `seed_agent.py` (Postgres-only: tools/policy/agent
config) is independent of this script and can be re-run on its own.

Idempotent: `--reset` drops and recreates the four MySQL tables and deletes
the demo `users` rows (identified by email domain `@creditfacility.demo`)
before regenerating; without `--reset`, running again on top of existing
data is a no-op.

Usage (from backend/, so `app.*` imports resolve):
    python -m app.domains.credit_facility.seed_data [--reset]
"""

import argparse
import asyncio
import random
from datetime import datetime, timezone

from sqlalchemy import delete

from app.auth_users import hash_password
from app.db import async_session_factory
from app.domains.credit_facility.mysql_client import (
    COMPANY_FACILITY_MONTHLY_TABLE,
    COMPANY_MASTER_TABLE,
    SCHEMA_DDL,
    USER_COMPANY_COVERAGE_TABLE,
    USER_PERSONA_TABLE,
    get_connection,
)
from app.models.users import User

DEMO_EMAIL_DOMAIN = "creditfacility.demo"
DEMO_PASSWORD = "Demo@12345"

# sector (L2) -> group (L3) -> [operating companies (L4)]
HIERARCHY = {
    "Automotive & Mobility": {
        "Tesla Group": ["Tesla Inc", "Tesla Energy Operations", "Tesla Financial Services"],
        "Ford Group": ["Ford Motor Company", "Ford Credit"],
    },
    "Technology & Software": {
        "Microsoft Group": ["Microsoft Corporation", "Microsoft Azure Services", "LinkedIn Corporation"],
        "Alphabet Group": ["Google LLC", "Google Cloud EMEA", "Waymo LLC"],
    },
    "Energy & Utilities": {
        "ExxonMobil Group": ["Exxon Mobil Corporation", "XTO Energy"],
        "NextEra Group": ["NextEra Energy Inc", "Florida Power & Light"],
    },
    "Financial Services": {
        "JPMorgan Group": ["JPMorgan Chase Bank", "Chase Auto Finance", "JPMorgan Securities"],
        "Goldman Group": ["Goldman Sachs Bank USA", "Goldman Sachs Asset Management"],
    },
    "Healthcare & Pharma": {
        "Pfizer Group": ["Pfizer Inc", "Pfizer CentreOne"],
        "JNJ Group": ["Johnson & Johnson", "Janssen Pharmaceuticals", "DePuy Synthes"],
    },
}

MONTHS_OF_HISTORY = 6

# email local-part -> persona
DEMO_USERS = [
    ("gcm1", "GCM"),
    ("gcm2", "GCM"),
    ("gsg1", "GSG"),
    ("gsg2", "GSG"),
    ("nongsg1", "NON_GSG"),
    ("nongsg2", "NON_GSG"),
    ("ccb1", "CCB"),
    ("ccb2", "CCB"),
]


def _load_ids(n: int) -> list[int]:
    """Last `n` YYYYMM load ids ending at the current month, using pure
    integer month arithmetic (no extra dependency needed for this)."""
    now = datetime.now(timezone.utc)
    total_months = now.year * 12 + (now.month - 1)
    ids = []
    for offset in range(n - 1, -1, -1):
        y, m = divmod(total_months - offset, 12)
        ids.append(y * 100 + (m + 1))
    return ids


def _monthly_metrics(rng: random.Random, base_limit: float) -> dict:
    utilization_pct = round(rng.uniform(0.2, 0.95), 4)
    utilized = round(base_limit * utilization_pct, 2)
    overdue = round(utilized * rng.uniform(0.0, 0.05), 2) if rng.random() < 0.1 else 0.0
    return {
        "total_facility_limit": base_limit,
        "utilized_amount": utilized,
        "available_amount": round(base_limit - utilized, 2),
        "utilization_pct": utilization_pct,
        "outstanding_balance": round(utilized * rng.uniform(0.9, 1.0), 2),
        "overdue_amount": overdue,
        "interest_accrued": round(utilized * rng.uniform(0.004, 0.009), 2),
        "num_transactions": rng.randint(5, 120),
    }


def _build_companies() -> list[dict]:
    """Returns one hierarchy node per L2/L3/L4 entry. L4 nodes get a
    `gfcid` (an operating entity is what actually holds a booked facility);
    L2/L3 rollup nodes don't."""
    companies: list[dict] = []
    seq = 0
    gf_seq = 0
    for l2_name, groups in HIERARCHY.items():
        seq += 1
        companies.append(
            {
                "company_id": f"CF{seq:04d}",
                "company_name": l2_name,
                "gfcid": None,
                "company_level": "L2",
                "l2": l2_name,
                "l3": None,
                "l4": None,
            }
        )
        for l3_name, l4_names in groups.items():
            seq += 1
            companies.append(
                {
                    "company_id": f"CF{seq:04d}",
                    "company_name": l3_name,
                    "gfcid": None,
                    "company_level": "L3",
                    "l2": l2_name,
                    "l3": l3_name,
                    "l4": None,
                }
            )
            for l4_name in l4_names:
                seq += 1
                gf_seq += 1
                companies.append(
                    {
                        "company_id": f"CF{seq:04d}",
                        "company_name": l4_name,
                        "gfcid": f"GF{gf_seq:05d}",
                        "company_level": "L4",
                        "l2": l2_name,
                        "l3": l3_name,
                        "l4": l4_name,
                    }
                )
    return companies


def _build_facility_rows(companies: list[dict]) -> list[dict]:
    load_ids = _load_ids(MONTHS_OF_HISTORY)
    rows = []
    for company in companies:
        rng = random.Random(company["company_id"])
        base_limit = round(rng.uniform(5_000_000, 500_000_000), 2)
        for load_id in load_ids:
            rows.append({**company, "load_id": load_id, **_monthly_metrics(rng, base_limit)})
    return rows


def _reset_mysql() -> None:
    print("Resetting previously-seeded credit-facility MySQL tables...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table in (
                COMPANY_FACILITY_MONTHLY_TABLE,
                COMPANY_MASTER_TABLE,
                USER_COMPANY_COVERAGE_TABLE,
                USER_PERSONA_TABLE,
            ):
                cur.execute(f"DROP TABLE IF EXISTS {table}")
    finally:
        conn.close()


async def _reset_postgres_users() -> None:
    async with async_session_factory() as session:
        await session.execute(delete(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")))
        await session.commit()


def _ensure_schema() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for statement in SCHEMA_DDL.strip().split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
    finally:
        conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset:
        _reset_mysql()
        await _reset_postgres_users()

    _ensure_schema()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {COMPANY_FACILITY_MONTHLY_TABLE}")
            existing = cur.fetchone()["n"]
    finally:
        conn.close()

    if existing:
        print(f"Credit-facility data already seeded ({existing} facility rows). Use --reset to reseed.")
        return

    companies = _build_companies()
    facility_rows = _build_facility_rows(companies)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {COMPANY_MASTER_TABLE} "
                "(company_id, company_name, gfcid, l2, l3, l4, company_level) "
                "VALUES (%(company_id)s, %(company_name)s, %(gfcid)s, %(l2)s, %(l3)s, %(l4)s, %(company_level)s)",
                companies,
            )
            print(f"Inserted {len(companies)} cf_company_master rows.")

            cur.executemany(
                f"INSERT INTO {COMPANY_FACILITY_MONTHLY_TABLE} "
                "(company_id, company_name, gfcid, l2, l3, l4, company_level, load_id, "
                "total_facility_limit, utilized_amount, available_amount, utilization_pct, "
                "outstanding_balance, overdue_amount, interest_accrued, num_transactions) "
                "VALUES (%(company_id)s, %(company_name)s, %(gfcid)s, %(l2)s, %(l3)s, %(l4)s, %(company_level)s, "
                "%(load_id)s, %(total_facility_limit)s, %(utilized_amount)s, %(available_amount)s, "
                "%(utilization_pct)s, %(outstanding_balance)s, %(overdue_amount)s, %(interest_accrued)s, "
                "%(num_transactions)s)",
                facility_rows,
            )
            print(f"Inserted {len(facility_rows)} cf_company_facility_monthly rows across {len(companies)} companies.")
    finally:
        conn.close()

    l4_companies = [c for c in companies if c["company_level"] == "L4"]

    # cf_user_persona/cf_user_company_coverage are keyed by SOEID (corporate
    # id), not Agent Forge's own account id — see policy_config.py's
    # "identity_state_key": "_principal_soeid". Any real Agent Forge account can
    # be granted one of these demo personas just by an admin setting that
    # account's SOEID (Users page) to one of the values below.
    soeids = {local_part: f"aa1{i:04d}" for i, (local_part, _persona) in enumerate(DEMO_USERS, start=1)}

    async with async_session_factory() as session:
        for local_part, persona in DEMO_USERS:
            email = f"{local_part}@{DEMO_EMAIL_DOMAIN}"
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                role="chat_user",
                status="approved",
                soeid=soeids[local_part],
            )
            session.add(user)
        await session.commit()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {USER_PERSONA_TABLE} (user_id, persona) VALUES (%(user_id)s, %(persona)s)",
                [{"user_id": soeids[lp], "persona": persona} for lp, persona in DEMO_USERS],
            )
            print(f"Inserted {len(DEMO_USERS)} cf_user_persona rows.")

            rng = random.Random("coverage")
            non_gsg_users = [lp for lp, persona in DEMO_USERS if persona == "NON_GSG"]
            half = len(l4_companies) // 2
            coverage_split = {non_gsg_users[0]: l4_companies[:half], non_gsg_users[1]: l4_companies[half:]}
            coverage_rows = []
            for local_part, covered in coverage_split.items():
                for company in rng.sample(covered, k=min(4, len(covered))):
                    coverage_rows.append({"user_id": soeids[local_part], **company})
            cur.executemany(
                f"INSERT INTO {USER_COMPANY_COVERAGE_TABLE} "
                "(user_id, company_id, company_name, gfcid, l2, l3, l4, company_level) "
                "VALUES (%(user_id)s, %(company_id)s, %(company_name)s, %(gfcid)s, %(l2)s, %(l3)s, %(l4)s, %(company_level)s)",
                coverage_rows,
            )
            print(f"Inserted {len(coverage_rows)} cf_user_company_coverage rows.")
    finally:
        conn.close()

    print("\nDemo logins (all use password: " + DEMO_PASSWORD + "), each with a SOEID an admin could")
    print("instead assign to any real Agent Forge account via the Users page to grant that persona:")
    for local_part, persona in DEMO_USERS:
        print(f"  {local_part}@{DEMO_EMAIL_DOMAIN}  soeid={soeids[local_part]}  ({persona})")


if __name__ == "__main__":
    asyncio.run(main())
