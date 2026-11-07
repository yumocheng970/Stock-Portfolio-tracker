"""app/rebalance.py: pure calculation, exact numbers (no database)."""
import random
from decimal import Decimal as D

import pytest

from app.rebalance import RebalanceError, parse_targets, plan_rebalance


def trades_of(plan):
    return plan.trades


# ---------------------------------------------------------------------
# The two examples from the specification
# ---------------------------------------------------------------------
def test_cash_only_to_targets():
    plan = plan_rebalance(D("10000"), {}, {"AAA": D("100"), "BBB": D("50")},
                          {"AAA": D("50"), "BBB": D("30")})
    assert plan.trades == [("AAA", "BUY", 50), ("BBB", "BUY", 60)]
    assert plan.cash_after == D("2000") and plan.cash_pct_after == D("20")
    assert plan.cash_target_pct == D("20")


def test_sell_one_buy_another_sell_comes_first():
    plan = plan_rebalance(D("0"), {"AAA": 100}, {"AAA": D("100"), "BBB": D("50")},
                          {"AAA": D("50"), "BBB": D("50")})
    assert plan.trades == [("AAA", "SELL", 50), ("BBB", "BUY", 100)]   # SELL first
    assert plan.cash_after == 0


# ---------------------------------------------------------------------
# Rounding never makes cash negative
# ---------------------------------------------------------------------
def test_rounding_with_uneven_prices():
    targets = {"X": D("33.33"), "Y": D("33.33"), "Z": D("33.34")}
    prices = {"X": D("7.77"), "Y": D("13.13"), "Z": D("29.99")}
    plan = plan_rebalance(D("1000"), {}, prices, targets)
    # 1000 x 33.33 % = 333.30 -> 333.30 / 7.77 = 42.9 -> BUY 42 (down), and so on
    assert plan.trades == [("X", "BUY", 42), ("Y", "BUY", 25), ("Z", "BUY", 11)]
    assert plan.cash_after == D("1000") - 42 * D("7.77") - 25 * D("13.13") - 11 * D("29.99")
    assert plan.cash_after == D("15.52")                               # 1000 - 984.48: the drift
    for line in plan.lines:
        assert line.value_after <= line.target_pct / 100 * plan.total_value
        assert line.drift <= 0                                       # at or below target


def test_sell_is_rounded_up():
    # 10 AAA @ 30 = 300, cash 0; target 50 % = 150 -> 5 shares exactly; 45 % = 135 -> 4.5 -> SELL 6
    plan = plan_rebalance(D("0"), {"AAA": 10}, {"AAA": D("30")}, {"AAA": D("45")})
    assert plan.trades == [("AAA", "SELL", 6)] and plan.cash_after == D("180")


def test_randomized_cash_never_negative_and_values_never_above_target():
    """The proof in the module docstring, checked on 1,000 random portfolios."""
    rng = random.Random(5200)                      # seeded: the same "random" cases every run
    for _ in range(1000):
        tickers = [f"T{i}" for i in range(rng.randint(1, 6))]
        prices = {t: D(rng.randint(100, 500000)) / 100 for t in tickers}      # 1.00 .. 5,000.00
        holdings = {t: rng.randint(0, 300) for t in tickers if rng.random() < 0.6}
        cash = D(rng.randint(0, 5_000_000)) / 100
        chosen = [t for t in tickers if rng.random() < 0.8] or tickers[:1]
        cuts = sorted(rng.randint(0, 10000) for _ in chosen)                 # random split of <= 100 %
        targets = {t: D(b - a) / 100 for t, a, b in zip(chosen, [0] + cuts[:-1], cuts)}
        try:
            plan = plan_rebalance(cash, holdings, prices, targets)
        except RebalanceError:
            continue                                # kept + targets > 100 % or nothing to rebalance
        assert plan.cash_after >= 0
        for line in plan.lines:
            if line.target_pct is not None:
                assert line.value_after <= line.target_pct / 100 * plan.total_value
            assert line.shares_after >= 0


# ---------------------------------------------------------------------
# Kept tickers, zero targets, errors
# ---------------------------------------------------------------------
def test_held_ticker_not_in_targets_is_kept_and_counts_in_the_total():
    # cash 1,000 + 10 KEEP @ 100 = 2,000; AAA 25 % = 500 -> BUY 5; KEEP stays (50 %)
    plan = plan_rebalance(D("1000"), {"KEEP": 10}, {"KEEP": D("100"), "AAA": D("100")}, {"AAA": D("25")})
    assert plan.trades == [("AAA", "BUY", 5)]
    keep = next(line for line in plan.lines if line.ticker == "KEEP")
    assert (keep.target_pct, keep.trade, keep.pct_after) == (None, 0, D("50"))
    assert plan.cash_target_pct == D("25") and plan.cash_after == D("500")


def test_targets_plus_kept_over_100_is_an_error():
    with pytest.raises(RebalanceError, match=r"Targets \(60.00 %\) \+ positions you keep \(50.00 %\)"):
        plan_rebalance(D("1000"), {"KEEP": 10}, {"KEEP": D("100"), "AAA": D("10")}, {"AAA": D("60")})


def test_zero_target_sells_everything():
    plan = plan_rebalance(D("0"), {"AAA": 7}, {"AAA": D("12.34")}, {"AAA": D("0")})
    assert plan.trades == [("AAA", "SELL", 7)] and plan.cash_after == 7 * D("12.34")


def test_missing_price_and_empty_portfolio():
    with pytest.raises(RebalanceError, match="No price for ZZZ"):
        plan_rebalance(D("100"), {}, {}, {"ZZZ": D("10")})
    with pytest.raises(RebalanceError, match="no value"):
        plan_rebalance(D("0"), {}, {"AAA": D("1")}, {"AAA": D("10")})


def test_no_trades_needed():
    plan = plan_rebalance(D("500"), {"AAA": 5}, {"AAA": D("100")}, {"AAA": D("50")})
    assert plan.trades == [] and plan.cash_after == D("500")


# ---------------------------------------------------------------------
# Parsing the targets (shape only)
# ---------------------------------------------------------------------
def test_parse_targets_formats():
    assert parse_targets("aapl 30, MSFT=20.5, KO: 10%") == \
        ({"AAPL": D("30"), "MSFT": D("20.5"), "KO": D("10")}, [])


@pytest.mark.parametrize("text, expected", [
    ("AAPL 60, MSFT 50", "The targets add up to 110 %, more than 100 %"),
    ("AAPL 30, aapl 10", "AAPL is listed twice"),
    ("AAPL thirty", "AAPL: 'thirty' is not a number with at most 2 decimals"),
    ("AAPL 120", "AAPL: 120 % is not between 0 and 100"),
    ("AAPL -5", "AAPL: -5 % is not between 0 and 100"),
    ("AAPL 1.234", "AAPL: '1.234' is not a number"),
    ("AAPL", "'AAPL': expected TICKER PERCENT"),
    ("TOOLONGTICKER 5", "'TOOLONGTICKER': a ticker has at most 10 characters"),
    ("", "Please type at least one target"),
])
def test_parse_targets_errors(text, expected):
    targets, errors = parse_targets(text)
    assert targets == {} and any(expected in e for e in errors)


def test_parse_targets_lists_all_errors():
    _, errors = parse_targets("AAPL abc, KO 150, MSFT 10")
    assert len(errors) == 2
