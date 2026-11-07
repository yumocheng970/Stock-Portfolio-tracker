"""Restore the dump WITHOUT psql, to prove it is plain SQL that any client can run
(DBeaver, pgAdmin, a Python program), with no psql meta-commands like \\restrict or COPY ... FROM stdin.

Usage (from the repo root, conda env spt):
    python -m db.tests.restore_without_psql <empty_database> db/dump/cheng_final_project.sql

The whole file is sent to the server as ONE string in ONE transaction. psycopg
sends a query without parameters as-is, and PostgreSQL itself splits it at the
semicolons. Only the server parses it, so a psql-only line would be a syntax error.
Called by `make verify-dump` (db/tests/verify_dump.sh) on a temporary database.
"""
import os
import sys
import time
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python -m db.tests.restore_without_psql <empty_database> <dump.sql>")
    dbname, dump_file = sys.argv[1], Path(sys.argv[2])

    # etl/db.py reads DB_NAME from the environment before .env (load_dotenv never
    # overrides a variable that is already set), so this points it at the target DB
    os.environ["DB_NAME"] = dbname
    from etl.db import connect

    sql = dump_file.read_text(encoding="utf-8")
    # autocommit=False: everything below is one transaction, all or nothing
    with connect(autocommit=False) as conn:
        # Safety: only restore into an EMPTY database, never over real data
        tables = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]
        if tables:
            sys.exit(f"refusing: database {dbname} is not empty ({tables} tables)")

        start = time.perf_counter()
        conn.execute(sql)          # the whole dump, as one string
        conn.commit()
        print(f"restored {dump_file} into {dbname} without psql "
              f"in {time.perf_counter() - start:.2f} s")


if __name__ == "__main__":
    main()
