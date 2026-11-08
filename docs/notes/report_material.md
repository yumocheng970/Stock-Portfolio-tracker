# Report material (Task 5)

A running list of material for the final report, organized by report section.
Every step that makes a design decision or finds a limitation adds a line here.

## Lessons learned: alternative designs considered

- **Soft delete vs hard delete.** Real systems often soft delete (a `deleted_at` column). We chose hard `DELETE` + `trade_audit`, because soft delete would force every view, trigger and query to filter out deleted rows, complicate unique constraints, and disable `ON DELETE CASCADE`. Cash transactions are append-only (a mistake is fixed with an opposite transaction), like an accounting ledger.
- **Separate insert / replay checks vs one history replay.** Trigger 2d could check an INSERT quickly with the current totals (`v_cash_balance`) and replay only on UPDATE/DELETE. We chose one replay (window functions over the whole history) for every change: one code path, so the two checks can never disagree. The cost is one pass over the portfolio's events per changed row, which is fine at paper-trading volumes. Possible optimization: statement-level triggers with transition tables.
- **`trade → daily_price` FK instead of `trade → stock`.** The composite FK `(ticker, trade_date) → daily_price(ticker, price_date)` guarantees that the stock exists *and* has a price on that day, declaratively. It also makes a stock with trades undeletable (its price rows are RESTRICTed), and a ticker rename cascades stock → daily_price → trade.

### Other decisions already made (backfilled from earlier steps)
- Average cost computed with a recursive CTE (`fn_position_history`), because it depends on trade order and a SUM or window SUM can't express it. Closed positions stay in `v_holdings` (`is_open = false`, `avg_cost NULL`) so realized P/L is kept.
- `v_holdings` = `portfolio CROSS JOIN LATERAL fn_position_history(...)`, so `WHERE portfolio_id = X` only walks that portfolio (a recursive CTE directly inside the view would walk all of them).
- `execute_trade()` / `record_cash_transaction()` add only missing-input and no-price errors. Every other rule stays in triggers and constraints, whose errors pass through unchanged (no duplicated rules).
- Trigger errors use `check_violation` + a named constraint (`trg_…`, `exec_…`), so Python maps every error by name.
- Tests run on a separate `portfolio_tracker_test`, rebuilt by every `make test`. Real data lives only in `portfolio_tracker`.
- Price loader: insert-only (download after the last stored date + `ON CONFLICT DO NOTHING`), and up to **yesterday**, because today's bar may still change and could never be corrected later.
- Sample data: one transaction for the whole seed (any rejection rolls everything back). `--replace` also clears `trade_audit` and restarts the ids, so reruns are identical.

### Analysis query 1 (monthly return vs S&P 500)
- **Modified Dietz for monthly returns**, so deposits and withdrawals aren't gains: R = (V_end − V_start − F) / (V_start + Σ wᵢFᵢ), with each flow weighted by the fraction of the month it was invested (counted from the start of its day, matching the "cash before trades" rule). Compared on one example (10,000 start, 3,100 deposit mid-month, 1,000 gain): naive 41 %, flows at end 10 %, flows at start 7.63 %, Modified Dietz 8.62 %. True time-weighted return was rejected (it needs a full valuation on every flow date).
- **First-month S&P base = the latest ^GSPC close before `start_date`** (matching V_start = cash at the start of that day); the fallback is the open on the first price day when the data starts that day.
- **Window functions:** `LAG()` for the start values. The `p_from_month` filter is applied in a later CTE, because a WHERE in the same SELECT runs before window functions. The cumulative return is `EXP(SUM(LN(1+r)) OVER (... ROWS UNBOUNDED PRECEDING)) − 1`, because PostgreSQL has no product aggregate.
- **Index `idx_daily_price_date`: added, measured, dropped when unused.** Added for `max(price_date)` (1.98 ms → 0.10 ms), but once the defaults became `CURRENT_DATE` no analysis function ran that lookup. EXPLAIN ANALYZE of `fn_monthly_returns()` on the real DB (index present) used `pk_daily_price` 4×, the new index 0×, because all price lookups are per ticker. Dropped with `DROP INDEX IF EXISTS` via `make apply-db` (data fingerprint unchanged).
- **Cross-check test:** for every portfolio, the latest month's `end_value` = `v_cash_balance` + market value from `fn_holding_pl`, so three independent code paths agree.

