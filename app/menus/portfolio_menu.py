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
from app import csv_import, rebalance
from app.inputs import ask_decimal, ask_int, ask_text, ask_yes_no, confirm_typed, pause
from app.menu import run_menu
from app.menus.common import ask_event_date, ask_ticker, ask_trading_date, match_company, show_ticker_list
from app.menus.reports_menu import reports_menu
from app.menus.trade_history_menu import trade_history_menu

NAME_MAX = 100          # portfolio.portfolio_name VARCHAR(100)

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
        ("Reports",          reports_menu),
        ("Deposit cash",     lambda s: cash(s, "DEPOSIT")),
        ("Withdraw cash",    lambda s: cash(s, "WITHDRAWAL")),
        ("Import from CSV",  import_csv),
        ("Rebalance",        rebalance_portfolio),
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

    ticker = ask_ticker(session, held_only=(trade_type == "SELL"))
    if ticker is None:
        print("  Cancelled.")
        return
    shares = ask_int("Shares", minimum=1)
    # A date without a price for this ticker is asked again (with the reason)
    day = ask_trading_date(session, "Trade date", ticker, session.portfolio_id)
    ok, prices = safe_call(da.price_on, session.conn, ticker, day)
    if ok and prices is not None:
        print(f"  {day}: low {prices['low']}, high {prices['high']}, close {prices['close']}")
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


def import_csv(session):
    """Import trades and cash transactions from a CSV file: check every row's shape,
    preview, confirm, then import ALL rows in one transaction (or none)."""
    print("\nImport from CSV. Columns: date,type,ticker,shares,price,amount")
    print("  BUY/SELL rows: ticker + shares (+ price; empty = that day's close).")
    print("  DEPOSIT/WITHDRAWAL rows: amount. Samples: data/samples/")
    ok, read_only = safe_call(da.is_read_only, session.conn)
    if ok and read_only:
        print("  Import is not possible in read-only mode: nothing was changed.")
        pause()
        return
    typed = ask_text("CSV file path (Enter = cancel)", 500, required=False)
    if typed is None:
        return
    path = csv_import.to_linux_path(typed)

    events, errors = csv_import.read_events(path)
    if errors:
        print(f"\n  The file has {len(errors)} problem(s); nothing was saved:")
        for error in errors:
            print(f"    {error}")
        pause()
        return

    info = csv_import.preview(events)
    print(f"\n  {path}")
    print(f"  {info['trades']} trades and {info['cash']} cash transactions, "
          f"{info['first_date']} to {info['last_date']}")
    print(f"  Tickers: {', '.join(info['tickers']) or '-'}")
    if info["reordered"]:
        print("  Rows will be imported in history order (date, cash before trades); "
              "messages use the file's row numbers.")
    if not ask_yes_no(f"Import these {len(events)} rows into {session.portfolio_name}?"):
        print("  Nothing was imported.")
        pause()
        return

    ok, counts = safe_call(da.import_events, session.conn, session.portfolio_id,
                           csv_import.history_order(events))
    if ok:
        print(f"\n  Imported {counts['trades']} trades and {counts['cash']} cash transactions.")
        show_cash_now(session)
    else:
        print("  Nothing was saved (the whole import was rolled back).")
    pause()


def resolve_target_names(session, targets):
    """Targets typed as company names ("apple 30") -> tickers, after confirming.
    Returns the targets with tickers, or None to ask for the targets again."""
    ok, known = safe_call(da.existing_tickers, session.conn, targets)
    if not ok:
        return targets                   # no hint available; the database decides
    resolved = {}
    for name, pct in targets.items():
        ticker = name
        if name not in known:
            ticker, matched = match_company(session, name, "stocks")
            if ticker is None:
                if not matched:
                    print(f"  {name} is not in the stock list (type ? for the list).")
                return None
        if ticker in resolved:
            print(f"  {ticker} is listed twice.")
            return None
        resolved[ticker] = pct
    return resolved


