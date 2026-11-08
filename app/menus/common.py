"""Prompts shared by several menus: the price range hint, the date prompt with
the project's default date, and the ticker prompt that re-asks unknown tickers."""
from app import data_access as da
from app import ticker_help, trading_days
from app.errors import safe_call
from app.inputs import ask_date, ask_text, ask_yes_no

TICKER_MAX = 10         # stock.ticker VARCHAR(10)
NAME_SEARCH_MAX = 100   # the ticker prompt also accepts a company name


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


def ask_trading_date(session, prompt, ticker=None, portfolio_id=None):
    """Ask for a date that must be a trading day (for `ticker`, or the market ^GSPC when
    ticker is None). A date without a price is asked again at once, with the reason
    (weekend, holiday, after the last price, ...) and the nearest trading days; Enter
    then offers the nearest earlier one. Dates before the portfolio's earliest allowed
    date (start date or latest event) are asked again too, and never suggested.
    A hint only: the database still decides."""
    earliest = None
    if portfolio_id is not None:
        ok, context = safe_call(da.trade_context, session.conn, portfolio_id)
        earliest = context["latest_allowed"] if ok and context else None
    day = ask_event_date(session, prompt, portfolio_id)
    while True:
        ok, info = safe_call(da.trading_day_info, session.conn, ticker, day, earliest)
        if not ok:
            return day
        problem = trading_days.too_early(day, earliest)
        if problem:              # before the start date / latest event: ask again right away
            print(f"  Too early: {problem}")
            day = ask_date(prompt, default=info["first_allowed"] or earliest)
            continue
        if info["has_price"]:
            return day
        if ticker is None and not info["market_known"]:
            return day           # no ^GSPC prices to judge "the market" by: the database decides
        print(f"  No price: {trading_days.no_price_reason(day, info)}")
        default = trading_days.next_default(info, earliest)
        if default is None:      # no trading day at all to offer: asking again can't help
            return day           # the database refuses it with a clear message
        print(f"  {trading_days.nearest_days(info, earliest)}")
        day = ask_date(prompt, default=default)


def show_ticker_list(session, kind):
    """Print the "? = list": the tickers this prompt accepts, grouped by sector.
    kind: "stocks" (Buy, Rebalance), "all" (stocks + indexes) or "held" (Sell)."""
    ok, rows = safe_call(da.ticker_catalog, session.conn, kind, session.portfolio_id)
    if not ok:
        return
    if not rows:
        print("  You hold no shares in this portfolio yet." if kind == "held" else "  No tickers yet.")
        return
    titles = {"stocks": "Stocks", "all": "Stocks and indexes", "held": "What you hold (shares)"}
    print(f"  {titles[kind]}:")
    print(ticker_help.format_catalog(rows))


def match_company(session, text, kind):
    """`text` is not a ticker: look for companies whose name contains it.
    One match: suggest it and ask to confirm. Several: list them.
    Returns (ticker or None, whether anything matched)."""
    ok, rows = safe_call(da.search_company, session.conn, text, kind, session.portfolio_id)
    if not ok or not rows:
        return None, False
    if len(rows) == 1:
        row = rows[0]
        if ask_yes_no(f"  '{text}' is not a ticker. Did you mean {row['ticker']} ({row['company_name']})?"):
            return row["ticker"], True
        return None, True
    print(f"  Several companies match '{text}':")
    for row in rows:
        print(f"    {ticker_help.entry(row)}")
    print("  Type one of these tickers.")
    return None, True


def ask_ticker(session, allow_index=False, held_only=False):
    """Ask for a ticker and show what we know about it.
    - "?" lists the accepted tickers: all stocks, + indexes if allow_index (watchlists,
      price history), or only this portfolio's holdings if held_only (Sell).
    - A company name ("apple", partial, any case) is looked up and suggested.
    - An unknown ticker, an index when allow_index is False, or (held_only) a ticker
      you don't hold is asked again right away.
    Hints only: the database still decides.
    Returns the ticker in capitals, or None if the user pressed Enter (cancel)."""
    kind = "held" if held_only else ("all" if allow_index else "stocks")
    while True:
        text = ask_text("Ticker (? = list, Enter = cancel)", NAME_SEARCH_MAX, required=False)
        if text is None:
            return None
        if text == "?":
            show_ticker_list(session, kind)
            continue
        ticker = text.upper()
        ok, info = safe_call(da.ticker_context, session.conn, session.portfolio_id, ticker)
        if not ok:
            return ticker                 # no hint available; let the database decide
        if info["company_name"] is None:
            found, matched = match_company(session, text, kind)
            if found is None:
                if not matched:
                    print(f"  {ticker} is not in the stock list. Type another ticker, "
                          "? for the list, or Enter to cancel.")
                continue
            ticker = found
            ok, info = safe_call(da.ticker_context, session.conn, session.portfolio_id, ticker)
            if not ok:
                return ticker
        if info["security_type"] == "INDEX" and not allow_index:
            print(f"  {ticker} is an index: it can be watched but not traded. "
                  "Type another ticker, or Enter to cancel.")
            continue
        if held_only and not info["shares_held"]:
            print(f"  You don't hold {ticker} in this portfolio. Type ? for what you hold.")
            continue
        if session.portfolio_id is None:          # watchlists: no holdings to show
            print(f"  {ticker}: {info['company_name']}, latest price {info['last_price_date']}")
        else:
            print(f"  {ticker}: {info['company_name']}, you hold {info['shares_held']} shares, "
                  f"latest price {info['last_price_date']}")
        return ticker


def offer_chart(function_name, *args):
    """After a report: "Save as PNG chart?" -> charts.<function_name>(*args) writes
    the PNG and its CSV (app/charts.py). Prints the paths; on Windows, macOS and
    WSL offers to open the PNG. Only reads data, so it also works in read-only mode.
    The function is passed by NAME, so the menus don't import app.charts and
    matplotlib is loaded only when a chart is actually wanted."""
    if not ask_yes_no("Save as PNG chart (+ CSV data)?"):
        return
    from app import charts                         # loaded here, on first use
    save_function = getattr(charts, function_name)  # getattr(module, "name") = module.name
    paths = save_function(*args)
    if paths is None:
        print("  Nothing to chart: there is no data for this selection.")
        return
    png, csv_file = paths
    print(f"  Saved chart: {png}")
    print(f"  Saved data:  {csv_file}")
    if charts.can_open_charts() and ask_yes_no("Open the chart?"):
        charts.open_chart(png)
