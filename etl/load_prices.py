"""ETL A: load sectors, exchanges, stocks and daily prices from yfinance.

Run from the repo root, in the conda env `spt`:
    python -m etl.load_prices

- Tickers come from data/tickers.csv (kept by hand).
- Prices: 2021-01-01 up to YESTERDAY (today's bar may still be changing),
  yfinance auto_adjust=False (split-adjusted, not dividend-adjusted),
  rounded to 2 decimals.
- Insert-only: each run downloads only dates after the last stored one,
  and ON CONFLICT DO NOTHING means an existing row is never changed.
- A row that would break a CHECK on daily_price is skipped and logged.
"""
import csv
import logging
import math
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yfinance as yf

from etl.db import connect

TICKER_CSV = Path(__file__).resolve().parent.parent / "data" / "tickers.csv"
FIRST_DATE = date(2021, 1, 1)
CENT = Decimal("0.01")

log = logging.getLogger("load_prices")


# ---------------------------------------------------------------------------
# Cleaning (pure functions: no database, no network, easy to unit-test)
# ---------------------------------------------------------------------------
def is_missing(value):
    """True for None or NaN (pandas uses NaN for a missing number)."""
    if value is None:
        return True
    try:
        return math.isnan(value)
    except TypeError:          # not a number at all
        return False


def to_cents(value):
    """Round a price to 2 decimals as an exact Decimal, half up (100.005 -> 100.01).

    str() first: Decimal(100.005) would show the float's binary error
    (100.00499999...), Decimal("100.005") is exactly what yfinance printed.
    """
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def clean_price_row(ticker, price_date, open_, high, low, close, volume):
    """Return (row, None) for a valid row, or (None, reason) for one to skip.

    The checks mirror the CHECK constraints on daily_price, applied AFTER
    rounding (the database sees the rounded values).
    """
    if any(is_missing(v) for v in (open_, high, low, close, volume)):
        return None, "missing value"

    o, h, l, c = (to_cents(v) for v in (open_, high, low, close))
    vol = int(volume)

    if l <= 0:
        return None, f"low {l} is not positive"
    if not (l <= o and l <= c and h >= o and h >= c):
        return None, f"range broken: open {o}, high {h}, low {l}, close {c}"
    if vol < 0:
        return None, f"negative volume {vol}"

    return (ticker, price_date, o, h, l, c, vol), None


def read_tickers(csv_path):
    """Read data/tickers.csv into a list of dicts and check it.

    A ticker starting with ^ is an INDEX and must have no sector/exchange;
    every other ticker is a STOCK and must have both.
    """
    tickers = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for line_no, rec in enumerate(csv.DictReader(f), start=2):   # line 1 = header
            ticker = rec["ticker"].strip().upper()
            sector = rec["sector"].strip() or None
            exchange = rec["exchange"].strip() or None
            security_type = "INDEX" if ticker.startswith("^") else "STOCK"

            if ticker in seen:
                raise ValueError(f"{csv_path}:{line_no}: duplicate ticker {ticker}")
            if security_type == "INDEX" and (sector or exchange):
                raise ValueError(f"{csv_path}:{line_no}: index {ticker} must have no sector/exchange")
            if security_type == "STOCK" and not (sector and exchange):
                raise ValueError(f"{csv_path}:{line_no}: stock {ticker} needs a sector and an exchange")

            seen.add(ticker)
            tickers.append({
                "ticker": ticker,
                "company_name": rec["company_name"].strip(),
                "sector": sector,
                "exchange": exchange,
                "security_type": security_type,
            })
    return tickers


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def insert_reference_data(conn, tickers):
    """Insert missing sectors, exchanges and stocks (insert-only)."""
    sectors = sorted({t["sector"] for t in tickers if t["sector"]})
    exchanges = sorted({t["exchange"] for t in tickers if t["exchange"]})

    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sector (sector_name) VALUES (%s) ON CONFLICT (sector_name) DO NOTHING",
            [(s,) for s in sectors],
        )
        cur.executemany(
            "INSERT INTO exchange (exchange_name) VALUES (%s) ON CONFLICT (exchange_name) DO NOTHING",
            [(e,) for e in exchanges],
        )
        # The subqueries turn names into ids; a NULL name gives a NULL id (the index)
        cur.executemany(
            """
            INSERT INTO stock (ticker, company_name, security_type, sector_id, exchange_id)
            VALUES (%s, %s, %s,
                    (SELECT sector_id   FROM sector   WHERE sector_name   = %s),
                    (SELECT exchange_id FROM exchange WHERE exchange_name = %s))
            ON CONFLICT (ticker) DO NOTHING
            """,
            [(t["ticker"], t["company_name"], t["security_type"], t["sector"], t["exchange"])
             for t in tickers],
        )


