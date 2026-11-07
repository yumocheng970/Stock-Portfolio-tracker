"""App 4: watchlists on the test database (all rolled back).

Stocks WL1 (latest close 100), WL2 (latest close 50) and the index ^WLX
(closes 4000), prices on 2025-03-03 and 2025-03-04.
"""
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from app import data_access as da
from app.errors import MESSAGES, friendly_message
from app.inputs import CLEAR, ask_decimal
from app.menus.portfolio_menu import ask_ticker
from app.session import Session

D1, D2 = date(2025, 3, 3), date(2025, 3, 4)


@pytest.fixture
def wl(conn):
    conn.execute("INSERT INTO stock (ticker, company_name) VALUES ('WL1', 'Watch One'), ('WL2', 'Watch Two')")
    conn.execute("INSERT INTO stock (ticker, company_name, security_type) VALUES ('^WLX', 'Watch Index', 'INDEX')")
    for ticker, first, last in (("WL1", 90, 100), ("WL2", 60, 50), ("^WLX", 3900, 4000)):
        conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, %s, %s, %s, 0)",
                     (ticker, D1, first, first + 10, first - 10, first))
        conn.execute("INSERT INTO daily_price VALUES (%s, %s, %s, %s, %s, %s, 0)",
                     (ticker, D2, last, last + 10, last - 10, last))
    investor_id = da.create_investor(conn, "Wanda Watch", "wanda.watch@example.com")
    watchlist_id = da.create_watchlist(conn, investor_id, "Tech")
    return conn, investor_id, watchlist_id


def refused(func, *args):
    with pytest.raises(psycopg.Error) as caught:
        func(*args)
    return friendly_message(caught.value)


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


# ---------------------------------------------------------------------
def test_duplicate_watchlist_name_same_investor(wl):
    conn, investor_id, _ = wl
    assert refused(da.create_watchlist, conn, investor_id, "Tech") == MESSAGES["uq_watchlist_investor_name"]
    other = da.create_investor(conn, "Other", "other.wl@example.com")
    da.create_watchlist(conn, other, "Tech")                     # another investor: allowed


def test_same_ticker_twice_refused(wl):
    conn, _, wid = wl
    assert da.add_watchlist_item(conn, wid, " wl1 ") == "WL1"
    assert refused(da.add_watchlist_item, conn, wid, "WL1") == MESSAGES["pk_watchlist_item"]


def test_index_can_be_watched(wl):
    conn, _, wid = wl
    assert da.add_watchlist_item(conn, wid, "^wlx", Decimal("3950")) == "^WLX"
    item = da.list_watchlist_items(conn, wid)[0]
    assert (item["ticker"], item["close"], item["reached"]) == ("^WLX", 4000, True)


def test_unknown_ticker_reasked_and_fk_message(wl, monkeypatch, capsys):
    conn, _, _ = wl
    fake_input(monkeypatch, ["NOPE", "^wlx"])
    assert ask_ticker(Session(conn), allow_index=True) == "^WLX"     # index allowed here
    assert "NOPE is not in the stock list" in capsys.readouterr().out
    _, _, wid = wl
    assert refused(da.add_watchlist_item, conn, wid, "NOPE") == MESSAGES["fk_watchlist_item_stock"]


def test_negative_target_refused_and_clearing_sets_null(wl):
    conn, _, wid = wl
    da.add_watchlist_item(conn, wid, "WL1", Decimal("80"))
    assert refused(da.set_item_target, conn, wid, "WL1", Decimal("-5")) == MESSAGES["chk_watchlist_target_positive"]
    assert refused(da.add_watchlist_item, conn, wid, "WL2", Decimal("0")) == MESSAGES["chk_watchlist_target_positive"]
    da.set_item_target(conn, wid, "wl1", None)                  # clear
    target = conn.execute("SELECT target_price FROM watchlist_item WHERE watchlist_id = %s AND ticker = 'WL1'",
                          (wid,)).fetchone()[0]
    assert target is None
    with pytest.raises(da.NotFoundError):
        da.set_item_target(conn, wid, "WL2", Decimal("1"))     # not on the list


def test_ask_decimal_keep_clear_or_number(monkeypatch):
    fake_input(monkeypatch, [""])
    assert ask_decimal("Target", required=False, clear_word="none") is None     # keep
    fake_input(monkeypatch, ["NONE"])
    assert ask_decimal("Target", required=False, clear_word="none") is CLEAR    # clear
    fake_input(monkeypatch, ["-5"])
    assert ask_decimal("Target", required=False, clear_word="none") == Decimal("-5")  # the DB decides


def test_item_list_values(wl):
    conn, _, wid = wl
    da.add_watchlist_item(conn, wid, "WL1", Decimal("80"))     # 100 vs 80: +25.00 %, reached
    da.add_watchlist_item(conn, wid, "WL2", Decimal("100"))    # 50 vs 100: -50.00 %, not reached
    da.add_watchlist_item(conn, wid, "^WLX")                   # no target
    rows = {row["ticker"]: row for row in da.list_watchlist_items(conn, wid)}
    assert (rows["WL1"]["close"], rows["WL1"]["close_date"], rows["WL1"]["pct_vs_target"],
            rows["WL1"]["reached"]) == (100, D2, Decimal("25.00"), True)
    assert (rows["WL2"]["pct_vs_target"], rows["WL2"]["reached"]) == (Decimal("-50.00"), False)
    assert (rows["^WLX"]["target_price"], rows["^WLX"]["reached"]) == (None, None)
    listed = da.list_watchlists(conn, wl[1])[0]
    assert (listed["items"], listed["reached"]) == (3, 1)


def test_remove_item(wl):
    conn, _, wid = wl
    da.add_watchlist_item(conn, wid, "WL1")
    da.remove_watchlist_item(conn, wid, "wl1")
    assert da.list_watchlist_items(conn, wid) == []
    with pytest.raises(da.NotFoundError):
        da.remove_watchlist_item(conn, wid, "WL1")


def test_rename_and_delete_cascades_items(wl):
    conn, investor_id, wid = wl
    da.rename_watchlist(conn, investor_id, wid, "Renamed")
    da.add_watchlist_item(conn, wid, "WL1")
    da.add_watchlist_item(conn, wid, "WL2")
    assert da.delete_watchlist(conn, investor_id, wid) == 2
    assert da.list_watchlists(conn, investor_id) == []
    left = conn.execute("SELECT count(*) FROM watchlist_item WHERE watchlist_id = %s", (wid,)).fetchone()[0]
    assert left == 0
    other = da.create_investor(conn, "Not Owner", "not.owner@example.com")
    with pytest.raises(da.NotFoundError):                       # someone else's watchlist id
        da.delete_watchlist(conn, other, wid)


def test_targets_reached_matches_query_5(wl):
    conn, investor_id, wid = wl
    second = da.create_watchlist(conn, investor_id, "Index")
    da.add_watchlist_item(conn, wid, "WL1", Decimal("80"))      # reached
    da.add_watchlist_item(conn, wid, "WL2", Decimal("100"))     # not reached
    da.add_watchlist_item(conn, second, "^WLX", Decimal("4000"))  # reached (equal)
    rows = da.targets_reached(conn, investor_id)
    direct = conn.execute("SELECT watchlist_id, ticker FROM fn_watchlist_targets_reached(%s)",
                          (investor_id,)).fetchall()
    assert [(r["watchlist_id"], r["ticker"]) for r in rows] == direct
    assert sorted(r["ticker"] for r in rows) == ["WL1", "^WLX"]
