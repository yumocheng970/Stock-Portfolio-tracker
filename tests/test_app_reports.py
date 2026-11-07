"""App 5: reports and top movers (test DB, rolled back).

RP1 (sector RptSec): 05-01 close 100, 05-30 close 110, 06-30 close 99
RP2 (no sector):     05-01 close 100,                  06-30 close 50
^GSPC (index):       04-30 4000,      05-30 4400,      06-30 3960
The latest price date is 2025-06-30.
"Rpt":    10,000 from 05-01, BUY 100 RP1 @ 100 on 05-01 (May +10 %, June -10 %)
"Rpt PL": 10,000 from 05-01, BUY 5 RP1 @ 100 and BUY 10 RP2 @ 100 on 05-01,
          SELL 10 RP2 @ 50 on 06-30 (a closed position, realized -500)
"Empty":  10,000 from 05-01, no trades
"""
from datetime import date
from decimal import Decimal

import pytest
from psycopg.rows import dict_row

from app import data_access as da
from app.display import format_pct
from app.inputs import ask_month
from app.menus import market_menu, reports_menu
from app.menus.reports_menu import default_to_month, monthly_summary, pl_totals
from app.session import Session

MAY, JUNE = date(2025, 5, 1), date(2025, 6, 1)
END = date(2025, 6, 30)


@pytest.fixture
def rpt(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO sector (sector_name) VALUES ('RptSec')")
    conn.execute("INSERT INTO stock (ticker, company_name, sector_id) VALUES "
                 "('RP1', 'Report One', (SELECT sector_id FROM sector WHERE sector_name = 'RptSec')), "
                 "('RP2', 'Report Two', NULL)")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^GSPC', 'S&P 500', 'INDEX')")
    prices = [("RP1", "2025-05-01", 100), ("RP1", "2025-05-30", 110), ("RP1", "2025-06-30", 99),
              ("RP2", "2025-05-01", 100), ("RP2", "2025-06-30", 50),
              ("^GSPC", "2025-04-30", 4000), ("^GSPC", "2025-05-30", 4400), ("^GSPC", "2025-06-30", 3960)]
    for ticker, day, close in prices:
        conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, %s, %s, %s, 0)",
                     (ticker, day, close, close + 5, close - 5, close))
    investor_id = da.create_investor(conn, "Rita Report", "rita.report@example.com")
    ids = {name: da.create_portfolio(conn, investor_id, name, Decimal("10000"), MAY)
           for name in ("Rpt", "Rpt PL", "Empty")}
    da.execute_trade(conn, ids["Rpt"], "RP1", "BUY", 100, MAY)
    da.execute_trade(conn, ids["Rpt PL"], "RP1", "BUY", 5, MAY)
    da.execute_trade(conn, ids["Rpt PL"], "RP2", "BUY", 10, MAY)
    da.execute_trade(conn, ids["Rpt PL"], "RP2", "SELL", 10, END)
    return conn, ids


def session_for(conn, portfolio_id):
    session = Session(conn)
    session.choose_portfolio(portfolio_id, "test")
    return session


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def direct(conn, sql, params):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(sql, params).fetchall()


# 1. Each wrapper returns exactly what its SQL function returns ----------
def test_monthly_returns_wrapper_equals_function(rpt):
    conn, ids = rpt
    assert da.monthly_returns(conn, ids["Rpt"], None, JUNE) == \
        direct(conn, "SELECT * FROM fn_monthly_returns(%s, NULL, %s)", (ids["Rpt"], JUNE))


def test_sector_allocation_wrapper_equals_function(rpt):
    conn, ids = rpt
    assert da.sector_allocation(conn, ids["Rpt"], END) == \
        direct(conn, "SELECT * FROM fn_sector_allocation(%s, %s, true)", (ids["Rpt"], END))


def test_holding_pl_wrapper_equals_function(rpt):
    conn, ids = rpt
    assert da.holding_pl(conn, ids["Rpt PL"], END) == \
        direct(conn, "SELECT * FROM fn_holding_pl(%s, %s)", (ids["Rpt PL"], END))


def test_top_movers_wrapper_equals_function(rpt):
    conn, _ = rpt
    assert da.top_movers(conn, MAY, END) == \
        direct(conn, "SELECT * FROM fn_top_movers(%s, %s, 5)", (MAY, END))


# 2. Monthly returns: cumulative line = last row; to-month default ---------
def test_monthly_summary_matches_last_row(rpt):
    conn, ids = rpt
    rows = da.monthly_returns(conn, ids["Rpt"], None, JUNE)
    summary = monthly_summary(rows)
    assert (summary["cum_portfolio"], summary["cum_spx"]) == \
           (rows[-1]["cum_portfolio_pct"], rows[-1]["cum_spx_pct"]) == (Decimal("-1.00"), Decimal("-1.00"))
    assert summary["verdict"] == "the portfolio matched the S&P 500."


@pytest.mark.parametrize("portfolio, spx, verdict", [
    ("5.00", "2.50", "the portfolio beat the S&P 500 by 2.50 points."),
    ("-3.00", "4.00", "the portfolio trailed the S&P 500 by 7.00 points."),
])
def test_monthly_summary_verdicts(portfolio, spx, verdict):
    rows = [{"cum_portfolio_pct": Decimal("1"), "cum_spx_pct": Decimal("1")},
            {"cum_portfolio_pct": Decimal(portfolio), "cum_spx_pct": Decimal(spx)}]
    assert monthly_summary(rows)["verdict"] == verdict


