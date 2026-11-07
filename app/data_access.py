"""Data access: ALL SQL of the app lives in this module.

Rules:
- Every function takes the connection `conn` as its first argument.
- Every function runs inside `with conn.transaction():`. If the block finishes,
  the changes are committed; if an exception escapes it, they are rolled back.
  (The connection is in autocommit mode, see etl/db.py, so this block IS the
  transaction. Inside another transaction it becomes a savepoint, which the
  tests use to undo everything.)
- Rows come back as dicts: row["email"] instead of row[2].
- No business rules here: the database checks them (CHECK, UNIQUE, triggers).
  Errors are passed on unchanged; the menus show them via errors.safe_call().
"""
import psycopg
from psycopg.rows import dict_row


class NotFoundError(Exception):
    """The row the user chose doesn't exist (any more)."""


def _fetch_all(conn, sql, params=()):
    """Run a SELECT and return all rows as a list of dicts."""
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _fetch_one(conn, sql, params=()):
    """Run a statement and return its first row as a dict (None if no row)."""
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchone()


# ---------------------------------------------------------------------
# General
# ---------------------------------------------------------------------
def database_name(conn):
    """Name of the connected database (shown in the app's title)."""
    return _fetch_one(conn, "SELECT current_database() AS name")["name"]


def is_read_only(conn):
    """True when the session's transactions are read-only (make run-readonly)."""
    return _fetch_one(conn, "SELECT current_setting('default_transaction_read_only') = 'on' AS ro")["ro"]


# ---------------------------------------------------------------------
# investor
# ---------------------------------------------------------------------
def list_investors(conn):
    """All investors with how many portfolios and watchlists each has."""
    return _fetch_all(conn, """
        SELECT i.investor_id, i.name, i.email, i.created_date,
               (SELECT count(*) FROM portfolio p WHERE p.investor_id = i.investor_id) AS portfolios,
               (SELECT count(*) FROM watchlist w WHERE w.investor_id = i.investor_id) AS watchlists
        FROM investor i
        ORDER BY i.investor_id
    """)


def get_investor(conn, investor_id):
    """One investor as a dict, or None if there is no such id."""
    return _fetch_one(conn, """
        SELECT investor_id, name, email, created_date
        FROM investor WHERE investor_id = %s
    """, (investor_id,))


def create_investor(conn, name, email):
    """Insert an investor and return the new investor_id."""
    row = _fetch_one(conn, """
        INSERT INTO investor (name, email) VALUES (%s, %s)
        RETURNING investor_id
    """, (name.strip(), email.strip()))
    return row["investor_id"]


def update_investor(conn, investor_id, name=None, email=None):
    """Change the name and/or email. None means "keep the current value"."""
    row = _fetch_one(conn, """
        UPDATE investor
        SET name  = COALESCE(%s, name),
            email = COALESCE(%s, email)
        WHERE investor_id = %s
        RETURNING investor_id
    """, (name.strip() if name is not None else None,
          email.strip() if email is not None else None,
          investor_id))
    if row is None:
        raise NotFoundError(f"Investor {investor_id} doesn't exist (any more).")


def investor_delete_summary(conn, investor_id):
    """What deleting this investor would also delete (the FK cascades)."""
    return _fetch_one(conn, """
        SELECT (SELECT count(*) FROM portfolio WHERE investor_id = %(id)s) AS portfolios,
               (SELECT count(*) FROM trade t JOIN portfolio p USING (portfolio_id)
                 WHERE p.investor_id = %(id)s) AS trades,
               (SELECT count(*) FROM cash_transaction c JOIN portfolio p USING (portfolio_id)
                 WHERE p.investor_id = %(id)s) AS cash_transactions,
               (SELECT count(*) FROM watchlist WHERE investor_id = %(id)s) AS watchlists
    """, {"id": investor_id})


def delete_investor(conn, investor_id):
    """Delete an investor. The database cascades to portfolios (and their trades
    and cash transactions) and watchlists; deleted trades are copied to trade_audit."""
    row = _fetch_one(conn, """
        DELETE FROM investor WHERE investor_id = %s
        RETURNING investor_id
    """, (investor_id,))
    if row is None:
        raise NotFoundError(f"Investor {investor_id} doesn't exist (any more).")


