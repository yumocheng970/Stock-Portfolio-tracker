"""Printing tables in the terminal (with the tabulate library)."""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from tabulate import tabulate


def round2(value):
    """Round a Decimal to 2 places, half UP (12.345 -> 12.35), like PostgreSQL's
    ROUND and the price loader. Python's own formatting rounds half to EVEN
    ("banker's rounding": f"{Decimal('12.345'):.2f}" gives 12.34)."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_value(value):
    """How one cell is shown: money with 2 decimals and thousands separators,
    timestamps without seconds, None as an empty cell."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{round2(value):,.2f}"
    if isinstance(value, datetime):          # check datetime BEFORE date: a datetime is also a date
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def format_pct(value, signed=True):
    """A percentage. signed=True (changes, returns): 12.345 -> "+12.35 %",
    -1 -> "-1.00 %", 0 -> "0.00 %". signed=False (a share of a whole, e.g. sector
    allocation): 54.3 -> "54.30 %". None (not computable) -> "n/a"."""
    if value is None:
        return "n/a"
    value = round2(value)
    if value == 0 or not signed:
        return f"{value:.2f} %"
    return f"{value:+.2f} %"          # "+" in the format spec: always show the sign


def print_table(rows, columns, percent=(), signed=True):
    """Print rows (a list of dicts) as a table.

    columns: list of (key in the row dict, header text), in display order.
    percent: keys of columns that hold percentages; shown as "+12.34 %"
             (signed=False: "12.34 %", for shares of a whole).
    """
    if not rows:
        print("  (none)")
        return
    headers = [header for _key, header in columns]
    body = [[format_pct(row[key], signed) if key in percent else format_value(row[key])
             for key, _header in columns] for row in rows]
    # Numbers (int, Decimal) and percentages right-aligned, everything else left-aligned.
    # disable_numparse: tabulate must not re-read "100.50" as 100.5.
    align = ["right" if key in percent
             or any(isinstance(row[key], (int, Decimal)) for row in rows) else "left"
             for key, _header in columns]
    print(tabulate(body, headers=headers, tablefmt="rounded_outline",
                   disable_numparse=True, colalign=align))
