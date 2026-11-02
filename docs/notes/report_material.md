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

### Analysis queries 2–5
- **Analysis as SQL functions** (`db/analysis/`, `LANGUAGE sql STABLE`, defaulted parameters): Python only calls `SELECT * FROM fn_…()`, and the SQL stays in the DB, where it's tested (26 SQL tests on fictional data).
- **Query 2: cash is its own row** by default, so the percentages are of the whole portfolio. Without it, a mostly-cash portfolio would look fully invested. `p_include_cash => false` gives the stocks-only split.
- **Query 3: RANK() with ties kept** (`rank <= 5` can return more than 5 rows), instead of ROW_NUMBER (an arbitrary tie-break) or DENSE_RANK (no skipped ranks). Ranking uses the exact % (rounded only for display). Gainers must be > 0% and losers < 0%.
- **Query 4: "as of" uses only trades up to that date** (`fn_position_history`), not `v_holdings` (always all trades), so a past date isn't mixed with later trades. At the latest date the results equal `v_holdings`.
- **Secondary index `daily_price(price_date)`:** the global "latest price date" default can't use the PK `(ticker, price_date)`, where price_date is the second column. Measured on 38,064 rows: Seq Scan 1.98 ms → Index Only Scan reading 1 row, 0.10 ms. Per-ticker "latest close ≤ date" lookups already use the PK, so they need no index. *Open:* after the default became `CURRENT_DATE`, the analysis functions no longer run this lookup; keep or drop is decided with query 1.
- **Default date = today (`CURRENT_DATE`), not the latest price date.** Prices load only up to yesterday, so "latest price date" would leave today's cash transactions out of query 2 while `v_cash_balance` already counts them. With today, the analysis functions and the views always agree, and the closes are unchanged ("latest close on or before today" is still the latest price loaded). Found during testing (Bal Dates: 9,701 vs 9,702); decided by me.
- **`db/apply.sql` split from `db/reset.sql`:** objects without data (views, functions, triggers, analysis, indexes) are idempotent and listed once. `reset.sql` includes the list after creating the tables; `make apply-db` applies it to the real DB in one transaction without touching data (the fingerprint was unchanged).

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
- Sector allocation percentages are rounded per row, so a portfolio's rows sum to 100 ± 0.02 (seen on real data); market values are exact.

## Technical expertise gained

### Triggers
<!-- BEFORE vs AFTER, row vs statement level, TG_OP / NEW / OLD, trigger order by name, cascade detection -->

### Window functions
<!-- running SUM OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING), PARTITION BY, ROW_NUMBER -->

### Recursive CTE
<!-- anchor + recursive step, carrying state, matching column types -->

### Testing
<!-- rolled-back SQL test harness, expected constraint names, pytest, separate test DB, mutation checks -->
