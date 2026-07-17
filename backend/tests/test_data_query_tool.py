"""Pure-function tests for data_query_tool's SQL AST validation/RLS-injection
— no live DB required, mirrors test_templating.py's style. These prove the
security-critical properties: structure fixed at the AST level, policy
predicate ANDed on regardless of what the LLM's own query said."""

import sqlglot

from app.tool_registry.data_query_tool import (
    build_policy_condition,
    has_literal_equality,
    validate_single_select,
    validate_single_table,
)


def test_rejects_multi_statement():
    error = validate_single_select("SELECT 1; DROP TABLE t;")
    assert error is not None


def test_rejects_dml_anywhere_in_tree():
    error = validate_single_select("SELECT * FROM t WHERE id IN (SELECT id FROM t2); DELETE FROM t")
    assert error is not None


def test_rejects_delete_disguised_as_select_statement():
    error = validate_single_select("DELETE FROM t WHERE id = 1")
    assert error is not None


def test_accepts_plain_select():
    assert validate_single_select("SELECT company_name FROM cf_company_master") is None


def test_accepts_with_select():
    assert validate_single_select("WITH x AS (SELECT 1 AS a) SELECT a FROM x") is None


def test_rejects_foreign_table():
    parsed = sqlglot.parse_one("SELECT * FROM some_other_table", dialect="mysql")
    error = validate_single_table(parsed, "cf_company_master")
    assert error is not None
    assert "some_other_table" in error


def test_accepts_allowed_table():
    parsed = sqlglot.parse_one("SELECT * FROM cf_company_master", dialect="mysql")
    assert validate_single_table(parsed, "cf_company_master") is None


def test_global_mode_has_no_predicate():
    condition, reason = build_policy_condition({}, {"_policy_mode": "GLOBAL"})
    assert condition is None
    assert reason is None


def test_attribute_scoped_predicate_and_injected():
    parsed = sqlglot.parse_one("SELECT * FROM t WHERE company_name LIKE '%tesla%'", dialect="mysql")
    condition, reason = build_policy_condition(
        {"attribute": "company_level"}, {"_policy_mode": "ATTRIBUTE_SCOPED", "_attr_values": ["L3", "L4"]}
    )
    assert reason is None
    injected = parsed.where(condition, append=True)
    sql = injected.sql(dialect="mysql")
    assert "company_level" in sql
    assert "company_name" in sql  # the LLM's own filter survives
    assert " AND " in sql.upper() or "AND" in sql


def test_id_scoped_predicate_survives_even_if_llm_tries_to_override():
    """A crafted LLM query that already filters company_id to something else
    still gets the policy's own IN-list ANDed on top -- the LLM's WHERE
    clause is never trusted to self-scope."""
    parsed = sqlglot.parse_one("SELECT * FROM t WHERE company_id = 'C9999'", dialect="mysql")
    condition, reason = build_policy_condition(
        {"id": "company_id"}, {"_policy_mode": "ID_SCOPED", "_id_values": ["C0001", "C0002"]}
    )
    assert reason is None
    injected = parsed.where(condition, append=True)
    sql = injected.sql(dialect="mysql")
    assert "'C0001'" in sql and "'C0002'" in sql
    assert "C9999" in sql  # LLM's own (now-irrelevant-on-its-own) filter still there, harmless alongside the AND


def test_unrecognized_mode_denies_by_default():
    condition, reason = build_policy_condition({}, {"_policy_mode": "SOMETHING_NEW"})
    assert reason is None
    assert condition is not None
    assert condition.sql() in ("1 = 0", "1=0")


def test_exact_mode_detects_literal_equality():
    parsed = sqlglot.parse_one("SELECT * FROM t WHERE gfcid = 'GF00042'", dialect="mysql")
    assert has_literal_equality(parsed, "gfcid") is True


def test_exact_mode_rejects_missing_filter():
    parsed = sqlglot.parse_one("SELECT * FROM t", dialect="mysql")
    assert has_literal_equality(parsed, "gfcid") is False


def test_exact_mode_rejects_filter_hidden_behind_or():
    """`WHERE 1=1 OR gfcid = 'x'` doesn't actually constrain anything --
    must not count as a real exact-reference filter."""
    parsed = sqlglot.parse_one("SELECT * FROM t WHERE 1=1 OR gfcid = 'GF00042'", dialect="mysql")
    assert has_literal_equality(parsed, "gfcid") is False


def test_exact_mode_rejects_column_to_column_comparison():
    """`WHERE gfcid = other_column` isn't a caller-supplied literal -- must
    not satisfy the exact-reference requirement."""
    parsed = sqlglot.parse_one("SELECT * FROM t WHERE gfcid = other_column", dialect="mysql")
    assert has_literal_equality(parsed, "gfcid") is False
