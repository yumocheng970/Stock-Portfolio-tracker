"""App 6, admin: add / rename / delete stocks, refresh prices (test DB, rolled back).

NEVER the network: every download is replaced with unittest.mock, and the
autouse fixture `no_network` (conftest.py) makes a forgotten mock fail.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import psycopg
import pytest

from app import data_access as da
from app import market_data
from app.errors import MESSAGES, friendly_message, safe_call
from app.market_data import DownloadError, fetch_history
from app.menus import admin_menu
from app.session import Session
from etl.load_prices import FIRST_DATE, refresh_tickers

D1, D2, D3, D4, D5 = (date(2025, 3, day) for day in (3, 4, 5, 6, 7))


def raw(day, close, low=None):
    """One raw row as yfinance gives it: (date, open, high, low, close, volume), floats."""
    low = close - 1 if low is None else low
    return (day, close, close + 1, low, close, 1000)


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def refused(func, *args):
    with pytest.raises(psycopg.Error) as caught:
        func(*args)
    return friendly_message(caught.value)


@pytest.fixture
def base(conn):
    """Sector Tech, exchange NASDAQ; stock OLD1 (prices D1..D3) held in a portfolio
    with one trade and on a watchlist; ^GSPC (index) with one price."""
    assert count(conn, "SELECT count(*) FROM stock") == 0, "run `make test` first"
    conn.execute("INSERT INTO sector (sector_name) VALUES ('Tech')")
    conn.execute("INSERT INTO exchange (exchange_name) VALUES ('NASDAQ')")
    da.add_stock_with_prices(conn, "OLD1", "Old One", "Tech", "NASDAQ",
                             [("OLD1", d, 100, 105, 95, 100, 10) for d in (D1, D2, D3)])
    da.add_stock_with_prices(conn, "^GSPC", "S&P 500", None, None, [("^GSPC", D1, 4000, 4010, 3990, 4000, 0)])
    investor = da.create_investor(conn, "Ada Admin", "ada.admin@example.com")
    portfolio = da.create_portfolio(conn, investor, "P", Decimal("10000"), D1)
    da.execute_trade(conn, portfolio, "OLD1", "BUY", 5, D1)
    watchlist = da.create_watchlist(conn, investor, "W")
    da.add_watchlist_item(conn, watchlist, "OLD1", Decimal("90"))
    return conn, portfolio


# ---------------------------------------------------------------------
# Add a stock: download first, then one transaction
# ---------------------------------------------------------------------
def test_add_stock_saves_stock_and_clean_prices(base):
    conn, _ = base
    fake = [raw(D1, 50.0), raw(D2, 51.0), raw(D3, 52.0, low=60.0)]   # D3: low above close -> skipped
    # mock.patch replaces market_data.download_prices for the duration of the `with` block
    with mock.patch("app.market_data.download_prices", return_value=fake) as download:
        rows, skipped = fetch_history("NEW1", end=D5)
    download.assert_called_once_with("NEW1", FIRST_DATE, D5)
    assert (len(rows), skipped) == (2, 1)
    assert rows[0] == ("NEW1", D1, Decimal("50.00"), Decimal("51.00"), Decimal("49.00"),
                       Decimal("50.00"), 1000)                        # cleaned: Decimal cents, int volume
    assert da.add_stock_with_prices(conn, "new1", "New One", "Health", "NYSE", rows) == 2
    stock = da.get_stock(conn, "NEW1")
    assert (stock["company_name"], stock["sector_name"], stock["exchange_name"],
            stock["security_type"]) == ("New One", "Health", "NYSE", "STOCK")   # new sector + exchange
    assert count(conn, "SELECT count(*) FROM daily_price WHERE ticker = 'NEW1'") == 2


@pytest.mark.parametrize("download_mock, expected", [
    (mock.Mock(side_effect=ConnectionError("no route to host")), "Download failed for NEW2: no route to host"),
    (mock.Mock(return_value=[]), "Yahoo returned no prices for NEW2"),
    (mock.Mock(return_value=[raw(D1, 10.0, low=20.0)]), "None of the 1 price rows for NEW2 were usable"),
])
def test_failed_or_empty_download_saves_nothing(base, download_mock, expected):
    conn, _ = base
    with mock.patch("app.market_data.download_prices", download_mock):
        with pytest.raises(DownloadError) as caught:
            fetch_history("NEW2", end=D5)
    assert expected in str(caught.value) and "Nothing was saved." in str(caught.value)
    assert da.get_stock(conn, "NEW2") is None


def test_add_stock_menu_failed_download_says_nothing_saved(base, monkeypatch, capsys):
    conn, _ = base
    answers = iter(["NEW3", "New Three", "Brand New Sector", "1", ""])   # ticker, company, sector, exchange, pause
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    with mock.patch("app.market_data.download_prices", side_effect=TimeoutError("timed out")):
        admin_menu.add_stock(Session(conn))
    out = capsys.readouterr().out
    assert "Download failed for NEW3: timed out. Nothing was saved." in out
    assert da.get_stock(conn, "NEW3") is None
    # the new sector was only going to be created together with the stock
    assert count(conn, "SELECT count(*) FROM sector WHERE sector_name = 'Brand New Sector'") == 0


def test_add_stock_menu_success(base, monkeypatch, capsys):
    conn, _ = base
    answers = iter(["new4", "New Four", "1", "1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    with mock.patch("app.market_data.download_prices", return_value=[raw(D1, 20.0), raw(D2, 21.0)]):
        admin_menu.add_stock(Session(conn))
    assert "Added NEW4: 2 prices saved (2025-03-03 to 2025-03-04)" in capsys.readouterr().out


def test_duplicate_ticker_refused_and_prices_unchanged(base):
    conn, _ = base
    message = refused(da.add_stock_with_prices, conn, "OLD1", "Again", "Tech", "NASDAQ",
                      [("OLD1", D5, 1, 1, 1, 1, 1)])
    assert message == MESSAGES["stock_pkey"]
    assert count(conn, "SELECT count(*) FROM daily_price WHERE ticker = 'OLD1'") == 3
    ok, _ = safe_call(da.add_stock_with_prices, conn, "OLD1", "Again", "Tech", "NASDAQ", [])
    assert ok is False


# ---------------------------------------------------------------------
# Rename: ON UPDATE CASCADE + audit
# ---------------------------------------------------------------------
def test_rename_cascades_everywhere_and_audits_trades(base):
    conn, portfolio = base
    cash_before = count(conn, "SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s", portfolio)
    trade_before = conn.execute("SELECT trade_id, portfolio_id, trade_type, shares, price, trade_date "
                                "FROM trade WHERE ticker = 'OLD1'").fetchall()
    assert da.stock_usage(conn, "old1") == {"prices": 3, "trades": 1, "watchlist_items": 1}

    assert da.rename_ticker(conn, "OLD1", " new9 ") == "NEW9"

    assert da.stock_usage(conn, "OLD1") == {"prices": 0, "trades": 0, "watchlist_items": 0}
    assert da.stock_usage(conn, "NEW9") == {"prices": 3, "trades": 1, "watchlist_items": 1}
    # One UPDATE audit row per trade, with the OLD ticker and otherwise the same values
    audit = conn.execute("SELECT trade_id, portfolio_id, trade_type, shares, price, trade_date "
                         "FROM trade_audit WHERE operation = 'UPDATE' AND ticker = 'OLD1'").fetchall()
    assert audit == trade_before
    assert count(conn, "SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s", portfolio) == cash_before


def test_rename_refused_cases(base):
    conn, _ = base
    da.add_stock_with_prices(conn, "OTHER", "Other", "Tech", "NASDAQ", [("OTHER", D1, 1, 1, 1, 1, 1)])
    assert refused(da.rename_ticker, conn, "OLD1", "OTHER") == MESSAGES["stock_pkey"]
    assert refused(da.rename_ticker, conn, "OLD1", "BAD TKR") == MESSAGES["chk_stock_ticker_format"]
    assert refused(da.rename_ticker, conn, "OLD1", "TOOLONGTICKR") == "A value is too long."   # > VARCHAR(10)
    with pytest.raises(da.NotFoundError):
        da.rename_ticker(conn, "NOPE", "NOPE2")


# ---------------------------------------------------------------------
# Delete: the RESTRICT FK decides
# ---------------------------------------------------------------------
def test_delete_traded_stock_refused(base):
    conn, _ = base
    assert refused(da.delete_stock, conn, "OLD1") == MESSAGES["fk_trade_daily_price"]
    assert da.stock_usage(conn, "OLD1") == {"prices": 3, "trades": 1, "watchlist_items": 1}


def test_delete_untraded_stock_cascades(base):
    conn, _ = base
    da.add_stock_with_prices(conn, "GONE", "Gone", "Tech", "NASDAQ",
                             [("GONE", D1, 1, 1, 1, 1, 1), ("GONE", D2, 1, 1, 1, 1, 1)])
    watchlist = count(conn, "SELECT watchlist_id FROM watchlist WHERE watchlist_name = 'W'")
    da.add_watchlist_item(conn, watchlist, "GONE")
    assert da.stock_usage(conn, "GONE") == {"prices": 2, "trades": 0, "watchlist_items": 1}
    da.delete_stock(conn, "gone")
    assert da.get_stock(conn, "GONE") is None
    assert da.stock_usage(conn, "GONE") == {"prices": 0, "trades": 0, "watchlist_items": 0}


def test_benchmark_index_protected(base):
    conn, _ = base
    assert refused(da.delete_stock, conn, "^GSPC").startswith(MESSAGES["trg_stock_benchmark_protected"])
    assert refused(da.rename_ticker, conn, "^GSPC", "^SPX").startswith(MESSAGES["trg_stock_benchmark_protected"])
    da.update_stock(conn, "^GSPC", company_name="S&P 500 Index")         # allowed
    assert da.get_stock(conn, "^GSPC")["company_name"] == "S&P 500 Index"


def test_update_stock_keeps_unchanged_fields(base):
    conn, _ = base
    da.update_stock(conn, "OLD1", sector_name="Energy")                 # new sector, created on the fly
    stock = da.get_stock(conn, "OLD1")
    assert (stock["company_name"], stock["sector_name"], stock["exchange_name"]) == ("Old One", "Energy", "NASDAQ")
    with pytest.raises(da.NotFoundError):
        da.update_stock(conn, "NOPE", company_name="X")


# ---------------------------------------------------------------------
# Refresh: insert-only
# ---------------------------------------------------------------------
def test_refresh_is_insert_only(base):
    conn, _ = base                                                   # OLD1 stored up to D3
    fake = mock.Mock(return_value=[raw(D2, 999.0), raw(D3, 999.0), raw(D4, 101.0), raw(D5, 102.0)])
    summary = refresh_tickers(conn, ["OLD1"], D5, download=fake)
    fake.assert_called_once_with("OLD1", D4, D5)                     # starts the day after the last stored
    assert (summary["inserted"], summary["failed"]) == (2, [])
    assert count(conn, "SELECT close FROM daily_price WHERE ticker = 'OLD1' AND price_date = %s", D2) == 100

    fake.reset_mock()                                                # again, same answer from Yahoo
    summary = refresh_tickers(conn, ["OLD1"], D5, download=fake)
    fake.assert_not_called()                                         # already up to date: no download at all
    assert summary == {"inserted": 0, "skipped": 0, "up_to_date": 1, "failed": []}
    assert count(conn, "SELECT count(*) FROM daily_price WHERE ticker = 'OLD1'") == 5


def test_refresh_overlap_adds_no_duplicates(base):
    conn, _ = base
    # A download that (wrongly) returns old dates too: ON CONFLICT DO NOTHING keeps the stored rows
    fake = mock.Mock(return_value=[raw(D1, 1.0), raw(D4, 101.0)])
    refresh_tickers(conn, ["OLD1"], D4, download=fake)
    assert count(conn, "SELECT count(*) FROM daily_price WHERE ticker = 'OLD1'") == 4
    assert count(conn, "SELECT close FROM daily_price WHERE ticker = 'OLD1' AND price_date = %s", D1) == 100


def test_refresh_all_prices_covers_every_stock_and_reports_failures(base):
    conn, _ = base
    def fake(ticker, start, end):
        if ticker == "^GSPC":
            raise ConnectionError("down")
        return [raw(start, 100.0)]
    with mock.patch.object(market_data, "yesterday", return_value=D4):
        summary = da.refresh_all_prices(conn, download=fake)
    assert summary["failed"] == ["^GSPC"] and summary["inserted"] == 1    # OLD1: D4


def test_network_guard_blocks_a_real_download():
    from etl.load_prices import download_prices
    with pytest.raises(RuntimeError, match="network disabled in tests"):
        download_prices("AAPL", D1, D2)
