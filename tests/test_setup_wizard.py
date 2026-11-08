"""The setup wizard (setup/wizard.py) and the restore module (db/restore.py).

Real connections to the local PostgreSQL server; input() and getpass are mocked;
.env goes to tmp_path. Databases: only scratch ones (pt_scratch_<random>, created and
dropped here) and portfolio_tracker_test (read-only checks). portfolio_tracker is
only ever checked read-only (the refusal happens before any change).
"""
import secrets
from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values

from db import restore
from setup import wizard

SOCKET = "/var/run/postgresql"
TRICKY_PASSWORD = "p'a ss#$X\\y"        # quote, space, #, $, backslash


def admin():
    return psycopg.connect(dbname="postgres", host=SOCKET, autocommit=True)


@pytest.fixture
def scratch_name():
    """A fresh scratch database name; the database is dropped afterwards (if created)."""
    name = f"pt_scratch_{secrets.token_hex(4)}"
    yield name
    assert name.startswith("pt_scratch_")                     # never drop anything else
    with admin() as conn:
        conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            psycopg.sql.Identifier(name)))


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(wizard, "ENV_FILE", path)
    monkeypatch.setattr(wizard, "default_settings", lambda name=None: {
        "DB_HOST": SOCKET, "DB_PORT": "", "DB_USER": ""})       # this machine (WSL, peer login)
    return path


def answers(monkeypatch, inputs, passwords=("",)):
    inputs, passwords = iter(inputs), iter(passwords)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(passwords))


# ---------------------------------------------------------------------
# A full run
# ---------------------------------------------------------------------
def test_full_run_writes_env_creates_and_restores(env_file, scratch_name, monkeypatch, capsys):
    # host, port, user (all defaults), [password], database name, start the app? no
    answers(monkeypatch, ["", "", "", scratch_name, "n"], passwords=[TRICKY_PASSWORD])
    assert wizard.run() == 0
    out = capsys.readouterr().out
    assert "Connected to PostgreSQL 16." in out and f"on {SOCKET}:5432 as " in out
    assert "Created it." in out and "1,155 trade" in out
    assert TRICKY_PASSWORD not in out and "DB_PASSWORD=(set)" in out       # never printed
    values = dotenv_values(env_file)
    assert values == {"DB_NAME": scratch_name, "DB_USER": "", "DB_PASSWORD": TRICKY_PASSWORD,
                      "DB_HOST": SOCKET, "DB_PORT": ""}                    # exact round trip


def test_reasks_after_a_failed_connection(env_file, monkeypatch, capsys):
    answers(monkeypatch,
            ["/tmp/no_such_socket_dir", "", "",                 # 1st try: wrong socket folder
             SOCKET, "", "",                                    # 2nd try: right
             "portfolio_tracker_test", "n"], passwords=["", ""])
    assert wizard.run() == 0
    out = capsys.readouterr().out
    assert "!! Can't connect: No such file or directory" in out
    assert "already has the app's tables: nothing to restore" in out      # full schema: left alone


def test_refuses_a_database_with_other_tables(env_file, scratch_name, monkeypatch, capsys):
    with admin() as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(scratch_name)))
    with psycopg.connect(dbname=scratch_name, host=SOCKET, autocommit=True) as conn:
        conn.execute("CREATE TABLE someone_elses (x int)")
    answers(monkeypatch, ["", "", "", scratch_name])
    assert wizard.run() == 1
    assert "already has tables that aren't this app's" in capsys.readouterr().out
    with psycopg.connect(dbname=scratch_name, host=SOCKET) as conn:
        assert restore.table_count(conn) == 1                            # nothing restored


def test_existing_env_is_kept_when_the_answer_is_no(env_file, monkeypatch, capsys):
    original = f"# mine\nDB_NAME=portfolio_tracker_test\nDB_HOST={SOCKET}\nDB_PASSWORD='secret!'\n"
    env_file.write_text(original, encoding="utf-8")
    answers(monkeypatch, ["n", "n"])                                     # don't overwrite; don't start
    assert wizard.run() == 0
    out = capsys.readouterr().out
    assert "A .env file already exists" in out and "DB_PASSWORD=(set)" in out
    assert "secret!" not in out
    assert env_file.read_text(encoding="utf-8") == original              # byte for byte


def test_server_older_than_16_stops_before_anything(env_file, monkeypatch, capsys):
    monkeypatch.setattr(wizard, "server_version", lambda conn: (150004, "15.4"))
    monkeypatch.setattr(restore, "restore_dump", lambda *a, **k: pytest.fail("restore must not run"))
    answers(monkeypatch, ["", "", ""])
    assert wizard.run() == 1
    out = capsys.readouterr().out
    assert "PostgreSQL 15.4 is too old: version 16 or newer is needed" in out
    assert "https://www.postgresql.org/download/" in out
    assert not env_file.exists()                                         # nothing written


def test_env_quoting_round_trip(tmp_path):
    settings = {"DB_NAME": "pt", "DB_USER": "postgres", "DB_PASSWORD": TRICKY_PASSWORD,
                "DB_HOST": "localhost", "DB_PORT": "5432"}
    path = tmp_path / ".env"
    path.write_text(wizard.env_text(settings), encoding="utf-8")
    assert dotenv_values(path) == settings
    assert TRICKY_PASSWORD not in wizard.describe(settings)


def test_platform_defaults():
    assert wizard.default_settings("windows") == {"DB_HOST": "localhost", "DB_PORT": "5432",
                                                  "DB_USER": "postgres"}
    assert wizard.default_settings("macos")["DB_HOST"] == "/tmp"
    assert wizard.default_settings("wsl")["DB_HOST"] == SOCKET


# ---------------------------------------------------------------------
# db/restore.py
# ---------------------------------------------------------------------
def test_restore_into_a_new_scratch_database(scratch_name):
    with admin() as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(scratch_name)))
    with psycopg.connect(dbname=scratch_name, host=SOCKET, autocommit=True) as conn:
        seconds = restore.restore_dump(conn)
        counts = restore.count_rows(conn)
    assert seconds < 30
    assert (counts["trade"], counts["investor"], counts["stock"]) == (1155, 15, 26)


def test_restore_cli_reads_db_name(scratch_name, monkeypatch, capsys):
    with admin() as conn:
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(scratch_name)))
    monkeypatch.setenv("DB_NAME", scratch_name)
    monkeypatch.setenv("DB_HOST", SOCKET)
    assert restore.main([]) == 0
    assert f"into '{scratch_name}'" in capsys.readouterr().out


def test_restore_refuses_a_database_with_tables():
    # read-only: the refusal happens before anything is executed
    with psycopg.connect(dbname="portfolio_tracker", host=SOCKET, autocommit=True) as conn:
        with pytest.raises(restore.RestoreRefused):
            restore.restore_dump(conn)
