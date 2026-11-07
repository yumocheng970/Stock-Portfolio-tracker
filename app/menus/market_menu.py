"""Market data menu (Main menu -> 2): top movers, list of stocks, price history.
(Adding stocks and refreshing prices are in Admin.)"""
from datetime import timedelta

from app import data_access as da
from app.display import print_table
from app.errors import safe_call
from app.inputs import ask_date, ask_int, pause
from app.menu import run_menu
from app.menus.common import ask_ticker, show_price_range

MOVER_COLUMNS = [
    ("rank", "Rank"), ("ticker", "Ticker"), ("company_name", "Company"),
    ("start_date", "From"), ("start_close", "Close"), ("end_date", "To"), ("end_close", "Close"),
    ("pct_change", "Change"),
]


STOCK_COLUMNS = [
    ("ticker", "Ticker"), ("company_name", "Company"), ("sector_name", "Sector"),
    ("exchange_name", "Exchange"), ("security_type", "Type"), ("close", "Latest close"),
    ("close_date", "Date"),
]
PRICE_COLUMNS = [
    ("price_date", "Date"), ("open", "Open"), ("high", "High"), ("low", "Low"),
    ("close", "Close"), ("volume", "Volume"),
]


def market_menu(session):
    run_menu("Market data", [
        ("Top movers",    top_movers),
        ("List stocks",   list_stocks),
        ("Price history", price_history),
    ], session)


def list_stocks(session):
    ok, sectors = safe_call(da.list_sectors, session.conn)
    if not ok:
        pause()
        return
    print("\nFilter by sector: " + ", ".join(f"{n}) {row['sector_name']}"
                                             for n, row in enumerate(sectors, start=1)))
    choice = ask_int("Sector number (Enter = all)", minimum=1, maximum=len(sectors), required=False)
    sector_id = sectors[choice - 1]["sector_id"] if choice else None
    ok, rows = safe_call(da.list_stocks, session.conn, sector_id)
    if ok:
        if rows:
            print_table(rows, STOCK_COLUMNS)
        else:
            print("  No stocks in this sector.")
    pause()


def price_history(session):
    print("\nPrice history (indexes such as ^GSPC included)")
    ticker = ask_ticker(session, allow_index=True)
    if ticker is None:
        return
    ok, window = safe_call(da.price_window, session.conn, ticker)
    if not ok:
        pause()
        return
    if window["end"] is None:
        print(f"  {ticker} has no prices yet.")
        pause()
        return
    print(f"  (Enter = the last 30 trading days: {window['start']} to {window['end']})")
    start = ask_date("Start date", default=window["start"])
    end = ask_date("End date", default=window["end"])
    if end < start:
        print(f"  The end date {end} is before the start date {start}.")
        pause()
        return
    ok, rows = safe_call(da.price_history, session.conn, ticker, start, end)
    if ok:
        if rows:
            print_table(rows, PRICE_COLUMNS)
        else:
            print(f"  No prices for {ticker} between {start} and {end} (weekends / holidays?).")
    pause()


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