# ---------------------------------------------------------------------
# Dates: defaults and hints for the date prompts
# ---------------------------------------------------------------------
def price_date_range(conn):
    """First and last date that has prices (any ticker): {"first": date, "last": date}.
    Both are None in an empty database."""
    return _fetch_one(conn, """
        SELECT min(price_date) AS first, max(price_date) AS last FROM daily_price
    """)


def default_event_date(conn, portfolio_id=None):
    """The date offered when the user presses Enter at a date prompt:
    the latest price date, or the portfolio's latest allowed date if that is
    later. (Not "today": prices load only up to yesterday, and new events must
    not be before the portfolio's latest event, so "today" would block trading.)
    Returns None if there are no prices and no portfolio."""
    row = _fetch_one(conn, """
        SELECT GREATEST(
                   (SELECT max(price_date) FROM daily_price),
                   (SELECT start_date FROM portfolio WHERE portfolio_id = %(id)s),
                   (SELECT max(trade_date) FROM trade WHERE portfolio_id = %(id)s),
                   (SELECT max(txn_date) FROM cash_transaction WHERE portfolio_id = %(id)s)
               ) AS default_date
    """, {"id": portfolio_id})
    return row["default_date"]


# ---------------------------------------------------------------------
# portfolio
# ---------------------------------------------------------------------
def list_portfolios(conn, investor_id):
    """The investor's portfolios with cash, market value (today's closes) and total."""
    return _fetch_all(conn, """
        SELECT p.portfolio_id, p.portfolio_name, p.start_date, p.starting_cash,
               cb.cash_balance                                  AS cash,
               COALESCE(mv.market_value, 0)                     AS market_value,
               cb.cash_balance + COALESCE(mv.market_value, 0)   AS total_value
        FROM portfolio p
        JOIN v_cash_balance cb ON cb.portfolio_id = p.portfolio_id
        LEFT JOIN LATERAL (
            SELECT SUM(h.market_value) AS market_value
            FROM fn_holding_pl(p.portfolio_id) h
        ) mv ON true
        WHERE p.investor_id = %s
        ORDER BY p.portfolio_id
    """, (investor_id,))


def get_portfolio(conn, portfolio_id):
    """One portfolio as a dict, or None."""
    return _fetch_one(conn, """
        SELECT portfolio_id, investor_id, portfolio_name, starting_cash, start_date, created_date
        FROM portfolio WHERE portfolio_id = %s
    """, (portfolio_id,))


def create_portfolio(conn, investor_id, name, starting_cash, start_date):
    """Insert a portfolio and return the new portfolio_id."""
    row = _fetch_one(conn, """
        INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (%s, %s, %s, %s)
        RETURNING portfolio_id
    """, (investor_id, name.strip(), starting_cash, start_date))
    return row["portfolio_id"]


def rename_portfolio(conn, portfolio_id, name):
    row = _fetch_one(conn, """
        UPDATE portfolio SET portfolio_name = %s WHERE portfolio_id = %s
        RETURNING portfolio_id
    """, (name.strip(), portfolio_id))
    if row is None:
        raise NotFoundError(f"Portfolio {portfolio_id} doesn't exist (any more).")


def portfolio_delete_summary(conn, portfolio_id):
    """What deleting this portfolio would also delete (the FK cascades)."""
    return _fetch_one(conn, """
        SELECT (SELECT count(*) FROM trade WHERE portfolio_id = %(id)s)            AS trades,
               (SELECT count(*) FROM cash_transaction WHERE portfolio_id = %(id)s) AS cash_transactions
    """, {"id": portfolio_id})


def delete_portfolio(conn, portfolio_id):
    """Delete a portfolio; its trades (copied to trade_audit) and cash transactions cascade."""
    row = _fetch_one(conn, """
        DELETE FROM portfolio WHERE portfolio_id = %s
        RETURNING portfolio_id
    """, (portfolio_id,))
    if row is None:
        raise NotFoundError(f"Portfolio {portfolio_id} doesn't exist (any more).")


def cash_summary(conn, portfolio_id):
    """Cash breakdown from v_cash_balance (current balance, all events)."""
    return _fetch_one(conn, """
        SELECT starting_cash, deposits, withdrawals, buys, sells, cash_balance
        FROM v_cash_balance WHERE portfolio_id = %s
    """, (portfolio_id,))


def open_holdings(conn, portfolio_id):
    """Open positions valued at the latest close on or before today (fn_holding_pl)."""
    return _fetch_all(conn, """
        SELECT ticker, shares_held, avg_cost, cost_basis, close_date, close,
               market_value, unrealized_pl
        FROM fn_holding_pl(%s)
        WHERE shares_held > 0
        ORDER BY ticker
    """, (portfolio_id,))