### Analysis queries 2–5
- **Analysis as SQL functions** (`db/analysis/`, `LANGUAGE sql STABLE`, defaulted parameters): Python only calls `SELECT * FROM fn_…()`, and the SQL stays in the DB, where it's tested (26 SQL tests on fictional data).
- **Query 2: cash is its own row** by default, so the percentages are of the whole portfolio. Without it, a mostly-cash portfolio would look fully invested. `p_include_cash => false` gives the stocks-only split.
- **Query 3: RANK() with ties kept** (`rank <= 5` can return more than 5 rows), instead of ROW_NUMBER (an arbitrary tie-break) or DENSE_RANK (no skipped ranks). Ranking uses the exact % (rounded only for display). Gainers must be > 0% and losers < 0%.
- **Query 4: "as of" uses only trades up to that date** (`fn_position_history`), not `v_holdings` (always all trades), so a past date isn't mixed with later trades. At the latest date the results equal `v_holdings`.
- **Secondary index `daily_price(price_date)`** (later dropped, see query 1): the global "latest price date" default can't use the PK `(ticker, price_date)`, where price_date is the second column. Measured on 38,064 rows: Seq Scan 1.98 ms → Index Only Scan reading 1 row, 0.10 ms. Per-ticker "latest close ≤ date" lookups already use the PK, so they need no index. *Open:* after the default became `CURRENT_DATE`, the analysis functions no longer run this lookup; keep or drop is decided with query 1.
- **Default date = today (`CURRENT_DATE`), not the latest price date.** Prices load only up to yesterday, so "latest price date" would leave today's cash transactions out of query 2 while `v_cash_balance` already counts them. With today, the analysis functions and the views always agree, and the closes are unchanged ("latest close on or before today" is still the latest price loaded). Found during testing (Bal Dates: 9,701 vs 9,702); decided by me.
- **`db/apply.sql` split from `db/reset.sql`:** objects without data (views, functions, triggers, analysis, indexes) are idempotent and listed once. `reset.sql` includes the list after creating the tables; `make apply-db` applies it to the real DB in one transaction without touching data (the fingerprint was unchanged).

