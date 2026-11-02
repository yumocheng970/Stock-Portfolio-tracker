"""Database connection for the ETL scripts.

Settings come from the git-ignored .env file in the repo root (see .env.example).
Empty settings fall back to libpq defaults: local Unix socket, current Linux user,
no password (peer authentication).
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# .env sits in the repo root, one folder above this file (etl/)
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def connect(autocommit=True):
    """Open a connection to the database named in .env (DB_NAME).

    autocommit=True: every statement commits on its own, unless it runs inside
    a `with conn.transaction():` block, which commits or rolls back as one unit.
    """
    load_dotenv(ENV_FILE)
    params = {
        "dbname": os.getenv("DB_NAME", "portfolio_tracker"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
    }
    # Drop empty settings so libpq uses its defaults for them
    params = {key: value for key, value in params.items() if value}
    return psycopg.connect(**params, autocommit=autocommit)
