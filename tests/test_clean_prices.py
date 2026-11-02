"""Unit tests for the cleaning functions in etl/load_prices.py (no database, no network).

Run from the repo root:  python -m pytest
"""
from datetime import date
from decimal import Decimal

import pytest

from etl.load_prices import clean_price_row, read_tickers, to_cents

D = date(2024, 6, 7)


# --- to_cents -------------------------------------------------------------
def test_to_cents_rounds_to_two_decimals():
    assert to_cents(118.371002) == Decimal("118.37")
    assert to_cents(122.448997) == Decimal("122.45")


def test_to_cents_rounds_half_up_without_float_error():
    # Decimal(100.005) would be 100.00499999..., which rounds down to 100.00
    assert to_cents(100.005) == Decimal("100.01")


# --- clean_price_row: valid rows --------------------------------------------
def test_valid_row_is_rounded_and_volume_is_int():
    row, reason = clean_price_row("NVDA", D, 119.769997, 121.692001, 119.0, 120.888000, 412386000.0)
    assert reason is None
    assert row == ("NVDA", D, Decimal("119.77"), Decimal("121.69"), Decimal("119.00"),
                   Decimal("120.89"), 412386000)
    assert isinstance(row[6], int)


def test_flat_day_open_high_low_close_equal_is_valid():
    row, reason = clean_price_row("X", D, 10, 10, 10, 10, 0)
    assert reason is None
    assert row[2:6] == (Decimal("10.00"),) * 4


def test_zero_volume_is_valid():
    row, reason = clean_price_row("^GSPC", D, 10, 11, 9, 10, 0)
    assert reason is None


# --- clean_price_row: rows that must be skipped --------------------------------
def test_low_above_open_is_skipped():
    row, reason = clean_price_row("X", D, 100.00, 105.00, 101.00, 102.00, 1000)
    assert row is None
    assert "range broken" in reason


def test_close_above_high_is_skipped():
    row, reason = clean_price_row("X", D, 100, 105, 99, 106, 1000)
    assert row is None
    assert "range broken" in reason


def test_nan_value_is_skipped():
    row, reason = clean_price_row("X", D, 100, float("nan"), 99, 100, 1000)
    assert row is None
    assert reason == "missing value"


def test_none_volume_is_skipped():
    row, reason = clean_price_row("X", D, 100, 101, 99, 100, None)
    assert row is None
    assert reason == "missing value"


def test_low_that_rounds_to_zero_is_skipped():
    row, reason = clean_price_row("X", D, 0.004, 0.004, 0.004, 0.004, 1)
    assert row is None
    assert "not positive" in reason


def test_negative_volume_is_skipped():
    row, reason = clean_price_row("X", D, 100, 101, 99, 100, -5)
    assert row is None
    assert "negative volume" in reason


# --- read_tickers ------------------------------------------------------------------
def write_csv(tmp_path, body):
    path = tmp_path / "tickers.csv"
    path.write_text("ticker,company_name,sector,exchange\n" + body, encoding="utf-8")
    return path


def test_read_tickers_normalizes_and_detects_index(tmp_path):
    path = write_csv(tmp_path, " aapl ,Apple Inc.,Technology,NASDAQ\n^GSPC,S&P 500,,\n")
    tickers = read_tickers(path)
    assert tickers[0]["ticker"] == "AAPL"
    assert tickers[0]["security_type"] == "STOCK"
    assert tickers[1] == {"ticker": "^GSPC", "company_name": "S&P 500", "sector": None,
                          "exchange": None, "security_type": "INDEX"}


def test_read_tickers_rejects_index_with_sector(tmp_path):
    path = write_csv(tmp_path, "^GSPC,S&P 500,Technology,\n")
    with pytest.raises(ValueError, match="must have no sector"):
        read_tickers(path)


def test_read_tickers_rejects_stock_without_exchange(tmp_path):
    path = write_csv(tmp_path, "AAPL,Apple Inc.,Technology,\n")
    with pytest.raises(ValueError, match="needs a sector and an exchange"):
        read_tickers(path)


def test_read_tickers_rejects_duplicates(tmp_path):
    path = write_csv(tmp_path, "AAPL,Apple,Technology,NASDAQ\naapl,Apple,Technology,NASDAQ\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_tickers(path)


def test_project_csv_is_valid():
    """The real data/tickers.csv: 25 stocks in 8 sectors plus ^GSPC, NVDA included."""
    from etl.load_prices import TICKER_CSV
    tickers = read_tickers(TICKER_CSV)
    stocks = [t for t in tickers if t["security_type"] == "STOCK"]
    assert len(stocks) == 25
    assert len({t["sector"] for t in stocks}) == 8
    assert {"NVDA", "^GSPC"} <= {t["ticker"] for t in tickers}
