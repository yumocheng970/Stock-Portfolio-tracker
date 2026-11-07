"""Extra 2: CSV import (test DB rolled back; CSV files in pytest's tmp_path).

Fixture prices: IMP1, IMP2 close 100 on 2025-03-03 .. 2025-03-07 (low 1, high 1000),
and the sample files' tickers (AAPL, MSFT, KO, NVDA) close 100 on their dates.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import csv_import
from app import data_access as da
from app.errors import MESSAGES, friendly_message, safe_call
from app.menus import portfolio_menu
from app.session import Session

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
HEADER = "date,type,ticker,shares,price,amount\n"


@pytest.fixture
def pf(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    days = [date(2025, 3, d) for d in range(3, 8)]
    sample_days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 15), date(2026, 9, 30), date(2026, 10, 1)]
    for ticker, ticker_days in (("IMP1", days), ("IMP2", days), ("AAPL", sample_days),
                                ("MSFT", sample_days), ("KO", sample_days), ("NVDA", sample_days)):
        conn.execute("INSERT INTO stock (ticker, company_name) VALUES (%s, %s)", (ticker, f"Test {ticker}"))
        for day in ticker_days:
            conn.execute("INSERT INTO daily_price VALUES (%s, %s, 100, 1000, 1, 100, 0)", (ticker, day))
    investor = da.create_investor(conn, "Ian Import", "ian.import@example.com")
    portfolio = da.create_portfolio(conn, investor, "Imports", Decimal("10000"), date(2025, 3, 3))
    session = Session(conn)
    session.choose_portfolio(portfolio, "Imports")
    return conn, portfolio, session


def write(tmp_path, body, name="trades.csv"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def saved_rows(conn, pid):
    trades = conn.execute("SELECT count(*) FROM trade WHERE portfolio_id = %s", (pid,)).fetchone()[0]
    cash = conn.execute("SELECT count(*) FROM cash_transaction WHERE portfolio_id = %s", (pid,)).fetchone()[0]
    return trades, cash


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


# ---------------------------------------------------------------------
# A valid file
# ---------------------------------------------------------------------
def test_valid_file_imports_everything_and_matches_the_views(pf, tmp_path):
    conn, pid, _ = pf
    path = write(tmp_path, HEADER +
                 "2025-03-03,DEPOSIT,,,,500\n"
                 "2025-03-03,buy,imp1,10,,\n"          # lower case is fine
                 "2025-03-04,BUY,IMP2,5,101.50,\n"     # explicit price
                 "2025-03-05,SELL,IMP1,4,,\n"
                 "2025-03-05,WITHDRAWAL,,,,200\n")
    events, errors = csv_import.read_events(path)
    assert errors == [] and len(events) == 5
    counts = da.import_events(conn, pid, csv_import.history_order(events))
    assert counts == {"trades": 3, "cash": 2}
    cash = conn.execute("SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = %s", (pid,)).fetchone()[0]
    # 10,000 + 500 - 1,000 - 507.50 + 400 - 200
    assert cash == Decimal("9192.50") == da.cash_summary(conn, pid)["cash_balance"]
    held = dict(conn.execute("SELECT ticker, shares_held FROM v_holdings WHERE portfolio_id = %s",
                             (pid,)).fetchall())
    assert held == {"IMP1": 6, "IMP2": 5}


# ---------------------------------------------------------------------
# Shape errors: ALL listed, nothing saved
# ---------------------------------------------------------------------
def test_shape_errors_on_rows_3_and_5_are_all_listed(pf, tmp_path):
    conn, pid, _ = pf
    path = write(tmp_path, HEADER +
                 "2025-03-03,BUY,IMP1,1,,\n"           # row 2: fine
                 "2025-03-32,BUY,IMP1,1,,\n"           # row 3: bad date
                 "2025-03-04,BUY,IMP1,1,,\n"           # row 4: fine
                 "2025-03-05,TRANSFER,,,,10\n")        # row 5: unknown type
    events, errors = csv_import.read_events(path)
    assert errors == ["Row 3: date '2025-03-32' is not a real date (YYYY-MM-DD)",
                      "Row 5: type 'TRANSFER' is not BUY, SELL, DEPOSIT or WITHDRAWAL"]
    assert saved_rows(conn, pid) == (0, 0)


@pytest.mark.parametrize("line, expected", [
    ("2025-03-03,BUY,,1,,", "a trade needs a ticker"),
    ("2025-03-03,BUY,IMP1,1.5,,", "shares '1.5' is not a whole number"),
    ("2025-03-03,BUY,IMP1,1,abc,", "price 'abc' is not a number with at most 2 decimals"),
    ("2025-03-03,BUY,IMP1,1,,50", "a trade has no amount"),
    ("2025-03-03,DEPOSIT,,,,1.234", "amount '1.234' is not a number with at most 2 decimals"),
    ("2025-03-03,DEPOSIT,IMP1,,,10", "a cash row has no ticker, shares or price"),
    ("2025-03-03,DEPOSIT,,,,10,extra", "more values than columns"),
])
def test_each_shape_rule(tmp_path, line, expected):
    _, errors = csv_import.read_events(write(tmp_path, HEADER + line + "\n"))
    assert len(errors) == 1 and errors[0].startswith("Row 2: ") and expected in errors[0]


@pytest.mark.parametrize("body, expected", [
    ("", "The file is empty."),
    (HEADER, "The file has a header but no rows."),
    ("date,ticker\n2025-03-03,IMP1\n", "Missing column(s): type"),
    ("date,type,qty\n", "Unknown column(s): qty"),
])
def test_file_level_problems(tmp_path, body, expected):
    events, errors = csv_import.read_events(write(tmp_path, body))
    assert events == [] and expected in errors[0]


def test_missing_file_and_folder(tmp_path):
    assert csv_import.read_events(tmp_path / "nope.csv")[1] == [f"File not found: {tmp_path / 'nope.csv'}"]
    assert csv_import.read_events(tmp_path)[1] == [f"Not a file: {tmp_path}"]


def test_row_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(csv_import, "MAX_ROWS", 3)
    path = write(tmp_path, HEADER + "2025-03-03,DEPOSIT,,,,1\n" * 4)
    assert csv_import.read_events(path)[1] == ["More than 3 rows: please split the file."]


def test_excel_bom_and_header_spacing(tmp_path):
    path = tmp_path / "excel.csv"
    path.write_text(" Date , TYPE ,amount\n2025-03-03,DEPOSIT,10\n", encoding="utf-8-sig")   # with BOM
    events, errors = csv_import.read_events(path)
    assert errors == [] and events[0].amount == Decimal("10")


# ---------------------------------------------------------------------
# A refusal on a later row: nothing saved, the message names the row
# ---------------------------------------------------------------------
def test_db_refusal_on_a_later_row_rolls_back_everything(pf, tmp_path):
    conn, pid, _ = pf
    path = write(tmp_path, HEADER +
                 "2025-03-03,DEPOSIT,,,,500\n"
                 "2025-03-03,BUY,IMP1,10,,\n"
                 "2025-03-04,BUY,IMP2,1000,,\n"        # row 4: 100,000 > cash
                 "2025-03-05,SELL,IMP1,1,,\n")
    events, _ = csv_import.read_events(path)
    ok, _ = safe_call(da.import_events, conn, pid, csv_import.history_order(events))
    assert ok is False
    with pytest.raises(da.ImportRowError) as caught:
        da.import_events(conn, pid, csv_import.history_order(events))
    message = friendly_message(caught.value)
    assert message.startswith("Row 4: " + MESSAGES["trg_cash_never_negative"])
    assert "Cash would be -90,500.00 on 2025-03-04" in message      # 10,500 - 1,000 - 100,000
    assert saved_rows(conn, pid) == (0, 0)                          # rows 2 and 3 rolled back too


def test_history_order_puts_cash_first_and_keeps_row_numbers(pf, tmp_path):
    conn, pid, _ = pf
    # The buy (row 2) needs the deposit (row 3) of the same day; the 03-03 row comes last
    path = write(tmp_path, HEADER +
                 "2025-03-04,BUY,IMP1,150,,\n"         # 15,000: only possible after the deposit
                 "2025-03-04,DEPOSIT,,,,6000\n"
                 "2025-03-03,BUY,IMP2,1,,\n")
    events, _ = csv_import.read_events(path)
    ordered = csv_import.history_order(events)
    assert [e.row for e in ordered] == [4, 3, 2]
    assert csv_import.preview(events)["reordered"] is True
    assert da.import_events(conn, pid, ordered) == {"trades": 2, "cash": 1}


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
@pytest.mark.parametrize("typed, expected", [
    (r"C:\Users\me\Desktop\trades.csv", "/mnt/c/Users/me/Desktop/trades.csv"),
    (r'"D:\data\my trades.csv"', "/mnt/d/data/my trades.csv"),        # quotes from "Copy as path"
    ("c:/Users/me/a.csv", "/mnt/c/Users/me/a.csv"),
    ("data/samples/import_valid.csv", "data/samples/import_valid.csv"),
])
def test_to_linux_path(typed, expected):
    assert csv_import.to_linux_path(typed) == Path(expected)


def test_home_folder_is_expanded():
    assert csv_import.to_linux_path("~/a.csv") == Path.home() / "a.csv"


# ---------------------------------------------------------------------
# The sample files (data/samples/) behave as described
# ---------------------------------------------------------------------
def sample_portfolio(conn):
    investor = da.create_investor(conn, "Sam Sample", "sam.sample@example.com")
    return da.create_portfolio(conn, investor, "Sample", Decimal("10000"), date(2026, 9, 1))


def test_sample_valid_file(pf):
    conn, _, _ = pf
    pid = sample_portfolio(conn)
    events, errors = csv_import.read_events(SAMPLES / "import_valid.csv")
    assert errors == [] and csv_import.preview(events)["reordered"] is True
    assert da.import_events(conn, pid, csv_import.history_order(events)) == {"trades": 5, "cash": 2}


def test_sample_failing_file(pf):
    conn, _, _ = pf
    pid = sample_portfolio(conn)
    events, errors = csv_import.read_events(SAMPLES / "import_fails_row_6.csv")
    assert errors == []
    with pytest.raises(da.ImportRowError) as caught:
        da.import_events(conn, pid, csv_import.history_order(events))
    assert friendly_message(caught.value).startswith("Row 6: Not enough cash. Cash would be")
    assert saved_rows(conn, pid) == (0, 0)


# ---------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------
def test_menu_import_confirmed(pf, tmp_path, monkeypatch, capsys):
    conn, pid, session = pf
    path = write(tmp_path, HEADER + "2025-03-03,BUY,IMP1,2,,\n2025-03-03,DEPOSIT,,,,100\n")
    fake_input(monkeypatch, [str(path), "y", ""])
    portfolio_menu.import_csv(session)
    out = capsys.readouterr().out
    assert "1 trades and 1 cash transactions, 2025-03-03 to 2025-03-03" in out
    assert "Rows will be imported in history order" in out
    assert "Imported 1 trades and 1 cash transactions." in out and "Cash now: 9,900.00" in out


def test_menu_import_declined_or_bad_file_saves_nothing(pf, tmp_path, monkeypatch, capsys):
    conn, pid, session = pf
    path = write(tmp_path, HEADER + "2025-03-03,BUY,IMP1,2,,\n")
    fake_input(monkeypatch, [str(path), "n", ""])
    portfolio_menu.import_csv(session)
    bad = write(tmp_path, HEADER + "x,BUY,IMP1,2,,\n", name="bad.csv")
    fake_input(monkeypatch, [str(bad), ""])
    portfolio_menu.import_csv(session)
    out = capsys.readouterr().out
    assert "Nothing was imported." in out
    assert "The file has 1 problem(s); nothing was saved:" in out and "Row 2: date 'x'" in out
    assert saved_rows(conn, pid) == (0, 0)


def test_menu_import_refused_in_read_only_mode(pf, tmp_path, monkeypatch, capsys):
    conn, pid, session = pf
    monkeypatch.setattr(da, "is_read_only", lambda conn: True)      # like make run-readonly
    fake_input(monkeypatch, [""])                                    # only the pause
    portfolio_menu.import_csv(session)
    assert "Import is not possible in read-only mode: nothing was changed." in capsys.readouterr().out
    assert saved_rows(conn, pid) == (0, 0)