# ---------------------------------------------------------------------
# Hints shown before a trade or cash transaction (the database decides)
# ---------------------------------------------------------------------
def trade_context(conn, portfolio_id):
    """Cash now, and the earliest date a new event may have (latest event or start_date)."""
    return _fetch_one(conn, """
        SELECT cb.cash_balance AS cash,
               GREATEST(p.start_date,
                        (SELECT max(trade_date) FROM trade WHERE portfolio_id = p.portfolio_id),
                        (SELECT max(txn_date) FROM cash_transaction WHERE portfolio_id = p.portfolio_id)
               ) AS latest_allowed
        FROM portfolio p
        JOIN v_cash_balance cb ON cb.portfolio_id = p.portfolio_id
        WHERE p.portfolio_id = %s
    """, (portfolio_id,))


def ticker_context(conn, portfolio_id, ticker):
    """Company name and type (None if the ticker is unknown), shares held now,
    and the ticker's latest price date. The ticker is normalized like
    execute_trade does (trim + upper case)."""
    return _fetch_one(conn, """
        WITH t AS (SELECT upper(btrim(%(ticker)s)) AS ticker)
        SELECT t.ticker,
               s.company_name, s.security_type,
               COALESCE((SELECT h.shares_held FROM v_holdings h
                         WHERE h.portfolio_id = %(id)s AND h.ticker = t.ticker), 0) AS shares_held,
               (SELECT max(price_date) FROM daily_price dp WHERE dp.ticker = t.ticker) AS last_price_date
        FROM t
        LEFT JOIN stock s ON s.ticker = t.ticker
    """, {"id": portfolio_id, "ticker": ticker})


def price_on(conn, ticker, day):
    """That day's low / high / close for a ticker, or None if there is no price row."""
    return _fetch_one(conn, """
        SELECT low, high, close FROM daily_price
        WHERE ticker = upper(btrim(%s)) AND price_date = %s
    """, (ticker, day))


# ---------------------------------------------------------------------
# trade / cash_transaction: through the procedures
# ---------------------------------------------------------------------
def get_trade(conn, trade_id):
    return _fetch_one(conn, """
        SELECT trade_id, portfolio_id, ticker, trade_type, shares, price, trade_date
        FROM trade WHERE trade_id = %s
    """, (trade_id,))


def execute_trade(conn, portfolio_id, ticker, trade_type, shares, day, price=None):
    """CALL execute_trade(); price None = that day's close. Returns the new trade row
    (so the caller can show the price actually used)."""
    with conn.transaction():
        # The last argument is the INOUT p_trade_id: we pass NULL, and CALL
        # returns one row with its final value.
        row = _fetch_one(conn, "CALL execute_trade(%s, %s, %s, %s, %s, %s, NULL)",
                         (portfolio_id, ticker, trade_type, shares, day, price))
        return get_trade(conn, row["p_trade_id"])


def record_cash_transaction(conn, portfolio_id, txn_type, amount, day):
    """CALL record_cash_transaction(); returns the new cash_txn_id."""
    row = _fetch_one(conn, "CALL record_cash_transaction(%s, %s, %s, %s, NULL)",
                     (portfolio_id, txn_type, amount, day))
    return row["p_cash_txn_id"]


# ---------------------------------------------------------------------
# Trade history, edit / delete, audit log, restore (App 3)
# Every function takes the portfolio_id too, so a trade or audit row of
# another portfolio can never be touched through this portfolio's menu.
# ---------------------------------------------------------------------
def list_trades(conn, portfolio_id, ticker=None):
    """The portfolio's trades in history order (date, then trade_id: the
    order the balance replay uses for trades). ticker None = all tickers."""
    return _fetch_all(conn, """
        SELECT trade_id, trade_date, trade_type, ticker, shares, price,
               shares * price AS amount
        FROM trade
        WHERE portfolio_id = %(id)s
          AND (%(ticker)s::text IS NULL OR ticker = upper(btrim(%(ticker)s::text)))
        ORDER BY trade_date, trade_id
    """, {"id": portfolio_id, "ticker": ticker})


