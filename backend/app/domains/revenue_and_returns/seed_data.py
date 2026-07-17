"""Generates synthetic Revenue and Returns data: a 3-level product
hierarchy (L2 business unit -> L3 category -> L4 product), written once as
`rr_product_master` (name/id/hierarchy/level/region — one row per product,
for resolve/list queries) and once as `rr_revenue_returns_monthly` (the
same key fields plus 6 months of numeric metrics per product, for the
actual revenue/returns lookup). Mirrors
`app.domains.credit_facility.seed_data` almost verbatim — same structural
pattern (hierarchy + monthly-metrics fact table), different domain, and
deliberately no row-level-security demo users: this domain ships with
global access only (see `seed_agent.py`'s docstring for how to add RLS
later the same way credit_facility did, if ever needed).

Idempotent: `--reset` drops and recreates the two MySQL tables before
regenerating; without `--reset`, running again on top of existing data is
a no-op.

Usage (from backend/, so `app.*` imports resolve):
    python -m app.domains.revenue_and_returns.seed_data [--reset]
"""

import argparse
import random
from datetime import datetime, timezone

from app.domains.revenue_and_returns.mysql_client import (
    PRODUCT_MASTER_TABLE,
    REVENUE_RETURNS_MONTHLY_TABLE,
    SCHEMA_DDL,
    get_connection,
)

# business unit (L2) -> category (L3) -> [products (L4)]
HIERARCHY = {
    "Consumer Electronics": {
        "Audio": ["Wireless Earbuds Pro", "Bluetooth Speaker Mini", "Studio Headphones X1"],
        "Wearables": ["Fitness Tracker 2", "Smartwatch Series 5"],
    },
    "Home & Kitchen": {
        "Small Appliances": ["Espresso Machine Deluxe", "Air Fryer XL", "Blender 3000"],
        "Cookware": ["Non-Stick Pan Set", "Cast Iron Skillet"],
    },
    "Apparel": {
        "Footwear": ["Running Shoes Elite", "Casual Sneakers"],
        "Outerwear": ["Rain Jacket Pro", "Winter Parka"],
    },
    "Office Supplies": {
        "Furniture": ["Ergonomic Chair", "Standing Desk"],
        "Stationery": ["Premium Notebook Set", "Fountain Pen Collection"],
    },
}

REGIONS = ["AMER", "EMEA", "APAC"]
MONTHS_OF_HISTORY = 6


def _load_ids(n: int) -> list[int]:
    """Last `n` YYYYMM load ids ending at the current month, using pure
    integer month arithmetic — identical helper to credit_facility's."""
    now = datetime.now(timezone.utc)
    total_months = now.year * 12 + (now.month - 1)
    ids = []
    for offset in range(n - 1, -1, -1):
        y, m = divmod(total_months - offset, 12)
        ids.append(y * 100 + (m + 1))
    return ids


def _build_products() -> list[dict]:
    """Returns one hierarchy node per L2/L3/L4 entry. Only L4 (leaf)
    products carry a `sku`/`launch_date`/single `region` — L2/L3 rollup
    nodes describe an aggregate, not a sellable unit, mirroring how
    credit_facility's L2/L3 rollups carry no `gfcid`."""
    products: list[dict] = []
    seq = 0
    rng = random.Random("rr-products")
    for bu_name, categories in HIERARCHY.items():
        seq += 1
        products.append(
            {
                "product_id": f"RR{seq:04d}",
                "product_name": bu_name,
                "sku": None,
                "business_unit": bu_name,
                "category": None,
                "sub_category": None,
                "region": "GLOBAL",
                "product_level": "L2",
                "launch_date": None,
            }
        )
        for cat_name, leaf_names in categories.items():
            seq += 1
            products.append(
                {
                    "product_id": f"RR{seq:04d}",
                    "product_name": cat_name,
                    "sku": None,
                    "business_unit": bu_name,
                    "category": cat_name,
                    "sub_category": None,
                    "region": "GLOBAL",
                    "product_level": "L3",
                    "launch_date": None,
                }
            )
            for leaf_name in leaf_names:
                seq += 1
                products.append(
                    {
                        "product_id": f"RR{seq:04d}",
                        "product_name": leaf_name,
                        "sku": f"SKU-{seq:05d}",
                        "business_unit": bu_name,
                        "category": cat_name,
                        "sub_category": leaf_name,
                        "region": rng.choice(REGIONS),
                        "product_level": "L4",
                        "launch_date": datetime(rng.randint(2022, 2025), rng.randint(1, 12), rng.randint(1, 28)).date(),
                    }
                )
    return products


