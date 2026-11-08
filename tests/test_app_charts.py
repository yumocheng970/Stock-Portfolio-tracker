"""Extra 1: PNG charts + CSV data (test DB, rolled back; files go to tmp_path).

Same fictional data as test_app_reports.py:
RP1 (sector RptSec) 05-01 100, 05-30 110, 06-30 99; RP2 05-01 100, 06-30 50;
^GSPC 04-30 4000, 05-30 4400, 06-30 3960. Portfolio "Rpt": BUY 100 RP1 @ 100 on 05-01.
"""
import csv
import subprocess
from datetime import date
from decimal import Decimal

import matplotlib
import pytest

from app import charts
from app import data_access as da
from app.display import print_table
from app.menus import market_menu, reports_menu
from app.session import Session

MAY, JUNE, END = date(2025, 5, 1), date(2025, 6, 1), date(2025, 6, 30)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"           # the first 8 bytes of every PNG file


@pytest.fixture
def rpt(conn):
    assert conn.execute("SELECT count(*) FROM daily_price").fetchone()[0] == 0, "run `make test` first"
    conn.execute("INSERT INTO sector (sector_name) VALUES ('RptSec')")
    conn.execute("INSERT INTO stock (ticker, company_name, sector_id) VALUES "
                 "('RP1', 'Report One', (SELECT sector_id FROM sector WHERE sector_name = 'RptSec')), "
                 "('RP2', 'Report Two', NULL)")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^GSPC', 'S&P 500', 'INDEX')")
    for ticker, day, close in [("RP1", "2025-05-01", 100), ("RP1", "2025-05-30", 110), ("RP1", "2025-06-30", 99),
                               ("RP2", "2025-05-01", 100), ("RP2", "2025-06-30", 50),
                               ("^GSPC", "2025-04-30", 4000), ("^GSPC", "2025-05-30", 4400),
                               ("^GSPC", "2025-06-30", 3960)]:
        conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, %s, %s, %s, 0)",
                     (ticker, day, close, close + 5, close - 5, close))
    investor_id = da.create_investor(conn, "Cora Chart", "cora.chart@example.com")
    portfolio_id = da.create_portfolio(conn, investor_id, "Rpt", Decimal("10000"), MAY)
    da.execute_trade(conn, portfolio_id, "RP1", "BUY", 100, MAY)
    return conn, portfolio_id


