"""Extra 3: rebalance on the test database (rolled back).

AAA close 100 and BBB close 50 on 2025-03-03 and 2025-03-04 (low 1, high 1000).
LATE has a price on 2025-03-03 only (valued, but no price ON 2025-03-04).
^IDX is an index with a price on both days.
"""
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, friendly_message
from app.menus import portfolio_menu
from app.rebalance import plan_rebalance
from app.session import Session

D1, D2 = date(2025, 3, 3), date(2025, 3, 4)


@pytest.fixture
def pf(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('AAA', 'A'), ('BBB', 'B'), ('LATE', 'Late')")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^IDX', 'Index', 'INDEX')")
    for ticker, close, days in (("AAA", 100, (D1, D2)), ("BBB", 50, (D1, D2)),
                                ("LATE", 20, (D1,)), ("^IDX", 10, (D1, D2))):
        for day in days:
            conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, 1000, 1, %s, 0)", (ticker, day, close, close))
    investor = da.create_investor(conn, "Reba Lance", "reba.lance@example.com")
    # 10,000 starting cash, all of it in 100 AAA on D1: cash 0 (the spec's second example)
    pid = da.create_portfolio(conn, investor, "Rebal", Decimal("10000"), D1)
    da.execute_trade(conn, pid, "AAA", "BUY", 100, D1)
    session = Session(conn)
    session.choose_portfolio(pid, "Rebal")
    return conn, pid, session


def state(conn, pid):
    cash = conn.execute("SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s", (pid,)).fetchone()[0]
    held = dict(conn.execute("SELECT ticker, shares_held FROM v_holdings WHERE portfolio_id = %s AND is_open",
                             (pid,)).fetchall())
    return cash, held


def make_plan(conn, pid, targets, day=D2):
    cash, held = state(conn, pid)
    prices = da.latest_closes(conn, set(held) | set(targets), day)
    return plan_rebalance(cash, held, prices, targets)


# ---------------------------------------------------------------------
def test_rebalance_executes_sell_then_buy(pf):
    conn, pid, _ = pf
    plan = make_plan(conn, pid, {"AAA": Decimal("50"), "BBB": Decimal("50")})
    assert plan.trades == [("AAA", "SELL", 50), ("BBB", "BUY", 100)]
    assert da.execute_rebalance(conn, pid, plan.trades, D2) == 2
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 50, "BBB": 100}) == (plan.cash_after, {
        line.ticker: line.shares_after for line in plan.lines})


def test_buy_before_sell_would_be_refused(pf):
    """Why SELLs go first: replayed BUY-first, the purchase has no cash yet."""
    conn, pid, _ = pf
    with pytest.raises(da.RebalanceTradeError) as caught:
        da.execute_rebalance(conn, pid, [("BBB", "BUY", 100), ("AAA", "SELL", 50)], D2)
    message = friendly_message(caught.value)
    assert message.startswith("BUY 100 BBB: " + MESSAGES["trg_cash_never_negative"])
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 100})          # nothing saved


def test_all_or_nothing_when_a_later_trade_has_no_price_that_day(pf):
    conn, pid, _ = pf
    plan = make_plan(conn, pid, {"AAA": Decimal("50"), "LATE": Decimal("50")})   # LATE valued at its D1 close
    assert plan.trades == [("AAA", "SELL", 50), ("LATE", "BUY", 250)]
    with pytest.raises(da.RebalanceTradeError) as caught:
        da.execute_rebalance(conn, pid, plan.trades, D2)
    assert friendly_message(caught.value) == \
        "BUY 250 LATE: No price for LATE on 2025-03-04 (not a trading day, or unknown ticker)."
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 100})          # the SELL was rolled back


def test_index_in_targets_is_refused_by_the_database(pf):
    conn, pid, _ = pf
    plan = make_plan(conn, pid, {"AAA": Decimal("50"), "^IDX": Decimal("50")})
    with pytest.raises(da.RebalanceTradeError) as caught:
        da.execute_rebalance(conn, pid, plan.trades, D2)
    assert friendly_message(caught.value).startswith("BUY 500 ^IDX: " + MESSAGES["trg_trade_not_index"])
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 100})


def test_latest_closes(pf):
    conn, _, _ = pf
    assert da.latest_closes(conn, {"AAA", "LATE", "NOPE"}, D2) == {"AAA": 100, "LATE": 20}


# ---------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------
def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_menu_rebalance_confirmed(pf, monkeypatch, capsys):
    conn, pid, session = pf
    # date (Enter = D2, the latest price date), bad targets, good targets, confirm, pause
    fake_input(monkeypatch, ["", "AAA 70, BBB 50", "AAA 50, BBB 50", "y", ""])
    portfolio_menu.rebalance_portfolio(session)
    out = capsys.readouterr().out
    assert "The targets add up to 120 %, more than 100 %" in out
    assert "Trades, in this order (sales first): SELL 50 AAA, BUY 100 BBB" in out
    assert "Done: 2 trades." in out
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 50, "BBB": 100})


def test_menu_rebalance_declined_or_read_only_saves_nothing(pf, monkeypatch, capsys):
    conn, pid, session = pf
    fake_input(monkeypatch, ["", "AAA 50, BBB 50", "n", ""])
    portfolio_menu.rebalance_portfolio(session)
    monkeypatch.setattr(da, "is_read_only", lambda conn: True)        # like make run-readonly
    fake_input(monkeypatch, ["", "AAA 50, BBB 50", "y", ""])
    portfolio_menu.rebalance_portfolio(session)
    out = capsys.readouterr().out
    assert "Nothing was traded." in out
    assert "Rebalancing is not possible in read-only mode: nothing was changed." in out
    assert state(conn, pid) == (Decimal("0.00"), {"AAA": 100})


def test_menu_rebalance_missing_price_message(pf, monkeypatch, capsys):
    # (Changed with the ticker help: an unknown ticker is now caught at the targets
    # prompt and asked again, instead of failing later with "No price for ZZZ".)
    conn, pid, session = pf
    fake_input(monkeypatch, ["", "ZZZ 10", ""])          # date, targets, Enter = cancel at the re-ask
    portfolio_menu.rebalance_portfolio(session)
    assert "ZZZ is not in the stock list (type ? for the list)." in capsys.readouterr().out
