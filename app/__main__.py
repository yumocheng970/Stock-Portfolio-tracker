"""Entry point:  python -m app   (from the repo root)

Connects with the settings in .env, the same way as the ETL scripts. The
DB_NAME environment variable wins over .env, so `make run-test-db` can point
the app at the test database:  DB_NAME=portfolio_tracker_test python -m app

Exit codes (echo $? after the app ends):
    0  normal exit
    1  unexpected error outside a menu action (details in logs/app.log)
    2  can't connect to PostgreSQL
    3  the database doesn't exist
    4  the database exists but has no app tables (the dump wasn't restored)
APP_DEBUG=1 python -m app  also prints the traceback of unexpected errors.
"""
import os
import sys

import psycopg

from app import data_access as da
from app.error_log import report_unexpected, setup_logging, shown_path
from app.menus.main_menu import main_menu
from app.session import Session
from etl.db import connect

EXIT_OK, EXIT_UNEXPECTED, EXIT_NO_SERVER, EXIT_NO_DATABASE, EXIT_NO_SCHEMA = 0, 1, 2, 3, 4
CREATE_HELP = "    createdb {db}\n"
RESTORE_HELP = ("    psql -v ON_ERROR_STOP=1 --single-transaction -d {db} -f db/dump/cheng_final_project.sql\n"
                "  (README.md -> 'Restore the database from the dump')")


def database_setting():
    """The database name the app tries to use (DB_NAME from the environment or .env)."""
    return os.getenv("DB_NAME", "portfolio_tracker")


def explain_connection_error(error):
    """A friendly message and exit code for a failed connection. Connection errors
    have no SQLSTATE (they happen before a session exists), so the server's text decides."""
    text = str(error)
    db = database_setting()
    if "database" in text and "does not exist" in text:     # FATAL: database "x" does not exist
        return (f"The database '{db}' doesn't exist. Create it and restore the dump:\n"
                + CREATE_HELP.format(db=db) + RESTORE_HELP.format(db=db)), EXIT_NO_DATABASE
    reason = text.split("failed:")[-1].strip().splitlines()[0] if "failed:" in text else text.splitlines()[0]
    return (f"Can't connect to PostgreSQL ({reason}).\n"
            "  Is the server running? In WSL start it with:  sudo service postgresql start\n"
            "  Also check DB_HOST / DB_PORT / DB_USER in .env (see .env.example)."), EXIT_NO_SERVER


def main():
    log_file = setup_logging()
    try:
        conn = connect()            # autocommit=True; each data_access function is one transaction
    except psycopg.OperationalError as error:
        message, code = explain_connection_error(error)
        print(message)
        return code

    with conn:                      # closes the connection at the end, whatever happens
        try:
            missing = da.missing_schema_objects(conn)
            if missing:
                db = da.database_name(conn)
                print(f"The database '{db}' has no app tables (missing: {', '.join(missing[:5])}"
                      f"{', ...' if len(missing) > 5 else ''}): the dump hasn't been restored.\n"
                      "  Restore it into this (empty) database:\n" + RESTORE_HELP.format(db=db))
                return EXIT_NO_SCHEMA

            print("Paper-Trading Portfolio Tracker")
            print(f"Database: {da.database_name(conn)}   (log: {shown_path(log_file)})")
            if da.is_read_only(conn):
                print("READ-ONLY mode: you can browse, every change will be refused.")
            print("Choose a number and press Enter. Exit with 0 from the main menu.")
            main_menu(Session(conn))
        except (KeyboardInterrupt, EOFError):   # Ctrl+C / Ctrl+D
            print()
        except Exception as error:              # outside any menu action
            report_unexpected(error, "startup / main menu", conn)
            return EXIT_UNEXPECTED
        print("Goodbye.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
