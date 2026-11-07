"""Trade history of the chosen portfolio: list, edit, delete, audit log,
restore a deleted trade.

Edits, deletes and restores go to the database, which replays the whole
history (cash and shares must never go below zero) and may refuse; the
refusal is shown with the database's DETAIL. Nothing is checked here.
"""
from app import data_access as da
from app.display import print_table
from app.errors import safe_call
from app.inputs import ask_decimal, ask_int, ask_text, confirm_typed, pause
from app.menu import run_menu

TICKER_MAX = 10

TRADE_COLUMNS = [
    ("trade_id", "ID"), ("trade_date", "Date"), ("trade_type", "Type"), ("ticker", "Ticker"),
    ("shares", "Shares"), ("price", "Price"), ("amount", "Amount"),
]
AUDIT_COLUMNS = [
    ("audit_id", "Audit ID"), ("operation", "Operation"), ("changed_at", "Changed at"),
    ("trade_id", "Trade ID"), ("trade_date", "Date"), ("trade_type", "Type"), ("ticker", "Ticker"),
    ("shares", "Old shares"), ("price", "Old price"), ("status", "Status"),
]


def trade_history_menu(session):
    run_menu(lambda s: f"Trade history: {s.portfolio_name}", [
        ("List trades",             list_trades),
        ("Edit a trade",            edit_trade),
        ("Delete a trade",          delete_trade),
        ("Audit log",               show_audit_log),
        ("Restore a deleted trade", restore_trade),
    ], session)


def list_trades(session):
    ticker = ask_text("Ticker filter (Enter = all)", TICKER_MAX, required=False)
    ok, rows = safe_call(da.list_trades, session.conn, session.portfolio_id, ticker)
    if ok:
        print("\nTrades in history order (date, then trade ID)")
        print_table(rows, TRADE_COLUMNS)
    pause()


def choose_trade(session, action):
    """Ask for a trade ID of this portfolio and show it. Returns the trade, or None."""
    trade_id = ask_int(f"Trade ID to {action} (Enter = cancel)", minimum=1, required=False)
    if trade_id is None:
        return None
    ok, trade = safe_call(da.get_portfolio_trade, session.conn, session.portfolio_id, trade_id)
    if not ok:
        return None
    if trade is None:
        print(f"  This portfolio has no trade {trade_id}.")
        return None
    print_table([trade], TRADE_COLUMNS)
    return trade


def edit_trade(session):
    trade = choose_trade(session, "edit")
    if trade is None:
        pause()
        return
    print(f"  That day's range for {trade['ticker']}: low {trade['low']}, high {trade['high']}")
    print("  Only shares and price can change; the date, type and ticker are fixed.")
    shares = ask_int(f"New shares (Enter = keep {trade['shares']})", minimum=1, required=False)
    price = ask_decimal(f"New price (Enter = keep {trade['price']})", required=False)
    if shares is None and price is None:
        print("  Nothing changed.")
        pause()
        return
    ok, _ = safe_call(da.update_trade, session.conn, session.portfolio_id,
                      trade["trade_id"], shares, price)
    if ok:
        ok, new = safe_call(da.get_portfolio_trade, session.conn, session.portfolio_id,
                            trade["trade_id"])
        if ok:
            print("\n  Changed (the old values are in the audit log):")
            print_table([new], TRADE_COLUMNS)
    pause()


def delete_trade(session):
    trade = choose_trade(session, "delete")
    if trade is None:
        pause()
        return
    print("  The trade will be copied to the audit log; it can be restored later.")
    if not confirm_typed(str(trade["trade_id"]), "the trade ID"):
        pause()
        return
    ok, _ = safe_call(da.delete_trade, session.conn, session.portfolio_id, trade["trade_id"])
    if ok:
        print(f"  Deleted trade {trade['trade_id']}.")
    pause()


def show_audit_log(session):
    ok, rows = safe_call(da.audit_log, session.conn, session.portfolio_id)
    if ok:
        print("\nAudit log, newest first (old values of changed or deleted trades)")
        print_table(rows, AUDIT_COLUMNS)
    pause()


def restore_trade(session):
    ok, deletes = safe_call(da.audit_log, session.conn, session.portfolio_id, only_deletes=True)
    if not ok:
        pause()
        return
    if not deletes:
        print("\n  No deleted trades in this portfolio.")
        pause()
        return
    print("\nDeleted trades (status 'restorable' can be put back)")
    print_table(deletes, AUDIT_COLUMNS)
    audit_id = ask_int("Audit ID to restore (Enter = cancel)", minimum=1, required=False)
    if audit_id is None:
        return
    ok, trade = safe_call(da.restore_trade, session.conn, session.portfolio_id, audit_id)
    if ok:
        print("\n  Restored, with its original trade ID, date, shares and price:")
        print_table([trade], TRADE_COLUMNS)
    pause()
