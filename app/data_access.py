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
