"""Shared pytest fixtures.

`conn`: a connection to the TEST database (portfolio_tracker_test, never the
real one). Each test runs inside a transaction that is ALWAYS rolled back, so
the database is unchanged afterwards. The data-access functions open their own
`with conn.transaction():` blocks; inside this outer transaction those become
savepoints, so a failing statement still rolls back only its own part.
"""
import psycopg
import pytest

TEST_DB = "portfolio_tracker_test"


@pytest.fixture
def conn(monkeypatch):
    # etl/db.py reads DB_NAME from the environment before .env
    monkeypatch.setenv("DB_NAME", TEST_DB)
    from etl.db import connect
    try:
        connection = connect()
    except psycopg.OperationalError as error:
        pytest.skip(f"test database not reachable (run `make test` to build it): {error}")
    with connection:
        name = connection.execute("SELECT current_database()").fetchone()[0]
        assert name == TEST_DB, f"refusing to run tests on database {name}"
        with connection.transaction(force_rollback=True):
            yield connection


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test: a real yfinance download fails at once. Tests must replace
    the download with a fake (unittest.mock); if one forgets, it fails loudly
    instead of quietly downloading from Yahoo."""
    import yfinance

    def refuse(*args, **kwargs):
        raise RuntimeError("network disabled in tests: mock the download")

    monkeypatch.setattr(yfinance, "Ticker", refuse)
