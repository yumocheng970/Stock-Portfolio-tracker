"""App 3: trade history, edit, delete, audit log, restore (test DB, rolled back).

Stock PTH1, prices 2025-03-03 .. 07: low 90, high 115, close 100.
Portfolio of 10,000 starting 2025-03-03.
"""
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, format_money_in_text, friendly_message

D1, D2, D3, D4, D5 = (date(2025, 3, day) for day in (3, 4, 5, 6, 7))


@pytest.fixture
def pf(conn):
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('PTH1', 'History One'), "
                 "('PTH2', 'History Two')")
    for ticker in ("PTH1", "PTH2"):
        for day in (D1, D2, D3, D4, D5):
            conn.execute("INSERT INTO daily_price VALUES (%s, %s, 100, 115, 90, 100, 1000)", (ticker, day))
    investor_id = da.create_investor(conn, "Hist Ory", "hist.ory@example.com")
    portfolio_id = da.create_portfolio(conn, investor_id, "History", Decimal("10000"), D1)
    return conn, portfolio_id


def refused(func, *args):
    with pytest.raises(psycopg.Error) as caught:
        func(*args)
    return friendly_message(caught.value)


def cash(conn, pid):
    return conn.execute("SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s",
                        (pid,)).fetchone()[0]


def shares_held(conn, pid, ticker="PTH1"):
    row = conn.execute("SELECT shares_held FROM v_holdings WHERE portfolio_id = %s AND ticker = %s",
                       (pid, ticker)).fetchone()
    return row[0] if row else 0


def audit_rows(conn, trade_id):
    return conn.execute("SELECT operation, shares, price FROM trade_audit WHERE trade_id = %s "
                        "ORDER BY audit_id", (trade_id,)).fetchall()


# ---------------------------------------------------------------------
def test_history_order_matches_the_balance_replay(pf):
    conn, pid = pf
    da.execute_trade(conn, pid, "PTH1", "BUY", 5, D1)
    da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("10"), D2)
    da.execute_trade(conn, pid, "PTH2", "BUY", 3, D2)
    da.execute_trade(conn, pid, "PTH1", "SELL", 2, D2)
    da.execute_trade(conn, pid, "PTH1", "BUY", 1, D4)
    listed = [row["trade_id"] for row in da.list_trades(conn, pid)]
    replay = [row[0] for row in conn.execute(
        "SELECT event_id FROM fn_portfolio_history(%s) WHERE event_order = 1 "
        "ORDER BY event_date, event_order, event_id", (pid,)).fetchall()]
    assert listed == replay and len(listed) == 4
    only_pth2 = da.list_trades(conn, pid, " pth2 ")
    assert [(r["ticker"], r["shares"], r["amount"]) for r in only_pth2] == [("PTH2", 3, 300)]


def test_edit_shares_writes_update_audit_row_with_old_values(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 10, D1)
    da.update_trade(conn, pid, trade["trade_id"], shares=4)
    assert audit_rows(conn, trade["trade_id"]) == [("UPDATE", 10, Decimal("100.00"))]
    assert shares_held(conn, pid) == 4
    assert da.get_portfolio_trade(conn, pid, trade["trade_id"])["price"] == 100   # price kept


def test_edit_price_outside_range_refused(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 1, D1)
    message = refused(da.update_trade, conn, pid, trade["trade_id"], None, Decimal("200"))
    assert message.startswith(MESSAGES["trg_trade_price_in_range"])
    assert "90.00 to 115.00" in message


def test_edit_that_breaks_history_is_refused_and_changes_nothing(pf):
    conn, pid = pf
    buy = da.execute_trade(conn, pid, "PTH1", "BUY", 10, D1)
    da.execute_trade(conn, pid, "PTH1", "SELL", 8, D2)
    message = refused(da.update_trade, conn, pid, buy["trade_id"], 5, None)
    assert message.startswith(MESSAGES["trg_shares_never_negative"])
    assert "PTH1 shares would be -3" in message
    assert da.get_portfolio_trade(conn, pid, buy["trade_id"])["shares"] == 10
    assert audit_rows(conn, buy["trade_id"]) == []             # the audit row was rolled back too
    assert shares_held(conn, pid) == 2


