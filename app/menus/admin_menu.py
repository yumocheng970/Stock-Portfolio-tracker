"""Admin (Main menu -> 3): add a stock (downloads its price history), edit,
rename a ticker, delete, refresh all prices, list sectors and exchanges.

As everywhere: the database decides (FKs, CHECKs, the ^GSPC trigger); this
module shows hints and the database's answer.
"""
from app import data_access as da
from app import market_data
from app.display import print_table
from app.errors import safe_call
from app.inputs import ask_int, ask_text, confirm_typed, pause
from app.menu import run_menu
from app.menus.common import TICKER_MAX

COMPANY_MAX = 100       # stock.company_name VARCHAR(100)
NAME_MAX = 50           # sector_name / exchange_name VARCHAR(50)

SECTOR_COLUMNS = [("sector_id", "ID"), ("sector_name", "Sector"), ("stocks", "Stocks")]
EXCHANGE_COLUMNS = [("exchange_id", "ID"), ("exchange_name", "Exchange"), ("stocks", "Stocks")]


def admin_menu(session):
    run_menu("Admin", [
        ("Add a stock (downloads its prices)", add_stock),
        ("Edit a stock",                       edit_stock),
        ("Rename a ticker",                    rename_ticker),
        ("Delete a stock",                     delete_stock),
        ("Refresh all prices",                 refresh_prices),
        ("List sectors",                       list_sectors),
        ("List exchanges",                     list_exchanges),
    ], session)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def ask_name_from_list(session, what, list_function, name_key, required=True):
    """Show the existing sectors (or exchanges) as a numbered list. The user types
    a number, or a NEW name (it is created together with the stock), or Enter.
    Returns the chosen / new name, or None for Enter (required=False: "keep")."""
    ok, rows = safe_call(list_function, session.conn)
    names = [row[name_key] for row in rows] if ok else []
    print(f"  {what.capitalize()}s: " + ", ".join(f"{n}) {name}" for n, name in enumerate(names, start=1)))
    hint = "number or a new name" + ("" if required else ", Enter = keep")
    while True:
        answer = ask_text(f"{what.capitalize()} ({hint})", NAME_MAX, required=required)
        if answer is None:
            return None
        if answer.isdigit():                       # "3" -> the 3rd name in the list
            number = int(answer)
            if 1 <= number <= len(names):
                return names[number - 1]
            print(f"  Please type 1 to {len(names)}, or a new name.")
            continue
        if answer not in names:
            print(f"  New {what} '{answer}' will be created with the stock.")
        return answer


def ask_existing_stock(session, action):
    """Ask for a ticker that exists; returns the stock row, or None (Enter = cancel)."""
    while True:
        ticker = ask_text(f"Ticker to {action} (Enter = cancel)", TICKER_MAX, required=False)
        if ticker is None:
            return None
        ok, stock = safe_call(da.get_stock, session.conn, ticker)
        if not ok:
            return None
        if stock is None:
            print(f"  {ticker.upper()} is not in the stock list. Type another ticker, or Enter to cancel.")
            continue
        print(f"  {stock['ticker']}: {stock['company_name']} ({stock['security_type']}), "
              f"sector {stock['sector_name'] or '-'}, exchange {stock['exchange_name'] or '-'}")
        return stock


# ---------------------------------------------------------------------
# Menu items
# ---------------------------------------------------------------------
def add_stock(session):
    print("\nAdd a stock: its full price history is downloaded from Yahoo Finance first;")
    print("only if that works are the stock and its prices saved (all or nothing).")
    ticker = ask_text("Ticker (Enter = cancel)", TICKER_MAX, required=False)
    if ticker is None:
        return
    ticker = ticker.upper()
    ok, existing = safe_call(da.get_stock, session.conn, ticker)
    if ok and existing is not None:
        print(f"  {ticker} already exists ({existing['company_name']}).")      # hint; the PK decides
        pause()
        return
    company = ask_text("Company name", COMPANY_MAX)
    if ticker.startswith("^"):
        print("  A ticker starting with ^ is an INDEX: no sector or exchange.")
        sector = exchange = None
    else:
        sector = ask_name_from_list(session, "sector", da.list_sectors, "sector_name")
        exchange = ask_name_from_list(session, "exchange", da.list_exchanges, "exchange_name")

    print(f"\n  Downloading {ticker} from {market_data.FIRST_DATE} to {market_data.yesterday()} ...")
    ok, result = safe_call(market_data.fetch_history, ticker)
    if not ok:                                   # DownloadError: message already printed
        pause()
        return
    rows, skipped = result
    ok, inserted = safe_call(da.add_stock_with_prices, session.conn, ticker, company,
                             sector, exchange, rows)
    if ok:
        print(f"  Added {ticker}: {inserted} prices saved ({rows[0][1]} to {rows[-1][1]}), "
              f"{skipped} rows skipped by the cleaning rules.")
    else:
        print("  Nothing was saved.")
    pause()


