"""The preview before a Buy or Sell is saved, and the concentration warning.
Pure Python (no database, no input), so it can be tested with exact numbers.

Hints only: the database still decides (cash, shares, price range, dates).
The warning never blocks a trade; the user still confirms or cancels.

Concentration after a BUY of n shares of ticker t at price p, valued at the
closes of the trade day (c_i), with the cash before the trade:
    value_t = (held_t + n) x c_t
    total   = cash - n x p + sum(held_i x c_i) + n x c_t
    share_t = value_t / total x 100
"""
from decimal import Decimal

from app.display import format_pct, format_value, round2

# One ticker above this % of the portfolio's total value (holdings + cash) -> warning
CONCENTRATION_WARNING_PCT = Decimal("40")
HUNDRED = Decimal("100")


def trade_amount(shares, price):
    """shares x price, rounded to cents like the database (trade price has 2 decimals)."""
    return round2(Decimal(shares) * Decimal(price))


def cash_after(cash, trade_type, amount):
    """Cash after the trade: a BUY spends the amount, a SELL brings it in."""
    return cash - amount if trade_type == "BUY" else cash + amount


def preview_text(trade_type, shares, ticker, price, day, cash):
    """'BUY 10 AAPL @ 204.64 on 2026-11-06 = 2,046.40. Cash after: 97,953.60.'"""
    amount = trade_amount(shares, price)
    return (f"{trade_type} {shares} {ticker} @ {format_value(round2(price))} on {day} = "
            f"{format_value(amount)}. Cash after: {format_value(cash_after(cash, trade_type, amount))}.")


def not_enough_cash(cash, shares, price):
    """The line shown instead of the concentration warning when a BUY would make
    cash negative, or None when the cash is enough. A hint: the database refuses it."""
    if cash_after(cash, "BUY", trade_amount(shares, price)) >= 0:
        return None
    return f"Not enough cash: the database will refuse this trade (you have {format_value(cash)})."


def allowed_date_source(context):
    """Which event sets the earliest allowed date (da.trade_context row):
    'the latest event: DEPOSIT 5,000.00 on 2026-10-22' / 'BUY 10 AAPL @ 204.64 on ...',
    or "the portfolio's start date" (no events, or the start date is later)."""
    day = context["event_date"]
    if day is None or day < context["latest_allowed"]:
        return "the portfolio's start date"
    if context["event_kind"] == "trade":
        what = (f"{context['event_type']} {context['event_shares']} {context['event_ticker']} "
                f"@ {format_value(context['event_price'])}")
    else:
        what = f"{context['event_type']} {format_value(context['event_amount'])}"
    return f"the latest event: {what} on {day}"


def concentration_after_buy(cash, holdings, closes, ticker, shares, price):
    """The ticker's % of the total value after buying `shares` at `price`.
    holdings = {ticker: shares held now}, closes = {ticker: close on the trade day}.
    None when it can't be computed (a missing close, or a total value <= 0)."""
    if ticker not in closes or any(t not in closes for t in holdings):
        return None
    held_value = sum((Decimal(n) * closes[t] for t, n in holdings.items()), Decimal("0"))
    ticker_value = (holdings.get(ticker, 0) + shares) * closes[ticker]
    total = cash - Decimal(shares) * Decimal(price) + held_value + shares * closes[ticker]
    if total <= 0:
        return None
    return ticker_value / total * HUNDRED


def concentration_warning(ticker, pct, limit=CONCENTRATION_WARNING_PCT):
    """The warning line, or None at or below the limit (or when pct is None)."""
    if pct is None or pct <= limit:
        return None
    return (f"Warning: {ticker} would be {format_pct(pct, signed=False)} of this portfolio "
            f"(limit for the warning: {limit:g} %).")