def test_delete_writes_delete_audit_row(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 7, D1)
    da.delete_trade(conn, pid, trade["trade_id"])
    assert da.get_portfolio_trade(conn, pid, trade["trade_id"]) is None
    assert audit_rows(conn, trade["trade_id"]) == [("DELETE", 7, Decimal("100.00"))]
    log = da.audit_log(conn, pid)
    assert (log[0]["operation"], log[0]["status"]) == ("DELETE", "restorable")
    with pytest.raises(da.NotFoundError):
        da.delete_trade(conn, pid, trade["trade_id"])


def test_restore_brings_the_trade_back_as_it_was(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 7, D1)
    cash_before = cash(conn, pid)
    da.delete_trade(conn, pid, trade["trade_id"])
    da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("1"), D3)     # a later event
    da.record_cash_transaction(conn, pid, "WITHDRAWAL", Decimal("1"), D3)  # (net 0)
    audit_id = da.audit_log(conn, pid)[0]["audit_id"]

    restored = da.restore_trade(conn, pid, audit_id)
    keys = ("trade_id", "trade_date", "trade_type", "ticker", "shares", "price")
    assert {k: restored[k] for k in keys} == {k: trade[k] for k in keys}   # same id and values
    assert cash(conn, pid) == cash_before
    assert da.audit_log(conn, pid)[0]["status"] == "restored"


def test_restoring_the_same_trade_twice_is_refused(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 2, D1)
    da.delete_trade(conn, pid, trade["trade_id"])
    audit_id = da.audit_log(conn, pid)[0]["audit_id"]
    da.restore_trade(conn, pid, audit_id)
    message = refused(da.restore_trade, conn, pid, audit_id)
    assert message == f"Trade {trade['trade_id']} is already back in the portfolio."


def test_restore_refused_when_the_cash_was_spent_since(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 60, D1)        # 6,000
    da.delete_trade(conn, pid, trade["trade_id"])
    da.execute_trade(conn, pid, "PTH2", "BUY", 90, D2)                # spends 9,000
    audit_id = da.audit_log(conn, pid, only_deletes=True)[0]["audit_id"]
    message = refused(da.restore_trade, conn, pid, audit_id)
    assert message.startswith(MESSAGES["trg_cash_never_negative"])
    assert "Cash would be -5,000.00" in message                         # 10,000 - 6,000 - 9,000
    assert da.get_portfolio_trade(conn, pid, trade["trade_id"]) is None


def test_restore_of_another_portfolios_audit_row_is_not_found(pf):
    conn, pid = pf
    trade = da.execute_trade(conn, pid, "PTH1", "BUY", 1, D1)
    da.delete_trade(conn, pid, trade["trade_id"])
    audit_id = da.audit_log(conn, pid)[0]["audit_id"]
    other = da.create_portfolio(conn, da.create_investor(conn, "O", "o.th@example.com"),
                                "Other", Decimal("100"), D1)
    with pytest.raises(da.NotFoundError):
        da.restore_trade(conn, other, audit_id)


# Thousands separators in the database's DETAIL -------------------------
def test_money_in_detail_gets_thousands_separators():
    text = "Cash would be -20366046.40 on 2025-03-04, after trade 1159 (BUY 1000 DEMO @ 107.00)."
    assert format_money_in_text(text) == \
        "Cash would be -20,366,046.40 on 2025-03-04, after trade 1159 (BUY 1000 DEMO @ 107.00)."
    assert format_money_in_text("Allowed range: 90.00 to 1150.00.") == "Allowed range: 90.00 to 1,150.00."


def test_overdraw_message_uses_separators(pf):
    conn, pid = pf
    message = refused(da.execute_trade, conn, pid, "PTH1", "BUY", 1000, D1)
    assert "Cash would be -90,000.00 on 2025-03-03" in message
