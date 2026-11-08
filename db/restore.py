"""Restore the database dump WITHOUT psql: no command-line tools needed, only Python.

    python -m db.restore                    # into DB_NAME from .env, the default dump
    python -m db.restore --file other.sql   # another dump file

The whole file is sent to the server as ONE string in ONE transaction: psycopg
sends a query without parameters as-is, and PostgreSQL splits it at the
semicolons itself. So it works only with a plain-SQL dump without psql
meta-commands, which is what `make dump` writes. All or nothing.

Safety: it refuses a database that already has tables (it never restores over
data). Used by the setup wizard (python -m setup), by `make verify-dump`
(db/tests/restore_without_psql.py) and on its own.
"""
import argparse
import sys
import time
from pathlib import Path

DUMP_FILE = Path(__file__).resolve().parent / "dump" / "cheng_final_project.sql"


class RestoreRefused(Exception):
    """The target database is not empty; nothing was changed."""


def table_count(conn):
    """Number of tables in the public schema."""
    return conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]


def restore_dump(conn, path=DUMP_FILE):
    """Run the dump file on `conn` in one transaction. Refuses (RestoreRefused) if the
    database already has tables. Returns the seconds it took."""
    tables = table_count(conn)
    if tables:
        raise RestoreRefused(f"the database already has {tables} tables; "
                             "restore only into a new, empty database")
    sql = Path(path).read_text(encoding="utf-8")
    start = time.perf_counter()
    with conn.transaction():                 # all or nothing
        conn.execute(sql)
    # The dump runs set_config('search_path', '', false), which empties the search
    # path for the rest of this SESSION (not just the restore): put the normal one back,
    # so later queries on this connection find the tables again.
    conn.execute("RESET search_path")
    return time.perf_counter() - start


def count_rows(conn):
    """The row counts shown after a restore (the sample data has 1155 trades)."""
    counts = {}
    for table in ("investor", "portfolio", "trade", "cash_transaction", "stock", "daily_price"):
        counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Restore the dump into DB_NAME from .env (no psql needed).")
    parser.add_argument("--file", default=str(DUMP_FILE), help="the dump file (default: %(default)s)")
    args = parser.parse_args(argv)

    from etl.db import connect               # reads .env
    with connect() as conn:                  # autocommit; restore_dump opens its own transaction
        db = conn.info.dbname
        try:
            seconds = restore_dump(conn, args.file)
        except RestoreRefused as error:
            print(f"Not restored into '{db}': {error}.")
            return 1
        counts = count_rows(conn)
    print(f"Restored {args.file} into '{db}' in {seconds:.1f} s: "
          + ", ".join(f"{n} {table}" for table, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
