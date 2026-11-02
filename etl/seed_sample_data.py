"""ETL B: fill portfolio_tracker with reproducible sample users.

Run from the repo root, in the conda env `spt`, after ETL A (prices):
    python -m etl.seed_sample_data              # refuses if investors exist
    python -m etl.seed_sample_data --replace    # delete all sample data first

Creates investors (Faker), portfolios, cash transactions and trades (simulated
by etl/simulate.py, inserted with CALL record_cash_transaction() / CALL
execute_trade()), watchlists, and a few UPDATE/DELETEs so trade_audit has rows.

Everything runs in ONE transaction: if the database rejects anything, the
whole seed is rolled back and nothing is left half-done.
Same --seed + same price data + same Faker version = identical data.
"""
import argparse
import logging
import random
import re
import sys
from collections import Counter
from datetime import date
from decimal import Decimal

import psycopg
from faker import Faker
from psycopg import sql

from etl.db import connect
from etl.simulate import simulate_portfolio

DEFAULT_SEED = 5200
SIM_END = date(2026, 10, 30)       # fixed, so later price refreshes don't change the data
START_FROM, START_TO = date(2021, 1, 1), date(2024, 12, 31)
N_INVESTORS = 15
CENT = Decimal("0.01")

PORTFOLIO_NAMES = ["Growth", "Retirement", "Tech Bets", "Dividend Income",
                   "Play Money", "Long Term", "Swing Trades", "College Fund"]
WATCHLIST_NAMES = ["Watching", "Big Tech", "Maybe Later", "Value Picks", "Dividend Ideas"]

# Identity columns restarted by --replace, so a rerun gets the same ids
IDENTITY_COLUMNS = [("investor", "investor_id"), ("portfolio", "portfolio_id"),
                    ("trade", "trade_id"), ("cash_transaction", "cash_txn_id"),
                    ("watchlist", "watchlist_id"), ("trade_audit", "audit_id")]

log = logging.getLogger("seed_sample_data")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Seed portfolio_tracker with sample users.")
    parser.add_argument("--replace", action="store_true",
                        help="delete ALL investors (cascades), audit rows and reset ids first")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"random seed (default {DEFAULT_SEED})")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Reading prices
# ---------------------------------------------------------------------------
def load_market(conn):
    """Closes up to SIM_END, the trading days, and the tickers."""
    closes = {}
    for ticker, day, close in conn.execute(
            "SELECT ticker, price_date, close FROM daily_price WHERE price_date <= %s",
            (SIM_END,)):
        closes[(ticker, day)] = close                 # close is already a Decimal
    days = sorted({day for _, day in closes})
    stocks = [r[0] for r in conn.execute(
        "SELECT ticker FROM stock WHERE security_type = 'STOCK' ORDER BY ticker")]
    all_tickers = [r[0] for r in conn.execute("SELECT ticker FROM stock ORDER BY ticker")]
    latest_close = {t: closes[(t, d)] for (t, d) in closes if d == days[-1]} if days else {}
    return closes, days, stocks, all_tickers, latest_close


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def clear_sample_data(conn):
    """--replace: remove all user data. Stocks and prices are kept."""
    conn.execute("DELETE FROM investor")           # cascades: portfolios, trades, cash, watchlists
    conn.execute("DELETE FROM trade_audit")        # incl. the DELETE rows the cascade just wrote
    for table, column in IDENTITY_COLUMNS:
        # sql.Identifier quotes names safely; never paste names into SQL with f-strings
        conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN {} RESTART").format(
            sql.Identifier(table), sql.Identifier(column)))


def create_investor(conn, fake, number):
    first, last = fake.first_name(), fake.last_name()
    # letters only, so names like O'Connor still give a clean address
    local = re.sub(r"[^a-z.]", "", f"{first}.{last}".lower())
    email = f"{local}{number}@example.com"           # example.com: reserved for examples
    return conn.execute(
        "INSERT INTO investor (name, email) VALUES (%s, %s) RETURNING investor_id",
        (f"{first} {last}", email)).fetchone()[0]


def create_portfolio(conn, rng, investor_id, name, market, stats):
    """Insert a portfolio and its simulated history. Returns (portfolio_id, last_event, last_trade_id)."""
    closes, days, stocks, _, _ = market
    starting_cash = Decimal(rng.randrange(10_000, 500_001, 1_000))
    start_date = rng.choice([d for d in days if START_FROM <= d <= START_TO])

    portfolio_id = conn.execute(
        """INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
           VALUES (%s, %s, %s, %s) RETURNING portfolio_id""",
        (investor_id, name, starting_cash, start_date)).fetchone()[0]

    events = simulate_portfolio(
        rng, starting_cash,
        trading_days=[d for d in days if d >= start_date],
        closes=closes, tickers=stocks,
        n_trades=rng.randint(20, 60), n_cash=rng.randint(1, 5))

    last_trade_id = None
    for e in events:
        if e.kind == "TRADE":
            # price NULL: execute_trade() uses that day's close, like the simulation
            last_trade_id = conn.execute(
                "CALL execute_trade(%s, %s, %s, %s, %s, NULL, NULL)",
                (portfolio_id, e.ticker, e.type, e.shares, e.date)).fetchone()[0]
            stats["trades"] += 1
        else:
            conn.execute(
                "CALL record_cash_transaction(%s, %s, %s, %s, NULL)",
                (portfolio_id, e.type, e.amount, e.date))
            stats["cash transactions"] += 1
    stats["portfolios"] += 1

    last_event = events[-1] if events else None
    return portfolio_id, last_event, (last_trade_id if last_event and last_event.kind == "TRADE" else None)


