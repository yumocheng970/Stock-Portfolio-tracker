"""PNG charts (matplotlib) and the CSV data behind each chart.

Each save_* function takes the rows a report already showed (from the SQL
function, unchanged), writes <name>.png and <name>.csv into charts/ (or
`out_dir`) and returns (png_path, csv_path), or None when there is nothing to
draw. No SQL and no input() here; the menus call these functions.

matplotlib runs with the non-interactive "Agg" backend: it only draws into
image files and can never open a window (safe in tests, SSH, WSL).
"""
import csv
import os
import platform
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                    # must come BEFORE importing pyplot
import matplotlib.pyplot as plt          # noqa: E402  (import after use() on purpose)

from app.display import format_pct       # noqa: E402

# charts/ in the repo root (git-ignored)
CHART_DIR = Path(__file__).resolve().parent.parent / "charts"


# ---------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------
def _out_dir(out_dir):
    """The folder to write into: `out_dir`, or CHART_DIR looked up at CALL time
    (so tests can point it at a temporary folder). Created if missing."""
    folder = Path(out_dir) if out_dir is not None else CHART_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_csv(rows, path):
    """Write the rows (list of dicts) as CSV: one column per key, None -> empty."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _save(fig, rows, folder, name):
    """Save the figure as <name>.png, the rows as <name>.csv; close the figure."""
    png, csv_path = folder / f"{name}.png", folder / f"{name}.csv"
    fig.savefig(png, dpi=120, bbox_inches="tight")
    plt.close(fig)                       # free the memory; nothing stays open
    write_csv(rows, csv_path)
    return png, csv_path


# ---------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------
def index_level(cum_pct):
    """Cumulative return in % -> level of a line that starts at 100:
    +18.24 % -> 118.24, -1.00 % -> 99.00."""
    return 100 * (1 + Decimal(cum_pct) / 100)


def save_returns_chart(rows, portfolio_id, out_dir=None):
    """Portfolio vs S&P 500, both indexed to 100 at the start (fn_monthly_returns rows)."""
    # Months whose cumulative return can't be computed (None) are left out of the
    # LINES only; the CSV keeps every row exactly as the SQL function returned it.
    plotted = [r for r in rows if r["cum_portfolio_pct"] is not None and r["cum_spx_pct"] is not None]
    if not plotted:
        return None
    # x: the start of the first period, then each month's end; y: 100, then the index levels
    x = [plotted[0]["period_start"]] + [r["period_end"] for r in plotted]
    portfolio = [100] + [index_level(r["cum_portfolio_pct"]) for r in plotted]
    spx = [100] + [index_level(r["cum_spx_pct"]) for r in plotted]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(x, portfolio, label=f"Portfolio {portfolio_id}", linewidth=2)
    ax.plot(x, spx, label="S&P 500", linewidth=2, linestyle="--")
    ax.axhline(100, color="grey", linewidth=0.8)                     # the starting level
    first, last = plotted[0]["month"].strftime("%Y-%m"), plotted[-1]["month"].strftime("%Y-%m")
    ax.set_title(f"Portfolio {portfolio_id} vs S&P 500, {first} to {last}\n"
                 f"portfolio {format_pct(plotted[-1]['cum_portfolio_pct'])}, "
                 f"S&P 500 {format_pct(plotted[-1]['cum_spx_pct'])} (deposits/withdrawals excluded)")
    ax.set_ylabel("Value (start = 100)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()                                              # slanted date labels
    name = f"portfolio-{portfolio_id}_returns-vs-sp500_{rows[-1]['period_end']}"
    return _save(fig, rows, _out_dir(out_dir), name)


def save_sector_chart(rows, portfolio_id, as_of, out_dir=None):
    """Horizontal bars: % of the portfolio's total value per sector, cash included."""
    if not rows:
        return None
    labels = [r["sector_name"] for r in rows]
    values = [float(r["pct"] or 0) for r in rows]                     # matplotlib wants numbers
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(rows) + 1.5))
    bars = ax.barh(labels, values, color=["grey" if l == "Cash" else "tab:blue" for l in labels])
    ax.bar_label(bars, labels=[format_pct(r["pct"], signed=False) for r in rows], padding=3)
    ax.invert_yaxis()                                                 # first row at the top
    ax.set_xlabel("% of total value")
    ax.set_xlim(0, max(values) * 1.15 or 1)                          # room for the labels
    ax.set_title(f"Portfolio {portfolio_id}: sector allocation as of {as_of}")
    name = f"portfolio-{portfolio_id}_sector-allocation_{as_of}"
    return _save(fig, rows, _out_dir(out_dir), name)


def save_movers_chart(rows, start, end, out_dir=None):
    """Horizontal bars: % change of the top gainers (green) and losers (red)."""
    if not rows:
        return None
    # Sorted copy for the bars only (biggest gain on top); the CSV keeps the SQL order
    bars_rows = sorted(rows, key=lambda r: r["pct_change"], reverse=True)
    labels = [r["ticker"] for r in bars_rows]
    values = [float(r["pct_change"]) for r in bars_rows]
    fig, ax = plt.subplots(figsize=(9, 0.5 * len(rows) + 1.5))
    bars = ax.barh(labels, values, color=["tab:green" if v > 0 else "tab:red" for v in values])
    ax.bar_label(bars, labels=[format_pct(r["pct_change"]) for r in bars_rows], padding=3)
    ax.invert_yaxis()
    ax.axvline(0, color="grey", linewidth=0.8)
    # 30 % extra room on each side, so the "+20.19 %" / "-31.36 %" labels fit inside the plot
    ax.set_xlim(min(min(values), 0) * 1.3, max(max(values), 0) * 1.3 or 1)
    ax.set_xlabel("% change")
    ax.set_title(f"Top movers, {start} to {end}")
    name = f"top-movers_{start}_to_{end}"
    return _save(fig, rows, _out_dir(out_dir), name)


# ---------------------------------------------------------------------
# Opening a saved chart: Windows, macOS, WSL (plain Linux: not offered)
# ---------------------------------------------------------------------
def is_wsl():
    """True when Python runs inside WSL (Linux on Windows)."""
    return "microsoft" in platform.uname().release.lower() or "WSL_DISTRO_NAME" in os.environ


def open_in_windows(path):
    """Open the file with its Windows program. wslpath turns /home/... into
    \\\\wsl.localhost\\...; explorer.exe opens it like a double-click."""
    windows_path = subprocess.run(["wslpath", "-w", str(path)], capture_output=True,
                                  text=True, check=True).stdout.strip()
    subprocess.run(["explorer.exe", windows_path], check=False)     # explorer.exe exits with 1 even on success


def can_open_charts():
    """True where the app knows how to open a PNG with the system's viewer."""
    return is_wsl() or sys.platform in ("win32", "darwin")


def open_chart(path):
    """Open the PNG with the system's default program:
    WSL -> explorer.exe (via open_in_windows), native Windows -> os.startfile
    (like a double-click), macOS -> the `open` command."""
    if is_wsl():
        open_in_windows(path)
    elif sys.platform == "win32":
        os.startfile(str(path))                  # exists only on Windows
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
