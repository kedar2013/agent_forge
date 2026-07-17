-- Revenue and Returns domain — MySQL table creation script.
-- Mirrors the credit_facility domain's proven structure exactly:
--   one hierarchy/master (dimension) table for lookup/search,
--   one monthly-metrics fact table sharing the same hierarchy columns,
--   two optional RLS support tables (persona + coverage), only needed if
--   this domain requires row-level access control.
--
-- Table names are prefixed `rr_` so they never collide with other domains
-- in the same database (matches credit_facility's `cf_` prefix convention).
-- Run this against whichever MySQL database your REVENUE_RETURNS_MYSQL_*
-- env vars point at (see the onboarding steps txt for env var setup).

CREATE TABLE IF NOT EXISTS rr_product_master (
    product_id      VARCHAR(20)   NOT NULL PRIMARY KEY,
    product_name    VARCHAR(255)  NOT NULL,
    sku             VARCHAR(64),
    business_unit   VARCHAR(255)  NOT NULL,   -- hierarchy level L2 (rollup)
    category        VARCHAR(255),             -- hierarchy level L3 (NULL for an L2 rollup row itself)
    sub_category    VARCHAR(255),             -- hierarchy level L4 (finest grain, optional)
    region          VARCHAR(100)  NOT NULL,
    product_level   VARCHAR(5)    NOT NULL,   -- 'L2' | 'L3' | 'L4' — which rollup this row represents
    launch_date     DATE,
    INDEX idx_rr_master_business_unit (business_unit),
    INDEX idx_rr_master_category (category),
    INDEX idx_rr_master_region (region),
    INDEX idx_rr_master_level (product_level)
);

CREATE TABLE IF NOT EXISTS rr_revenue_returns_monthly (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    product_id       VARCHAR(20)    NOT NULL,
    product_name     VARCHAR(255)   NOT NULL,
    business_unit    VARCHAR(255)   NOT NULL,
    category         VARCHAR(255)   NOT NULL,
    sub_category     VARCHAR(255),
    region           VARCHAR(100)   NOT NULL,
    product_level    VARCHAR(5)     NOT NULL,
    load_id          INT            NOT NULL,   -- period key, YYYYMM (e.g. 202607)
    gross_revenue    DECIMAL(18,2)  NOT NULL,
    returns_amount   DECIMAL(18,2)  NOT NULL,
    refund_amount    DECIMAL(18,2)  NOT NULL,
    net_revenue      DECIMAL(18,2)  NOT NULL,   -- gross_revenue - returns_amount - refund_amount
    return_rate_pct  DECIMAL(7,4)   NOT NULL,   -- returns_amount / gross_revenue
    units_sold       INT            NOT NULL,
    units_returned   INT            NOT NULL,
    num_orders       INT            NOT NULL,
    UNIQUE KEY uq_rr_revenue_product_load (product_id, load_id),
    INDEX idx_rr_revenue_business_unit (business_unit),
    INDEX idx_rr_revenue_category (category),
    INDEX idx_rr_revenue_region (region),
    INDEX idx_rr_revenue_level (product_level)
);

-- --- Optional: only create these two if this domain needs row-level
-- security (i.e. different users/personas should see different subsets of
-- products). Skip them entirely if every user should see all data — the
-- onboarding wizard's Access step has a "skip, everyone sees the same
-- data" option for exactly this case.

CREATE TABLE IF NOT EXISTS rr_user_persona (
    user_id   VARCHAR(64)  NOT NULL PRIMARY KEY,
    persona   VARCHAR(20)  NOT NULL   -- e.g. 'GLOBAL', 'REGIONAL', 'BU_OWNER', 'PRODUCT_OWNER'
);

CREATE TABLE IF NOT EXISTS rr_user_product_coverage (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         VARCHAR(64)   NOT NULL,
    product_id      VARCHAR(20)   NOT NULL,
    product_name    VARCHAR(255)  NOT NULL,
    business_unit   VARCHAR(255)  NOT NULL,
    category        VARCHAR(255)  NOT NULL,
    region          VARCHAR(100)  NOT NULL,
    product_level   VARCHAR(5)    NOT NULL,
    INDEX idx_rr_coverage_user (user_id)
);