"""Restore the dump WITHOUT psql, to prove it is plain SQL that any client can run
(DBeaver, pgAdmin, a Python program), with no psql meta-commands like \\restrict or COPY ... FROM stdin.

Usage (from the repo root, conda env spt):
    python -m db.tests.restore_without_psql <empty_database> db/dump/cheng_final_project.sql

Called by `make verify-dump` (db/tests/verify_dump.sh) on a temporary database.
The restore itself is db/restore.py (also used by the setup wizard); this file
only keeps the command line that verify_dump.sh uses.
"""
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python -m db.tests.restore_without_psql <empty_database> <dump.sql>")
    dbname, dump_file = sys.argv[1], Path(sys.argv[2])

    # etl/db.py reads DB_NAME from the environment before .env (load_dotenv never
    # overrides a variable that is already set), so this points it at the target DB
    os.environ["DB_NAME"] = dbname
    from db.restore import RestoreRefused, restore_dump
    from etl.db import connect

    with connect() as conn:
        try:
            seconds = restore_dump(conn, dump_file)
        except RestoreRefused as error:
            sys.exit(f"refusing: database {dbname}: {error}")
    print(f"restored {dump_file} into {dbname} without psql in {seconds:.2f} s")


if __name__ == "__main__":
    main()
