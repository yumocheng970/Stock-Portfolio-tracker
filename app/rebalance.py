"""Rebalance to target percentages: parsing the targets and computing the trades.
Pure Python (no database, no input), so it can be tested with exact numbers.

Targets are per ticker, as % of the portfolio's total value (cash + all
holdings at one date's closes). Held tickers that are not in the targets are
KEPT unchanged; a target of 0 sells everything. The rest is the cash target.

Whole shares, and the rounding that keeps cash >= 0:
    SELL n = ceil(current - target_shares)    (round the sale UP)
    BUY  n = floor(target_shares - current)   (round the purchase DOWN)
Both leave every targeted ticker at or BELOW its target value T_i = p_i x V.
All trades use the valuation price, so the total value V doesn't change and
    cash_after = V - sum(values after) - kept >= V - sum(T_i) - kept
               = V x (1 - sum(p_i)) - kept >= 0
whenever targets + kept positions <= 100 %. That is the only check needed.
"""
import math
import re
from decimal import Decimal
from typing import NamedTuple

from app.inputs import parse_amount

HUNDRED = Decimal("100")
TICKER_MAX = 10
# "AAPL 30" or "AAPL=30" or "AAPL: 30" (one entry; the line is split at commas)
ENTRY = re.compile(r"(\S+?)\s*[=:\s]\s*(\S+)")


class RebalanceError(Exception):
    """The plan can't be computed (missing price, more than 100 %, empty portfolio).
    str(error) is a sentence for the user."""


class Line(NamedTuple):
    """One ticker in the plan. target_pct None = kept (not in the targets).
    trade > 0 = BUY that many shares, < 0 = SELL, 0 = nothing."""
    ticker: str
    price: Decimal
    shares: int
    value: Decimal
    pct: Decimal
    target_pct: Decimal | None
    trade: int
    shares_after: int
    value_after: Decimal
    pct_after: Decimal
    drift: Decimal | None            # pct_after - target_pct (None for kept tickers)


class Plan(NamedTuple):
    lines: list
    total_value: Decimal
    cash_before: Decimal
    cash_after: Decimal
    cash_pct: Decimal
    cash_target_pct: Decimal
    cash_pct_after: Decimal
    trades: list                     # [(ticker, "SELL" / "BUY", shares)], SELLs first


# ---------------------------------------------------------------------
# Parsing "AAPL 30, MSFT 20, KO 10"
# ---------------------------------------------------------------------
def parse_targets(text):
    """Returns (targets, errors): targets = {"AAPL": Decimal("30"), ...};
    errors = every shape problem found (empty list = fine). Only the SHAPE is
    checked: unknown tickers and indexes are found later (price / database)."""
    targets, errors = {}, []
    entries = [part.strip() for part in text.split(",") if part.strip()]
    if not entries:
        return {}, ["Please type at least one target, e.g. AAPL 30, MSFT 20."]
    for entry in entries:
        match = ENTRY.fullmatch(entry)
        if match is None:
            errors.append(f"'{entry}': expected TICKER PERCENT, e.g. AAPL 30")
            continue
        ticker, number = match.group(1).upper(), match.group(2).rstrip("%")
        if len(ticker) > TICKER_MAX:
            errors.append(f"'{ticker}': a ticker has at most {TICKER_MAX} characters")
            continue
        try:
            pct = parse_amount(number)
        except ValueError:
            errors.append(f"{ticker}: '{number}' is not a number with at most 2 decimals")
            continue
        if not 0 <= pct <= 100:
            errors.append(f"{ticker}: {pct} % is not between 0 and 100")
            continue
        if ticker in targets:
            errors.append(f"{ticker} is listed twice")
            continue
        targets[ticker] = pct
    total = sum(targets.values(), Decimal("0"))
    if total > HUNDRED:
        errors.append(f"The targets add up to {total} %, more than 100 %")
    return (targets if not errors else {}), errors


# ---------------------------------------------------------------------
# The calculation
# ---------------------------------------------------------------------
def plan_rebalance(cash, holdings, prices, targets):
    """cash: Decimal; holdings: {ticker: shares}; prices: {ticker: close} for every
    held or targeted ticker; targets: {ticker: percent}. Returns a Plan."""
    tickers = sorted(set(holdings) | set(targets))
    missing = [t for t in tickers if prices.get(t) is None]
    if missing:
        raise RebalanceError(f"No price for {', '.join(missing)} on or before the chosen date "
                             f"(unknown ticker?). Nothing was calculated.")

    total = cash + sum((holdings.get(t, 0) * prices[t] for t in tickers), Decimal("0"))
    if total <= 0:
        raise RebalanceError("The portfolio has no value to rebalance.")

    kept_value = sum((holdings[t] * prices[t] for t in holdings if t not in targets), Decimal("0"))
    target_sum = sum(targets.values(), Decimal("0"))
    kept_pct = HUNDRED * kept_value / total
    if target_sum + kept_pct > HUNDRED:
        raise RebalanceError(
            f"Targets ({target_sum:.2f} %) + positions you keep ({kept_pct:.2f} %) exceed 100 %: "
            f"lower a target, or add a held ticker with 0 to sell it.")

    lines, sells, buys = [], [], []
    cash_after = cash
    for t in tickers:
        price, shares = prices[t], holdings.get(t, 0)
        if t in targets:
            target_shares = targets[t] / HUNDRED * total / price          # exact Decimal, not whole
            if shares > target_shares:
                trade = -math.ceil(shares - target_shares)                # SELL, rounded UP
            else:
                trade = math.floor(target_shares - shares)                # BUY, rounded DOWN
        else:
            trade = 0                                                     # kept unchanged
        cash_after -= trade * price
        if trade < 0:
            sells.append((t, "SELL", -trade))
        elif trade > 0:
            buys.append((t, "BUY", trade))
        after = shares + trade
        pct_after = HUNDRED * after * price / total
        lines.append(Line(t, price, shares, shares * price, HUNDRED * shares * price / total,
                          targets.get(t), trade, after, after * price, pct_after,
                          pct_after - targets[t] if t in targets else None))

    return Plan(lines, total, cash, cash_after, HUNDRED * cash / total,
                HUNDRED - target_sum - kept_pct, HUNDRED * cash_after / total,
                sells + buys)                                             # SELLs first