def get_portfolio_trade(conn, portfolio_id, trade_id):
    """One trade of this portfolio, with that day's low/high (None if not found)."""
    return _fetch_one(conn, """
        SELECT t.trade_id, t.trade_date, t.trade_type, t.ticker, t.shares, t.price,
               t.shares * t.price AS amount, dp.low, dp.high
        FROM trade t
        LEFT JOIN daily_price dp ON dp.ticker = t.ticker AND dp.price_date = t.trade_date
        WHERE t.portfolio_id = %s AND t.trade_id = %s
    """, (portfolio_id, trade_id))


def update_trade(conn, portfolio_id, trade_id, shares=None, price=None):
    """Change shares and/or price (None = keep). The triggers check the price
    range, write the audit row and replay the history; a refusal rolls back."""
    row = _fetch_one(conn, """
        UPDATE trade
        SET shares = COALESCE(%s, shares),
            price  = COALESCE(%s, price)
        WHERE portfolio_id = %s AND trade_id = %s
        RETURNING trade_id
    """, (shares, price, portfolio_id, trade_id))
    if row is None:
        raise NotFoundError(f"This portfolio has no trade {trade_id}.")


def delete_trade(conn, portfolio_id, trade_id):
    """Delete one trade (copied to trade_audit by the trigger; history replayed)."""
    row = _fetch_one(conn, """
        DELETE FROM trade WHERE portfolio_id = %s AND trade_id = %s
        RETURNING trade_id
    """, (portfolio_id, trade_id))
    if row is None:
        raise NotFoundError(f"This portfolio has no trade {trade_id}.")


def audit_log(conn, portfolio_id, only_deletes=False):
    """This portfolio's trade_audit rows (only_deletes=True: just the DELETE
    rows, for choosing a trade to restore), newest first, with a status for
    DELETE rows: 'restorable' (the trade is gone and this is its newest audit
    row) or 'restored' (the trade is back). Same rules as restore_trade()."""
    return _fetch_all(conn, """
        SELECT a.audit_id, a.operation, a.changed_at, a.changed_by, a.trade_id,
               a.trade_date, a.trade_type, a.ticker, a.shares, a.price,
               CASE
                   WHEN a.operation <> 'DELETE' THEN ''
                   WHEN a.audit_id <> (SELECT max(b.audit_id) FROM trade_audit b
                                       WHERE b.trade_id = a.trade_id) THEN ''
                   WHEN EXISTS (SELECT 1 FROM trade t WHERE t.trade_id = a.trade_id) THEN 'restored'
                   ELSE 'restorable'
               END AS status
        FROM trade_audit a
        WHERE a.portfolio_id = %s
          AND (NOT %s OR a.operation = 'DELETE')
        ORDER BY a.audit_id DESC
    """, (portfolio_id, only_deletes))


def restore_trade(conn, portfolio_id, audit_id):
    """CALL restore_trade(): put a deleted trade back as it was (original
    trade_id, date, ticker, shares, price). Returns the restored trade row."""
    with conn.transaction():
        owner = _fetch_one(conn, "SELECT portfolio_id FROM trade_audit WHERE audit_id = %s",
                           (audit_id,))
        if owner is None or owner["portfolio_id"] != portfolio_id:
            raise NotFoundError(f"This portfolio has no audit row {audit_id}.")
        row = _fetch_one(conn, "CALL restore_trade(%s, NULL)", (audit_id,))
        return get_portfolio_trade(conn, portfolio_id, row["p_trade_id"])


# ---------------------------------------------------------------------
# watchlist / watchlist_item (App 4)
# Functions take the investor_id or watchlist_id they act on, and filter by
# it, so another investor's watchlist can't be touched from this menu.
# "Reached" always comes from fn_watchlist_targets_reached (analysis query 5),
# so the app and the report use one definition: latest close >= target.
# ---------------------------------------------------------------------
def list_watchlists(conn, investor_id):
    """The investor's watchlists with the number of items and of targets reached."""
    return _fetch_all(conn, """
        SELECT w.watchlist_id, w.watchlist_name, w.created_date,
               (SELECT count(*) FROM watchlist_item wi WHERE wi.watchlist_id = w.watchlist_id) AS items,
               COALESCE(r.reached, 0) AS reached
        FROM watchlist w
        LEFT JOIN (SELECT f.watchlist_id, count(*) AS reached
                   FROM fn_watchlist_targets_reached(%(id)s) f
                   GROUP BY f.watchlist_id) r ON r.watchlist_id = w.watchlist_id
        WHERE w.investor_id = %(id)s
        ORDER BY w.watchlist_id
    """, {"id": investor_id})


