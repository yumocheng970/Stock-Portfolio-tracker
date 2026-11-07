"""App 2: portfolio data-access functions on the test database (all rolled back).

Fictional stock PFT1 with prices on 2025-03-03 .. 2025-03-07 (low 90, high 115):
    closes 100, 105, 95, 110, 100
The test database has no other prices (make test rebuilds it empty), so
2025-03-07 is the latest price date.
"""
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, friendly_message
from app.inputs import ask_date, ask_decimal

D1, D2, D3, D4, D5 = (date(2025, 3, day) for day in (3, 4, 5, 6, 7))
CLOSES = {D1: 100, D2: 105, D3: 95, D4: 110, D5: 100}


@pytest.fixture
def setup(conn):
    """An investor, stock PFT1 with a week of prices, and a portfolio of 10,000 from D1."""
    others = conn.execute("SELECT count(*) FROM daily_price").fetchone()[0]
    assert others == 0, "expected an empty test database (run `make test`)"
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('PFT1', 'Portfolio Test One')")
    for day, close in CLOSES.items():
        conn.execute("INSERT INTO daily_price VALUES ('PFT1', %s, %s, 115, 90, %s, 1000)",
                     (day, close, close))
    investor_id = da.create_investor(conn, "Pat Folio", "pat.folio@example.com")
    portfolio_id = da.create_portfolio(conn, investor_id, "Main", Decimal("10000"), D1)
    return {"conn": conn, "investor_id": investor_id, "portfolio_id": portfolio_id}


def refused(func, *args):
    """Call func, expect the database to refuse; return the friendly message."""
    with pytest.raises(psycopg.Error) as caught:
        func(*args)
    return friendly_message(caught.value)


# ---------------------------------------------------------------------
def test_create_and_list_portfolio(setup):
    conn = setup["conn"]
    rows = da.list_portfolios(conn, setup["investor_id"])
    assert len(rows) == 1
    row = rows[0]
    assert (row["portfolio_name"], row["start_date"], row["cash"], row["market_value"],
            row["total_value"]) == ("Main", D1, 10000, 0, 10000)


def test_duplicate_name_same_investor_refused_other_investor_ok(setup):
    conn = setup["conn"]
    message = refused(da.create_portfolio, conn, setup["investor_id"], "Main", Decimal("1"), D1)
    assert message == MESSAGES["uq_portfolio_investor_name"]
    other = da.create_investor(conn, "Other", "other.pf@example.com")
    da.create_portfolio(conn, other, "Main", Decimal("1"), D1)       # allowed


