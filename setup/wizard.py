"""Setup wizard: connection -> .env -> database -> restore the dump -> start the app.

    python -m setup          (or setup.bat / ./setup.sh, which also create the conda env)

Steps:
  1. If .env exists: show it (password only as "set"), ask before overwriting.
  2. Ask host / port / user / password (defaults per platform; the password is
     typed hidden with getpass) and TEST the connection right away; ask again on failure.
  3. Check the server version: PostgreSQL 16 or newer is needed.
  4. Write .env (the password is never printed).
  5. Create the database if it doesn't exist.
  6. Restore the dump (db/restore.py) only into an EMPTY database; a database
     that already has this app's tables is left alone ("already restored");
     one with other tables is refused.
  7. Show the row counts and offer to start the app.
It does NOT install PostgreSQL or Miniforge.
"""
import getpass
import os
import platform
import sys
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"                 # looked up at call time, so tests can redirect it
DEFAULT_DB = "portfolio_tracker"
MIN_SERVER_VERSION = 160000              # server_version_num of PostgreSQL 16.0
DOWNLOAD_PAGE = "https://www.postgresql.org/download/"
KEYS = ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT")


class SetupStopped(Exception):
    """The wizard can't continue; str(error) says why and what to do."""


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------
def platform_name():
    """'windows', 'macos', 'wsl' or 'linux'."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if "microsoft" in platform.uname().release.lower():
        return "wsl"
    return "linux"


def default_settings(name=None):
    """Connection defaults per platform (see README step 4)."""
    name = name or platform_name()
    if name == "windows":
        return {"DB_HOST": "localhost", "DB_PORT": "5432", "DB_USER": "postgres"}
    if name == "macos":
        return {"DB_HOST": "/tmp", "DB_PORT": "", "DB_USER": getpass.getuser()}
    return {"DB_HOST": "/var/run/postgresql", "DB_PORT": "", "DB_USER": getpass.getuser()}


def ask(prompt, default):
    """Ask with a default shown in brackets; Enter = the default."""
    shown = default if default else "none"
    answer = input(f"  {prompt} [{shown}]: ").strip()
    return answer or default


def ask_yes_no(prompt, default=False):
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"  {prompt} ({hint}): ").strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please type y or n.")


def connect(settings, dbname):
    """Connect with the settings (empty ones left to libpq's defaults)."""
    params = {"dbname": dbname, "user": settings.get("DB_USER"), "password": settings.get("DB_PASSWORD"),
              "host": settings.get("DB_HOST"), "port": settings.get("DB_PORT")}
    params = {key: value for key, value in params.items() if value}
    return psycopg.connect(**params, autocommit=True, connect_timeout=5)


def service_hint(text, host, port):
    """The 'Nothing answered on localhost:5432 ...' hint (shared with the app's startup check)."""
    from app.__main__ import service_hint as hint
    return hint(text, host, port)


def reason(error):
    """The server's one-line reason from a connection error."""
    text = str(error)
    part = text.split("failed:")[-1] if "failed:" in text else text
    return part.strip().splitlines()[0]


def quote(value):
    """A value for .env in single quotes: python-dotenv takes it literally (no ${...}
    expansion); only backslash and single quote need a backslash in front."""
    if value == "":
        return ""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def env_text(settings):
    lines = ["# Written by the setup wizard (python -m setup). Never commit this file (it is git-ignored)."]
    lines += [f"{key}={quote(settings.get(key, ''))}" for key in KEYS]
    return "\n".join(lines) + "\n"


def describe(settings):
    """The settings for the screen, the password only as (set) / (none)."""
    parts = [f"{key}={settings.get(key) or ''}" for key in KEYS if key != "DB_PASSWORD"]
    parts.append("DB_PASSWORD=" + ("(set)" if settings.get("DB_PASSWORD") else "(none)"))
    return ", ".join(parts)


# ---------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------
def ask_connection(defaults):
    """Ask until a connection to the maintenance database 'postgres' works.
    Returns (settings, connection)."""
    settings = dict(defaults)
    while True:
        settings["DB_HOST"] = ask("Host (a name, or the socket folder)", settings["DB_HOST"])
        settings["DB_PORT"] = ask("Port", settings["DB_PORT"])
        settings["DB_USER"] = ask("User", settings["DB_USER"])
        settings["DB_PASSWORD"] = getpass.getpass("  Password (hidden; Enter = none): ")
        try:
            return settings, connect(settings, "postgres")
        except psycopg.OperationalError as error:
            print(f"\n  !! Can't connect: {reason(error)}")
            hint = service_hint(str(error), settings["DB_HOST"], settings["DB_PORT"])
            if hint:
                print(f"     {hint}")
            print("     Check that PostgreSQL is running and the values are right, then try again"
                  " (Ctrl+C quits).\n")


def server_version(conn):
    """(version number like 180006, version text like '18.6')."""
    number = int(conn.execute("SHOW server_version_num").fetchone()[0])
    text = conn.execute("SHOW server_version").fetchone()[0].split()[0]
    return number, text


def check_version(conn):
    number, text = server_version(conn)
    if number < MIN_SERVER_VERSION:
        raise SetupStopped(f"PostgreSQL {text} is too old: version 16 or newer is needed. "
                           f"Download a current version: {DOWNLOAD_PAGE}")
    return text


def connected_line(conn, version_text):
    """'Connected to PostgreSQL 18.6 on localhost:5432 as postgres.'"""
    info = conn.info
    return f"Connected to PostgreSQL {version_text} on {info.host}:{info.port} as {info.user}."


def database_exists(admin, name):
    return admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def create_database(admin, name):
    # CREATE DATABASE can't take a parameter: sql.Identifier quotes the name safely
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def database_state(conn):
    """'empty' (no tables), 'restored' (the app's whole schema) or 'other'."""
    from app.data_access import missing_schema_objects
    from db.restore import table_count
    if table_count(conn) == 0:
        return "empty"
    return "restored" if not missing_schema_objects(conn) else "other"


def write_env(settings):
    ENV_FILE.write_text(env_text(settings), encoding="utf-8")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def run(start_app=None):
    """The whole wizard. Returns an exit code (0 = ready)."""
    from db.restore import count_rows, restore_dump
    from dotenv import dotenv_values

    print("Paper-Trading Portfolio Tracker: setup")
    print("(This doesn't install PostgreSQL or Miniforge; see README.md -> Quick start.)\n")

    keep_env = False
    if ENV_FILE.exists():
        existing = {key: value or "" for key, value in dotenv_values(ENV_FILE).items()}
        print(f"  A .env file already exists: {describe(existing)}")
        keep_env = not ask_yes_no("Overwrite it?")

    try:
        if keep_env:
            settings = {key: existing.get(key, "") for key in KEYS}
            print("  Keeping .env and using its settings.")
            try:
                admin = connect(settings, "postgres")
            except psycopg.OperationalError as error:
                hint = service_hint(str(error), settings.get("DB_HOST"), settings.get("DB_PORT"))
                if hint:
                    print(f"  {hint}")
                raise SetupStopped(f"Can't connect with the settings in .env: {reason(error)}. "
                                   "Run the wizard again and answer y to overwrite .env, "
                                   "or fix .env by hand.") from error
        else:
            print(f"Step 1: connect to PostgreSQL ({platform_name()} defaults shown in brackets)")
            settings, admin = ask_connection(default_settings())

        with admin:
            version_text = check_version(admin)
            print(f"\n  {connected_line(admin, version_text)}")
            if not keep_env:
                settings["DB_NAME"] = ask("Database name", DEFAULT_DB)
                write_env(settings)
                print(f"  Wrote {ENV_FILE.name}: {describe(settings)}")
            name = settings.get("DB_NAME") or DEFAULT_DB

            print(f"\nStep 2: database '{name}'")
            if database_exists(admin, name):
                print("  It exists already.")
            else:
                create_database(admin, name)
                print("  Created it.")

        with connect(settings, name) as conn:
            state = database_state(conn)
            if state == "other":
                raise SetupStopped(f"The database '{name}' already has tables that aren't this app's. "
                                   "Nothing was restored: choose another database name.")
            if state == "restored":
                print("  It already has the app's tables: nothing to restore.")
            else:
                print("  Restoring the dump (a few seconds) ...")
                seconds = restore_dump(conn)
                print(f"  Restored in {seconds:.1f} s.")
            counts = count_rows(conn)
        print("  " + ", ".join(f"{n:,} {table}" for table, n in counts.items()))
    except SetupStopped as error:
        print(f"\n  !! {error}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup cancelled; nothing more was changed.")
        return 1

    print("\nReady. Start the app any time with:  python -m app   (in the 'spt' environment)")
    if ask_yes_no("Start the app now?"):
        start_app = start_app or __import__("app.__main__", fromlist=["main"]).main
        return start_app()
    return 0