def create_watchlist(conn, investor_id, name):
    row = _fetch_one(conn, """
        INSERT INTO watchlist (investor_id, watchlist_name) VALUES (%s, %s)
        RETURNING watchlist_id
    """, (investor_id, name.strip()))
    return row["watchlist_id"]


def rename_watchlist(conn, investor_id, watchlist_id, name):
    row = _fetch_one(conn, """
        UPDATE watchlist SET watchlist_name = %s
        WHERE investor_id = %s AND watchlist_id = %s
        RETURNING watchlist_id
    """, (name.strip(), investor_id, watchlist_id))
    if row is None:
        raise NotFoundError(f"You have no watchlist {watchlist_id}.")


def delete_watchlist(conn, investor_id, watchlist_id):
    """Delete a watchlist; its items cascade. Returns how many items went with it."""
    with conn.transaction():
        items = _fetch_one(conn, "SELECT count(*) AS n FROM watchlist_item WHERE watchlist_id = %s",
                           (watchlist_id,))["n"]
        row = _fetch_one(conn, """
            DELETE FROM watchlist WHERE investor_id = %s AND watchlist_id = %s
            RETURNING watchlist_id
        """, (investor_id, watchlist_id))
        if row is None:
            raise NotFoundError(f"You have no watchlist {watchlist_id}.")
        return items


def list_watchlist_items(conn, watchlist_id):
    """Items with company, latest close (on or before today), target,
    % from target and reached (NULL when there is no target)."""
    return _fetch_all(conn, """
        SELECT wi.ticker, s.company_name, c.price_date AS close_date, c.close, wi.target_price,
               ROUND(100 * (c.close - wi.target_price) / wi.target_price, 2) AS pct_vs_target,
               CASE WHEN wi.target_price IS NULL THEN NULL
                    ELSE r.ticker IS NOT NULL END AS reached
        FROM watchlist_item wi
        JOIN watchlist w ON w.watchlist_id = wi.watchlist_id
        JOIN stock s     ON s.ticker = wi.ticker
        LEFT JOIN LATERAL (
            SELECT dp.price_date, dp.close FROM daily_price dp
            WHERE dp.ticker = wi.ticker AND dp.price_date <= CURRENT_DATE
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) c ON true
        LEFT JOIN fn_watchlist_targets_reached(w.investor_id) r
               ON r.watchlist_id = wi.watchlist_id AND r.ticker = wi.ticker
        WHERE wi.watchlist_id = %s
        ORDER BY wi.ticker
    """, (watchlist_id,))


def add_watchlist_item(conn, watchlist_id, ticker, target_price=None):
    """Add a ticker (trimmed, upper case) with an optional target price."""
    row = _fetch_one(conn, """
        INSERT INTO watchlist_item (watchlist_id, ticker, target_price)
        VALUES (%s, upper(btrim(%s)), %s)
        RETURNING ticker
    """, (watchlist_id, ticker, target_price))
    return row["ticker"]


def set_item_target(conn, watchlist_id, ticker, target_price):
    """Set the target price; None clears it (no target)."""
    row = _fetch_one(conn, """
        UPDATE watchlist_item SET target_price = %s
        WHERE watchlist_id = %s AND ticker = upper(btrim(%s))
        RETURNING ticker
    """, (target_price, watchlist_id, ticker))
    if row is None:
        raise NotFoundError(f"{ticker.strip().upper()} is not on this watchlist.")


def remove_watchlist_item(conn, watchlist_id, ticker):
    row = _fetch_one(conn, """
        DELETE FROM watchlist_item WHERE watchlist_id = %s AND ticker = upper(btrim(%s))
        RETURNING ticker
    """, (watchlist_id, ticker))
    if row is None:
        raise NotFoundError(f"{ticker.strip().upper()} is not on this watchlist.")


def targets_reached(conn, investor_id):
    """All of the investor's items whose latest close >= target (analysis query 5)."""
    return _fetch_all(conn, """
        SELECT watchlist_id, watchlist_name, ticker, target_price, close_date,
               latest_close, pct_above_target
        FROM fn_watchlist_targets_reached(%s)
    """, (investor_id,))


# ---------------------------------------------------------------------
# Reports (App 5): thin wrappers, exactly the analysis functions' output.
# The ::type casts tell PostgreSQL the parameter types when a value is None.
# ---------------------------------------------------------------------
def monthly_returns(conn, portfolio_id, from_month=None, to_month=None):
    """Analysis query 1: monthly return vs the S&P 500 (Modified Dietz)."""
    return _fetch_all(conn, "SELECT * FROM fn_monthly_returns(%s::int, %s::date, %s::date)",
                      (portfolio_id, from_month, to_month))


