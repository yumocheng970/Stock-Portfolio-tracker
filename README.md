# Paper-Trading Portfolio Tracker

CS 5200 final project (Yumo Cheng). A PostgreSQL database of investors, portfolios, trades, cash
transactions, watchlists and real daily stock prices (25 stocks + the S&P 500, 2021 to today,
from Yahoo Finance), with a Python command-line app (numbered menus) on top. All business rules
(enough cash, enough shares, price within the day's range, date order, ...) live in the database:
constraints, triggers and procedures.

- Database deliverable: `db/dump/cheng_final_project.sql` (a plain-SQL `pg_dump`: tables, data,
  views, functions, procedures, triggers, indexes)
- App: `app/` (run with `python -m app`); design: `docs/app_design.md`

## Tested platform (and what is not tested)

| Platform | Status |
|---|---|
| **Windows 11 + WSL 2, Ubuntu 24.04**, PostgreSQL 16.15, conda 26.1 (Miniforge), Python 3.12.14 | **Tested**: every step below was run on a clean clone by following this README |
| Windows (native, without WSL) | Instructions written, **not tested** |
| macOS | Instructions written, **not tested** |

## 1. Install the prerequisites (download pages)

| Software | Required | Tested | Download | Needed for |
|---|---|---|---|---|
| PostgreSQL | 16 or newer | 16.15 | https://www.postgresql.org/download/ | the database (server + `psql` / `createdb`) |
| Miniforge (conda) | any recent | conda 26.1.0 | https://github.com/conda-forge/miniforge | Python 3.12 + the libraries (recommended) |
| *or* Python | 3.12 | 3.12.14 | https://www.python.org/downloads/ | if you use `pip` + `venv` instead of conda |
| Git | any | 2.43.0 | https://git-scm.com/downloads | getting the code (not needed if you use the zip) |
| GNU Make (optional) | any | 4.3 | https://www.gnu.org/software/make/ (Ubuntu: `apt install make`; macOS: part of the Xcode Command Line Tools) | the developer shortcuts in section 9 (`make test`, ...); not needed to run the app |
| DBeaver (optional) | any recent | not version-tested | https://dbeaver.io/download/ | browsing the database / restoring the dump in a GUI |
| WSL (Windows, optional) | WSL 2 + Ubuntu 24.04 | Ubuntu 24.04.1 | https://learn.microsoft.com/windows/wsl/install | the tested setup on Windows |
| Homebrew (macOS) | any | not tested | https://brew.sh | installing PostgreSQL and Git on macOS |

**Linux / WSL (Ubuntu), tested:**
```bash
sudo apt update && sudo apt install postgresql postgresql-client git make
sudo service postgresql start                 # WSL has no systemd by default; on Linux: sudo systemctl start postgresql
sudo -u postgres createuser --createdb "$USER" # a database role with your Linux user name (peer login, no password)
```
Then install Miniforge (download page above; `bash Miniforge3-Linux-x86_64.sh`, answer "yes" to init, open a new terminal).

**Windows, native (untested):** run the PostgreSQL installer (EDB) from the download page; remember the
password you give the `postgres` user. Its tools are in `C:\Program Files\PostgreSQL\<version>\bin`
(add that folder to PATH, or use the full path). Install Miniforge, then use the **Miniforge Prompt** for
all commands below. `make` is not available on Windows; every command is also given without it.

**macOS (untested):** `brew install postgresql@16 git` then `brew services start postgresql@16`
(Homebrew: https://brew.sh). Your macOS user becomes a database user without a password.
Install Miniforge.

### Where everything is installed (default locations)

| | Linux / WSL (Ubuntu, tested) | Windows, native (untested) | macOS, Homebrew (untested) |
|---|---|---|---|
| PostgreSQL programs (`psql`, `createdb`, ...) | `/usr/lib/postgresql/16/bin`; `apt` puts `psql` / `createdb` on PATH (`/usr/bin`) for you | `C:\Program Files\PostgreSQL\16\bin`: **not** on PATH by default; **add it to PATH** (Settings > System > About > Advanced system settings > Environment Variables > Path > New), or type the full path | `/opt/homebrew/opt/postgresql@16/bin` (Apple silicon) or `/usr/local/opt/postgresql@16/bin` (Intel): **not** on PATH (Homebrew installs `postgresql@16` "keg-only"); add it: `echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc` |
| PostgreSQL data (created by the installer; you never edit it) | `/var/lib/postgresql/16/main` | `C:\Program Files\PostgreSQL\16\data` | `/opt/homebrew/var/postgresql@16` |
| Miniforge | `~/miniforge3` (e.g. `/home/<you>/miniforge3`) | `C:\Users\<you>\miniforge3` | `~/miniforge3` |
| The `spt` environment (step 3) | `~/miniforge3/envs/spt` | `C:\Users\<you>\miniforge3\envs\spt` | `~/miniforge3/envs/spt` |
| The project folder (step 2) | anywhere you like, e.g. `~/projects/Stock-Portfolio-tracker` (tested at `/home/<you>/projects/5200/Stock-Portfolio-tracker`); in WSL keep it on the Linux side, not under `/mnt/c` | anywhere, e.g. `C:\Users\<you>\projects\cheng_project` (a path without spaces is easiest) | anywhere, e.g. `~/projects/cheng_project` |

`psql` / `createdb` are only needed to restore the dump (step 5; DBeaver can do that instead).
The app itself connects through the Python driver and does not need them on PATH.

## 2. Get the code
```bash
git clone https://github.com/yumocheng970/Stock-Portfolio-tracker.git
cd Stock-Portfolio-tracker
```
(or unzip `cheng_project.zip` and `cd cheng_project`). **Run every command below from this folder.**

## 3. Create the Python environment

| Library | Tested version | Used for | Download page |
|---|---|---|---|
| Python | 3.12.14 | everything | https://www.python.org/downloads/ |
| psycopg (+ libpq) | 3.3.4 (libpq 18.6) | PostgreSQL driver | https://pypi.org/project/psycopg/ |
| python-dotenv | 1.2.4 | reading `.env` | https://pypi.org/project/python-dotenv/ |
| tabulate | 0.10.0 | tables in the terminal | https://pypi.org/project/tabulate/ |
| matplotlib | 3.11.2 | PNG charts | https://pypi.org/project/matplotlib/ |
| pandas | 3.0.6 | price download (yfinance) | https://pypi.org/project/pandas/ |
| yfinance | 1.7.0 | Yahoo Finance prices (price loader, Admin → Add a stock) | https://pypi.org/project/yfinance/ |
| Faker | 40.40.0 (exact) | sample investor names / emails (reproducible seed) | https://pypi.org/project/Faker/ |
| pytest | 9.2.0 | tests | https://pypi.org/project/pytest/ |

You don't download these one by one: step 3 installs all of them (conda from conda-forge,
https://conda-forge.org/, or pip from PyPI).

With conda (recommended, all platforms):
```bash
conda env create -f environment.yml     # about a minute; creates the environment "spt"
conda activate spt
```
Or with pip:
```bash
python3.12 -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Configure the connection (`.env`)
```bash
cp .env.example .env                     # Windows: copy .env.example .env
```
Then edit `.env` for your PostgreSQL login (never commit `.env`; it is git-ignored):

| Your setup | Settings in `.env` |
|---|---|
| **Linux / WSL**, your own user, no password (tested) | `DB_HOST=/var/run/postgresql` (as in the template), leave `DB_USER` / `DB_PASSWORD` / `DB_PORT` empty |
| **Windows / any password login** (e.g. user `postgres`) | `DB_HOST=localhost`, `DB_PORT=5432`, `DB_USER=postgres`, `DB_PASSWORD=<your password>` |
| **macOS (Homebrew)**, your own user | `DB_HOST=/tmp`, leave the others empty |

`DB_NAME` is the database the app uses (default `portfolio_tracker`); change it if you restore under
another name. A `DB_NAME=...` environment variable overrides `.env` for one run.
Without a `.env`, conda's PostgreSQL client looks for the server socket in `/tmp` and the app reports
"Can't connect to PostgreSQL".

## 5. Create the database and restore the dump

`db/dump/cheng_final_project.sql` (about 2.6 MB) has no owners or grants (it restores under any role
that may create a database), loads the data with ordinary `INSERT`s and has no psql meta-commands,
so it runs in `psql` **or** a GUI such as DBeaver / pgAdmin. Requires PostgreSQL 16 or newer.
Always restore into a NEW, EMPTY database.

### Option 1: psql (command line)
```bash
# 1. Create an EMPTY database (any name; use the same name as DB_NAME in .env)
createdb portfolio_tracker

# 2. Load the dump; stop at the first error, all or nothing
psql -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f db/dump/cheng_final_project.sql

# 3. Quick check: sample data present (1155 trades)
psql -d portfolio_tracker -c "SELECT count(*) AS trades FROM trade" -c "SELECT * FROM v_cash_balance LIMIT 5"
```
With a password login (Windows, user `postgres`), add `-h localhost -U postgres` to each command
(you are asked for the password; on Windows use `db\dump\cheng_final_project.sql`):
```bash
createdb -h localhost -U postgres portfolio_tracker
psql -h localhost -U postgres -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f db/dump/cheng_final_project.sql
```

### Option 2: DBeaver (GUI)
1. In the Database Navigator, right-click the connection > **Create** > **Database**, name it
   `portfolio_tracker` (an empty database), then select it.
2. **File > Open File...** and choose `db/dump/cheng_final_project.sql`. Make sure the editor uses
   that new database (the active database is shown in the editor's toolbar).
3. **SQL Editor > Execute SQL Script** (`Alt+X`). It runs 148 statements, including 50 multi-row
   INSERTs, and takes a few seconds.
4. Refresh the database: schema `public` has 11 tables, 2 views, 16 functions, 3 procedures, 10 triggers.

(pgAdmin: create an empty database, open the file in the **Query Tool**, press **Execute script** (F5).)
If anything fails, drop the database and start again with a new empty one: a GUI runs the
statements one by one, so a failed run can leave a half-restored database.

## 6. Run the app
```bash
conda activate spt                      # (or activate your .venv)
python -m app                           # uses DB_NAME from .env
```
Choose a number and press Enter; **exit with 0** from the main menu. The first screen shows which
database you are connected to.
- Another database for one run: `DB_NAME=portfolio_tracker_test python -m app`
  (Windows PowerShell: `$env:DB_NAME="portfolio_tracker_test"; python -m app`)
- Read-only (browse safely, every change is refused): `make run-readonly`, or
  `PGOPTIONS="-c default_transaction_read_only=on" python -m app`
- `make run` / `make run-test-db` start the app too, but Ctrl+C under make prints
  "make: *** Interrupt". That is make reporting the interrupt, not an app error, so prefer
  `python -m app` for demos and exit with 0.
- Charts are saved in `charts/`, the error log in `logs/app.log` (both git-ignored).
- Sample CSV files for "Import from CSV": `data/samples/` (see its README).

## 7. Errors, the log and debug mode
- A database refusal (not enough cash, duplicate name, ...) is shown as a friendly message; nothing
  is saved and you are back at the menu.
- An unexpected error (a bug) shows `Something went wrong. Details were saved to logs/app.log
  (error 3f9a1c).` and the menu comes back. The log has the time, the error id, the menu action
  and the full traceback; search it for the id. `logs/` is git-ignored; the file is rotated at 1 MB
  (3 old files kept: `app.log.1` .. `app.log.3`).
- Debug mode prints the traceback on screen too: `APP_DEBUG=1 python -m app`

## 8. If the app doesn't start
| The app says | Exit code | What to do |
|---|---|---|
| `Can't connect to PostgreSQL (...)` | 2 | Start the server (WSL: `sudo service postgresql start`); check `DB_HOST` / `DB_PORT` / `DB_USER` in `.env` (template: `.env.example`) |
| `The database 'X' doesn't exist` | 3 | `createdb X`, then restore the dump (section 5) |
| `The database 'X' has no app tables ... the dump hasn't been restored` | 4 | Restore the dump into it (section 5) |

(`echo $?` right after the app ends shows the exit code; 0 = normal exit, 1 = an unexpected error
outside a menu action, see the log.)

## 9. For developers (Linux / WSL / macOS, needs `make`)
| Command | What it does |
|---|---|
| `make test` | creates (if needed) and rebuilds the TEST database `portfolio_tracker_test` from `db/reset.sql`, runs the SQL tests and pytest (your role needs the CREATEDB right, see step 1) |
| `make apply-db` | adds / replaces views, functions, triggers in `portfolio_tracker` (no data touched) |
| `make load-prices` | insert-only price refresh from Yahoo Finance (needs the network) |
| `make seed` / `make reseed` | sample investors, portfolios, trades (`reseed` replaces them) |
| `make dump` / `make verify-dump` | regenerate the dump / restore it into a temporary database and compare |
| `make package` | build `cheng_project.zip` from the committed files (commit first) |

Building the database from source instead of the dump: `createdb portfolio_tracker`,
`psql -d portfolio_tracker -f db/reset.sql` (all tables and objects, no data), `make load-prices`,
`make seed`. Without make (Windows): `python -m pytest`, `python -m etl.load_prices`,
`python -m etl.seed_sample_data`.
