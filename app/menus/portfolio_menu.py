"""Portfolios of the chosen investor: list, create, choose -> Portfolio home
(summary, buy, sell, deposit, withdraw, rename, delete).

Before a trade or cash transaction the app SHOWS hints (cash, shares held,
the latest allowed date, that day's prices). It never enforces them: the
database decides (execute_trade / record_cash_transaction + triggers), and
a refusal comes back as a friendly message with the database's DETAIL.
"""
from decimal import Decimal

from app import data_access as da
from app.display import format_value, print_table
from app.errors import safe_call
from app.inputs import ask_date, ask_decimal, ask_int, ask_text, confirm_typed, pause
from app.menu import run_menu
from app.menus.trade_history_menu import trade_history_menu

NAME_MAX = 100          # portfolio.portfolio_name VARCHAR(100)
TICKER_MAX = 10         # stock.ticker VARCHAR(10)

PORTFOLIO_COLUMNS = [
    ("portfolio_id", "ID"), ("portfolio_name", "Name"), ("start_date", "Start"),
    ("starting_cash", "Starting cash"), ("cash", "Cash"),
    ("market_value", "Market value"), ("total_value", "Total"),
]
HOLDING_COLUMNS = [
    ("ticker", "Ticker"), ("shares_held", "Shares"), ("avg_cost", "Avg cost"),
    ("cost_basis", "Cost basis"), ("close", "Close"), ("close_date", "Close date"),
    ("market_value", "Market value"), ("unrealized_pl", "Unrealized P/L"),
]


def portfolios_menu(session):
    run_menu(lambda s: f"Portfolios of {s.investor_name}", [
        ("List my portfolios", list_portfolios),
        ("Create portfolio",   create_portfolio),
        ("Choose portfolio",   choose_portfolio),
    ], session)


# ---------------------------------------------------------------------
# Helpers for the date prompts
# ---------------------------------------------------------------------
def show_price_range(session):
    """Print the available price range, e.g. "prices: 2021-01-04 to 2026-10-30"."""
    ok, prices = safe_call(da.price_date_range, session.conn)
    if ok and prices["last"] is not None:
        print(f"  (prices: {prices['first']} to {prices['last']})")
    elif ok:
        print("  (no prices loaded yet)")


def ask_event_date(session, prompt, portfolio_id=None):
    """Ask for a date. Enter = the latest price date, or the portfolio's latest
    allowed date if that is later (see da.default_event_date)."""
    show_price_range(session)
    ok, default = safe_call(da.default_event_date, session.conn, portfolio_id)
    if not ok:
        return ask_date(prompt, no_default_reason="the default date could not be looked up")
    return ask_date(prompt, default=default, no_default_reason="no prices are loaded yet")


def ask_ticker(session, allow_index=False):
    """Ask for a ticker and show what we know about it. An unknown ticker (or,
    unless allow_index, an index) is asked again right away (a hint: the
    database still decides). Watchlists use allow_index=True: watching ^GSPC
    is fine, only trading it isn't.
    Returns the ticker in capitals, or None if the user pressed Enter (cancel)."""
    while True:
        ticker = ask_text("Ticker (Enter = cancel)", TICKER_MAX, required=False)
        if ticker is None:
            return None
        ticker = ticker.upper()
        ok, info = safe_call(da.ticker_context, session.conn, session.portfolio_id, ticker)
        if not ok:
            return ticker                 # no hint available; let the database decide
        if info["company_name"] is None:
            print(f"  {ticker} is not in the stock list. Type another ticker, or Enter to cancel.")
            continue
        if info["security_type"] == "INDEX" and not allow_index:
            print(f"  {ticker} is an index: it can be watched but not traded. "
                  "Type another ticker, or Enter to cancel.")
            continue
        if session.portfolio_id is None:          # watchlists: no holdings to show
            print(f"  {ticker}: {info['company_name']}, latest price {info['last_price_date']}")
        else:
            print(f"  {ticker}: {info['company_name']}, you hold {info['shares_held']} shares, "
                  f"latest price {info['last_price_date']}")
        return ticker


# ---------------------------------------------------------------------
# Portfolios menu items
# ---------------------------------------------------------------------
def list_portfolios(session):
    ok, rows = safe_call(da.list_portfolios, session.conn, session.investor_id)
    if ok:
        print_table(rows, PORTFOLIO_COLUMNS)
    pause()


def create_portfolio(session):
    print("\nNew portfolio")
    name = ask_text("Name", NAME_MAX)
    starting_cash = ask_decimal("Starting cash")
    start_date = ask_event_date(session, "Start date")
    ok, portfolio_id = safe_call(da.create_portfolio, session.conn, session.investor_id,
                                 name, starting_cash, start_date)
    if ok:
        print(f"\n  Created portfolio {portfolio_id}: {name}")
        session.choose_portfolio(portfolio_id, name)
        portfolio_home(session)
    else:
        pause()


def choose_portfolio(session):
    ok, rows = safe_call(da.list_portfolios, session.conn, session.investor_id)
    if not ok:
        pause()
        return
    if not rows:
        print("\n  No portfolios yet: create one first.")
        pause()
        return
    print_table(rows, PORTFOLIO_COLUMNS)
    portfolio_id = ask_int("Portfolio ID (Enter = cancel)", minimum=1, required=False)
    if portfolio_id is None:
        return
    # Only this investor's portfolios can be chosen
    chosen = [row for row in rows if row["portfolio_id"] == portfolio_id]
    if not chosen:
        print(f"\n  You have no portfolio with ID {portfolio_id}.")
        pause()
        return
    session.choose_portfolio(portfolio_id, chosen[0]["portfolio_name"])
    portfolio_home(session)


