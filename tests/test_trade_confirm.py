"""Buy / Sell confirm step and the Buy concentration warning (test DB, rolled back).

CC1 close 100 and CC2 close 50 on 2025-03-03 (low 1, high 1000).
Portfolio "Conc": 10,000 starting cash, holds 20 CC2 (1,000) -> cash 9,000, total 10,000.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import data_access as da
from app.menus import portfolio_menu
from app.session import Session
from app.trade_preview import (CONCENTRATION_WARNING_PCT, concentration_after_buy,
                               concentration_warning, preview_text)

D1 = date(2025, 3, 3)


@pytest.fixture
def pf(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('CC1', 'Conc One'), ('CC2', 'Conc Two')")
    for ticker, close in (("CC1", 100), ("CC2", 50)):
        conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, 1000, 1, %s, 0)", (ticker, D1, close, close))
    investor = da.create_investor(conn, "Cora Conc", "cora.conc@example.com")
    pid = da.create_portfolio(conn, investor, "Conc", Decimal("10000"), D1)
    da.execute_trade(conn, pid, "CC2", "BUY", 20, D1)
    session = Session(conn)
    session.choose_portfolio(pid, "Conc")
    return conn, pid, session


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def trade_count(conn, pid):
    return conn.execute("SELECT count(*) FROM trade WHERE portfolio_id = %s", (pid,)).fetchone()[0]


# ---------------------------------------------------------------------
# Pure: preview text and the concentration %
# ---------------------------------------------------------------------
def test_preview_text():
    assert preview_text("BUY", 10, "AAPL", Decimal("204.64"), date(2026, 11, 6), Decimal("100000")) == \
        "BUY 10 AAPL @ 204.64 on 2026-11-06 = 2,046.40. Cash after: 97,953.60."
    assert preview_text("SELL", 3, "KO", Decimal("70"), D1, Decimal("5")) == \
        "SELL 3 KO @ 70.00 on 2025-03-03 = 210.00. Cash after: 215.00."


def test_concentration_after_buy():
    closes = {"CC1": Decimal("100"), "CC2": Decimal("50")}
    # 50 CC1 at 100: CC1 5,000 of total 10,000 (cash 4,000 + CC2 1,000 + CC1 5,000)
    assert concentration_after_buy(Decimal("9000"), {"CC2": 20}, closes, "CC1", 50, Decimal("100")) == 50
    # paying above the close lowers the total: 5,000 / (10,000 - 50 x 10) -> 52.63 %
    pct = concentration_after_buy(Decimal("9000"), {"CC2": 20}, closes, "CC1", 50, Decimal("110"))
    assert round(pct, 2) == Decimal("52.63")
    assert concentration_after_buy(Decimal("9000"), {"CC2": 20}, {"CC2": 50}, "CC1", 1, 100) is None  # no close


def test_warning_only_above_the_limit():
    assert CONCENTRATION_WARNING_PCT == 40
    assert concentration_warning("NVDA", Decimal("52")) == \
        "Warning: NVDA would be 52.00 % of this portfolio (limit for the warning: 40 %)."
    assert concentration_warning("NVDA", Decimal("40")) is None        # exactly at the limit: no warning
    assert concentration_warning("NVDA", Decimal("39.9")) is None
    assert concentration_warning("NVDA", None) is None


# ---------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------
def test_buy_confirmed_saves(pf, monkeypatch, capsys):
    conn, pid, session = pf
    fake_input(monkeypatch, ["CC1", "10", "", "", "y", ""])           # ticker, shares, date, price, confirm, pause
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    assert "BUY 10 CC1 @ 100.00 on 2025-03-03 = 1,000.00. Cash after: 8,000.00." in out
    assert "Bought 10 CC1 @ 100.00 on 2025-03-03" in out
    assert trade_count(conn, pid) == 2


@pytest.mark.parametrize("answer", ["n", ""])                          # "n" and Enter (default No)
def test_buy_declined_saves_nothing(pf, monkeypatch, capsys, answer):
    conn, pid, session = pf
    fake_input(monkeypatch, ["CC1", "10", "", "", answer, ""])
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    assert "Cancelled, nothing saved." in out and "Bought" not in out
    assert trade_count(conn, pid) == 1


def test_warning_above_40_and_it_does_not_block(pf, monkeypatch, capsys):
    conn, pid, session = pf
    fake_input(monkeypatch, ["CC1", "50", "", "", "y", ""])           # CC1 would be 50 %
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    warning = "Warning: CC1 would be 50.00 % of this portfolio (limit for the warning: 40 %)."
    assert warning in out
    assert out.index(warning) < out.index("Bought 50 CC1")            # shown before, trade still saved
    assert trade_count(conn, pid) == 2


def test_no_warning_below_40(pf, monkeypatch, capsys):
    conn, pid, session = pf
    fake_input(monkeypatch, ["CC1", "30", "", "", "y", ""])           # CC1 would be 30 %
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    assert "Warning" not in out and "Bought 30 CC1" in out


def test_sell_has_the_confirm_but_no_warning(pf, monkeypatch, capsys):
    conn, pid, session = pf
    # CC2 is 10 % now; selling 10 leaves 5 %: either way no warning is computed for a SELL.
    # A SELL of all 20 at 1000 (the day's high) is also never warned about.
    fake_input(monkeypatch, ["CC2", "10", "", "", "n", ""])
    portfolio_menu.trade(session, "SELL")
    out = capsys.readouterr().out
    assert "SELL 10 CC2 @ 50.00 on 2025-03-03 = 500.00. Cash after: 9,500.00." in out
    assert "Cancelled, nothing saved." in out and trade_count(conn, pid) == 1
    fake_input(monkeypatch, ["CC2", "10", "", "", "y", ""])
    portfolio_menu.trade(session, "SELL")
    out = capsys.readouterr().out
    assert "Sold 10 CC2" in out and "Warning" not in out
    assert trade_count(conn, pid) == 2


def test_sell_never_warns_even_when_a_holding_is_concentrated(pf, monkeypatch, capsys):
    conn, pid, session = pf
    da.execute_trade(conn, pid, "CC1", "BUY", 80, D1)                 # CC1 8,000 of 10,000 = 80 %
    fake_input(monkeypatch, ["CC2", "1", "", "", "y", ""])            # selling CC2 makes CC1 even bigger
    portfolio_menu.trade(session, "SELL")
    out = capsys.readouterr().out
    assert "Warning" not in out and "Sold 1 CC2" in out


def test_the_database_still_decides_after_yes(pf, monkeypatch, capsys):
    conn, pid, session = pf
    fake_input(monkeypatch, ["CC1", "200", "", "", "y", ""])          # 20,000 > 9,000 cash
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    assert "Cash after: -11,000.00." in out                            # the preview just shows it
    assert "Bought" not in out and trade_count(conn, pid) == 1        # refused by trg_cash_never_negative
