"""Market data menu (Main menu -> 2): top movers for now; price history and
price refresh come in App 6."""
from datetime import timedelta

from app import data_access as da
from app.display import print_table
from app.errors import safe_call
from app.inputs import ask_date, pause
from app.menu import run_menu
from app.menus.common import show_price_range

MOVER_COLUMNS = [
    ("rank", "Rank"), ("ticker", "Ticker"), ("company_name", "Company"),
    ("start_date", "From"), ("start_close", "Close"), ("end_date", "To"), ("end_close", "Close"),
    ("pct_change", "Change"),
]


def market_menu(session):
    run_menu("Market data", [
        ("Top movers", top_movers),
    ], session)


def top_movers(session):
    print("\nTop movers: % change from the first close on/after the start date "
          "to the last close on/before the end date (stocks only)")
    show_price_range(session)
    ok, latest = safe_call(da.default_event_date, session.conn)   # no portfolio: latest price date
    if not ok:
        pause()
        return
    end_default = latest
    # timedelta(days=30): "30 days"; date - timedelta gives the date 30 days earlier
    start_default = latest - timedelta(days=30) if latest else None
    start = ask_date("Start date", default=start_default, no_default_reason="no prices are loaded yet")
    end = ask_date("End date", default=end_default, no_default_reason="no prices are loaded yet")
    if end < start:
        # Shape of the request, checked here; fn_top_movers would just return nothing
        print(f"  The end date {end} is before the start date {start}: nothing to compare.")
        pause()
        return
    ok, rows = safe_call(da.top_movers, session.conn, start, end)
    if not ok:
        pause()
        return
    for direction, title in (("GAINER", "Gainers"), ("LOSER", "Losers")):
        side = [row for row in rows if row["direction"] == direction]
        print(f"\n{title}")
        if side:
            print_table(side, MOVER_COLUMNS, percent=("pct_change",))
        else:
            print(f"  No {title.lower()} between {start} and {end}.")
    print("\n  Tied stocks share a rank, and the next rank is skipped (1, 1, 3).")
    pause()
