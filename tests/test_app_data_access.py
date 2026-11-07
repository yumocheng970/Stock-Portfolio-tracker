"""app/data_access.py against the test database (everything is rolled back)."""
import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, friendly_message, safe_call


def test_create_and_read_investor(conn):
    new_id = da.create_investor(conn, "  Test Person  ", " test.person@example.com ")
    investor = da.get_investor(conn, new_id)
    # create_investor strips spaces at both ends
    assert investor["name"] == "Test Person"
    assert investor["email"] == "test.person@example.com"
    listed = [row for row in da.list_investors(conn) if row["investor_id"] == new_id]
    assert len(listed) == 1
    assert listed[0]["portfolios"] == 0 and listed[0]["watchlists"] == 0


def test_get_missing_investor_returns_none(conn):
    assert da.get_investor(conn, -1) is None


def test_update_name_then_email_keeps_the_other_field(conn):
    new_id = da.create_investor(conn, "Old Name", "old@example.com")
    da.update_investor(conn, new_id, name="New Name")
    assert da.get_investor(conn, new_id)["email"] == "old@example.com"
    da.update_investor(conn, new_id, email="new@example.com")
    investor = da.get_investor(conn, new_id)
    assert (investor["name"], investor["email"]) == ("New Name", "new@example.com")


def test_update_missing_investor_raises_not_found(conn):
    with pytest.raises(da.NotFoundError):
        da.update_investor(conn, -1, name="Nobody")


def test_delete_investor_cascades_to_portfolio(conn):
    new_id = da.create_investor(conn, "Leaving", "leaving@example.com")
    # Tests may use SQL directly; only the menus may not
    conn.execute("INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date) "
                  "VALUES (%s, 'P', 1000, '2025-01-02')", (new_id,))
    summary = da.investor_delete_summary(conn, new_id)
    assert summary == {"portfolios": 1, "trades": 0, "cash_transactions": 0, "watchlists": 0}
    da.delete_investor(conn, new_id)
    assert da.get_investor(conn, new_id) is None
    count = conn.execute("SELECT count(*) FROM portfolio WHERE investor_id = %s", (new_id,)).fetchone()[0]
    assert count == 0


def test_delete_missing_investor_raises_not_found(conn):
    with pytest.raises(da.NotFoundError):
        da.delete_investor(conn, -1)


def test_duplicate_email_any_case_gives_friendly_message(conn):
    da.create_investor(conn, "First", "Same.Person@Example.com")
    with pytest.raises(psycopg.errors.UniqueViolation) as caught:
        da.create_investor(conn, "Second", "same.person@example.COM")
    assert caught.value.diag.constraint_name == "uq_investor_email_lower"
    assert friendly_message(caught.value) == MESSAGES["uq_investor_email_lower"]


def test_safe_call_prints_message_and_connection_still_works(conn, capsys):
    da.create_investor(conn, "First", "dup@example.com")
    ok, result = safe_call(da.create_investor, conn, "Second", "DUP@example.com")
    assert (ok, result) == (False, None)
    assert MESSAGES["uq_investor_email_lower"] in capsys.readouterr().out
    # The failed INSERT was rolled back (savepoint): the connection is usable
    # and only the first investor exists
    rows = [r for r in da.list_investors(conn) if r["email"].lower() == "dup@example.com"]
    assert len(rows) == 1


def test_bad_email_gives_format_message(conn):
    ok, _ = safe_call(da.create_investor, conn, "Bad Email", "not-an-email")
    assert ok is False
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        da.create_investor(conn, "Bad Email", "not-an-email")
    assert friendly_message(caught.value) == MESSAGES["chk_investor_email_format"]


def test_blank_name_gives_message(conn):
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        da.create_investor(conn, "   ", "blank@example.com")
    assert friendly_message(caught.value) == MESSAGES["chk_investor_name_not_blank"]