REBALANCE_COLUMNS = [
    ("ticker", "Ticker"), ("price", "Price"), ("shares", "Shares now"), ("pct", "% now"),
    ("target_text", "Target"), ("trade_text", "Trade"), ("shares_after", "Shares after"),
    ("pct_after", "% after"), ("drift", "Drift"),
]


def trade_text(trade):
    """+5 -> "BUY 5", -3 -> "SELL 3", 0 -> "-"."""
    if trade > 0:
        return f"BUY {trade}"
    if trade < 0:
        return f"SELL {-trade}"
    return "-"


def rebalance_portfolio(session):
    """Rebalance to target % per ticker: compute whole-share trades (app/rebalance.py),
    preview, confirm, then all trades in ONE transaction (SELLs first)."""
    print("\nRebalance to target percentages of the portfolio's total value.")
    print("  Held tickers you leave out are kept as they are; a target of 0 sells all.")
    print("  The rest is the cash target. Trades are whole shares at the chosen day's close.")
    # ticker None: the date is checked against the market (^GSPC); a missing price
    # for one target ticker is still caught by the database (all or nothing)
    day = ask_trading_date(session, "Date (valuation and trades)", None, session.portfolio_id)

    ok, cash_row = safe_call(da.cash_summary, session.conn, session.portfolio_id)
    ok2, holdings_rows = safe_call(da.open_holdings, session.conn, session.portfolio_id)
    if not (ok and ok2):
        pause()
        return
    holdings = {row["ticker"]: row["shares_held"] for row in holdings_rows}
    print(f"  Now: cash {format_value(cash_row['cash_balance'])}, holdings: "
          + (", ".join(f"{t} {n}" for t, n in holdings.items()) or "none"))

    while True:
        text = ask_text("Targets, e.g. AAPL 30, MSFT 20, KO 10 (? = list, Enter = cancel)", 500,
                        required=False)
        if text is None:
            return
        if text == "?":
            show_ticker_list(session, "stocks")
            continue
        targets, errors = rebalance.parse_targets(text)
        if errors:
            for error in errors:
                print(f"  {error}")
            continue
        targets = resolve_target_names(session, targets)
        if targets is not None:
            break

    ok, prices = safe_call(da.latest_closes, session.conn, set(holdings) | set(targets), day)
    if not ok:
        pause()
        return
    try:
        plan = rebalance.plan_rebalance(cash_row["cash_balance"], holdings, prices, targets)
    except rebalance.RebalanceError as error:
        print(f"\n  !! {error}")
        pause()
        return

    shown = [{**line._asdict(),
              "target_text": "keep" if line.target_pct is None else f"{line.target_pct:.2f} %",
              "trade_text": trade_text(line.trade)} for line in plan.lines]
    print(f"\nPlan on {day} (total value {format_value(plan.total_value)})")
    print_table(shown, REBALANCE_COLUMNS, percent=("pct", "pct_after", "drift"), signed=False)
    print(f"  Cash: {format_value(plan.cash_before)} ({plan.cash_pct:.2f} %) -> "
          f"{format_value(plan.cash_after)} ({plan.cash_pct_after:.2f} %), "
          f"target {plan.cash_target_pct:.2f} %. Whole shares leave a small drift; "
          f"cash can't go below zero.")
    if not plan.trades:
        print("  No trades needed: the portfolio already matches the targets (to the whole share).")
        pause()
        return
    print("  Trades, in this order (sales first): "
          + ", ".join(f"{kind} {n} {t}" for t, kind, n in plan.trades))

    if not ask_yes_no(f"Make these {len(plan.trades)} trades on {day}?"):
        print("  Nothing was traded.")
        pause()
        return
    ok, read_only = safe_call(da.is_read_only, session.conn)
    if ok and read_only:
        print("  Rebalancing is not possible in read-only mode: nothing was changed.")
        pause()
        return
    ok, count = safe_call(da.execute_rebalance, session.conn, session.portfolio_id, plan.trades, day)
    if ok:
        print(f"\n  Done: {count} trades.")
        show_cash_now(session)
    else:
        print("  Nothing was saved (all trades were rolled back).")
    pause()


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