def test_to_month_default_is_the_latest_price_month(rpt, monkeypatch, capsys):
    conn, ids = rpt
    session = session_for(conn, ids["Rpt"])
    assert default_to_month(session) == JUNE                     # month of 2025-06-30
    # The SQL function's own default (to = current month) would end with a flat month:
    assert da.monthly_returns(conn, ids["Rpt"])[-1]["month"] == date.today().replace(day=1)
    fake_input(monkeypatch, ["", "", "", ""])                     # from, to, save chart? (no), pause
    reports_menu.monthly_report(session)
    out = capsys.readouterr().out
    assert "2025-06 " in out and date.today().strftime("%Y-%m") + " " not in out
    assert "Cumulative 2025-05 to 2025-06: portfolio -1.00 % vs S&P 500 -1.00 %" in out


# 3. P/L totals --------------------------------------------------------------
def test_pl_totals_equal_the_sum_of_rows(rpt, monkeypatch, capsys):
    conn, ids = rpt
    rows = da.holding_pl(conn, ids["Rpt PL"], END)
    totals = pl_totals(rows)
    for key in ("unrealized_pl", "realized_pl", "total_pl"):
        assert totals[key] == sum(row[key] for row in rows)
    assert totals["realized_pl"] == Decimal("-500.00")             # RP2: sold 10 @ 50, bought @ 100
    fake_input(monkeypatch, ["", ""])                             # as of (Enter), pause
    reports_menu.pl_report(session_for(conn, ids["Rpt PL"]))
    out = capsys.readouterr().out
    assert "closed" in out and "open" in out
    assert f"realized {totals['realized_pl']:,.2f}" in out


# 4. A portfolio with no trades: clear messages, no errors -------------------
def test_empty_portfolio_reports(rpt, monkeypatch, capsys):
    conn, ids = rpt
    session = session_for(conn, ids["Empty"])
    fake_input(monkeypatch, ["", ""])
    reports_menu.pl_report(session)
    assert "No holdings yet as of 2025-06-30." in capsys.readouterr().out
    fake_input(monkeypatch, ["", "", ""])                         # as of, save chart? (no), pause
    reports_menu.sector_report(session)
    assert "No stock holdings as of 2025-06-30: 100.00 % cash (10,000.00)." in capsys.readouterr().out
    fake_input(monkeypatch, ["", "", "", ""])                     # from, to, save chart? (no), pause
    reports_menu.monthly_report(session)
    assert "portfolio 0.00 %" in capsys.readouterr().out          # cash only: no return


def test_sector_report_before_the_start_date(rpt, monkeypatch, capsys):
    conn, ids = rpt
    fake_input(monkeypatch, ["2025-4-30", ""])
    reports_menu.sector_report(session_for(conn, ids["Rpt"]))
    assert "the portfolio had not started yet" in capsys.readouterr().out


# 5. Top movers ----------------------------------------------------------------
def test_top_movers_end_before_start_is_a_friendly_message(rpt, monkeypatch, capsys):
    conn, _ = rpt
    def must_not_be_called(*args):
        raise AssertionError("the database function should not be called")
    monkeypatch.setattr(da, "top_movers", must_not_be_called)
    fake_input(monkeypatch, ["2025-06-30", "2025-05-01", ""])
    market_menu.top_movers(Session(conn))
    assert "The end date 2025-05-01 is before the start date 2025-06-30" in capsys.readouterr().out


def test_top_movers_gainers_and_empty_losers(rpt, monkeypatch, capsys):
    conn, _ = rpt
    fake_input(monkeypatch, ["2025-05-01", "2025-05-30", "", ""])   # + "save chart?" (no); RP2 has 1 day only
    market_menu.top_movers(Session(conn))
    out = capsys.readouterr().out
    assert "RP1" in out and "+10.00 %" in out
    assert "No losers between 2025-05-01 and 2025-05-30." in out


def test_top_movers_default_dates(rpt, monkeypatch, capsys):
    conn, _ = rpt
    # Enter twice: end = the latest price date (06-30), start = 30 days earlier (05-31).
    # Every stock has only ONE price day in that range (06-30), and a move needs two
    # different days, so there are no movers: both sides get their message.
    fake_input(monkeypatch, ["", "", ""])
    market_menu.top_movers(Session(conn))
    out = capsys.readouterr().out
    assert "No gainers between 2025-05-31 and 2025-06-30." in out
    assert "No losers between 2025-05-31 and 2025-06-30." in out


# 6. Formatting and month input ---------------------------------------------
@pytest.mark.parametrize("value, signed, text", [
    (Decimal("12.345"), True, "+12.35 %"), (Decimal("-1"), True, "-1.00 %"),
    (Decimal("0"), True, "0.00 %"), (None, True, "n/a"), (Decimal("54.3"), False, "54.30 %"),
])
def test_format_pct(value, signed, text):
    assert format_pct(value, signed=signed) == text


def test_ask_month(monkeypatch, capsys):
    fake_input(monkeypatch, ["2025-13", "2025/3", "2025-3"])
    assert ask_month("From month", "first month") == date(2025, 3, 1)
    assert "year-month" in capsys.readouterr().out
    fake_input(monkeypatch, [""])
    assert ask_month("From month", "first month") is None


def test_money_display_rounds_half_up_like_postgresql():
    from app.display import format_value
    assert format_value(Decimal("2.345")) == "2.35"            # Python alone: "2.34" (half to even)
    assert format_value(Decimal("-1234.565")) == "-1,234.57"
