"""Entry point:  python -m app   (from the repo root)

Connects with the settings in .env, the same way as the ETL scripts. The
DB_NAME environment variable wins over .env, so `make run-test-db` can point
the app at the test database:  DB_NAME=portfolio_tracker_test python -m app
"""
import psycopg

from app import data_access as da
from app.menus.main_menu import main_menu
from app.session import Session
from etl.db import connect


def main():
    try:
        conn = connect()            # autocommit=True; each data_access function is one transaction
    except psycopg.OperationalError as error:
        print(f"Can't connect to the database. Check .env and that PostgreSQL is running.\n  {error}")
        return
    with conn:                      # closes the connection at the end, whatever happens
        print("Paper-Trading Portfolio Tracker")
        print(f"Database: {da.database_name(conn)}")
        print("Choose a number and press Enter. Exit with 0 from the main menu.")
        try:
            main_menu(Session(conn))
        except (KeyboardInterrupt, EOFError):   # Ctrl+C / Ctrl+D
            print()
        print("Goodbye.")


if __name__ == "__main__":
    main()