def test_buy_within_cash_and_summary_matches_views(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    row = da.execute_trade(conn, pid, " pft1 ", "BUY", 10, D2)       # price None = close
    assert (row["ticker"], row["shares"], row["price"]) == ("PFT1", 10, 105)

    cash = da.cash_summary(conn, pid)
    view_cash = conn.execute("SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s",
                             (pid,)).fetchone()[0]
    assert cash["cash_balance"] == view_cash == Decimal("8950.00")

    holding = da.open_holdings(conn, pid)[0]
    view = conn.execute("SELECT shares_held, round(avg_cost, 2), cost_basis FROM v_holdings "
                        "WHERE portfolio_id = %s AND ticker = 'PFT1'", (pid,)).fetchone()
    assert (holding["shares_held"], holding["avg_cost"], holding["cost_basis"]) == view
    # valued at the latest close (D5, 100), not the trade price
    assert (holding["close_date"], holding["market_value"]) == (D5, 1000)

    listed = da.list_portfolios(conn, setup["investor_id"])[0]
    assert (listed["market_value"], listed["total_value"]) == (1000, Decimal("9950.00"))


def test_buy_with_explicit_price_outside_range_refused(setup):
    message = refused(da.execute_trade, setup["conn"], setup["portfolio_id"],
                      "PFT1", "BUY", 1, D1, Decimal("200"))
    assert message.startswith(MESSAGES["trg_trade_price_in_range"])
    assert "90.00 to 115.00" in message                              # the DETAIL


def test_overdraw_message_includes_detail_amount(setup):
    message = refused(da.execute_trade, setup["conn"], setup["portfolio_id"], "PFT1", "BUY", 1000, D1)
    assert message.startswith(MESSAGES["trg_cash_never_negative"])
    assert "Cash would be -90000.00 on 2025-03-03" in message        # 10,000 - 1000 x 100


def test_sell_more_than_held_refused(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    da.execute_trade(conn, pid, "PFT1", "BUY", 5, D1)
    message = refused(da.execute_trade, conn, pid, "PFT1", "SELL", 6, D2)
    assert message.startswith(MESSAGES["trg_shares_never_negative"])
    assert "PFT1 shares would be -1" in message


def test_deposit_works_and_too_large_withdrawal_refused(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    txn_id = da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("500"), D2)
    assert txn_id is not None
    assert da.cash_summary(conn, pid)["cash_balance"] == Decimal("10500.00")
    message = refused(da.record_cash_transaction, conn, pid, "WITHDRAWAL", Decimal("10500.01"), D2)
    assert message.startswith(MESSAGES["trg_cash_never_negative"])
    assert "Cash would be -0.01" in message


def test_trade_before_latest_event_refused(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("100"), D3)
    assert da.trade_context(conn, pid)["latest_allowed"] == D3
    message = refused(da.execute_trade, conn, pid, "PFT1", "BUY", 1, D2)
    assert message.startswith(MESSAGES["trg_date_before_latest"])


def test_hints_price_and_ticker(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    assert da.price_on(conn, "pft1", D4) == {"low": 90, "high": 115, "close": 110}
    assert da.price_on(conn, "PFT1", date(2025, 3, 8)) is None       # no price that day
    unknown = da.ticker_context(conn, pid, "NOPE")
    assert (unknown["company_name"], unknown["shares_held"], unknown["last_price_date"]) == (None, 0, None)
    known = da.ticker_context(conn, pid, " pft1 ")
    assert (known["ticker"], known["company_name"], known["last_price_date"]) == \
           ("PFT1", "Portfolio Test One", D5)
    assert da.price_date_range(conn) == {"first": D1, "last": D5}


def test_default_dates_let_a_new_portfolio_trade(setup):
    """Enter at every date prompt: a portfolio started on the default date can
    trade on the default trade date (with "today" as the default it couldn't:
    there is no price for today)."""
    conn = setup["conn"]
    start = da.default_event_date(conn)                  # no portfolio yet
    assert start == D5                                   # the latest price date
    pid = da.create_portfolio(conn, setup["investor_id"], "Defaults", Decimal("1000"), start)
    trade_day = da.default_event_date(conn, pid)
    assert trade_day == D5
    row = da.execute_trade(conn, pid, "PFT1", "BUY", 1, trade_day)
    assert (row["trade_date"], row["price"]) == (D5, 100)


def test_default_date_follows_a_later_portfolio_event(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    later = date(2025, 3, 20)                            # after the last price date
    da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("1"), later)
    assert da.default_event_date(conn, pid) == later


def test_rename_and_duplicate_rename(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    da.rename_portfolio(conn, pid, "Renamed")
    assert da.get_portfolio(conn, pid)["portfolio_name"] == "Renamed"
    da.create_portfolio(conn, setup["investor_id"], "Second", Decimal("1"), D1)
    assert refused(da.rename_portfolio, conn, pid, "Second") == MESSAGES["uq_portfolio_investor_name"]
    with pytest.raises(da.NotFoundError):
        da.rename_portfolio(conn, -1, "X")


def test_delete_summary_and_cascade(setup):
    conn, pid = setup["conn"], setup["portfolio_id"]
    da.record_cash_transaction(conn, pid, "DEPOSIT", Decimal("100"), D1)
    da.execute_trade(conn, pid, "PFT1", "BUY", 5, D1)
    da.execute_trade(conn, pid, "PFT1", "SELL", 2, D2)
    assert da.portfolio_delete_summary(conn, pid) == {"trades": 2, "cash_transactions": 1}

    da.delete_portfolio(conn, pid)
    assert da.get_portfolio(conn, pid) is None
    for table in ("trade", "cash_transaction"):
        left = conn.execute(f"SELECT count(*) FROM {table} WHERE portfolio_id = %s", (pid,)).fetchone()[0]
        assert left == 0
    audited = conn.execute("SELECT count(*) FROM trade_audit WHERE portfolio_id = %s "
                           "AND operation = 'DELETE'", (pid,)).fetchone()[0]
    assert audited == 2
    with pytest.raises(da.NotFoundError):
        da.delete_portfolio(conn, pid)


# ---------------------------------------------------------------------
# New input helpers (no database)
# ---------------------------------------------------------------------
def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_ask_decimal_reasks(monkeypatch, capsys):
    fake_input(monkeypatch, ["abc", "1.234", "NaN", "1,000.50"])
    assert ask_decimal("Amount") == Decimal("1000.50")
    out = capsys.readouterr().out
    assert "type a number" in out and "2 decimals" in out and "normal number" in out


def test_ask_decimal_optional_empty(monkeypatch):
    fake_input(monkeypatch, [""])
    assert ask_decimal("Price", required=False) is None


def test_ask_date_reasks_and_default(monkeypatch, capsys):
    fake_input(monkeypatch, ["2025-02-30", "march 3", ""])
    assert ask_date("Date", default=D5) == D5
    assert "real date" in capsys.readouterr().out
    fake_input(monkeypatch, ["2025-03-04"])
    assert ask_date("Date", default=D5) == D2
