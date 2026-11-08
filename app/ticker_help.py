"""Formatting the "? = list" ticker list (pure Python: no database, no input)."""
from itertools import groupby

NAME_WIDTH = 24          # company names are cut to this width, so two entries fit on a line


def entry(row):
    """'AAPL   Apple Inc.' (+ the shares held, for the Sell list)."""
    name = row["company_name"]
    if len(name) > NAME_WIDTH:
        name = name[:NAME_WIDTH - 1] + "…"
    text = f"{row['ticker']:<6} {name:<{NAME_WIDTH}}"
    if row.get("shares_held"):
        text += f" {row['shares_held']:>6} sh"
    return text


def format_catalog(rows, columns=2):
    """The tickers grouped by sector, `columns` entries per line, compact enough for
    one screen. rows must be sorted by sector (data_access.ticker_catalog does that)."""
    lines = []
    for sector, group in groupby(rows, key=lambda row: row["sector_name"]):
        lines.append(f"  {sector}")
        entries = [entry(row) for row in group]
        for start in range(0, len(entries), columns):
            lines.append("    " + "   ".join(entries[start:start + columns]))
    return "\n".join(lines)