def sector_allocation(conn, portfolio_id, as_of=None, include_cash=True):
    """Analysis query 2: market value and % per sector (plus a Cash row)."""
    return _fetch_all(conn, "SELECT * FROM fn_sector_allocation(%s::int, %s::date, %s::boolean)",
                      (portfolio_id, as_of, include_cash))


def holding_pl(conn, portfolio_id, as_of=None):
    """Analysis query 4: realized / unrealized P/L per holding (open and closed)."""
    return _fetch_all(conn, "SELECT * FROM fn_holding_pl(%s::int, %s::date)",
                      (portfolio_id, as_of))


def top_movers(conn, start, end=None, limit=5):
    """Analysis query 3: top gainers and losers between two dates (ties kept)."""
    return _fetch_all(conn, "SELECT * FROM fn_top_movers(%s::date, %s::date, %s::int)",
                      (start, end, limit))


# ---------------------------------------------------------------------
# Market data and admin (App 6)
# ---------------------------------------------------------------------
def list_stocks(conn, sector_id=None):
    """Stocks (and the index) with sector, exchange, type and latest close (on or
    before today). sector_id None = all."""
    return _fetch_all(conn, """
        SELECT s.ticker, s.company_name, sec.sector_name, ex.exchange_name, s.security_type,
               c.close, c.price_date AS close_date
        FROM stock s
        LEFT JOIN sector sec  ON sec.sector_id  = s.sector_id
        LEFT JOIN exchange ex ON ex.exchange_id = s.exchange_id
        LEFT JOIN LATERAL (
            SELECT dp.close, dp.price_date FROM daily_price dp
            WHERE dp.ticker = s.ticker AND dp.price_date <= CURRENT_DATE
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) c ON true
        WHERE %(sector)s::int IS NULL OR s.sector_id = %(sector)s::int
        ORDER BY s.security_type DESC, s.ticker          -- STOCK before INDEX
    """, {"sector": sector_id})


def get_stock(conn, ticker):
    """One stock with its sector and exchange names, or None."""
    return _fetch_one(conn, """
        SELECT s.ticker, s.company_name, s.security_type, sec.sector_name, ex.exchange_name
        FROM stock s
        LEFT JOIN sector sec  ON sec.sector_id  = s.sector_id
        LEFT JOIN exchange ex ON ex.exchange_id = s.exchange_id
        WHERE s.ticker = upper(btrim(%s))
    """, (ticker,))


def list_sectors(conn):
    return _fetch_all(conn, """
        SELECT sec.sector_id, sec.sector_name,
               (SELECT count(*) FROM stock s WHERE s.sector_id = sec.sector_id) AS stocks
        FROM sector sec ORDER BY sec.sector_name
    """)


def list_exchanges(conn):
    return _fetch_all(conn, """
        SELECT ex.exchange_id, ex.exchange_name,
               (SELECT count(*) FROM stock s WHERE s.exchange_id = ex.exchange_id) AS stocks
        FROM exchange ex ORDER BY ex.exchange_name
    """)


def price_window(conn, ticker, days=30):
    """Default date range for the price history: the last `days` price dates
    of this ticker -> {"start": date, "end": date} (both None if no prices)."""
    return _fetch_one(conn, """
        SELECT min(price_date) AS start, max(price_date) AS end
        FROM (SELECT price_date FROM daily_price
              WHERE ticker = upper(btrim(%s))
              ORDER BY price_date DESC
              LIMIT %s) last_days
    """, (ticker, days))


def price_history(conn, ticker, start, end):
    """Daily prices of one ticker between two dates (inclusive), oldest first."""
    return _fetch_all(conn, """
        SELECT price_date, open, high, low, close, volume
        FROM daily_price
        WHERE ticker = upper(btrim(%s)) AND price_date BETWEEN %s AND %s
        ORDER BY price_date
    """, (ticker, start, end))


def _ensure_sector_and_exchange(cur, sector_name, exchange_name):
    """Insert the sector / exchange if it doesn't exist yet (inside the caller's
    transaction, so a later failure removes it again)."""
    if sector_name is not None:
        cur.execute("INSERT INTO sector (sector_name) VALUES (btrim(%s)) "
                    "ON CONFLICT (sector_name) DO NOTHING", (sector_name,))
    if exchange_name is not None:
        cur.execute("INSERT INTO exchange (exchange_name) VALUES (btrim(%s)) "
                    "ON CONFLICT (exchange_name) DO NOTHING", (exchange_name,))