# ---------------------------------------------------------------------
# Portfolio home
# ---------------------------------------------------------------------
def portfolio_home(session):
    run_menu(lambda s: f"Portfolio: {s.portfolio_name}", [
        ("Summary",          summary),
        ("Buy",              lambda s: trade(s, "BUY")),
        ("Sell",             lambda s: trade(s, "SELL")),
        ("Trade history",    trade_history_menu),
        ("Deposit cash",     lambda s: cash(s, "DEPOSIT")),
        ("Withdraw cash",    lambda s: cash(s, "WITHDRAWAL")),
        ("Rename portfolio", rename),
        ("Delete portfolio", delete),
    ], session)
    session.forget_portfolio()


def summary(session):
    ok, cash_row = safe_call(da.cash_summary, session.conn, session.portfolio_id)
    if not ok or cash_row is None:
        pause()
        return
    print("\nCash")
    print_table([cash_row], [("starting_cash", "Starting"), ("deposits", "Deposits"),
                             ("withdrawals", "Withdrawals"), ("buys", "Buys"),
                             ("sells", "Sells"), ("cash_balance", "Cash")])
    ok, holdings = safe_call(da.open_holdings, session.conn, session.portfolio_id)
    if not ok:
        pause()
        return
    print("\nOpen holdings (valued at the latest close)")
    print_table(holdings, HOLDING_COLUMNS)
    # start=Decimal("0"): with no holdings the sum is still a Decimal (shown as 0.00)
    market_value = sum((row["market_value"] for row in holdings), Decimal("0"))
    print(f"\n  Market value {format_value(market_value)} + cash "
          f"{format_value(cash_row['cash_balance'])} = total "
          f"{format_value(market_value + cash_row['cash_balance'])}")
    pause()


def show_context(session):
    """Hints before a trade or cash transaction: cash now and the latest allowed date."""
    ok, context = safe_call(da.trade_context, session.conn, session.portfolio_id)
    if ok and context is not None:
        print(f"  Cash available: {format_value(context['cash'])}")
        print(f"  New events must be dated on or after {context['latest_allowed']}.")


def trade(session, trade_type):
    """Buy or sell (trade_type "BUY" / "SELL") through execute_trade()."""
    verb = "Buy" if trade_type == "BUY" else "Sell"
    print(f"\n{verb}")
    show_context(session)

    ticker = ask_ticker(session)
    if ticker is None:
        print("  Cancelled.")
        return
    shares = ask_int("Shares", minimum=1)
    day = ask_event_date(session, "Trade date", session.portfolio_id)
    ok, prices = safe_call(da.price_on, session.conn, ticker, day)
    if ok and prices is not None:
        print(f"  {day}: low {prices['low']}, high {prices['high']}, close {prices['close']}")
    elif ok:
        print(f"  (no price for {ticker} on {day})")
    price = ask_decimal("Price (Enter = that day's close)", required=False)

    ok, row = safe_call(da.execute_trade, session.conn, session.portfolio_id,
                        ticker, trade_type, shares, day, price)
    if ok:
        done = "Bought" if trade_type == "BUY" else "Sold"
        print(f"\n  {done} {row['shares']} {row['ticker']} @ {row['price']} "
              f"on {row['trade_date']} (trade {row['trade_id']}).")
        show_cash_now(session)
    pause()


def cash(session, txn_type):
    """Deposit or withdraw (txn_type "DEPOSIT" / "WITHDRAWAL") through record_cash_transaction()."""
    verb = "Deposit" if txn_type == "DEPOSIT" else "Withdraw"
    print(f"\n{verb} cash")
    print("  Note: cash transactions can't be edited or deleted later; "
          "a mistake is fixed with an opposite transaction.")
    show_context(session)
    amount = ask_decimal("Amount")
    day = ask_event_date(session, "Date", session.portfolio_id)
    ok, txn_id = safe_call(da.record_cash_transaction, session.conn, session.portfolio_id,
                           txn_type, amount, day)
    if ok:
        done = "Deposited" if txn_type == "DEPOSIT" else "Withdrew"
        print(f"\n  {done} {format_value(amount)} on {day} (cash transaction {txn_id}).")
        show_cash_now(session)
    pause()


def show_cash_now(session):
    ok, cash_row = safe_call(da.cash_summary, session.conn, session.portfolio_id)
    if ok and cash_row is not None:
        print(f"  Cash now: {format_value(cash_row['cash_balance'])}")


def rename(session):
    name = ask_text("New name (Enter = keep)", NAME_MAX, required=False)
    if name is None:
        return
    ok, _ = safe_call(da.rename_portfolio, session.conn, session.portfolio_id, name)
    if ok:
        session.choose_portfolio(session.portfolio_id, name)
        print("  Renamed.")
    pause()


def delete(session):
    ok, counts = safe_call(da.portfolio_delete_summary, session.conn, session.portfolio_id)
    if not ok:
        pause()
        return
    print(f"\n  Delete portfolio {session.portfolio_name}?")
    print(f"  This also deletes {counts['trades']} trade(s) and "
          f"{counts['cash_transactions']} cash transaction(s).")
    print("  Deleted trades stay visible in the trade audit log.")
    if not confirm_typed(session.portfolio_name, "the portfolio name"):
        pause()
        return
    ok, _ = safe_call(da.delete_portfolio, session.conn, session.portfolio_id)
    if ok:
        print(f"  Deleted portfolio {session.portfolio_name}.")
        session.forget_portfolio()
        pause()
        return "back"
    pause()
