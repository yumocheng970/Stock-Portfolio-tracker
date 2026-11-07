"""Unexpected errors: write them to a log file, show a friendly line instead.

Database errors are NOT handled here: errors.safe_call shows them with their
friendly messages. This module is for everything else, i.e. bugs: a menu
action that raises an unexpected Python error is caught by run_menu
(app/menu.py), which calls report_unexpected():
    - the full traceback goes to logs/app.log, with a short error id
    - any transaction still open is rolled back
    - the user sees one friendly line with that id, and the menu again
APP_DEBUG=1 also prints the traceback on screen (for development).
"""
import logging
import os
import secrets
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psycopg

# logs/ in the repo root (git-ignored); looked up at call time so tests can redirect it
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_NAME = "app.log"

logger = logging.getLogger("app")           # the app's own logger (not the root logger)


def setup_logging(log_dir=None, max_bytes=1_000_000, backups=3):
    """Send the "app" logger to <log_dir>/app.log. RotatingFileHandler keeps the file
    small: when it would pass max_bytes, it is renamed app.log.1 (app.log.1 ->
    app.log.2, ...), a new app.log is started, and only `backups` old files are kept.
    Returns the log file path."""
    folder = Path(log_dir) if log_dir is not None else LOG_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME

    for old in list(logger.handlers):        # calling setup twice must not log twice
        logger.removeHandler(old)
        old.close()
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False                 # don't also hand the records to the root logger
    return path


def log_path():
    """The file the "app" logger writes to (None before setup_logging)."""
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return None


def shown_path(path):
    """logs/app.log instead of /home/.../logs/app.log, when it is under the current folder."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def recover_connection(conn):
    """Safety net after an unexpected error: if a transaction is still open (or failed),
    roll it back, so the next action starts clean. Normally there is none: every
    data_access function's `with conn.transaction():` already rolled back."""
    if conn is None:
        return
    try:
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()
    except Exception:          # a broken connection: the next DB action reports "Lost the connection"
        pass


def report_unexpected(error, action, conn=None):
    """Log the error with its traceback, clean up, print one friendly line.
    Returns the short error id (6 hex characters, e.g. '3f9a1c')."""
    error_id = secrets.token_hex(3)
    # exc_info=error: the log record gets the full traceback of `error`
    logger.error("error %s in %s: %s", error_id, action, error, exc_info=error)
    recover_connection(conn)
    if os.environ.get("APP_DEBUG") == "1":
        traceback.print_exception(error)     # the same text Python prints for an uncaught error
    path = log_path()
    where = shown_path(path) if path else "the log"
    print(f"\n  !! Something went wrong. Details were saved to {where} (error {error_id}).")
    return error_id