def add_stock_with_prices(conn, ticker, company_name, sector_name, exchange_name, rows):
    """Add a stock and its downloaded prices in ONE transaction: if anything is
    refused (duplicate ticker, bad format, ...) nothing at all is saved, not even
    a new sector or exchange. A ticker starting with ^ is an INDEX (like the loader).
    rows: (ticker, date, open, high, low, close, volume) tuples from market_data.
    Returns the number of price rows inserted."""
    ticker = ticker.strip().upper()
    security_type = "INDEX" if ticker.startswith("^") else "STOCK"
    with conn.transaction(), conn.cursor() as cur:
        _ensure_sector_and_exchange(cur, sector_name, exchange_name)
        cur.execute("""
            INSERT INTO stock (ticker, company_name, security_type, sector_id, exchange_id)
            VALUES (%s, btrim(%s), %s,
                    (SELECT sector_id   FROM sector   WHERE sector_name   = btrim(%s)),
                    (SELECT exchange_id FROM exchange WHERE exchange_name = btrim(%s)))
        """, (ticker, company_name, security_type, sector_name, exchange_name))
        cur.executemany("""
            INSERT INTO daily_price (ticker, price_date, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [(ticker,) + tuple(row[1:]) for row in rows])
        return cur.rowcount


def update_stock(conn, ticker, company_name=None, sector_name=None, exchange_name=None):
    """Change company name / sector / exchange (None = keep). A new sector or
    exchange name is created in the same transaction."""
    with conn.transaction(), conn.cursor() as cur:
        _ensure_sector_and_exchange(cur, sector_name, exchange_name)
        cur.execute("""
            UPDATE stock
            SET company_name = COALESCE(btrim(%(company)s), company_name),
                sector_id    = COALESCE((SELECT sector_id FROM sector
                                         WHERE sector_name = btrim(%(sector)s)), sector_id),
                exchange_id  = COALESCE((SELECT exchange_id FROM exchange
                                         WHERE exchange_name = btrim(%(exchange)s)), exchange_id)
            WHERE ticker = upper(btrim(%(ticker)s))
            RETURNING ticker
        """, {"company": company_name, "sector": sector_name, "exchange": exchange_name,
              "ticker": ticker})
        if cur.fetchone() is None:
            raise NotFoundError(f"There is no stock {ticker.strip().upper()}.")


def stock_usage(conn, ticker):
    """What depends on a ticker: what a rename takes along, or a delete removes / is blocked by."""
    return _fetch_one(conn, """
        SELECT (SELECT count(*) FROM daily_price    WHERE ticker = t.ticker) AS prices,
               (SELECT count(*) FROM trade          WHERE ticker = t.ticker) AS trades,
               (SELECT count(*) FROM watchlist_item WHERE ticker = t.ticker) AS watchlist_items
        FROM (SELECT upper(btrim(%s)) AS ticker) t
    """, (ticker,))


def rename_ticker(conn, old, new):
    """UPDATE stock SET ticker: ON UPDATE CASCADE carries the change to daily_price,
    from there to trade (whose audit trigger logs each trade with the OLD ticker),
    and to watchlist_item."""
    row = _fetch_one(conn, """
        UPDATE stock SET ticker = upper(btrim(%s)) WHERE ticker = upper(btrim(%s))
        RETURNING ticker
    """, (new, old))
    if row is None:
        raise NotFoundError(f"There is no stock {old.strip().upper()}.")
    return row["ticker"]


def delete_stock(conn, ticker):
    """Delete a stock: its prices and watchlist items cascade. If it has trades,
    the RESTRICT FK fk_trade_daily_price refuses (trades must be kept)."""
    row = _fetch_one(conn, """
        DELETE FROM stock WHERE ticker = upper(btrim(%s)) RETURNING ticker
    """, (ticker,))
    if row is None:
        raise NotFoundError(f"There is no stock {ticker.strip().upper()}.")


def refresh_all_prices(conn, download=None):
    """Insert-only refresh of EVERY stock in the stock table (also ones added in
    the app), with the ETL loader's code: one transaction per ticker.
    download None = the real yfinance download. Returns the loader's summary."""
    from app import market_data           # here, not at the top: keeps data_access light
    from etl import load_prices
    tickers = [row["ticker"] for row in _fetch_all(conn, "SELECT ticker FROM stock ORDER BY ticker")]
    return load_prices.refresh_tickers(conn, tickers, market_data.yesterday(),
                                       download=download or market_data.download_prices)


# ---------------------------------------------------------------------
# CSV import (Extra 2): all rows in ONE transaction
# ---------------------------------------------------------------------
class ImportRowError(Exception):
    """The database refused one row of an import. Carries the file row number
    and the original database error (errors.friendly_message shows both)."""
    def __init__(self, row, error):
        super().__init__(f"row {row}: {error}")
        self.row = row
        self.error = error


def import_events(conn, portfolio_id, events):
    """Import checked rows (app/csv_import.Event) in ONE transaction, in the given
    order, each through execute_trade() / record_cash_transaction() so every rule
    applies. The first refusal raises ImportRowError INSIDE the transaction block,
    which rolls back every row imported before it: all or nothing.
    Returns {"trades": n, "cash": m}."""
    counts = {"trades": 0, "cash": 0}
    with conn.transaction():
        for event in events:
            try:
                if event.is_cash:
                    record_cash_transaction(conn, portfolio_id, event.kind, event.amount, event.date)
                    counts["cash"] += 1
                else:
                    execute_trade(conn, portfolio_id, event.ticker, event.kind, event.shares,
                                  event.date, event.price)
                    counts["trades"] += 1
            except psycopg.Error as error:
                raise ImportRowError(event.row, error) from error
    return counts


# ---------------------------------------------------------------------
# Rebalance (Extra 3): prices for the plan, then all trades in ONE transaction
# ---------------------------------------------------------------------
class RebalanceTradeError(Exception):
    """The database refused one trade of a rebalance. Carries the trade as text
    ("SELL 50 AAA") and the original database error."""
    def __init__(self, trade_text, error):
        super().__init__(f"{trade_text}: {error}")
        self.trade_text = trade_text
        self.error = error


def latest_closes(conn, tickers, as_of):
    """{ticker: latest close on or before as_of} (the reports' valuation rule).
    Tickers without any price are simply missing from the dict."""
    rows = _fetch_all(conn, """
        SELECT t.ticker, c.close
        FROM unnest(%s::text[]) AS t(ticker)
        CROSS JOIN LATERAL (
            SELECT dp.close FROM daily_price dp
            WHERE dp.ticker = t.ticker AND dp.price_date <= %s
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) c
    """, (list(tickers), as_of))
    return {row["ticker"]: row["close"] for row in rows}


def execute_rebalance(conn, portfolio_id, trades, day):
    """Make the plan's trades [(ticker, "SELL"/"BUY", shares)] in the given order
    (SELLs first) on `day` at that day's close, in ONE transaction: the first
    refusal raises RebalanceTradeError inside the block, so nothing is saved."""
    with conn.transaction():
        for ticker, trade_type, shares in trades:
            try:
                execute_trade(conn, portfolio_id, ticker, trade_type, shares, day, None)
            except psycopg.Error as error:
                raise RebalanceTradeError(f"{trade_type} {shares} {ticker}", error) from error
    return len(trades)


# ---------------------------------------------------------------------
# Startup check (final step): is the schema there?
# ---------------------------------------------------------------------
REQUIRED_RELATIONS = ("sector", "exchange", "investor", "stock", "daily_price", "portfolio",
                      "cash_transaction", "trade", "watchlist", "watchlist_item", "trade_audit",
                      "v_cash_balance", "v_holdings")
REQUIRED_ROUTINES = ("execute_trade", "record_cash_transaction", "fn_monthly_returns")


def missing_schema_objects(conn):
    """Names of required tables / views / routines that don't exist in this database
    (an empty list = the schema is there). to_regclass gives NULL for a missing name."""
    rows = _fetch_all(conn, """
        SELECT name FROM unnest(%s::text[]) AS name
        WHERE to_regclass('public.' || name) IS NULL
        UNION ALL
        SELECT name FROM unnest(%s::text[]) AS name
        WHERE NOT EXISTS (SELECT 1 FROM pg_proc p
                          WHERE p.proname = name AND p.pronamespace = 'public'::regnamespace)
    """, (list(REQUIRED_RELATIONS), list(REQUIRED_ROUTINES)))
    return [row["name"] for row in rows]
