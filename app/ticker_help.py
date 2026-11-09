"""Formatting the "? = list" ticker list (pure Python: no database, no input)."""
from itertools import groupby

NAME_WIDTH = 24          # company names are cut to this width, so two entries fit on a line
SHARES_WIDTH = 10        # " 12345 sh": the share-count column (spaces when a row has none)


def entry(row, shares_column=None):
    """'AAPL   Apple Inc.' + the shares held ("    17 sh").
    shares_column: True = always add the share column (blank if this row has no
    shares), so entries line up in a list where only some rows hold shares;
    None = add it only if this row has shares (a single entry)."""
    name = row["company_name"]
    if len(name) > NAME_WIDTH:
        name = name[:NAME_WIDTH - 1] + "…"
    text = f"{row['ticker']:<6} {name:<{NAME_WIDTH}}"
    shares = row.get("shares_held")
    if shares:
        text += f" {shares:>6} sh"
    elif shares_column:
        text += " " * SHARES_WIDTH
    return text


def format_catalog(rows, columns=2):
    """The tickers grouped by sector, `columns` entries per line, compact enough for
    one screen. rows must be sorted by sector (data_access.ticker_catalog does that)."""
    # If ANY row shows a share count, every entry gets the (maybe blank) share
    # column, so the second column starts at the same place on every line
    shares_column = any(row.get("shares_held") for row in rows)
    lines = []
    for sector, group in groupby(rows, key=lambda row: row["sector_name"]):
        lines.append(f"  {sector}")
        entries = [entry(row, shares_column) for row in group]
        for start in range(0, len(entries), columns):
            lines.append("    " + "   ".join(entries[start:start + columns]))
    return "\n".join(lines)
