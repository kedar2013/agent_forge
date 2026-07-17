"""Connection settings + table names for the credit-facility MySQL tables,
shared by the seed scripts. The `mysql_query_tool` rows `seed_agent.py`
creates read the same `{ENV_PREFIX}_HOST/_PORT/_USER/_PASSWORD/_DATABASE`
env vars independently at request time via `connection_env_prefix` — this
module exists only so the seed scripts have one place to get a connection
and agree on table names.

Tables live in your existing MySQL server/database (default: the same
`agentic_ai` database other domains in this repo already use) — prefixed
`cf_` so they don't collide with anything else there.
"""

import os

import pymysql
from dotenv import load_dotenv

# Standalone-script invocation (`python -m app.domains.credit_facility.*`)
# never goes through app/config.py's pydantic Settings (which only bridges
# a couple of specific keys into os.environ) — load .env directly here,
# same pattern as mcp_servers/_db.py, path-independent of cwd.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

ENV_PREFIX = "CREDIT_FACILITY_MYSQL"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "3306"
DEFAULT_USER = "root"
DEFAULT_DATABASE = "agentic_ai"

USER_PERSONA_TABLE = "cf_user_persona"
USER_COMPANY_COVERAGE_TABLE = "cf_user_company_coverage"
COMPANY_MASTER_TABLE = "cf_company_master"
COMPANY_FACILITY_MONTHLY_TABLE = "cf_company_facility_monthly"

SCHEMA_DDL = f"""
CREATE TABLE IF NOT EXISTS {USER_PERSONA_TABLE} (
    user_id VARCHAR(64) PRIMARY KEY,
    persona VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS {USER_COMPANY_COVERAGE_TABLE} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    company_id VARCHAR(20) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    gfcid VARCHAR(20),
    l2 VARCHAR(255),
    l3 VARCHAR(255),
    l4 VARCHAR(255),
    company_level VARCHAR(5) NOT NULL,
    INDEX idx_cf_coverage_user (user_id)
);

CREATE TABLE IF NOT EXISTS {COMPANY_MASTER_TABLE} (
    company_id VARCHAR(20) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    gfcid VARCHAR(20),
    l2 VARCHAR(255),
    l3 VARCHAR(255),
    l4 VARCHAR(255),
    company_level VARCHAR(5) NOT NULL,
    INDEX idx_cf_master_gfcid (gfcid),
    INDEX idx_cf_master_level (company_level)
);

CREATE TABLE IF NOT EXISTS {COMPANY_FACILITY_MONTHLY_TABLE} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    company_id VARCHAR(20) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    gfcid VARCHAR(20),
    l2 VARCHAR(255),
    l3 VARCHAR(255),
    l4 VARCHAR(255),
    company_level VARCHAR(5) NOT NULL,
    load_id INT NOT NULL,
    total_facility_limit DECIMAL(18,2) NOT NULL,
    utilized_amount DECIMAL(18,2) NOT NULL,
    available_amount DECIMAL(18,2) NOT NULL,
    utilization_pct DECIMAL(7,4) NOT NULL,
    outstanding_balance DECIMAL(18,2) NOT NULL,
    overdue_amount DECIMAL(18,2) NOT NULL,
    interest_accrued DECIMAL(18,2) NOT NULL,
    num_transactions INT NOT NULL,
    UNIQUE KEY uq_cf_facility_company_load (company_id, load_id),
    INDEX idx_cf_facility_gfcid (gfcid),
    INDEX idx_cf_facility_level (company_level)
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
