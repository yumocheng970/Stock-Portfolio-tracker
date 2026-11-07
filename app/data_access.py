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