def _monthly_metrics(rng: random.Random, base_revenue: float, unit_price: float) -> dict:
    gross_revenue = round(base_revenue * rng.uniform(0.75, 1.35), 2)
    return_rate_pct = round(rng.uniform(0.02, 0.20), 4)
    returns_amount = round(gross_revenue * return_rate_pct, 2)
    refund_amount = round(returns_amount * rng.uniform(0.85, 1.0), 2)
    net_revenue = round(gross_revenue - refund_amount, 2)
    units_sold = max(1, round(gross_revenue / unit_price))
    units_returned = max(0, round(units_sold * return_rate_pct))
    num_orders = max(1, round(units_sold / rng.uniform(1.1, 1.6)))
    return {
        "gross_revenue": gross_revenue,
        "returns_amount": returns_amount,
        "refund_amount": refund_amount,
        "net_revenue": net_revenue,
        "return_rate_pct": return_rate_pct,
        "units_sold": units_sold,
        "units_returned": units_returned,
        "num_orders": num_orders,
    }


def _build_revenue_rows(products: list[dict]) -> list[dict]:
    """`products` here is always the L4 (leaf) subset — see call site — so
    `category`/`sub_category` are always populated, never a rollup node."""
    load_ids = _load_ids(MONTHS_OF_HISTORY)
    rows = []
    for product in products:
        rng = random.Random(product["product_id"])
        base_revenue = round(rng.uniform(5_000, 500_000), 2)
        unit_price = round(rng.uniform(15, 250), 2)
        for load_id in load_ids:
            metrics = _monthly_metrics(rng, base_revenue, unit_price)
            rows.append(
                {
                    "product_id": product["product_id"],
                    "product_name": product["product_name"],
                    "business_unit": product["business_unit"],
                    "category": product["category"],
                    "sub_category": product["sub_category"],
                    "region": product["region"],
                    "product_level": product["product_level"],
                    "load_id": load_id,
                    **metrics,
                }
            )
    return rows


def _reset_mysql() -> None:
    print("Resetting previously-seeded revenue-and-returns MySQL tables...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table in (REVENUE_RETURNS_MONTHLY_TABLE, PRODUCT_MASTER_TABLE):
                cur.execute(f"DROP TABLE IF EXISTS {table}")
    finally:
        conn.close()


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset:
        _reset_mysql()

    _ensure_schema()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {REVENUE_RETURNS_MONTHLY_TABLE}")
            existing = cur.fetchone()["n"]
    finally:
        conn.close()

    if existing:
        print(f"Revenue-and-returns data already seeded ({existing} rows). Use --reset to reseed.")
        return

    products = _build_products()
    revenue_rows = _build_revenue_rows([p for p in products if p["product_level"] == "L4"])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {PRODUCT_MASTER_TABLE} "
                "(product_id, product_name, sku, business_unit, category, sub_category, region, "
                "product_level, launch_date) "
                "VALUES (%(product_id)s, %(product_name)s, %(sku)s, %(business_unit)s, %(category)s, "
                "%(sub_category)s, %(region)s, %(product_level)s, %(launch_date)s)",
                products,
            )
            print(f"Inserted {len(products)} rr_product_master rows.")

            cur.executemany(
                f"INSERT INTO {REVENUE_RETURNS_MONTHLY_TABLE} "
                "(product_id, product_name, business_unit, category, sub_category, region, product_level, "
                "load_id, gross_revenue, returns_amount, refund_amount, net_revenue, return_rate_pct, "
                "units_sold, units_returned, num_orders) "
                "VALUES (%(product_id)s, %(product_name)s, %(business_unit)s, %(category)s, %(sub_category)s, "
                "%(region)s, %(product_level)s, %(load_id)s, %(gross_revenue)s, %(returns_amount)s, "
                "%(refund_amount)s, %(net_revenue)s, %(return_rate_pct)s, %(units_sold)s, %(units_returned)s, "
                "%(num_orders)s)",
                revenue_rows,
            )
            l4_count = len([p for p in products if p["product_level"] == "L4"])
            print(f"Inserted {len(revenue_rows)} rr_revenue_returns_monthly rows across {l4_count} products.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
