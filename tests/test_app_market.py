"""App 6, market data: list stocks, price history (test DB, rolled back)."""
from datetime import date, timedelta

import pytest

from app import data_access as da
from app.menus import market_menu
from app.session import Session

FIRST = date(2025, 1, 1)


@pytest.fixture
def market(conn):
    assert conn.execute("SELECT count(*) FROM stock").fetchone()[0] == 0, "run `make test` first"
    # 40 consecutive days of prices for MK1 (Tech), 1 day for MK2 (Energy)
    da.add_stock_with_prices(conn, "MK1", "Market One", "Tech", "NYSE",
                             [("MK1", FIRST + timedelta(days=i), 10 + i, 11 + i, 9 + i, 10 + i, 100)
                              for i in range(40)])
    da.add_stock_with_prices(conn, "MK2", "Market Two", "Energy", "NYSE",
                             [("MK2", FIRST, 5, 6, 4, 5, 100)])
    return conn


def test_list_stocks_with_latest_close_and_sector_filter(market):
    rows = {row["ticker"]: row for row in da.list_stocks(market)}
    assert (rows["MK1"]["close"], rows["MK1"]["close_date"]) == (49, FIRST + timedelta(days=39))
    assert (rows["MK2"]["sector_name"], rows["MK2"]["exchange_name"]) == ("Energy", "NYSE")
    tech = [s["sector_id"] for s in da.list_sectors(market) if s["sector_name"] == "Tech"][0]
    assert [row["ticker"] for row in da.list_stocks(market, tech)] == ["MK1"]


def test_price_window_is_the_last_30_trading_days(market):
    window = da.price_window(market, "mk1")
    assert window == {"start": FIRST + timedelta(days=10), "end": FIRST + timedelta(days=39)}
    assert da.price_window(market, "MK2") == {"start": FIRST, "end": FIRST}    # fewer than 30 days
    rows = da.price_history(market, "MK1", window["start"], window["end"])
    assert len(rows) == 30 and rows[0]["price_date"] == window["start"]       # oldest first


def test_price_history_menu_defaults_and_end_before_start(market, monkeypatch, capsys):
    answers = iter(["MK1", "", "", "",                     # ticker, Enter, Enter, pause
                    "MK1", "2025-02-01", "2025-01-15", ""])  # end before start
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    market_menu.price_history(Session(market))
    out = capsys.readouterr().out
    assert "last 30 trading days: 2025-01-11 to 2025-02-09" in out
    assert "2025-02-09" in out and "2025-01-10" not in out.split("trading days")[1]
    market_menu.price_history(Session(market))
    assert "The end date 2025-01-15 is before the start date 2025-02-01." in capsys.readouterr().out
