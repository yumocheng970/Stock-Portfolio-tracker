"""Printing tables in the terminal (with the tabulate library)."""
from datetime import date, datetime
from decimal import Decimal

from tabulate import tabulate


def format_value(value):
    """How one cell is shown: money with 2 decimals and thousands separators,
    timestamps without seconds, None as an empty cell."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if isinstance(value, datetime):          # check datetime BEFORE date: a datetime is also a date
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def print_table(rows, columns):
    """Print rows (a list of dicts) as a table.

    columns: list of (key in the row dict, header text), in display order.
    """
    if not rows:
        print("  (none)")
        return
    headers = [header for _key, header in columns]
    body = [[format_value(row[key]) for key, _header in columns] for row in rows]
    # Numbers (int, Decimal) right-aligned, everything else left-aligned.
    # disable_numparse: tabulate must not re-read "100.50" as 100.5.
    align = ["right" if any(isinstance(row[key], (int, Decimal)) for row in rows) else "left"
             for key, _header in columns]
    print(tabulate(body, headers=headers, tablefmt="rounded_outline",
                   disable_numparse=True, colalign=align))
