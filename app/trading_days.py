"""Why a date has no price, and the nearest trading days (pure Python: no database,
no input). Used by the date prompts that need a trading day (Buy / Sell, Rebalance).

These are HINTS: the database still decides (execute_trade refuses a date
without a price). The facts come from data_access.trading_day_info.
"""


def no_price_reason(day, info):
    """One sentence saying why `day` has no price for info["ticker"], or None if it has one.
    Checked in this order: weekend, no prices at all, after the last price, before
    the first price, market holiday, missing for this stock only."""
    if info["has_price"]:
        return None
    ticker = info["ticker"]
    if day.weekday() >= 5:                                   # 5 = Saturday, 6 = Sunday
        return f"{day} is a {day.strftime('%A')}: the market is closed on weekends."
    if info["last"] is None:
        return f"{ticker} has no prices at all."
    if day > info["last"]:
        return f"{day} is after {ticker}'s latest loaded price ({info['last']})."
    if day < info["first"]:
        return f"{day} is before {ticker}'s first price ({info['first']})."
    if info["market_known"] and not info["market_open"]:
        return f"{day} is a market holiday: no prices that day, ^GSPC has none either."
    if info["market_known"]:
        return f"{ticker} has no price on {day}, although the market was open (^GSPC has one)."
    return f"{ticker} has no price on {day}."


def nearest_days(info):
    """'Nearest trading days for AAPL: before 2026-11-06, after 2026-11-09'."""
    parts = []
    if info["before"]:
        parts.append(f"before {info['before']}")
    if info["after"]:
        parts.append(f"after {info['after']}")
    if not parts:
        return f"{info['ticker']} has no trading days to suggest."
    return f"Nearest trading days for {info['ticker']}: " + ", ".join(parts) + "."


def next_default(info):
    """The date offered at the next prompt: the nearest earlier trading day
    (a weekend -> Friday), or the next one if there is none earlier."""
    return info["before"] or info["after"]
