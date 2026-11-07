"""Reports for the chosen portfolio (Portfolio home -> Reports):
monthly return vs the S&P 500, sector allocation, P/L per holding.

Each report shows exactly what its analysis function returns (db/analysis/);
this module only formats it, adds a summary line, and prints a clear sentence
instead of an empty table.
"""
from decimal import Decimal

from app import data_access as da
from app.display import format_pct, format_value, print_table
from app.errors import safe_call
from app.inputs import ask_month, pause
from app.menu import run_menu
from app.menus.common import ask_event_date, offer_chart

MONTHLY_COLUMNS = [
    ("month_text", "Month"), ("start_value", "Start value"), ("end_value", "End value"),
    ("net_flow", "Net flow"), ("portfolio_return_pct", "Portfolio"),
    ("spx_return_pct", "S&P 500"), ("excess_return_pct", "Excess"),
]
SECTOR_COLUMNS = [("sector_name", "Sector"), ("market_value", "Market value"), ("pct", "% of total")]
PL_COLUMNS = [
    ("ticker", "Ticker"), ("status", "Status"), ("shares_held", "Shares"), ("avg_cost", "Avg cost"),
    ("cost_basis", "Cost basis"), ("close", "Close"), ("market_value", "Market value"),
    ("unrealized_pl", "Unrealized"), ("realized_pl", "Realized"), ("total_pl", "Total P/L"),
]


def reports_menu(session):
    run_menu(lambda s: f"Reports: {s.portfolio_name}", [
        ("Monthly return vs S&P 500", monthly_report),
        ("Sector allocation",         sector_report),
        ("P/L per holding",           pl_report),
    ], session)


# ---------------------------------------------------------------------
# Pure helpers (no input, no database): easy to test
# ---------------------------------------------------------------------
def monthly_summary(rows):
    """The cumulative line: the LAST row's cumulative values and who did better."""
    last = rows[-1]
    portfolio, spx = last["cum_portfolio_pct"], last["cum_spx_pct"]
    if portfolio is None or spx is None:
        verdict = "a comparison is not possible (missing data)."
    elif portfolio > spx:
        verdict = f"the portfolio beat the S&P 500 by {portfolio - spx:.2f} points."
    elif portfolio < spx:
        verdict = f"the portfolio trailed the S&P 500 by {spx - portfolio:.2f} points."
    else:
        verdict = "the portfolio matched the S&P 500."
    return {"cum_portfolio": portfolio, "cum_spx": spx, "verdict": verdict}


def pl_totals(rows):
    """Sums of unrealized, realized and total P/L over all rows (Decimal, exact)."""
    return {key: sum((row[key] for row in rows), Decimal("0"))
            for key in ("unrealized_pl", "realized_pl", "total_pl")}


def default_to_month(session):
    """Enter at "to month" = the month of the latest price date (not the current
    month: prices stop before today, so the current month would end the report
    with a misleading 0.00 % row). None if no prices are loaded."""
    ok, prices = safe_call(da.price_date_range, session.conn)
    if not ok or prices["last"] is None:
        return None
    return prices["last"].replace(day=1)        # first day of that month


# ---------------------------------------------------------------------
# The three reports
# ---------------------------------------------------------------------
def monthly_report(session):
    print("\nMonthly return vs S&P 500 (Modified Dietz: deposits and withdrawals are not returns)")
    to_default = default_to_month(session)
    to_text = to_default.strftime("%Y-%m") if to_default else "current month"
    from_month = ask_month("From month", "first month")
    to_month = ask_month("To month", to_text) or to_default    # `or`: Enter (None) -> the default
    ok, rows = safe_call(da.monthly_returns, session.conn, session.portfolio_id, from_month, to_month)
    if not ok:
        pause()
        return
    if not rows:
        print("  No months to show for this range (check the portfolio's start date and the months).")
        pause()
        return
    shown = [{**row, "month_text": row["month"].strftime("%Y-%m")} for row in rows]
    print_table(shown, MONTHLY_COLUMNS,
                percent=("portfolio_return_pct", "spx_return_pct", "excess_return_pct"))
    summary = monthly_summary(shown)
    print(f"\n  Cumulative {shown[0]['month_text']} to {shown[-1]['month_text']}: "
          f"portfolio {format_pct(summary['cum_portfolio'])} vs S&P 500 "
          f"{format_pct(summary['cum_spx'])}: {summary['verdict']}")
    # the chart's CSV gets the SQL function's rows unchanged (not the display copy)
    offer_chart("save_returns_chart", rows, session.portfolio_id)
    pause()


def sector_report(session):
    print("\nSector allocation (market value per sector, cash included)")
    as_of = ask_event_date(session, "As of", session.portfolio_id)
    ok, rows = safe_call(da.sector_allocation, session.conn, session.portfolio_id, as_of)
    if not ok:
        pause()
        return
    if not rows:
        print(f"  Nothing to show as of {as_of}: the portfolio had not started yet.")
    elif all(row["sector_name"] == "Cash" for row in rows):
        cash = rows[0]
        print(f"  No stock holdings as of {as_of}: {format_pct(cash['pct'], signed=False)} cash "
              f"({format_value(cash['market_value'])}).")
    else:
        print_table(rows, SECTOR_COLUMNS, percent=("pct",), signed=False)   # shares: no "+"
    if rows:
        offer_chart("save_sector_chart", rows, session.portfolio_id, as_of)
    pause()


def pl_report(session):
    print("\nP/L per holding (average cost; open and closed positions)")
    as_of = ask_event_date(session, "As of", session.portfolio_id)
    ok, rows = safe_call(da.holding_pl, session.conn, session.portfolio_id, as_of)
    if not ok:
        pause()
        return
    if not rows:
        print(f"  No holdings yet as of {as_of}.")
        pause()
        return
    rows = [{**row, "status": "open" if row["shares_held"] > 0 else "closed"} for row in rows]
    print_table(rows, PL_COLUMNS)
    totals = pl_totals(rows)
    print(f"\n  Totals: unrealized {format_value(totals['unrealized_pl'])}, "
          f"realized {format_value(totals['realized_pl'])}, "
          f"total {format_value(totals['total_pl'])}")
    pause()
