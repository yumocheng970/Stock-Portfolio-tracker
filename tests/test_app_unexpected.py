"""Final step: unexpected errors are logged with an id; startup problems get
friendly messages and exit codes. Logs go to tmp_path (conftest.log_to_tmp_path).
"""
import re
from unittest import mock

import psycopg
import pytest

from app import __main__ as app_main
from app import data_access as da
from app import error_log
from app.menu import run_menu
from app.session import Session

ID = re.compile(r"\(error ([0-9a-f]{6})\)")


def fake_input(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def explode(session):
    raise RuntimeError("boom")


# ---------------------------------------------------------------------
# An unexpected error in a menu action
# ---------------------------------------------------------------------
def test_unexpected_error_is_logged_and_the_menu_comes_back(monkeypatch, capsys):
    monkeypatch.delenv("APP_DEBUG", raising=False)
    calls = []
    fake_input(monkeypatch, ["1", "2", "0"])           # explode, then a normal item, then leave
    run_menu("Test", [("Explode", explode), ("Fine", lambda s: calls.append("fine"))], session=None)
    out = capsys.readouterr().out
    assert "Something went wrong. Details were saved to" in out
    assert "Traceback" not in out and "boom" not in out               # nothing technical on screen
    error_id = ID.search(out).group(1)
    assert calls == ["fine"]                                           # the menu came back and worked
    log = error_log.log_path().read_text(encoding="utf-8")
    assert f"error {error_id} in Test > Explode: boom" in log
    assert "Traceback (most recent call last)" in log and "RuntimeError: boom" in log


def test_debug_mode_shows_the_traceback(monkeypatch, capsys):
    monkeypatch.setenv("APP_DEBUG", "1")
    fake_input(monkeypatch, ["1", "0"])
    run_menu("Test", [("Explode", explode)], session=None)
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and "RuntimeError: boom" in captured.err
    assert ID.search(captured.out)                                     # still logged, with an id


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt])
def test_ctrl_d_and_ctrl_c_still_leave_the_app(monkeypatch, exception):
    def leave(session):
        raise exception()
    fake_input(monkeypatch, ["1"])
    with pytest.raises(exception):
        run_menu("Test", [("Leave", leave)], session=None)


def test_open_transaction_is_rolled_back_after_an_unexpected_error(monkeypatch, capsys):
    conn = mock.Mock()
    conn.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    fake_input(monkeypatch, ["1", "0"])
    run_menu("Test", [("Explode", explode)], session=Session(conn))
    conn.rollback.assert_called_once()


def test_recover_connection_cases():
    idle = mock.Mock()
    idle.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    error_log.recover_connection(idle)
    idle.rollback.assert_not_called()
    broken = mock.Mock()
    broken.info.transaction_status = psycopg.pq.TransactionStatus.INERROR
    broken.rollback.side_effect = psycopg.OperationalError("connection lost")
    error_log.recover_connection(broken)                               # ignored, no exception
    error_log.recover_connection(None)


def test_log_file_is_rotated(tmp_path, capsys):
    path = error_log.setup_logging(tmp_path / "small", max_bytes=2000, backups=2)
    for _ in range(30):
        try:
            raise ValueError("x" * 100)
        except ValueError as error:
            error_log.report_unexpected(error, "rotation test")
    assert (tmp_path / "small" / "app.log.1").exists()
    assert not (tmp_path / "small" / "app.log.3").exists()             # only 2 backups kept
    assert path.stat().st_size <= 2000


def test_logs_are_not_written_into_the_repo():
    repo = error_log.LOG_DIR.parent
    assert repo not in error_log.log_path().parents


# ---------------------------------------------------------------------
# Startup problems: real connection attempts that change nothing
# ---------------------------------------------------------------------
def run_main(monkeypatch, capsys, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(app_main, "setup_logging", lambda: error_log.log_path())   # keep tmp log
    code = app_main.main()
    return code, capsys.readouterr().out


def test_cannot_connect(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, DB_HOST="/tmp/no_such_socket_dir_for_tests")
    assert code == 2
    assert "Can't connect to PostgreSQL" in out and "sudo service postgresql start" in out
    assert "Traceback" not in out


def test_database_does_not_exist(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, DB_NAME="pt_does_not_exist_xyz")
    assert code == 3
    assert "The database 'pt_does_not_exist_xyz' doesn't exist." in out
    assert "createdb pt_does_not_exist_xyz" in out and "Traceback" not in out


def test_empty_database_without_schema(monkeypatch, capsys):
    # "postgres" always exists and has none of the app's tables
    code, out = run_main(monkeypatch, capsys, DB_NAME="postgres")
    assert code == 4
    assert "The database 'postgres' has no app tables" in out
    assert "the dump hasn't been restored" in out and "Traceback" not in out


def test_test_database_has_the_whole_schema(conn):
    assert da.missing_schema_objects(conn) == []
