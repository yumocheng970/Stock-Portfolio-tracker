"""Simulate one portfolio forward in time: which trades and cash transactions happen.

Pure Python: no database, no network, so it is easy to unit-test
(tests/test_simulate.py). The seeder (etl/seed_sample_data.py) sends the
events to the database through execute_trade() / record_cash_transaction().

Rules the simulation keeps, so the database triggers never have to reject:
  - events are in date order; on the same date cash events come before trades
    (the same order the balance replay in 04_balance_checks.sql uses)
  - BUY only what the cash allows; SELL only shares actually held
  - trades use that day's close (execute_trade() with no price does the same)
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SELL_CHANCE = 0.35          # when something is held
WITHDRAW_CHANCE = 0.4       # on a cash day, if cash >= MIN_CASH_TO_WITHDRAW
MIN_CASH_TO_WITHDRAW = Decimal(1000)


@dataclass(frozen=True)
class Event:
    """One cash transaction or trade. frozen=True: can't be changed after creation."""
    date: date
    kind: str                      # 'CASH' or 'TRADE'
    type: str                      # DEPOSIT / WITHDRAWAL / BUY / SELL
    ticker: str | None = None      # trades only
    shares: int | None = None      # trades only
    amount: Decimal | None = None  # cash amount, or shares * close for a trade


def simulate_portfolio(rng, starting_cash, trading_days, closes, tickers, n_trades, n_cash):
    """Return the portfolio's events, in the order they must be inserted.

    rng           a random.Random(seed): all randomness comes from it
    starting_cash Decimal
    trading_days  sorted list of dates (from the start date on)
    closes        dict {(ticker, date): Decimal close}
    tickers       stock tickers that may be traded (never an index)
    n_trades      how many trade days to pick
    n_cash        how many cash-transaction days to pick
    """
    # 1. Pick the days. sorted(): rng.sample returns them in random order.
    trade_days = sorted(rng.sample(trading_days, min(n_trades, len(trading_days))))
    cash_days = sorted(rng.sample(trading_days, min(n_cash, len(trading_days))))

    # 2. One plan in history order: by date, cash (0) before trades (1)
    plan = [(d, 0) for d in cash_days] + [(d, 1) for d in trade_days]
    plan.sort()

    # 3. Walk forward, keeping the state up to date
    cash = starting_cash
    holdings = {}                  # ticker -> shares held
    events = []

    for day, order in plan:
        if order == 0:
            event = _cash_event(rng, day, cash)
            cash += event.amount if event.type == "DEPOSIT" else -event.amount
        else:
            event = _trade_event(rng, day, cash, holdings, closes, tickers)
            if event is None:      # nothing affordable and nothing to sell
                continue
            if event.type == "BUY":
                cash -= event.amount
                holdings[event.ticker] = holdings.get(event.ticker, 0) + event.shares
            else:
                cash += event.amount
                holdings[event.ticker] -= event.shares
        events.append(event)

    return events


def _cash_event(rng, day, cash):
    """A deposit, or a withdrawal of at most 30% of the cash at that moment."""
    if cash >= MIN_CASH_TO_WITHDRAW and rng.random() < WITHDRAW_CHANCE:
        amount = Decimal(rng.randint(100, int(cash * Decimal("0.3"))))
        return Event(day, "CASH", "WITHDRAWAL", amount=amount)
    amount = Decimal(rng.randint(1, 40) * 500)          # 500 .. 20,000
    return Event(day, "CASH", "DEPOSIT", amount=amount)


def _trade_event(rng, day, cash, holdings, closes, tickers):
    """A BUY that cash allows or a SELL of shares held; None if neither is possible."""
    # sorted(): never depend on dict order, so the same seed gives the same result
    held = sorted(t for t, n in holdings.items() if n > 0 and (t, day) in closes)
    available = [t for t in tickers if (t, day) in closes]

    if held and rng.random() < SELL_CHANCE:
        return _sell(rng, day, holdings, closes, held)

    if available:
        ticker = rng.choice(available)
        price = closes[(ticker, day)]
        budget = cash * Decimal(rng.randint(5, 25)) / 100      # 5% .. 25% of cash
        shares = int(budget // price)
        if shares == 0 and cash >= price:
            shares = 1
        if shares > 0:
            return Event(day, "TRADE", "BUY", ticker, shares, shares * price)

    # Couldn't buy: sell something instead, if anything is held
    if held:
        return _sell(rng, day, holdings, closes, held)
    return None


def _sell(rng, day, holdings, closes, held):
    ticker = rng.choice(held)
    shares = rng.randint(1, holdings[ticker])
    return Event(day, "TRADE", "SELL", ticker, shares, shares * closes[(ticker, day)])