@pytest.fixture(autouse=True)
def never_open_windows(monkeypatch):
    """No window may ever open: fail if anything tries to start explorer.exe / wslpath."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"a test tried to run a program: {args}")
    monkeypatch.setattr(subprocess, "run", refuse)


def assert_png(path):
    data = path.read_bytes()
    assert len(data) > 1000 and data[:8] == PNG_SIGNATURE


def csv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def as_csv_text(rows):
    """What csv.DictWriter writes for SQL rows: str(value), None -> ''."""
    return [{k: "" if v is None else str(v) for k, v in row.items()} for row in rows]


# ---------------------------------------------------------------------
def test_backend_is_agg_so_no_window_can_open():
    assert matplotlib.get_backend().lower() == "agg"


def test_returns_chart_png_and_csv_match_the_sql_function(rpt, tmp_path):
    conn, pid = rpt
    rows = da.monthly_returns(conn, pid, None, JUNE)
    png, csv_file = charts.save_returns_chart(rows, pid, out_dir=tmp_path)
    assert png.name == f"portfolio-{pid}_returns-vs-sp500_2025-06-30.png"
    assert_png(png)
    sql_rows = conn.execute("SELECT * FROM fn_monthly_returns(%s, NULL, %s)", (pid, JUNE))
    columns = [c.name for c in sql_rows.description]
    assert csv_rows(csv_file) == as_csv_text([dict(zip(columns, r)) for r in sql_rows.fetchall()])


def test_index_levels_start_at_100():
    assert charts.index_level(Decimal("18.24")) == Decimal("118.24")
    assert charts.index_level(Decimal("-1.00")) == Decimal("99.00")


def test_sector_chart_includes_cash(rpt, tmp_path):
    conn, pid = rpt
    rows = da.sector_allocation(conn, pid, END)
    assert {r["sector_name"] for r in rows} == {"RptSec", "Cash"}
    png, csv_file = charts.save_sector_chart(rows, pid, END, out_dir=tmp_path)
    assert png.name == f"portfolio-{pid}_sector-allocation_2025-06-30.png"
    assert_png(png)
    assert csv_rows(csv_file) == as_csv_text(rows)


def test_movers_chart(rpt, tmp_path):
    conn, _ = rpt
    rows = da.top_movers(conn, MAY, END)
    png, csv_file = charts.save_movers_chart(rows, MAY, END, out_dir=tmp_path)
    assert png.name == "top-movers_2025-05-01_to_2025-06-30.png"
    assert_png(png)
    assert csv_rows(csv_file) == as_csv_text(rows)


@pytest.mark.parametrize("save, args", [
    (charts.save_returns_chart, (1,)),
    (charts.save_sector_chart, (1, END)),
    (charts.save_movers_chart, (MAY, END)),
])
def test_empty_result_writes_no_file(tmp_path, save, args):
    assert save([], *args, out_dir=tmp_path) is None
    assert list(tmp_path.iterdir()) == []


# Through the menus: the files land in charts.CHART_DIR (pointed at tmp_path) -----
def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_menu_saves_chart_and_offers_windows_in_wsl(rpt, tmp_path, monkeypatch, capsys):
    conn, pid = rpt
    monkeypatch.setattr(charts, "CHART_DIR", tmp_path)
    monkeypatch.setattr(charts, "is_wsl", lambda: True)
    opened = []
    monkeypatch.setattr(charts, "open_in_windows", opened.append)   # record instead of opening
    session = Session(conn)
    session.choose_portfolio(pid, "Rpt")
    fake_input(monkeypatch, ["", "y", "y", ""])                      # as of, save, open, pause
    reports_menu.sector_report(session)
    out = capsys.readouterr().out
    png = tmp_path / f"portfolio-{pid}_sector-allocation_2025-06-30.png"
    assert f"Saved chart: {png}" in out and png.exists()
    assert opened == [png]


def test_menu_answer_no_saves_nothing(rpt, tmp_path, monkeypatch):
    conn, _ = rpt
    monkeypatch.setattr(charts, "CHART_DIR", tmp_path)
    fake_input(monkeypatch, ["2025-05-01", "2025-06-30", "n", ""])   # start, end, no chart, pause
    market_menu.top_movers(Session(conn))
    assert list(tmp_path.iterdir()) == []


def test_charts_work_in_read_only_mode(rpt, tmp_path):
    conn, pid = rpt
    conn.execute("SET LOCAL transaction_read_only = on")             # like make run-readonly
    rows = da.monthly_returns(conn, pid, None, JUNE)                  # reading still works
    assert charts.save_returns_chart(rows, pid, out_dir=tmp_path) is not None


# Volume with thousands separators (App 6 note) -------------------------------
def test_volume_has_thousands_separators(capsys):
    print_table([{"price_date": END, "volume": 4828050000}], [("price_date", "Date"), ("volume", "Volume")],
                thousands=("volume",))
    assert "4,828,050,000" in capsys.readouterr().out


# Opening a chart: the right command per platform (mocked; nothing is ever opened) ------
def test_open_chart_per_platform(monkeypatch, tmp_path):
    png = tmp_path / "c.png"
    calls = []
    monkeypatch.setattr(charts, "open_in_windows", lambda path: calls.append(("wsl", path)))
    monkeypatch.setattr(charts.os, "startfile", lambda path: calls.append(("startfile", path)), raising=False)
    monkeypatch.setattr(charts.subprocess, "run", lambda args, **kw: calls.append(("run", args)))

    monkeypatch.setattr(charts, "is_wsl", lambda: True)                       # WSL
    assert charts.can_open_charts()
    charts.open_chart(png)

    monkeypatch.setattr(charts, "is_wsl", lambda: False)
    monkeypatch.setattr(charts.sys, "platform", "win32")                      # native Windows
    assert charts.can_open_charts()
    charts.open_chart(png)

    monkeypatch.setattr(charts.sys, "platform", "darwin")                     # macOS
    assert charts.can_open_charts()
    charts.open_chart(png)

    assert calls == [("wsl", png), ("startfile", str(png)), ("run", ["open", str(png)])]


def test_plain_linux_is_not_offered_to_open(monkeypatch):
    monkeypatch.setattr(charts, "is_wsl", lambda: False)
    monkeypatch.setattr(charts.sys, "platform", "linux")
    assert charts.can_open_charts() is False