def create_watchlists(conn, rng, investor_id, market, stats):
    """1-2 watchlists with 3-6 items. Target: 30% reached, 50% above, 20% none."""
    _, _, _, all_tickers, latest_close = market
    for name in rng.sample(WATCHLIST_NAMES, rng.randint(1, 2)):
        watchlist_id = conn.execute(
            "INSERT INTO watchlist (investor_id, watchlist_name) VALUES (%s, %s) RETURNING watchlist_id",
            (investor_id, name)).fetchone()[0]
        stats["watchlists"] += 1
        for ticker in rng.sample(all_tickers, rng.randint(3, 6)):
            r = rng.random()
            if r < 0.3:      # already reached: target below the latest close
                target = (latest_close[ticker] * rng.randint(85, 99) / 100).quantize(CENT)
                stats["targets reached"] += 1
            elif r < 0.8:    # not reached yet
                target = (latest_close[ticker] * rng.randint(105, 130) / 100).quantize(CENT)
            else:
                target = None
            conn.execute(
                "INSERT INTO watchlist_item (watchlist_id, ticker, target_price) VALUES (%s, %s, %s)",
                (watchlist_id, ticker, target))
            stats["watchlist items"] += 1


def ensure_one_reached_target(conn, latest_close, stats):
    """Analysis query 5 needs at least one reached target. Almost always true already."""
    if stats["targets reached"] > 0:
        return
    watchlist_id, ticker = conn.execute(
        "SELECT watchlist_id, ticker FROM watchlist_item ORDER BY watchlist_id, ticker LIMIT 1").fetchone()
    conn.execute("UPDATE watchlist_item SET target_price = %s WHERE watchlist_id = %s AND ticker = %s",
                 ((latest_close[ticker] * Decimal("0.9")).quantize(CENT), watchlist_id, ticker))
    stats["targets reached"] += 1


def audit_demo(conn, rng, last_events, stats):
    """Plain UPDATE/DELETE on a few trades, so trade_audit has both kinds of rows.

    Only the LAST event of a portfolio is changed: nothing comes after it, so
    the history replay stays valid (the triggers still check it):
      - UPDATE a last BUY to 1 share fewer: cash goes up, no later SELL needs the share
      - DELETE a last trade: the state goes back to the one before it, which was valid
    """
    candidates = sorted((pid, ev, tid) for pid, ev, tid in last_events if tid is not None)
    rng.shuffle(candidates)
    updates = [c for c in candidates if c[1].type == "BUY" and c[1].shares > 1][:3]
    used = {c[0] for c in updates}
    deletes = [c for c in candidates if c[0] not in used][:3]

    for _, _, trade_id in updates:
        conn.execute("UPDATE trade SET shares = shares - 1 WHERE trade_id = %s", (trade_id,))
        stats["audit UPDATEs"] += 1
    for _, _, trade_id in deletes:
        conn.execute("DELETE FROM trade WHERE trade_id = %s", (trade_id,))
        stats["audit DELETEs"] += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    args = parse_args(argv)
    rng = random.Random(args.seed)     # our own generator: nothing else can change its sequence
    fake = Faker("en_US")
    fake.seed_instance(args.seed)
    stats = Counter()

    with connect() as conn:
        log.info("Connected to database %s, seed %s", conn.info.dbname, args.seed)
        existing = conn.execute("SELECT count(*) FROM investor").fetchone()[0]
        if existing and not args.replace:
            log.error("%s investors already exist. Use --replace to delete them and reseed.", existing)
            return 1

        # Checked BEFORE the transaction: a `return` inside `with conn.transaction():`
        # is a normal exit and would COMMIT (e.g. the --replace deletes).
        market = load_market(conn)
        if not market[1]:
            log.error("No price data. Run `make load-prices` first.")
            return 1

        try:
            with conn.transaction():
                if args.replace:
                    clear_sample_data(conn)
                    log.info("Deleted all investors and audit rows, reset ids")

                last_events = []
                for number in range(1, N_INVESTORS + 1):
                    investor_id = create_investor(conn, fake, number)
                    stats["investors"] += 1
                    for name in rng.sample(PORTFOLIO_NAMES, rng.randint(1, 3)):
                        last_events.append(create_portfolio(conn, rng, investor_id, name, market, stats))
                    create_watchlists(conn, rng, investor_id, market, stats)

                ensure_one_reached_target(conn, market[4], stats)
                audit_demo(conn, rng, last_events, stats)
        except psycopg.Error as e:
            # The database rejected something: the transaction is rolled back
            log.error("Seed rolled back. Database error [%s]: %s",
                      e.diag.constraint_name or e.sqlstate, e.diag.message_primary)
            if e.diag.message_detail:
                log.error("DETAIL: %s", e.diag.message_detail)
            return 1

    print()
    print("=== Summary ===")
    for key, label in [("investors", "Investors"), ("portfolios", "Portfolios"),
                       ("cash transactions", "Cash transactions"), ("trades", "Trades"),
                       ("watchlists", "Watchlists"), ("watchlist items", "Watchlist items"),
                       ("targets reached", "Targets reached"),
                       ("audit UPDATEs", "Audit UPDATEs"), ("audit DELETEs", "Audit DELETEs")]:
        print(f"{label + ':':22}{stats[key]}")
    print("Rejected by database:  0 (any rejection rolls back the whole seed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
