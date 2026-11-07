"""app/errors.py: a friendly message for EVERY named rule in the database.

The names are read from the catalog of the test database, so adding a
constraint or a trigger error without a message here makes this test fail.
"""
import psycopg
import pytest

from app.errors import MESSAGES, friendly_message

# Every name a database error can carry (e.diag.constraint_name):
#   1. constraints: CHECK, FOREIGN KEY, UNIQUE, PRIMARY KEY
#   2. unique indexes that are not constraints (uq_investor_email_lower)
#   3. names raised by triggers / procedures: USING CONSTRAINT = 'trg_...'
CATALOG_NAMES_SQL = r"""
    SELECT conname FROM pg_constraint
    WHERE connamespace = 'public'::regnamespace
    UNION
    SELECT c.relname FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relnamespace = 'public'::regnamespace AND i.indisunique
      AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)
    UNION
    SELECT m[1] FROM pg_proc p,
           regexp_matches(p.prosrc, 'CONSTRAINT\s*=\s*''([a-z_]+)''', 'g') AS m
    WHERE p.pronamespace = 'public'::regnamespace
"""


@pytest.fixture
def catalog_names(conn):
    return {row[0] for row in conn.execute(CATALOG_NAMES_SQL).fetchall()}


def test_catalog_query_finds_all_kinds(catalog_names):
    # Guard against a broken query that would make the next test pass trivially
    assert {"chk_trade_shares", "fk_trade_daily_price", "uq_investor_email_lower",
            "investor_pkey", "trg_cash_never_negative", "exec_no_price_data"} <= catalog_names
    assert len(catalog_names) >= 60


def test_every_database_name_has_a_message(catalog_names):
    missing = sorted(catalog_names - MESSAGES.keys())
    assert missing == [], f"add these to app/errors.py MESSAGES: {missing}"


def test_every_message_name_exists_in_the_database(catalog_names):
    stale = sorted(MESSAGES.keys() - catalog_names)
    assert stale == [], f"typo or removed from the database: {stale}"


def test_trigger_message_adds_database_detail(conn):
    # A withdrawal larger than the cash: trg_cash_never_negative with a DETAIL line
    investor_id = conn.execute("INSERT INTO investor (name, email) VALUES ('T', 't@example.com') "
                               "RETURNING investor_id").fetchone()[0]
    portfolio_id = conn.execute(
        "INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date) "
        "VALUES (%s, 'P', 100, '2025-01-02') RETURNING portfolio_id", (investor_id,)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        with conn.transaction():
            conn.execute("CALL record_cash_transaction(%s, 'WITHDRAWAL', 150, '2025-01-03', NULL)",
                         (portfolio_id,))
    message = friendly_message(caught.value)
    assert message.startswith(MESSAGES["trg_cash_never_negative"])
    assert "-50.00" in message                      # the detail: cash would be -50.00


def test_unnamed_not_null_uses_sqlstate_message(conn):
    with pytest.raises(psycopg.errors.NotNullViolation) as caught:
        with conn.transaction():
            conn.execute("INSERT INTO investor (name, email) VALUES ('No Email', NULL)")
    assert friendly_message(caught.value) == "Email is required."
