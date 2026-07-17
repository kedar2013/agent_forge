"""Connection settings + table names for the revenue-and-returns MySQL
tables, shared by the seed scripts. `data_query_tool` rows `seed_agent.py`
creates read the same `{ENV_PREFIX}_HOST/_PORT/_USER/_PASSWORD/_DATABASE`
env vars independently at request time via `connection_env_prefix` — this
module exists only so the seed scripts have one place to get a connection
and agree on table names. Mirrors
`app.domains.credit_facility.mysql_client` almost verbatim — same
structural pattern, different domain.

Tables live in your existing MySQL server/database (default: the same
`agentic_ai` database other domains in this repo already use) — prefixed
`rr_` so they don't collide with anything else there.
"""

import os

import pymysql
from dotenv import load_dotenv

# Standalone-script invocation (`python -m app.domains.revenue_and_returns.*`)
# never goes through app/config.py's pydantic Settings (which only bridges
# a couple of specific keys into os.environ) — load .env directly here,
# same pattern as mcp_servers/_db.py and credit_facility's mysql_client.py,
# path-independent of cwd.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

ENV_PREFIX = "REVENUE_RETURNS_MYSQL"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "3306"
DEFAULT_USER = "root"
DEFAULT_DATABASE = "agentic_ai"

PRODUCT_MASTER_TABLE = "rr_product_master"
REVENUE_RETURNS_MONTHLY_TABLE = "rr_revenue_returns_monthly"

SCHEMA_DDL = f"""
CREATE TABLE IF NOT EXISTS {PRODUCT_MASTER_TABLE} (
    product_id      VARCHAR(20)   NOT NULL PRIMARY KEY,
    product_name    VARCHAR(255)  NOT NULL,
    sku             VARCHAR(64),
    business_unit   VARCHAR(255)  NOT NULL,
    category        VARCHAR(255),
    sub_category    VARCHAR(255),
    region          VARCHAR(100)  NOT NULL,
    product_level   VARCHAR(5)    NOT NULL,
    launch_date     DATE,
    INDEX idx_rr_master_business_unit (business_unit),
    INDEX idx_rr_master_category (category),
    INDEX idx_rr_master_region (region),
    INDEX idx_rr_master_level (product_level)
);

CREATE TABLE IF NOT EXISTS {REVENUE_RETURNS_MONTHLY_TABLE} (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    product_id       VARCHAR(20)    NOT NULL,
    product_name     VARCHAR(255)   NOT NULL,
    business_unit    VARCHAR(255)   NOT NULL,
    category         VARCHAR(255)   NOT NULL,
    sub_category     VARCHAR(255),
    region           VARCHAR(100)   NOT NULL,
    product_level    VARCHAR(5)     NOT NULL,
    load_id          INT            NOT NULL,
    gross_revenue    DECIMAL(18,2)  NOT NULL,
    returns_amount   DECIMAL(18,2)  NOT NULL,
    refund_amount    DECIMAL(18,2)  NOT NULL,
    net_revenue      DECIMAL(18,2)  NOT NULL,
    return_rate_pct  DECIMAL(7,4)   NOT NULL,
    units_sold       INT            NOT NULL,
    units_returned   INT            NOT NULL,
    num_orders       INT            NOT NULL,
    UNIQUE KEY uq_rr_revenue_product_load (product_id, load_id),
    INDEX idx_rr_revenue_business_unit (business_unit),
    INDEX idx_rr_revenue_category (category),
    INDEX idx_rr_revenue_region (region),
    INDEX idx_rr_revenue_level (product_level)
);
"""


def get_connection():
    return pymysql.connect(
        host=os.environ.get(f"{ENV_PREFIX}_HOST", DEFAULT_HOST),
        port=int(os.environ.get(f"{ENV_PREFIX}_PORT", DEFAULT_PORT)),
        user=os.environ.get(f"{ENV_PREFIX}_USER", DEFAULT_USER),
        password=os.environ.get(f"{ENV_PREFIX}_PASSWORD", ""),
        database=os.environ.get(f"{ENV_PREFIX}_DATABASE", DEFAULT_DATABASE),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
