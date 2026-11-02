"""Unit tests for etl/simulate.py (no database, no network).

The tests replay the events with their own simple code (an independent
check) in the same order the database uses, and assert cash and shares
never go below zero.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from etl.simulate import Event, simulate_portfolio

STOCKS = ["AAA", "BBB", "CCC", "EXP"]      # EXP is expensive (5000)


def make_market(n_days=300, seed=1):
    """Weekdays from 2024-01-01 with made-up closes (Decimal, 2 decimals)."""
    rng = random.Random(seed)
    days = []
    d = date(2024, 1, 1)
    while len(days) < n_days:
        if d.weekday() < 5:            # Monday..Friday
            days.append(d)
        d += timedelta(days=1)
    base = {"AAA": 20, "BBB": 150, "CCC": 600, "EXP": 5000, "^GSPC": 4800}
    closes = {}
    for t, b in base.items():
        for day in days:
            closes[(t, day)] = (Decimal(b) * Decimal(rng.randint(80, 120)) / 100).quantize(Decimal("0.01"))
    return days, closes


DAYS, CLOSES = make_market()


def replay(starting_cash, events):
    """Independent re-calculation: return (lowest cash, lowest shares) ever seen."""
    cash = starting_cash
    holdings = {}
    lowest_cash = cash
    lowest_shares = 0
    for e in events:
        if e.kind == "CASH":
            cash += e.amount if e.type == "DEPOSIT" else -e.amount
        elif e.type == "BUY":
            cash -= e.shares * CLOSES[(e.ticker, e.date)]
            holdings[e.ticker] = holdings.get(e.ticker, 0) + e.shares
        else:
            cash += e.shares * CLOSES[(e.ticker, e.date)]
            holdings[e.ticker] = holdings.get(e.ticker, 0) - e.shares
        lowest_cash = min(lowest_cash, cash)
        lowest_shares = min([lowest_shares, *holdings.values()])
    return lowest_cash, lowest_shares


def run(seed, starting_cash=Decimal(10000), n_trades=40, n_cash=4, days=DAYS, tickers=STOCKS):
    rng = random.Random(seed)
    return simulate_portfolio(rng, starting_cash, days, CLOSES, tickers, n_trades, n_cash)


# --- the two core invariants, over many seeds and start amounts ---------------
@pytest.mark.parametrize("starting_cash", [Decimal(10000), Decimal(50000), Decimal(500000)])
def test_never_spends_more_than_cash_and_never_sells_more_than_held(starting_cash):
    for seed in range(300):
        events = run(seed, starting_cash, n_trades=60)
        lowest_cash, lowest_shares = replay(starting_cash, events)
        assert lowest_cash >= 0, f"seed {seed}: cash went to {lowest_cash}"
        assert lowest_shares >= 0, f"seed {seed}: shares went to {lowest_shares}"


def test_never_sells_a_ticker_not_held():
    for seed in range(100):
        held = set()
        for e in run(seed):
            if e.type == "BUY":
                held.add(e.ticker)
            if e.type == "SELL":
                assert e.ticker in held


# --- order and dates ------------------------------------------------------------
def test_events_in_db_history_order_cash_before_trades():
    for seed in range(100):
        events = run(seed)
        keys = [(e.date, 0 if e.kind == "CASH" else 1) for e in events]
        assert keys == sorted(keys)


def test_dates_come_from_the_given_days():
    days = DAYS[100:]                              # portfolio starts later
    events = run(7, days=days)
    assert all(e.date >= days[0] and e.date in set(days) for e in events)


# --- counts and amounts ------------------------------------------------------------
def test_trade_count_is_n_trades():
    for seed in range(100):
        events = run(seed, n_trades=37)
        assert sum(e.kind == "TRADE" for e in events) == 37


def test_cash_event_count_and_types():
    events = run(3, n_cash=5)
    cash_events = [e for e in events if e.kind == "CASH"]
    assert len(cash_events) == 5
    assert {e.type for e in cash_events} <= {"DEPOSIT", "WITHDRAWAL"}
    assert all(e.amount > 0 for e in cash_events)


def test_trade_amount_is_shares_times_close():
    for e in run(11):
        if e.kind == "TRADE":
            assert e.amount == e.shares * CLOSES[(e.ticker, e.date)]
            assert e.shares > 0


# --- tickers ---------------------------------------------------------------------------
def test_only_trades_the_given_tickers_never_the_index():
    for seed in range(50):
        traded = {e.ticker for e in run(seed) if e.kind == "TRADE"}
        assert traded <= set(STOCKS)
        assert "^GSPC" not in traded


# --- reproducibility ---------------------------------------------------------------------
def test_same_seed_gives_identical_events():
    assert run(42) == run(42)


def test_different_seed_gives_different_events():
    assert run(42) != run(43)


# --- edge case: nothing affordable, nothing held ---------------------------------------------
def test_too_little_cash_skips_trades_instead_of_breaking_rules():
    events = run(5, starting_cash=Decimal(100), n_cash=0, tickers=["EXP"])
    assert events == []                            # can't afford EXP, nothing to sell


def test_event_is_frozen():
    e = Event(date(2024, 1, 2), "CASH", "DEPOSIT", amount=Decimal(500))
    with pytest.raises(AttributeError):
        e.amount = Decimal(1)