def edit_stock(session):
    stock = ask_existing_stock(session, "edit")
    if stock is None:
        return
    company = ask_text("New company name (Enter = keep)", COMPANY_MAX, required=False)
    sector = exchange = None
    if stock["security_type"] == "STOCK":
        sector = ask_name_from_list(session, "sector", da.list_sectors, "sector_name", required=False)
        exchange = ask_name_from_list(session, "exchange", da.list_exchanges, "exchange_name", required=False)
    if company is None and sector is None and exchange is None:
        print("  Nothing changed.")
        pause()
        return
    ok, _ = safe_call(da.update_stock, session.conn, stock["ticker"], company, sector, exchange)
    if ok:
        ok, new = safe_call(da.get_stock, session.conn, stock["ticker"])
        if ok:
            print(f"  Saved: {new['ticker']}: {new['company_name']}, "
                  f"sector {new['sector_name'] or '-'}, exchange {new['exchange_name'] or '-'}")
    pause()


def rename_ticker(session):
    print("\nRename a ticker (e.g. FB -> META). The database's cascading foreign keys carry the")
    print("new ticker to its prices, trades and watchlist items; each trade is logged in the audit log.")
    stock = ask_existing_stock(session, "rename")
    if stock is None:
        return
    new = ask_text("New ticker", TICKER_MAX).upper()
    ok, usage = safe_call(da.stock_usage, session.conn, stock["ticker"])
    if not ok:
        pause()
        return
    print(f"  {stock['ticker']} -> {new}: {usage['prices']} prices, {usage['trades']} trades and "
          f"{usage['watchlist_items']} watchlist items will follow.")
    if not confirm_typed(new, "the new ticker"):
        pause()
        return
    ok, renamed = safe_call(da.rename_ticker, session.conn, stock["ticker"], new)
    if ok:
        print(f"  Renamed {stock['ticker']} to {renamed}.")
    pause()


def delete_stock(session):
    stock = ask_existing_stock(session, "delete")
    if stock is None:
        return
    ok, usage = safe_call(da.stock_usage, session.conn, stock["ticker"])
    if not ok:
        pause()
        return
    print(f"  Deleting {stock['ticker']} also removes {usage['prices']} prices and "
          f"{usage['watchlist_items']} watchlist items.")
    if usage["trades"]:
        print(f"  It has {usage['trades']} trades: the database will refuse (trades must be kept).")
    if not confirm_typed(stock["ticker"], "the ticker"):
        pause()
        return
    ok, _ = safe_call(da.delete_stock, session.conn, stock["ticker"])
    if ok:
        print(f"  Deleted {stock['ticker']}.")
    pause()


def refresh_prices(session):
    print("\nRefresh all prices: downloads from Yahoo Finance, for every stock, only the")
    print("days after its last stored price, up to yesterday. Existing prices never change.")
    ok, summary = safe_call(da.refresh_all_prices, session.conn)
    if ok:
        failed = ", ".join(summary["failed"]) or "none"
        print(f"\n  Inserted {summary['inserted']} prices, skipped {summary['skipped']} invalid rows, "
              f"{summary['up_to_date']} stocks already up to date, failed: {failed}.")
    pause()


def list_sectors(session):
    ok, rows = safe_call(da.list_sectors, session.conn)
    if ok:
        print_table(rows, SECTOR_COLUMNS)
    pause()


def list_exchanges(session):
    ok, rows = safe_call(da.list_exchanges, session.conn)
    if ok:
        print_table(rows, EXCHANGE_COLUMNS)
    pause()
