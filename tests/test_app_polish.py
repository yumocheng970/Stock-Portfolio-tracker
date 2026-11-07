"""App 2 polish: date input, ticker re-asking, one-line DETAIL errors, read-only mode."""
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, friendly_message
from app.inputs import ask_date, parse_date
from app.menus.portfolio_menu import ask_event_date, ask_ticker
from app.session import Session


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


# 1. Enter with no default: say why ------------------------------------
def test_ask_date_without_default_explains_why(monkeypatch, capsys):
    fake_input(monkeypatch, ["", "2025-03-04"])
    assert ask_date("Date", no_default_reason="no prices are loaded yet") == date(2025, 3, 4)
    out = capsys.readouterr().out
    assert "A date is required: no prices are loaded yet." in out
    assert "real date" not in out


def test_event_date_on_a_database_without_prices(conn, monkeypatch, capsys):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0
    fake_input(monkeypatch, ["", "2025-3-4"])
    assert ask_event_date(Session(conn), "Start date") == date(2025, 3, 4)
    out = capsys.readouterr().out
    assert "no prices loaded yet" in out                          # the price range hint
    assert "A date is required: no prices are loaded yet." in out


# 2. Dates without leading zeros ---------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("2026-11-6", date(2026, 11, 6)),
    ("2026-1-5", date(2026, 1, 5)),
    ("2026-01-05", date(2026, 1, 5)),
])
def test_parse_date_accepts_one_or_two_digits(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["2026/1/5", "26-1-5", "2026-1-5x", "2025-2-30", "2025-13-1", "5-1-2026"])
def test_parse_date_rejects_other_shapes_and_impossible_days(text):
    with pytest.raises(ValueError):
        parse_date(text)


# 3. Unknown ticker (or an index) is asked again ------------------------
@pytest.fixture
def stocks(conn):
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('PLX1', 'Polish Test')")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) "
                 "VALUES ('^PLX', 'Polish Index', 'INDEX')")
    investor_id = da.create_investor(conn, "Polly", "polly@example.com")
    portfolio_id = da.create_portfolio(conn, investor_id, "P", Decimal("1000"), date(2025, 3, 3))
    session = Session(conn)
    session.choose_portfolio(portfolio_id, "P")
    return session


def test_ask_ticker_reasks_unknown_and_index(stocks, monkeypatch, capsys):
    fake_input(monkeypatch, ["zzzz", "^plx", " plx1 "])
    assert ask_ticker(stocks) == "PLX1"
    out = capsys.readouterr().out
    assert "ZZZZ is not in the stock list" in out
    assert "^PLX is an index" in out
    assert "PLX1: Polish Test, you hold 0 shares" in out


def test_ask_ticker_enter_cancels(stocks, monkeypatch):
    fake_input(monkeypatch, ["zzzz", ""])
    assert ask_ticker(stocks) is None


# 4. No-price error: one clear line ---------------------------------------
def test_no_price_error_is_one_line_without_repetition(stocks):
    with pytest.raises(psycopg.Error) as caught:
        da.execute_trade(stocks.conn, stocks.portfolio_id, "PLX1", "BUY", 1, date(2025, 3, 3))
    message = friendly_message(caught.value)
    assert message == "No price for PLX1 on 2025-03-03 (not a trading day, or unknown ticker)."
    assert MESSAGES["exec_no_price_data"] not in message
    assert "\n" not in message


def test_other_trigger_errors_still_add_their_detail(stocks):
    # trg_date_before_start: message + DETAIL (the DETAIL adds the start date)
    with pytest.raises(psycopg.Error) as caught:
        da.record_cash_transaction(stocks.conn, stocks.portfolio_id, "DEPOSIT", Decimal("1"), date(2025, 1, 1))
    message = friendly_message(caught.value)
    assert message.startswith(MESSAGES["trg_date_before_start"])
    assert "starts on 2025-03-03" in message


# Extra: read-only mode (make run-readonly) --------------------------------
def test_read_only_refusal_is_friendly(conn):
    assert da.is_read_only(conn) is False
    conn.execute("SET LOCAL transaction_read_only = on")      # until the fixture's rollback
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction) as caught:
        da.create_investor(conn, "Nope", "nope@example.com")
    assert friendly_message(caught.value) == "The database is in read-only mode: nothing was changed."
