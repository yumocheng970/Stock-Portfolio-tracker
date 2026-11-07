"""Prompts shared by several menus: the price range hint, the date prompt with
the project's default date, and the ticker prompt that re-asks unknown tickers."""
from app import data_access as da
from app.errors import safe_call
from app.inputs import ask_date, ask_text, ask_yes_no

TICKER_MAX = 10         # stock.ticker VARCHAR(10)


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


def offer_chart(function_name, *args):
    """After a report: "Save as PNG chart?" -> charts.<function_name>(*args) writes
    the PNG and its CSV (app/charts.py). Prints the paths; in WSL offers to open
    the PNG in Windows. Only reads data, so it also works in read-only mode.
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
    if charts.is_wsl() and ask_yes_no("Open the chart in Windows?"):
        charts.open_in_windows(png)
