"""Watchlists of the chosen investor: list, create, choose -> Watchlist home
(items, add, edit target, remove, rename, delete), and the targets reached
across all of the investor's watchlists (analysis query 5).

Indexes such as ^GSPC may be watched (only trading them is blocked).
"""
from app import data_access as da
from app.display import print_table
from app.errors import safe_call
from app.inputs import CLEAR, ask_decimal, ask_int, ask_text, confirm_typed, pause
from app.menu import run_menu
from app.menus.common import ask_ticker

NAME_MAX = 100          # watchlist.watchlist_name VARCHAR(100)

WATCHLIST_COLUMNS = [
    ("watchlist_id", "ID"), ("watchlist_name", "Name"), ("items", "Items"),
    ("reached", "Targets reached"), ("created_date", "Created"),
]
ITEM_COLUMNS = [
    ("ticker", "Ticker"), ("company_name", "Company"), ("close", "Latest close"),
    ("close_date", "Close date"), ("target_price", "Target"), ("pct_vs_target", "% vs target"),
    ("reached_text", "Reached"),
]
REACHED_COLUMNS = [
    ("watchlist_name", "Watchlist"), ("ticker", "Ticker"), ("target_price", "Target"),
    ("latest_close", "Latest close"), ("close_date", "Close date"),
    ("pct_above_target", "% above target"),
]


def watchlists_menu(session):
    run_menu(lambda s: f"Watchlists of {s.investor_name}", [
        ("List my watchlists",                   list_watchlists),
        ("Create watchlist",                     create_watchlist),
        ("Choose watchlist",                     choose_watchlist),
        ("Targets reached (all my watchlists)",  targets_reached),
    ], session)


# ---------------------------------------------------------------------
# Watchlists menu items
# ---------------------------------------------------------------------
def list_watchlists(session):
    ok, rows = safe_call(da.list_watchlists, session.conn, session.investor_id)
    if ok:
        print_table(rows, WATCHLIST_COLUMNS)
    pause()


def create_watchlist(session):
    name = ask_text("Watchlist name", NAME_MAX)
    ok, watchlist_id = safe_call(da.create_watchlist, session.conn, session.investor_id, name)
    if ok:
        print(f"\n  Created watchlist {watchlist_id}: {name}")
        session.choose_watchlist(watchlist_id, name)
        watchlist_home(session)
    else:
        pause()


def choose_watchlist(session):
    ok, rows = safe_call(da.list_watchlists, session.conn, session.investor_id)
    if not ok:
        pause()
        return
    if not rows:
        print("\n  No watchlists yet: create one first.")
        pause()
        return
    print_table(rows, WATCHLIST_COLUMNS)
    watchlist_id = ask_int("Watchlist ID (Enter = cancel)", minimum=1, required=False)
    if watchlist_id is None:
        return
    chosen = [row for row in rows if row["watchlist_id"] == watchlist_id]
    if not chosen:
        print(f"\n  You have no watchlist with ID {watchlist_id}.")
        pause()
        return
    session.choose_watchlist(watchlist_id, chosen[0]["watchlist_name"])
    watchlist_home(session)


def targets_reached(session):
    ok, rows = safe_call(da.targets_reached, session.conn, session.investor_id)
    if ok:
        print("\nItems whose latest close is at or above the target, across all your watchlists")
        print_table(rows, REACHED_COLUMNS)
    pause()


# ---------------------------------------------------------------------
# Watchlist home
# ---------------------------------------------------------------------
def watchlist_home(session):
    run_menu(lambda s: f"Watchlist: {s.watchlist_name}", [
        ("List items",       list_items),
        ("Add item",         add_item),
        ("Edit target",      edit_target),
        ("Remove item",      remove_item),
        ("Rename watchlist", rename),
        ("Delete watchlist", delete),
    ], session)
    session.forget_watchlist()


def reached_text(reached):
    """True / False / None (no target) -> "yes" / "no" / ""."""
    if reached is None:
        return ""
    return "yes" if reached else "no"


def list_items(session):
    ok, rows = safe_call(da.list_watchlist_items, session.conn, session.watchlist_id)
    if ok:
        # {**row, "key": value} = a copy of the dict with one more key
        rows = [{**row, "reached_text": reached_text(row["reached"])} for row in rows]
        print_table(rows, ITEM_COLUMNS)
    pause()


def add_item(session):
    print("\nAdd a ticker (indexes like ^GSPC may be watched)")
    ticker = ask_ticker(session, allow_index=True)
    if ticker is None:
        print("  Cancelled.")
        return
    target = ask_decimal("Target price (Enter = none)", required=False)
    ok, added = safe_call(da.add_watchlist_item, session.conn, session.watchlist_id, ticker, target)
    if ok:
        print(f"  Added {added}" + (f" with target {target}." if target is not None else "."))
    pause()


def choose_item(session, action):
    """Show the items and ask for one of their tickers. Returns the item row or None."""
    ok, rows = safe_call(da.list_watchlist_items, session.conn, session.watchlist_id)
    if not ok:
        return None
    if not rows:
        print("\n  This watchlist is empty.")
        return None
    print_table([{**row, "reached_text": reached_text(row["reached"])} for row in rows], ITEM_COLUMNS)
    ticker = ask_text(f"Ticker to {action} (Enter = cancel)", 10, required=False)
    if ticker is None:
        return None
    chosen = [row for row in rows if row["ticker"] == ticker.upper()]
    if not chosen:
        print(f"  {ticker.upper()} is not on this watchlist.")
        return None
    return chosen[0]


def edit_target(session):
    item = choose_item(session, "edit")
    if item is None:
        pause()
        return
    current = item["target_price"] if item["target_price"] is not None else "none"
    print(f"  {item['ticker']}: target {current}, latest close {item['close']}")
    target = ask_decimal("New target (Enter = keep, 'none' = clear)", required=False, clear_word="none")
    if target is None:
        print("  Nothing changed.")
        pause()
        return
    new_value = None if target is CLEAR else target        # None = NULL in the database
    ok, _ = safe_call(da.set_item_target, session.conn, session.watchlist_id, item["ticker"], new_value)
    if ok:
        print(f"  {item['ticker']}: target " + ("cleared." if target is CLEAR else f"set to {target}."))
    pause()


def remove_item(session):
    item = choose_item(session, "remove")
    if item is None:
        pause()
        return
    ok, _ = safe_call(da.remove_watchlist_item, session.conn, session.watchlist_id, item["ticker"])
    if ok:
        print(f"  Removed {item['ticker']}.")
    pause()


def rename(session):
    name = ask_text("New name (Enter = keep)", NAME_MAX, required=False)
    if name is None:
        return
    ok, _ = safe_call(da.rename_watchlist, session.conn, session.investor_id, session.watchlist_id, name)
    if ok:
        session.choose_watchlist(session.watchlist_id, name)
        print("  Renamed.")
    pause()


def delete(session):
    ok, rows = safe_call(da.list_watchlists, session.conn, session.investor_id)
    if not ok:
        pause()
        return
    items = next((row["items"] for row in rows if row["watchlist_id"] == session.watchlist_id), 0)
    print(f"\n  Delete watchlist {session.watchlist_name}? This also removes its {items} item(s).")
    if not confirm_typed(session.watchlist_name, "the watchlist name"):
        pause()
        return
    ok, _ = safe_call(da.delete_watchlist, session.conn, session.investor_id, session.watchlist_id)
    if ok:
        print(f"  Deleted watchlist {session.watchlist_name}.")
        session.forget_watchlist()
        pause()
        return "back"
    pause()
