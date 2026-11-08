"""Dates without a price: the reason and the nearest trading days (test DB, rolled back).

Prices for TD1 and ^GSPC: Mon 2025-03-03 .. Fri 03-07, Mon 03-10, Tue 03-11, except:
  Wed 03-05  a "holiday": no price for anything
  Thu 03-06  ^GSPC has a price, TD1 doesn't (missing for this stock only)
"""
from datetime import date
from decimal import Decimal

import pytest

from app import data_access as da
from app.menus import portfolio_menu
from app.session import Session
from app.trading_days import nearest_days, next_default, no_price_reason

D = lambda day: date(2025, 3, day)                                     # noqa: E731


@pytest.fixture
def market(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('TD1', 'Trading Day One')")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^GSPC', 'S&P 500', 'INDEX')")
    for day in (3, 4, 6, 7, 10, 11):
        conn.execute("INSERT INTO daily_price VALUES ('^GSPC', %s, 100, 101, 99, 100, 0)", (D(day),))
        if day != 6:
            conn.execute("INSERT INTO daily_price VALUES ('TD1', %s, 50, 51, 49, 50, 0)", (D(day),))
    return conn


def facts(conn, ticker, day):
    return da.trading_day_info(conn, ticker, day)


@pytest.mark.parametrize("day, reason, before, after", [
    (D(8),  "2025-03-08 is a Saturday: the market is closed on weekends.", D(7), D(10)),
    (D(5),  "2025-03-05 is a market holiday: no prices that day, ^GSPC has none either.", D(4), D(7)),
    (D(6),  "TD1 has no price on 2025-03-06, although the market was open (^GSPC has one).", D(4), D(7)),
    (D(12), "2025-03-12 is after TD1's latest loaded price (2025-03-11).", D(11), None),
    (date(2025, 2, 28), "2025-02-28 is before TD1's first price (2025-03-03).", None, D(3)),
])
def test_each_reason_and_the_nearest_days(market, day, reason, before, after):
    info = facts(market, "TD1", day)
    assert no_price_reason(day, info) == reason
    assert (info["before"], info["after"]) == (before, after)
    assert next_default(info) == (before or after)


def test_a_trading_day_has_no_reason(market):
    assert no_price_reason(D(7), facts(market, "td1", D(7))) is None


def test_nearest_days_text(market):
    assert nearest_days(facts(market, "TD1", D(8))) == \
        "Nearest trading days for TD1: before 2025-03-07, after 2025-03-10."
    assert nearest_days(facts(market, "TD1", D(12))) == "Nearest trading days for TD1: before 2025-03-11."


def test_the_market_check_uses_gspc(market):
    info = facts(market, None, D(5))
    assert info["ticker"] == "^GSPC"
    assert no_price_reason(D(5), info).startswith("2025-03-05 is a market holiday")


def test_buy_reasks_the_date_before_the_price(market, monkeypatch, capsys):
    investor = da.create_investor(market, "Tina Day", "tina.day@example.com")
    pid = da.create_portfolio(market, investor, "Days", Decimal("1000"), D(3))
    session = Session(market)
    session.choose_portfolio(pid, "Days")
    prompts = []
    answers = iter(["TD1", "1", "2025-03-08", "", "", ""])   # ticker, shares, Saturday, Enter (=Friday), price, pause
    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)
    monkeypatch.setattr("builtins.input", fake_input)
    portfolio_menu.trade(session, "BUY")
    out = capsys.readouterr().out
    assert "No price: 2025-03-08 is a Saturday" in out
    assert "Nearest trading days for TD1: before 2025-03-07, after 2025-03-10." in out
    date_prompts = [i for i, p in enumerate(prompts) if p.startswith("Trade date")]
    price_prompt = next(i for i, p in enumerate(prompts) if p.startswith("Price"))
    assert len(date_prompts) == 2 and date_prompts[1] < price_prompt      # asked again BEFORE the price
    assert "[Enter = 2025-03-07]" in prompts[date_prompts[1]]
    assert "Bought 1 TD1 @ 50.00 on 2025-03-07" in out