### Deliverable: the database dump (Task 2)
- **`pg_dump --no-owner --no-privileges`, plain SQL.** Without these flags the file would contain `ALTER … OWNER TO ethan` and GRANTs, which fail on a computer without that role. Now every object belongs to whoever restores it (the file contains 0 OWNER/GRANT/REVOKE lines).
- **Portable to any client and psql version: `--column-inserts --rows-per-insert=1000` instead of COPY, and the `\restrict` lines removed.** COPY `FROM stdin` and `\restrict` (added by pg_dump 16.10+) are psql-only, so the first dump could not run in DBeaver/pgAdmin or in an older psql. The grader's tool is unknown, so the dump now has no line starting with `\` (checked by `make dump`). Multi-row INSERTs (50 statements for 39,508 rows) keep the file at 2.6 MB (COPY: 2.0 MB; one row per INSERT: 6.2 MB with 39,508 statements, slow in a GUI). Column names make each INSERT independent of column order. Restore time: psql 1.8 s, without psql 0.5 s.
- **Tested without psql:** `db/tests/restore_without_psql.py` sends the whole file through psycopg as one plain-SQL string (only the server parses it, like a GUI). Both restores pass the same checks. The old COPY dump fails this test at `\restrict`, which shows the test catches psql-only content.
- **The restore is verified, not assumed.** `make verify-dump` restores into a new empty database. It diffs an inventory against the real DB: row counts, every table/view/routine/trigger/index/constraint, the identity sequences, and an md5 of the views' and analysis functions' output (37 lines, identical). It also runs behaviour checks (an overdraw, an oversell, trading an INDEX, an UPDATE of a cash transaction, a TRUNCATE, an over-withdrawal: all rejected with their `trg_` names; a valid trade gets a new id and is audited) and compares the sample-data fingerprint. Then it drops the temporary database.
- pg_dump creates triggers and foreign keys **after** loading the data, so the restore's COPY doesn't fire the balance triggers (and doesn't have to satisfy them row by row).

### Python CLI app (Task 4), App 1: foundation
- **Layering: all SQL in one module (`app/data_access.py`).** Menus only call its functions, and a test fails if a menu file contains `SELECT/INSERT/UPDATE/DELETE/CALL`, `.execute(` or `import psycopg`. The UI can change without touching SQL, and every query is in one reviewable place.
- **Business rules only in the database; the app checks only the input's shape** (not empty, a number, max length). Email format, uniqueness, enough cash, date order and so on are decided by constraints and triggers. The app shows the database's answer, so no rule exists twice and the two can't disagree. Direct SQL (DBeaver) gets the same protection as the app.
- **Errors mapped by name, with coverage enforced by a catalog test.** `errors.MESSAGES` has a friendly sentence for all 61 names a database error can carry: 47 constraints, the unique index `uq_investor_email_lower`, and 13 names raised by triggers and procedures, found with a regexp over `pg_proc.prosrc`. The test reads the catalog in both directions: a new constraint without a message fails, and so does a stale or misspelled key. Trigger messages add the database's DETAIL (e.g. "Cash would be -50.00 on …"). Unnamed errors fall back to SQLSTATE (23502 NOT NULL reports the column name).
- **One transaction per user action** (`with conn.transaction():` on an autocommit connection). A refused action is rolled back, a friendly message is shown and the user is back at the menu, with no traceback. **Tests** wrap each test in `conn.transaction(force_rollback=True)`, so the data-access transactions become savepoints and the test DB is never changed. The fixture refuses any database except `portfolio_tracker_test`.
- **Typed confirmation for deletes:** the user types the investor's email, not "y". Before that, the app shows what the cascade will delete (portfolios, trades, cash transactions, watchlists).
- **tabulate for tables** (one function call, easy to explain) rather than rich (a large framework). All printing goes through `app/display.py`, so it is one file to change. Numbers are right-aligned via `colalign`, with `disable_numparse` so "100.50" isn't shown as "100.5".

### Python CLI app, App 2: portfolios
- **Hints, not rules.** Before a trade or a cash transaction the app shows the available cash, the shares held, the earliest allowed date and that day's low/high/close. It enforces none of them. `execute_trade()` / `record_cash_transaction()` and the triggers decide, and their refusal comes back with the database's DETAIL ("Not enough cash. Cash would be -98070.00 on 2025-03-07, after trade 109 (BUY 1000 DEMO @ 107.00)"). So the rules still exist once, and direct SQL is protected in the same way.
- **Date default = the latest price date, or the portfolio's latest allowed date if later (decided by me, after trying App 1).** The first idea, "Enter = today", was a trap. Prices load only up to yesterday, and new events can't be dated before the portfolio's latest event. A portfolio started today, or a deposit dated today, would block all trading until the next price load. Every date prompt (start date, trade date, deposit/withdrawal) now uses `GREATEST(max(price_date), latest event / start_date)` and shows the available price range. A test proves that a portfolio created with the default start date can buy on the default trade date.
- The app now runs `max(price_date)` (for the default and the price range) for each date prompt. On 38k rows that is a ~2 ms Seq Scan, because `idx_daily_price_date` was dropped (no analysis query used it). That is fine for an interactive prompt; the index could come back if the table grows a lot.
- One menu function serves both Buy and Sell (`lambda s: trade(s, "BUY")`), and another both Deposit and Withdraw: less duplicated code.

- **App 2 polish (from my own test run):**
  - Dates accept `2026-11-6` (YYYY-M-D, own regex parser instead of `date.fromisoformat`).
  - Enter with no default says why ("A date is required: no prices are loaded yet").
  - An unknown ticker, or an index, is asked again at once instead of after shares/date/price. This is still only a hint; the DB decides.
  - When the database's DETAIL already says everything the message says (`exec_no_price_data`, `exec_missing_input`), only the DETAIL is shown, as one precise line.
- **Read-only mode for safe demos (`make run-readonly`).** The server setting `default_transaction_read_only=on` (via `PGOPTIONS`) makes every transaction read-only: browsing works, and every change is refused with a friendly message (SQLSTATE 25006). It is enforced by PostgreSQL, not by the app, so no code path can bypass it. *Lesson:* while exploring the real DB with scripted input, the input got out of step and created a test portfolio. I removed it (the fingerprint was unchanged), and since then real-DB exploration only runs in this mode.

### Python CLI app, App 3: trade history, audit, restore
- **Restoring a deleted trade vs the date-order rule: an "exact-replay exemption" (decided by me among three options).** A restored trade is usually older than the portfolio's latest event, so `trg_date_before_latest` would reject it.
  - The new procedure `restore_trade(audit_id)` re-inserts the trade with its **original trade_id** (`OVERRIDING SYSTEM VALUE`).
  - The date-order trigger skips **only** that one check, and only when the new row equals that trade's **latest** audit row and that row is a DELETE.
  - Everything else still runs: the start-date check, price within the day's range, no INDEX, the daily_price FK and the history replay (cash / shares never negative).
  - The exemption is defined by the data, so it can't be claimed by other inserts: a normal insert gets a new id, and no audit row has it. SQL tests prove that a new trade on the old date, or the old id with different values, is still rejected.
  - **Rejected:** a session flag (anyone running SQL could set it and skip date order for any insert), and restoring as a new trade at the latest date (that changes the history; not "as it was").
- **Keeping the original trade_id** also keeps the trade's place among same-day trades in the replay (order: date, cash before trades, id). With a new id it would move to the end of its day, which can change whether the history is valid.
- **Restoring twice is refused by named errors** (`exec_trade_already_restored`, and `exec_restore_not_latest` for an older DELETE row after newer changes). The primary key on trade_id is the final guard if two sessions restore at the same time. A restore is an INSERT, so it writes no audit row; the DELETE row stays as history, and the app shows its status ("restorable" / "restored").
- **Money in the database's DETAIL gets thousands separators** in the app (`-20366046.40` → `-20,366,046.40`, the same style as the tables). A regex matches only numbers with exactly 2 decimals, so dates, ids and share counts are unchanged, and `Decimal` keeps it exact.

### Python CLI app, App 4: watchlists
- **One definition of "target reached".** The watchlist list (the "targets reached" count), the item list (the "reached" column) and the "Targets reached" screen all use `fn_watchlist_targets_reached` (analysis query 5: latest close on or before today >= target). The app and the report can't disagree, and a test compares the screen's rows with the function.
- **Watching an index is allowed, trading it isn't.** The same ticker prompt is reused with `allow_index=True` for watchlists, so ^GSPC can be added. The `trg_trade_not_index` rule applies only to trades.
- **Three answers for an optional value:** Enter = keep, a number = set, `none` = clear (NULL). The input helper returns a unique *sentinel* object `CLEAR` for "clear", so it can't be confused with `None` (keep) or with a number. A negative or zero target still goes to the database, which refuses it (`chk_watchlist_target_positive`): a hint, not a rule.

### Python CLI app, App 5: reports
- **Reports reuse the analysis functions unchanged.** Each data-access wrapper is `SELECT * FROM fn_…(…)`, and a test checks that it returns exactly the function's rows. The app adds only formatting: `+12.34 %`, a cumulative line ("the portfolio beat/trailed the S&P 500 by N points") and P/L totals. So the report and the CLI can't disagree.
- **The monthly report's "to" month defaults to the month of the latest price date (decided by me).** The function's own default is the current month, but prices stop before today. With that default, the last row would be a flat, partial month showing a misleading 0.00 %. A test checks the default and that the current month doesn't appear.
- **An empty result prints a sentence, never an empty table:** "No holdings yet as of …", "No stock holdings as of …: 100.00 % cash", "No losers between … and …". An end date before the start date (top movers) is checked in the app: it is the shape of a report request, not a data rule, and the SQL function would just return nothing.
- **Percentages:** changes and returns carry a sign (`+12.34 %`); shares of a whole (sector allocation) don't (`54.30 %`).
- **Display rounding = half up**, like PostgreSQL's `ROUND` and the price loader. Found by a test: Python formats `Decimal("12.345")` as `12.34` (round half to even, "banker's rounding"), so the app could have shown a different last digit than the database. `display.round2` now quantizes half up before formatting.
- Shared prompts (price range, default date, ticker) moved to `app/menus/common.py`. Reports and portfolios import each other's menus, and a shared module avoids a circular import.

### Python CLI app, App 6: market data and admin
- **Add a stock = a "complicated translation" (bonus).** Ticker + names → a yfinance download of the full history (2021-01-01 to yesterday) → the loader's cleaning rules (cents half up; rows that would break a CHECK are skipped) → database rows.
  - **All or nothing:** the download runs *before* the transaction. If it fails, returns nothing or has no usable rows, a `DownloadError` with a friendly sentence is shown and no transaction is opened.
  - Then **one** transaction inserts the new sector / exchange (if one was typed), the stock and all its prices. Any refusal (duplicate ticker, bad format) rolls all of it back, the new sector included.
- **One refresh code path.** The loader's per-ticker loop was moved out of `main()` into `refresh_tickers(conn, tickers, yesterday, download=…)`. `make load-prices` (tickers from the CSV) and the app's "Refresh all prices" (every row of the stock table, also app-added stocks) run the same insert-only code. A smoke test ran the refactored `main()` twice on the test DB with yfinance faked: the 2nd run inserted 0 rows.
- **Benchmark protection (decided by me): `trg_stock_benchmark_protected`.** ^GSPC can't be deleted or renamed, because `fn_monthly_returns` looks it up by name. A delete would not be stopped by the trades' RESTRICT FK, because an index can't be traded, so its prices would cascade away silently. The company name can still be edited. It is a DB trigger, so DBeaver users are protected too.
- **The app never writes `data/tickers.csv` (decided by me).** The CSV is the hand-kept bootstrap. An app writing into a repo file would mix runtime data with source code, and a rolled-back transaction couldn't undo the file change.
- **A new sector or exchange is created inside the add-stock transaction**, so a failed add leaves no orphan sector. Otherwise sectors and exchanges are read-only lists.
- **A ticker rename shows ON UPDATE CASCADE end to end:** stock → daily_price → trade (the audit trigger logs one UPDATE row per trade with the OLD ticker), and stock → watchlist_item. The app shows the counts first. Cash and holdings are unchanged (tested).
- **Tests never use the network.** Every download is replaced with `unittest.mock` (`return_value`, `side_effect`, `assert_called_once_with`). An autouse fixture also makes any real `yfinance.Ticker` call raise, so a forgotten mock fails loudly instead of quietly downloading.

### Extra 1: PNG charts
- **Charts reuse the report rows.** "Save as PNG chart?" is offered right after a report, with the rows the user just saw. The CSV next to each PNG is exactly the SQL function's rows (a test compares them), so every chart can be checked against its numbers.
- **The portfolio and S&P 500 lines are indexed to 100 at the start:** level = 100 × (1 + cumulative %). Both start at the same point even though the portfolio is worth e.g. 127,000 and the index 4,500, and the gap at the end is the cumulative difference.
- **Non-interactive matplotlib backend "Agg":** it only renders into files and can never open a window, so it is safe in tests, over SSH and in WSL. In WSL the app offers to open the PNG with Windows (`wslpath -w` + `explorer.exe`). A test fixture makes any attempt to start a program fail.
- Charts only read the database, so they also work in `make run-readonly` (tested with a read-only transaction). The files go into `charts/` (git-ignored), named by portfolio id, chart type and the data's date.
- `matplotlib-base` (conda-forge) instead of `matplotlib`: the same library without GUI toolkits (Qt), which a PNG-only backend doesn't need. It is loaded only when a chart is requested, so app start-up stays fast.

### Extra 2: CSV trade import
- **Two-stage validation.**
  - Python checks only the **shape** of every row (a real date, a known type, numbers that are numbers) and lists **all** bad rows with their row numbers before touching the database.
  - The database then decides whether each row is **allowed**: every row goes through `execute_trade()` / `record_cash_transaction()` and the same triggers as a hand-typed trade.
  - No business rule is written twice.
- **All or nothing, with row numbers.** All rows run inside ONE transaction. The first refusal raises `ImportRowError(row, error)` inside the transaction block, which rolls back every earlier row too. The user sees e.g. "Row 6: Not enough cash. Cash would be -204,679.60 on 2026-09-15, after trade … (BUY 1000 NVDA @ 212.17)."
- **Rows are sorted into history order (decided by me):** date, then cash before trades, then file order (a stable sort), which is exactly the order the database replays. The preview says when rows were reordered, and messages keep the file's row numbers.
- **Windows paths in WSL:** `C:\Users\…\trades.csv` → `/mnt/c/Users/…/trades.csv` (pure function; quotes from "Copy as path" stripped). Files saved by Excel (with a byte-order mark) are read with `utf-8-sig`.
- **Row limit 1,000:** each imported row replays the portfolio's history (the trigger design), so the cost grows faster than linearly. Measured on the test DB: 250 rows 0.29 s, 500 rows 0.65 s, 1,000 rows 1.70 s.
- **Read-only mode** refuses the import up front with a friendly message (the database would refuse anyway).
- Two sample files in `data/samples/` (one valid, one failing on row 6) for the demo video, both tested.

### Extra 3: rebalance to target %
- **A pure calculation** (`app/rebalance.py`: no database, no input), tested with exact numbers. The database only provides the inputs (cash, holdings, latest closes) and carries out the trades.
- **Rounding that provably keeps cash ≥ 0:** SELL n = ⌈current − target shares⌉ (round up), BUY n = ⌊target shares − current⌋ (round down).
  - So every targeted ticker ends at or below its target value.
  - Trades at the valuation price conserve the total value V.
  - Therefore cash after ≥ V·(1 − Σ targets) − kept ≥ 0 whenever targets + kept ≤ 100 % (checked first).
  - Verified on 1,000 seeded random portfolios. A worked example by hand is in `docs/notes/extra_3_rebalance.md`.
- **Decisions (mine, approved):**
  - targets per ticker (exact, easy to explain)
  - held tickers not in the targets are kept (a short list never sells everything else silently; `KO 0` sells)
  - no minimum-trade threshold (skipping a small SELL could break the cash guarantee); the whole-share drift is shown instead
- **SELLs are inserted before BUYs.** Same-day trades replay by trade_id, so the sale cash exists when the BUYs are checked. A test shows the BUY-first order is refused by `trg_cash_never_negative`.
- **All or nothing:** all trades in one transaction, and a refusal ("BUY 250 LATE: No price for LATE on …", or an index target) rolls back the earlier trades too.
- In read-only mode the preview works (it only reads), and the trades are refused at the confirm step.

### Final app step: unexpected errors and startup problems
- **One catch point.** Every menu action passes through `run_menu`, so one `try/except Exception` there covers the whole app. Database refusals are still handled earlier by `safe_call` (friendly messages unchanged). What reaches `run_menu` is a bug.
  - It is logged with a short **error id** (`secrets.token_hex(3)`), the menu path ("Portfolio: Growth > Rebalance") and the full traceback.
  - Any open transaction is rolled back (a safety net; normally `with conn.transaction()` already did it).
  - The user sees "Something went wrong. Details were saved to logs/app.log (error 3f9a1c)." and the same menu again.
  - `KeyboardInterrupt` / `EOFError` are re-raised so Ctrl+C / Ctrl+D still exit. `EOFError` is a subclass of `Exception` and would otherwise be swallowed.
- **Log file:** Python's `logging` with a `RotatingFileHandler` (1 MB, 3 backups, about 4 MB at most), in the git-ignored `logs/`. Tests send it to a temporary folder (an autouse fixture), so the repo is never written.
- **Debug mode `APP_DEBUG=1`** also prints the traceback on screen and still returns to the menu (decided by me): you see the bug and keep your place.
- **Startup diagnosis with exit codes:** can't connect → 2 (how to start PostgreSQL in WSL), database missing → 3 (`createdb` + restore), schema missing → 4 (restore the dump), unexpected → 1. Connection errors carry **no SQLSTATE** (checked: `e.sqlstate` is None, since no session exists yet), so "database … does not exist" is recognised from the server's message. The schema check looks for the 11 tables, both views and the key routines (`to_regclass`, `pg_proc`). All three cases are tested with real connection attempts that change nothing (a missing socket dir, a missing DB name, and the always-present `postgres` DB as the "empty" one).

### Submission check: building on a new computer
- **A fresh-machine test of the README** (clean clone, new conda environment, new scratch database, only the README) found **12 gaps** in the old README. There was no setup section at all: no clone, environment or `.env` step, and no download pages. The restore command pointed at the wrong path. `environment.yml` was a Linux-only build export. The DBeaver counts were stale. The rewritten README passed a second fresh run end to end: the restore, an app session with a trade and a report, and `make test` (343 SQL + 229 pytest) inside the clone. The table of findings is in `docs/notes/submission_check.md`.
- **Portable environment:** `environment.yml` and `requirements.txt` list only the 8 libraries the code imports, with the tested versions as minimums. Faker is pinned exactly because the seeded sample data depends on it. The C++ toolchain and kaggle were dropped (the C++ extension is future work).
- **The package is built from committed files only** (`git archive` of HEAD minus `analytics_cpp/`, `CLAUDE.md` (the AI assistant's working notes) and `docs/` except `docs/app_design.md` (the study notes stay in the repository)), so secrets and generated files (`.env`, `logs/`, `charts/`, `__pycache__`) can't get in, and a scan confirmed it.
- Honest scope: tested on Windows 11 + WSL 2 (Ubuntu 24.04). The native Windows and macOS instructions follow the official installers but were not run.

### Native-Windows test and setup wizard
- **Tested on native Windows 11** (Miniforge Prompt, PostgreSQL 18.6) from the zip: environment, restore (1,155 trades), app, reports and charts all worked. The dump made with PostgreSQL 16 restores into 18. Findings: the doubled folder after "Extract All", a port conflict with PostgreSQL in WSL, too many manual steps, the no-price date flow, and opening charts only in WSL. All were fixed.
- **Setup wizard (`setup.bat` / `./setup.sh` → `python -m setup`):**
  - it tests the connection **immediately** and asks again on failure
  - it shows "Connected to PostgreSQL 18.6 on localhost:5432 as postgres."
  - **version gate** ≥ 16 (`server_version_num`), before anything is changed
  - the password is typed hidden (getpass) and **never printed**; `.env` values are single-quoted, so python-dotenv takes them literally
  - it creates the database, and **never restores into a database that has tables** (the app's schema → "already restored"; other tables → refused)
  - it asks before overwriting `.env`
  - it doesn't install PostgreSQL or Miniforge

  `setup.sh` was tested end to end in WSL; `setup.bat` is written but not yet tested on Windows.
- **Bug found while testing the wizard:** the dump's `set_config('search_path', '', false)` empties the search path for the rest of the **session**, so queries on the same connection after a restore failed. `restore_dump` now resets it. `verify-dump` never saw it because it uses new connections.
- **Trading-day hints:** a date without a price is asked again at once, with the reason (weekend / after the last price / before the first / market holiday, detected because ^GSPC has no price either / missing for this stock only) and the nearest trading days. Hints only: the database still refuses a date without a price.
- **Opening charts:** WSL (explorer.exe), native Windows (`os.startfile`) and macOS (`open`).

## Lessons learned: known limitations (document honestly)

- **trade_audit is not strict 3NF:** it's an intentional snapshot table (it copies the old trade columns, with no FKs), because history must survive the deletion of the trade or portfolio and must show values as they were.
- **Same-day rule:** cash transactions come before trades on the same day, so sale proceeds can't be withdrawn on the same day as the sale.
- **Concurrency relies on READ COMMITTED** (the PostgreSQL default): after waiting for the portfolio row lock, the next query sees the other transaction's committed rows. Under REPEATABLE READ the lock alone wouldn't prevent two overdrawing trades.
- **A stock split after the first price load is not handled** (insert-only refresh): Yahoo re-adjusts old prices, but stored rows are never changed, so the history would jump. The fix would be reloading that ticker.
- Each statement is checked on its own (immediate triggers, not deferred to COMMIT): two changes that are only valid together must be made in an order where each step is valid.
- TRUNCATE is blocked on `trade` and `cash_transaction`, because row-level triggers don't fire on TRUNCATE. Cleanup must use `DELETE`, and this also blocks `TRUNCATE portfolio/investor CASCADE`.
- The balance replay runs once per changed row, so a multi-row statement (e.g. a ticker rename over many trades) replays the same portfolio several times.
- Reproducible sample data depends on the Faker version (40.40.0) and on the price data up to the fixed `SIM_END` (2026-10-30).
- `make apply-db` uses `CREATE OR REPLACE`, which can't change a function's return columns. That change needs a manual `DROP FUNCTION` first.
- The dump drops pg_dump's `\restrict` protection, a 2025 fix that stops psql from running meta-commands injected through malicious object names. That is acceptable because every name and value in this database was created by us. DBeaver itself could not be tested here (Windows GUI). The non-psql restore is tested through psycopg instead. A GUI runs the statements one by one, so a failed run can leave a half-restored database (restore into a new empty one again).
- Under `make run`, Ctrl+C prints "make: *** Interrupt" (make reports the signal, which the app can't prevent). The README and the start screen say to exit with 0, and demos use `python -m app`.
- Restore is all-or-nothing per trade: if the history no longer allows it (e.g. the cash was spent since), it is refused (`trg_cash_never_negative`), and the user must first make room (deposit, or restore in a different order).
- The audit log records UPDATE and DELETE only; a restore shows up as the DELETE row's status "restored", not as its own audit row.
- A stock added in the app is not in `data/tickers.csv`: after `reset.sql` + `make load-prices` it is gone unless it is added to the CSV by hand.
- Old trade_audit rows keep the ticker they had. Restoring a trade that was deleted *before* a ticker rename fails with the friendly FK message (no price for the old ticker).
- "Add a stock" and "Refresh all prices" need the network (Yahoo Finance). Failures are shown per ticker, and nothing partial is saved for an add.
- CSV import: the Windows-path conversion assumes WSL's default mount root `/mnt`; files must be comma-separated (Excel in some locales saves `;`); at most 1,000 rows per file.
- Rebalancing uses whole shares, so each target is met only to within one share's value (shown as drift). Expensive shares in a small portfolio drift more.
- Telling "database does not exist" from other connection failures relies on the server's English message text (connection errors have no SQLSTATE); with a non-English server locale it would fall back to the general "can't connect" advice.
- `setup.bat` has not been run on Windows yet (written to the same steps as the tested `setup.sh`); macOS is untested.
- The CLI app has no login or password: "choose investor" acts as the login (a stated simplification).
- Identity sequences aren't rolled back with a transaction, so the rolled-back tests use up ids (e.g. the next investor in the test DB is 35, not 1). This is harmless: ids are only unique, not consecutive.
- Sector allocation percentages are rounded per row, so a portfolio's rows sum to 100 ± 0.02 (seen on real data); market values are exact.
- Monthly returns: Modified Dietz is an approximation of the time-weighted return (it assumes the portfolio grows evenly within the month). A month with a zero denominator (everything withdrawn) gets a NULL return, which the cumulative return treats as 0 %. The current month shows 0 % until prices are refreshed. Excess is rounded from the exact difference (it may differ by 0.01 from the difference of rounded values).

## Future work

- **Friendly handling of unexpected Python errors** (planned as the last step before submission): today a bug (not a database error) still shows a traceback, so bugs stay visible during development. The plan is a short "unexpected error" message plus a log file.
- **C++ analytics extension (`analytics_cpp/`)**: an optional extension from the proposal. It will be built only after the Python CLI app works. If it isn't built, it goes here as future work.

## Technical expertise gained

### Triggers
<!-- BEFORE vs AFTER, row vs statement level, TG_OP / NEW / OLD, trigger order by name, cascade detection -->

### Window functions
<!-- running SUM OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING), PARTITION BY, ROW_NUMBER -->

### Recursive CTE
<!-- anchor + recursive step, carrying state, matching column types -->

### Testing
<!-- rolled-back SQL test harness, expected constraint names, pytest, separate test DB, mutation checks -->
