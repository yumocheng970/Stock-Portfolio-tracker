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
