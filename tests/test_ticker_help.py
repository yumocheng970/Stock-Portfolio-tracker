"""Ticker help at the prompts: "? = list" per context and company-name search
(test DB, rolled back).

Tech:     TK1 "Apple Test Inc."
Finance:  TK2 "Banking One Corp", TK3 "Banking Two Corp"
(none):   TK4 "Plain Sector-less Co"
Index:    ^GSPC "S&P 500"
Portfolio "Help" holds 10 TK1.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import data_access as da
from app.menus import admin_menu, portfolio_menu
from app.menus.common import ask_ticker
from app.session import Session
from app.ticker_help import entry, format_catalog

D1, D2 = date(2025, 3, 3), date(2025, 3, 4)


@pytest.fixture
def market(conn):
    assert conn.execute("SELECT count(*) FROM stock").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO sector (sector_name) VALUES ('Tech'), ('Finance')")
    for ticker, name, sector in (("TK1", "Apple Test Inc.", "Tech"), ("TK2", "Banking One Corp", "Finance"),
                                 ("TK3", "Banking Two Corp", "Finance"), ("TK4", "Plain Sector-less Co", None)):
        conn.execute("INSERT INTO stock (ticker, company_name, sector_id) VALUES "
                     "(%s, %s, (SELECT sector_id FROM sector WHERE sector_name = %s))", (ticker, name, sector))
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^GSPC', 'S&P 500', 'INDEX')")
    for ticker in ("TK1", "TK2", "TK3", "TK4", "^GSPC"):
        for day in (D1, D2):
            conn.execute("INSERT INTO daily_price VALUES (%s, %s, 10, 20, 5, 10, 0)", (ticker, day))
    investor = da.create_investor(conn, "Hal Help", "hal.help@example.com")
    pid = da.create_portfolio(conn, investor, "Help", Decimal("1000"), D1)
    da.execute_trade(conn, pid, "TK1", "BUY", 10, D1)
    session = Session(conn)
    session.choose_portfolio(pid, "Help")
    return session


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


# ---------------------------------------------------------------------
# The catalog per context
# ---------------------------------------------------------------------
def test_catalog_per_kind(market):
    conn, pid = market.conn, market.portfolio_id
    stocks = [r["ticker"] for r in da.ticker_catalog(conn, "stocks", pid)]
    assert stocks == ["TK2", "TK3", "TK4", "TK1"]                      # Finance, No sector, Tech
    every = {r["ticker"]: r["sector_name"] for r in da.ticker_catalog(conn, "all", pid)}
    assert every["^GSPC"] == "Indexes" and every["TK4"] == "No sector"
    held = da.ticker_catalog(conn, "held", pid)
    assert [(r["ticker"], r["shares_held"]) for r in held] == [("TK1", 10)]


def test_format_catalog_groups_by_sector_two_per_line(market):
    text = format_catalog(da.ticker_catalog(market.conn, "all"))
    lines = text.splitlines()
    assert lines[0] == "  Finance"
    assert "TK2" in lines[1] and "TK3" in lines[1]                      # two entries on one line
    assert "  Indexes" in lines and "  Tech" in lines
    assert entry({"ticker": "TK1", "company_name": "Apple Test Inc.", "shares_held": 10}).endswith("10 sh")
    long = entry({"ticker": "X", "company_name": "A" * 40})
    assert "…" in long and len(long) < 40                               # long names are cut


# ---------------------------------------------------------------------
# "?" at the ticker prompts
# ---------------------------------------------------------------------
def test_buy_list_has_stocks_but_no_index(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["?", "TK2"])
    assert ask_ticker(market) == "TK2"
    out = capsys.readouterr().out
    assert "Stocks:" in out and "Apple Test Inc." in out and "Banking One Corp" in out
    assert "^GSPC" not in out


def test_watchlist_and_price_history_list_includes_indexes(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["?", "^gspc"])
    assert ask_ticker(Session(market.conn), allow_index=True) == "^GSPC"
    out = capsys.readouterr().out
    assert "Stocks and indexes:" in out and "Indexes" in out and "^GSPC" in out


def test_sell_lists_only_held_tickers_and_reasks_others(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["?", "TK2", "TK1"])
    assert ask_ticker(market, held_only=True) == "TK1"
    out = capsys.readouterr().out
    list_part = out.split("You don't hold")[0]
    assert "What you hold (shares):" in list_part and "TK1" in list_part and "10 sh" in list_part
    assert "TK2" not in list_part and "Banking" not in list_part
    assert "You don't hold TK2 in this portfolio." in out


def test_sell_menu_uses_the_held_list(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["?", ""])                                  # list, then cancel
    portfolio_menu.trade(market, "SELL")
    out = capsys.readouterr().out
    assert "What you hold (shares):" in out and "Cancelled." in out


# ---------------------------------------------------------------------
# Company names instead of tickers
# ---------------------------------------------------------------------
def test_one_matching_company_is_suggested_and_confirmed(market, monkeypatch):
    fake_input(monkeypatch, ["apple", "y"])
    assert ask_ticker(market) == "TK1"


def test_declined_suggestion_asks_again(market, monkeypatch):
    fake_input(monkeypatch, ["APPLE", "n", ""])                         # no, then Enter = cancel
    assert ask_ticker(market) is None


def test_several_matching_companies_are_listed(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["banking", "TK3"])
    assert ask_ticker(market) == "TK3"
    out = capsys.readouterr().out
    assert "Several companies match 'banking':" in out
    assert "Banking One Corp" in out and "Banking Two Corp" in out


def test_name_search_in_sell_mode_only_finds_held(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["banking", ""])
    assert ask_ticker(market, held_only=True) is None
    assert "BANKING is not in the stock list" in capsys.readouterr().out


def test_search_treats_wildcards_literally(market):
    assert da.search_company(market.conn, "%", "all") == []
    assert [r["ticker"] for r in da.search_company(market.conn, "sector-less", "stocks")] == ["TK4"]


def test_rebalance_targets_list_and_company_name(market, monkeypatch, capsys):
    # date, "?", "apple 50" -> confirm TK1, then don't trade, pause
    fake_input(monkeypatch, ["", "?", "apple 50", "y", "n", ""])
    portfolio_menu.rebalance_portfolio(market)
    out = capsys.readouterr().out
    assert "Stocks:" in out and "^GSPC" not in out.split("Stocks:")[1].split("Plan on")[0]
    assert "Plan on" in out and "TK1" in out and "Nothing was traded." in out


def test_admin_finds_a_stock_by_company_name(market, monkeypatch, capsys):
    fake_input(monkeypatch, ["?", "banking two", "y"])
    stock = admin_menu.ask_existing_stock(Session(market.conn), "delete")
    assert stock["ticker"] == "TK3"
    assert "Stocks and indexes:" in capsys.readouterr().out


def test_columns_line_up_when_only_some_rows_hold_shares():
    # Buy in a portfolio with holdings: held tickers show "sh", the others don't
    rows = [{"ticker": t, "company_name": n, "sector_name": "S", "shares_held": h}
            for t, n, h in (("COST", "Costco Wholesale Corporation", None), ("KO", "The Coca-Cola Company", 34),
                            ("BA", "The Boeing Company", 12), ("CAT", "Caterpillar Inc.", None),
                            ("PG", "The Procter & Gamble Company", None), ("XOM", "Exxon Mobil", None))]
    lines = format_catalog(rows).splitlines()[1:]          # without the sector header
    second = [line.index(right) for line, right in zip(lines, ("KO", "CAT", "XOM"))]
    assert len(set(second)) == 1                           # the right column starts at the same place
    assert "34 sh" in lines[0] and "12 sh" in lines[1]


def test_no_share_column_when_nobody_holds_anything():
    rows = [{"ticker": "A", "company_name": "Alpha", "sector_name": "S", "shares_held": None},
            {"ticker": "B", "company_name": "Beta", "sector_name": "S", "shares_held": None}]
    line = format_catalog(rows).splitlines()[1]
    assert "sh" not in line and line.index("B ") == 4 + 6 + 1 + 24 + 3   # no extra padding
