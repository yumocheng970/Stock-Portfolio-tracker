"""Downloading prices for the app (Admin -> Add a stock).

Reuses the ETL loader (etl/load_prices.py): its yfinance download and its
cleaning rules (round half up to cents, skip rows that would break a CHECK).
No SQL here: saving is done by data_access.add_stock_with_prices, in one
transaction, and only AFTER the download succeeded. So a failed or empty
download saves nothing.
"""
from datetime import date, timedelta

from etl import load_prices
from etl.load_prices import FIRST_DATE, clean_price_row


class DownloadError(Exception):
    """The price download failed or gave nothing usable. str(error) is a
    sentence for the user (errors.safe_call prints it)."""


def download_prices(ticker, start, end_inclusive):
    """The loader's yfinance download, looked up at CALL time, so tests can
    replace it (unittest.mock.patch("app.market_data.download_prices", ...))."""
    return load_prices.download_prices(ticker, start, end_inclusive)


def yesterday():
    """Prices are loaded up to yesterday (today's bar may still change)."""
    return date.today() - timedelta(days=1)


def fetch_history(ticker, start=FIRST_DATE, end=None):
    """Download and clean a ticker's daily prices.

    Returns (rows, skipped): rows are ready for daily_price, skipped is the
    number of rows dropped by the cleaning rules.
    Raises DownloadError if the download fails or nothing usable comes back.
    """
    end = end or yesterday()
    try:
        raw = download_prices(ticker, start, end)
    except Exception as error:          # network down, Yahoo changed, rate limit, ...
        raise DownloadError(f"Download failed for {ticker}: {error}. Nothing was saved.") from error
    if not raw:
        raise DownloadError(f"Yahoo returned no prices for {ticker} (unknown symbol?). Nothing was saved.")

    rows, skipped = [], 0
    for price_date, o, h, l, c, v in raw:
        if not (start <= price_date <= end):          # same safety window as the loader
            continue
        row, _reason = clean_price_row(ticker, price_date, o, h, l, c, v)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if not rows:
        raise DownloadError(f"None of the {len(raw)} price rows for {ticker} were usable. Nothing was saved.")
    return rows, skipped
