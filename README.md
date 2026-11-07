# Stock-Portfolio-tracker
Course project for database system

## Run the app

From the repo root, with the project's conda env:
```bash
conda activate spt
python -m app                                   # real database (portfolio_tracker), use this for demos
DB_NAME=portfolio_tracker_test python -m app    # test database (emptied by `make test`)
make run-readonly                               # real database, READ-ONLY: browse safely, every change is refused
```
Choose a number and press Enter; **exit with 0** from the main menu.
(`make run` / `make run-test-db` do the same, but Ctrl+C under make prints
"make: *** Interrupt". That is make reporting the interrupt, not an app error, so prefer
`python -m app` for demos and exit with 0.)

### Errors, the log and debug mode
- A database refusal (not enough cash, duplicate name, ...) is shown as a friendly message; nothing
  is saved and you are back at the menu.
- An unexpected error (a bug) shows `Something went wrong. Details were saved to logs/app.log
  (error 3f9a1c).` and the menu comes back. The log has the time, the error id, the menu action
  and the full traceback; search it for the id. `logs/` is git-ignored; the file is rotated at 1 MB
  (3 old files kept: `app.log.1` .. `app.log.3`).
- Debug mode prints the traceback on screen too: `APP_DEBUG=1 python -m app`

### If the app doesn't start
| The app says | Exit code | What to do |
|---|---|---|
| `Can't connect to PostgreSQL (...)` | 2 | Start the server (WSL: `sudo service postgresql start`); check `DB_HOST` / `DB_PORT` / `DB_USER` in `.env` (template: `.env.example`) |
| `The database 'X' doesn't exist` | 3 | `createdb X`, then restore the dump (see below) |
| `The database 'X' has no app tables ... the dump hasn't been restored` | 4 | Restore the dump into it (see below) |

(`echo $?` right after the app ends shows the exit code; 0 = normal exit, 1 = an unexpected error
outside a menu action, see the log.)

## Restore the database from the dump

`db/dump/cheng_final_project.sql` is a plain-SQL `pg_dump` (tables, data, views, functions,
procedures, triggers, indexes), about 2.6 MB. It is portable:
- no owners or grants, so it restores under any role that may create a database;
- data as ordinary `INSERT` statements (no `COPY ... FROM stdin`) and no psql meta-commands
  (no line starts with `\`), so it runs in psql **or** in a GUI tool such as DBeaver / pgAdmin.

Requires PostgreSQL 16 (the version it was made with) or newer. Always restore into a NEW, EMPTY database.

### Option 1: psql (command line)
```bash
# 1. Create an EMPTY database (any name)
createdb portfolio_tracker

# 2. Load the dump; stop at the first error, all or nothing
psql -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql

# 3. Quick check: sample data present
psql -d portfolio_tracker -c "SELECT count(*) AS trades FROM trade" -c "SELECT * FROM v_cash_balance LIMIT 5"
```
With a password login (e.g. Windows, user `postgres`), add `-h localhost -U postgres` to each command:
```bash
createdb -h localhost -U postgres portfolio_tracker
psql -h localhost -U postgres -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql
```

### Option 2: DBeaver (GUI)
1. In the Database Navigator, right-click the connection > **Create** > **Database**, name it
   `portfolio_tracker` (an empty database), then select it.
2. **File > Open File...** and choose `cheng_final_project.sql`. Make sure the editor uses
   that new database (the active database is shown in the editor's toolbar).
3. **SQL Editor > Execute SQL Script** (`Alt+X`). It runs about 140 statements, including 50 multi-row
   INSERTs, and takes a few seconds.
4. Refresh the database: schema `public` has 11 tables, 2 views, 15 functions, 2 procedures.

(pgAdmin: create an empty database, open the file in the **Query Tool**, press **Execute script** (F5).)
If anything fails, drop the database and start again with a new empty one: a GUI runs the
statements one by one, so a failed run can leave a half-restored database.

To regenerate and re-verify the dump (developer machine): `make dump && make verify-dump`.
