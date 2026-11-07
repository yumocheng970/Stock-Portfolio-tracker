"""CSV import of trades and cash transactions: reading and checking (pure Python:
no SQL, no input()). Saving is data_access.import_events, in ONE transaction.

File format (header required, any case):
    date,type,ticker,shares,price,amount
    2026-09-01,DEPOSIT,,,,5000
    2026-09-01,BUY,AAPL,10,,          <- empty price = that day's close
Trade rows (BUY / SELL): ticker and shares; price optional; no amount.
Cash rows (DEPOSIT / WITHDRAWAL): amount; no ticker, shares or price.

Only the SHAPE of each row is checked here (a real date, a known type, numbers
that are numbers). Whether the row is ALLOWED (enough cash, price within the
day's range, date order, ...) is decided by the database during the import.
"""
import csv
import re
from pathlib import Path
from typing import NamedTuple

from app.inputs import parse_amount, parse_date

COLUMNS = ("date", "type", "ticker", "shares", "price", "amount")
TRADE_TYPES = ("BUY", "SELL")
CASH_TYPES = ("DEPOSIT", "WITHDRAWAL")
MAX_ROWS = 1000          # every imported row replays the portfolio's history (rows^2 work)
TICKER_MAX = 10

# C:\Users\me\file.csv  or  C:/Users/me/file.csv
WINDOWS_PATH = re.compile(r"([A-Za-z]):[\\/](.*)")


class Event(NamedTuple):
    """One checked row of the file. `row` is its line number in the file
    (the header is line 1), so messages can point at it."""
    row: int
    date: object             # datetime.date
    kind: str                # BUY / SELL / DEPOSIT / WITHDRAWAL
    ticker: str | None
    shares: int | None
    price: object            # Decimal or None (= that day's close)
    amount: object           # Decimal or None

    @property
    def is_cash(self):
        return self.kind in CASH_TYPES


# ---------------------------------------------------------------------
# The path the user typed
# ---------------------------------------------------------------------
def to_linux_path(text):
    """Turn what the user typed or pasted into a path:
    - surrounding quotes removed ("Copy as path" in Windows adds them)
    - ~ expanded to the home folder
    - a Windows path C:\\Users\\me\\a.csv -> /mnt/c/Users/me/a.csv
      (WSL mounts Windows drive C: at /mnt/c by default)"""
    text = text.strip().strip('"').strip("'")
    match = WINDOWS_PATH.fullmatch(text)
    if match:
        drive, rest = match.groups()
        return Path("/mnt") / drive.lower() / rest.replace("\\", "/")
    return Path(text).expanduser()


# ---------------------------------------------------------------------
# Reading and checking
# ---------------------------------------------------------------------
def check_row(row_number, record):
    """Check one CSV record (a dict column -> text). Returns (event, problems):
    an Event and [] when the shape is fine, or None and a list of sentences."""
    problems = []
    def text(column):
        return (record.get(column) or "").strip()

    date = None
    try:
        date = parse_date(text("date"))
    except ValueError:
        problems.append(f"date '{text('date')}' is not a real date (YYYY-MM-DD)")

    kind = text("type").upper()
    if kind not in TRADE_TYPES + CASH_TYPES:
        problems.append(f"type '{text('type')}' is not BUY, SELL, DEPOSIT or WITHDRAWAL")
        return None, problems                       # the other checks depend on the type

    ticker = shares = price = amount = None
    if kind in TRADE_TYPES:
        ticker = text("ticker").upper()
        if not ticker:
            problems.append("a trade needs a ticker")
        elif len(ticker) > TICKER_MAX:
            problems.append(f"ticker '{ticker}' is longer than {TICKER_MAX} characters")
        try:
            shares = int(text("shares"))
        except ValueError:
            problems.append(f"shares '{text('shares')}' is not a whole number")
        if text("price"):
            try:
                price = parse_amount(text("price"))
            except ValueError:
                problems.append(f"price '{text('price')}' is not a number with at most 2 decimals")
        if text("amount"):
            problems.append("a trade has no amount (leave it empty; use shares and price)")
    else:
        try:
            amount = parse_amount(text("amount"))
        except ValueError:
            problems.append(f"amount '{text('amount')}' is not a number with at most 2 decimals")
        if text("ticker") or text("shares") or text("price"):
            problems.append("a cash row has no ticker, shares or price (only an amount)")

    if problems:
        return None, problems
    return Event(row_number, date, kind, ticker or None, shares, price, amount), []


def read_events(path):
    """Read and check the WHOLE file. Returns (events, errors):
    errors is a list of sentences; if it is not empty, nothing may be imported.
    Every row is checked, so the user can fix all mistakes at once."""
    path = Path(path)
    if not path.exists():
        return [], [f"File not found: {path}"]
    if not path.is_file():
        return [], [f"Not a file: {path}"]

    # utf-8-sig: also reads files saved by Excel, which start with an invisible
    # "byte order mark" (BOM) that would otherwise stick to the first column name
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, restkey="_extra")
        if reader.fieldnames is None:
            return [], ["The file is empty."]
        # Header names: trimmed, lower case ("Date " -> "date")
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
        unknown = [name for name in reader.fieldnames if name not in COLUMNS]
        missing = [name for name in ("date", "type") if name not in reader.fieldnames]
        if unknown or missing:
            header_errors = []
            if missing:
                header_errors.append(f"Missing column(s): {', '.join(missing)}")
            if unknown:
                header_errors.append(f"Unknown column(s): {', '.join(unknown)} "
                                     f"(allowed: {', '.join(COLUMNS)})")
            return [], header_errors

        events, errors, data_rows = [], [], 0
        for record in reader:                       # DictReader skips fully empty lines
            data_rows += 1
            if data_rows > MAX_ROWS:
                return [], [f"More than {MAX_ROWS} rows: please split the file."]
            row_number = reader.line_num            # the line in the file (header = 1)
            if record.get("_extra"):
                errors.append(f"Row {row_number}: more values than columns")
                continue
            event, problems = check_row(row_number, record)
            if event is None:
                errors.extend(f"Row {row_number}: {problem}" for problem in problems)
            else:
                events.append(event)

    if data_rows == 0:
        return [], ["The file has a header but no rows."]
    return events, errors


# ---------------------------------------------------------------------
# Order and preview
# ---------------------------------------------------------------------
def history_order(events):
    """The order the database replays a portfolio's history: date, cash before
    trades on the same day, then file order. sorted() is stable, and the row
    number in the key keeps the file order for equal dates and kinds."""
    return sorted(events, key=lambda e: (e.date, 0 if e.is_cash else 1, e.row))


def preview(events):
    """What the import will do, for the confirmation question."""
    ordered = history_order(events)
    return {
        "trades": sum(1 for e in events if not e.is_cash),
        "cash": sum(1 for e in events if e.is_cash),
        "first_date": ordered[0].date,
        "last_date": ordered[-1].date,
        "tickers": sorted({e.ticker for e in events if e.ticker}),     # a set: each ticker once
        "reordered": [e.row for e in ordered] != [e.row for e in events],
    }