def last_stored_date(conn, ticker):
    """Latest price_date already in daily_price for this ticker, or None."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(price_date) FROM daily_price WHERE ticker = %s", (ticker,))
        return cur.fetchone()[0]


def insert_prices(conn, rows):
    """Insert cleaned rows; existing (ticker, date) rows are left alone.

    Returns the number of rows actually inserted.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO daily_price (ticker, price_date, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, price_date) DO NOTHING
            """,
            rows,
        )
        return cur.rowcount   # psycopg 3: summed over all rows of executemany


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------
def download_prices(ticker, start, end_inclusive):
    """Daily bars from yfinance as a list of (date, open, high, low, close, volume)."""
    df = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end_inclusive + timedelta(days=1)).isoformat(),   # yfinance's end is exclusive
        auto_adjust=False,
        actions=False,
    )
    return [
        (ts.date(), r["Open"], r["High"], r["Low"], r["Close"], r["Volume"])
        for ts, r in df.iterrows()
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    tickers = read_tickers(TICKER_CSV)
    yesterday = date.today() - timedelta(days=1)

    inserted_total = 0
    skipped_total = 0
    up_to_date = 0
    failed = []

    with connect() as conn:
        log.info("Connected to database %s", conn.info.dbname)
        insert_reference_data(conn, tickers)

        for t in tickers:
            symbol = t["ticker"]
            last = last_stored_date(conn, symbol)
            start = last + timedelta(days=1) if last else FIRST_DATE
            if start > yesterday:
                up_to_date += 1
                log.info("%-6s already up to date (last %s)", symbol, last)
                continue

            try:
                raw = download_prices(symbol, start, yesterday)
            except Exception as e:    # network error, Yahoo change, rate limit ...
                log.error("%-6s download failed: %s", symbol, e)
                failed.append(symbol)
                continue

            if not raw and last is None:
                log.error("%-6s no data returned from yfinance", symbol)
                failed.append(symbol)
                continue

            rows = []
            skipped = 0
            for price_date, o, h, l, c, v in raw:
                if not (start <= price_date <= yesterday):   # safety: stay inside the window
                    continue
                row, reason = clean_price_row(symbol, price_date, o, h, l, c, v)
                if row is None:
                    log.warning("%-6s skip %s: %s", symbol, price_date, reason)
                    skipped += 1
                else:
                    rows.append(row)

            inserted = insert_prices(conn, rows) if rows else 0
            inserted_total += inserted
            skipped_total += skipped
            log.info("%-6s %5d inserted, %d skipped (%s .. %s)",
                     symbol, inserted, skipped, start, yesterday)

        # Every ticker in the CSV should now have price rows
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(DISTINCT ticker) FROM daily_price WHERE ticker = ANY(%s)",
                ([t["ticker"] for t in tickers],),
            )
            with_prices = cur.fetchone()[0]

    print()
    print("=== Summary ===")
    print(f"Tickers in CSV:        {len(tickers)}")
    print(f"Tickers with prices:   {with_prices}")
    print(f"Already up to date:    {up_to_date}")
    print(f"Rows inserted:         {inserted_total}")
    print(f"Rows skipped:          {skipped_total}")
    print(f"Failed tickers:        {', '.join(failed) if failed else 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
