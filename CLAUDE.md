# CS 5200 Project: Paper-Trading Portfolio Tracker

## How to work with me
- I must understand and be able to explain all code (course requires my own work).
- Work in small steps. One table / function / feature at a time.
- Before writing code, explain the plan in English and Chinese. After writing, explain what each part does.
- Do not generate the whole project at once. Stop after each step and wait for me.
- I'm learning Python: explain Python syntax clearly.
- Be direct; point out design problems.
- Ask before running anything with sudo, DROP DATABASE, or deleting files.

## How to report
When you finish a step, reply in this order, and keep it short:
1. STATUS (max 3 lines): what's done, test count, and the commit hash + commit message.
2. NEEDS MY DECISION: only questions I must answer. Write "None" if there are none.
3. NEXT: one line.
Put the full explanation (how the code works, EN + 中文, with a tiny example) in a file
docs/notes/<step-name>.md instead of the chat, and tell me the file name.
Whenever a step makes a design decision or finds a limitation, add a line to
docs/notes/report_material.md (final report material, Task 5) as part of that step.

Commit rules:
- Commit at the end of every step, after all tests pass. Never commit failing tests.
- Message format: one short summary line (what changed and why),
  e.g. "Add v_cash_balance view and tests (fan-out safe)"
- No Co-Authored-By (or any other trailer) line: the message is only the summary line. Don't ask again.

## How to plan
Every plan must START with this short summary (max 10 lines), before any details:
1. APPROACH: 2-3 lines, plain words.
2. FILES: which files will be created or changed.
3. EXISTING TESTS CHANGED: list each one and why, or "None".
4. DECISIONS FOR ME: or "None".
5. RISKS: anything that could break, or "None".
Then the details.

## Environment
- WSL (Ubuntu) on Windows 11; Linux user `ethan`; project conda env is `spt` (`conda activate spt`;
  Python 3.12, psycopg 3, pandas, python-dotenv, yfinance, pytest). Not `base`.
- Repo: ~/projects/5200/Stock-Portfolio-tracker (app/, db/, etl/, data/, docs/, tests/)
- analytics_cpp/ is out of scope (C++ dropped from proposal); ignore it
- PostgreSQL 16 in WSL, role `ethan`. Two databases:
  - `portfolio_tracker`: REAL data (loaded prices). Never run tests here.
  - `portfolio_tracker_test`: tests only, rebuilt from scratch by every `make test`.
- Tests: `make test` = rebuild portfolio_tracker_test with reset.sql + SQL tests + pytest.
  db/tests/test_schema.sql exits non-zero if any test fails.
- Always rebuild with reset.sql (drops ALL data): `psql <db> -f db/reset.sql`. On portfolio_tracker
  that wipes the loaded prices: re-run `make load-prices` afterwards.
- New views/functions/triggers/analysis reach the REAL DB with `make apply-db` (db/apply.sql),
  never reset.sql. New idempotent object files go in db/apply.sql (reset.sql includes it).
  Never run schema files one at a time: 01 alone silently drops Part 2's FKs.
  New TABLE files go in db/reset.sql; every other new file goes in db/apply.sql.
- Python connects via etl/db.py using .env (git-ignored; template .env.example). Default is the
  Unix socket DB_HOST=/var/run/postgresql with peer auth (conda's libpq looks in /tmp otherwise).
- Run ETL as modules from the repo root: `python -m etl.load_prices` (or `make load-prices`),
  `python -m etl.seed_sample_data [--replace]` (or `make seed` / `make reseed`)
- Never write the DB password in code or commit it; read it from a git-ignored .env file
- DBeaver (Windows) connects via localhost:5432
- Final deliverable: `cheng_final_project.sql` (pg_dump: DDL, data, functions, procedures, triggers)

## Stack
PostgreSQL, Python 3 + psycopg (CLI numbered menus), yfinance (auto_adjust=False, insert-only refresh), Faker for names/emails

## Schema (11 tables)
investor, portfolio, cash_transaction, trade, stock, sector, exchange,
daily_price (PK ticker+price_date), watchlist, watchlist_item (M:N), trade_audit.
S&P 500 = stock row '^GSPC', security_type INDEX, no sector/exchange.
^GSPC may be on watchlists (watching is fine); only trading an INDEX is blocked.
Done so far:
- db/schema/01_reference_tables.sql (sector, exchange, investor, stock, daily_price)
- db/schema/02_portfolio_tables.sql (portfolio, cash_transaction, trade, watchlist, watchlist_item, trade_audit)
- db/reset.sql: rebuilds everything in order (one transaction)
- db/programmability/01_trade_validation.sql: trg_trade_validate (BEFORE INSERT OR UPDATE on trade):
  price in day's low..high, no INDEX, UPDATE only shares/price (ticker change allowed only via stock rename cascade)
- db/programmability/02_cash_txn_immutable.sql (written by me): trg_cash_txn_immutable
  (BEFORE UPDATE OR DELETE, row-level: rejects UPDATE and direct DELETE; allows cascade delete
  when parent portfolio is already gone) and trg_cash_txn_no_truncate (BEFORE TRUNCATE,
  statement-level; also blocks TRUNCATE portfolio/investor CASCADE, so cleanup must use DELETE)
- db/programmability/03_trade_audit.sql (written by me): trg_trade_audit is AFTER (not BEFORE)
  UPDATE OR DELETE, row-level: copies OLD row into trade_audit, so only changes that actually
  happen are logged (rejected/cancelled ones never reach it). Cascade deletes and ticker renames
  are audited too. trg_trade_no_truncate (BEFORE TRUNCATE) because TRUNCATE skips row triggers.
- db/views/01_v_cash_balance.sql: v_cash_balance, one row per portfolio: starting_cash, deposits,
  withdrawals, buys, sells, cash_balance. Each child table pre-aggregated per portfolio (CTE),
  then LEFT JOINed (no fan-out); COALESCE turns missing parts into 0. Shows CURRENT balance
  (all rows, any date). WHERE portfolio_id = X is pushed into both CTEs and uses
  idx_trade_portfolio_date / idx_cash_portfolio_date.
  Views load in reset.sql BEFORE programmability. Trigger 2d does NOT use it (needs running history);
  tests use it as a cross-check against fn_portfolio_history; execute_trade() and the app will use it
- db/programmability/04_balance_checks.sql: trigger 2d.
  fn_portfolio_history(id): running cash_after / shares_after per event (window SUM, ROWS UNBOUNDED
  PRECEDING; order date, cash before trades, id). fn_check_portfolio_history(id): raises at first
  negative point (trg_cash_never_negative / trg_shares_never_negative, DETAIL has date + amount).
  trg_trade_date_order / trg_cash_txn_date_order (BEFORE INSERT, shared fn_event_date_order):
  lock portfolio, trg_date_before_start / trg_date_before_latest / trg_cash_txn_future_date.
  trg_trade_history_check (AFTER INSERT/UPDATE/DELETE) / trg_cash_txn_history_check (AFTER INSERT):
  lock portfolio, replay whole history; portfolio gone = cascade delete -> skip.
- db/views/02_v_holdings.sql: fn_position_history(id) walks each ticker's trades in order
  (date, trade_id) with a recursive CTE, carrying shares / avg cost (full precision) / realized P/L.
  v_holdings = portfolio CROSS JOIN LATERAL fn_position_history, last row per (portfolio, ticker):
  shares_held, avg_cost, cost_basis, realized_pl, is_open, trade_count, last_trade_date.
  Closed positions kept (is_open false, avg_cost NULL, cost_basis 0). No unrealized P/L (needs a
  price date; later = shares_held * close - cost_basis)
- db/programmability/05_execute_trade.sql: PROCEDURE execute_trade(portfolio_id, ticker, trade_type,
  shares, trade_date, price DEFAULT NULL, INOUT trade_id). Normalizes (trim + upper), adds only
  exec_missing_input / exec_no_price_data, NULL price = that day's close, then one INSERT; all
  trigger/CHECK/FK errors pass through. No COMMIT, no own lock. CALL args can't contain subqueries.
- db/tests/test_schema.sql: constraint/cascade/trigger/view/procedure tests (runs in a rolled-back transaction)
- ETL A (real prices): data/tickers.csv (25 stocks, 8 sectors, + ^GSPC; kept by hand),
  etl/load_prices.py (yfinance auto_adjust=False, 2021-01-01 .. YESTERDAY, rounded half-up to 2 dp,
  insert-only: downloads dates after the last stored one + ON CONFLICT DO NOTHING; rows breaking a
  CHECK are skipped and logged; one transaction per ticker), tests/test_clean_prices.py (pytest),
  db/tests/check_prices.sql (read-only checks on the real DB, `make check-prices`), Makefile
- db/programmability/06_record_cash_transaction.sql: PROCEDURE record_cash_transaction(portfolio_id,
  txn_type, amount, txn_date, INOUT cash_txn_id), same style as execute_trade (exec_missing_input).
- ETL B (sample users): etl/simulate.py (pure; walks each portfolio forward: BUY only what cash allows,
  SELL only what is held, cash before trades same day), etl/seed_sample_data.py (seed 5200, Faker
  40.40.0, SIM_END 2026-10-30; 15 investors, 1-3 portfolios, 20-60 trades via CALL execute_trade with
  NULL price, cash via CALL record_cash_transaction, watchlists, audit demo on each portfolio's LAST
  trade; ONE transaction: any DB rejection rolls back everything). tests/test_simulate.py,
  db/tests/check_sample_data.sql (read-only + fingerprint). `make seed` refuses if investors exist;
  `make reseed` (--replace) deletes all investors, clears trade_audit and RESTARTs identity ids
  (DECIDED: so reruns are identical, ids included)
- db/apply.sql: idempotent objects only (views, programmability, analysis, indexes), included by
  reset.sql; `make apply-db` applies it to portfolio_tracker in one transaction, data untouched.
- db/analysis/: 00_indexes.sql (idx_daily_price_date for max(price_date) defaults),
  fn_sector_allocation(portfolio, as_of, include_cash) [Q2, cash row by default],
  fn_top_movers(start, end, limit) [Q3, RANK, ties kept, gainers > 0 / losers < 0],
  fn_holding_pl(portfolio, as_of) [Q4, trades up to as_of via fn_position_history],
  fn_watchlist_targets_reached(investor, as_of) [Q5]. NULL date = today (CURRENT_DATE, DECIDED:
  agrees with v_cash_balance); closes = latest close <= that date. idx_daily_price_date: keep/drop
  to be decided with query 1 (analysis defaults no longer use max(price_date)).
Next: analysis query 1 (monthly return vs S&P 500), then the Python CLI app
- Trigger errors: ERRCODE check_violation + USING CONSTRAINT = 'trg_...' so Python maps them
  the same way as chk_/fk_/uq_ names (e.diag.constraint_name)

## Design decisions
- Holdings and cash derived via views (v_holdings, v_cash_balance), never stored
- Cash = starting cash + deposits - withdrawals - buys + sells
- portfolio has start_date (simulation start) separate from created_date; all trades/cash txns >= start_date
- New trade/cash txn date >= portfolio's latest trade/cash txn date (>=, not >)
- Same-day ordering: cash transactions before trades (DECIDED, keep). Consequence: a withdrawal
  entered after a same-day SELL can't use that SELL's proceeds (it is replayed before the SELL)
- Buy fails if not enough cash; sell fails if not enough shares; withdrawal fails if > cash
- Trade price within that day's low/high; trade date must have price data
- Row-level rules (price range, not INDEX, valid date) in BEFORE INSERT OR UPDATE trigger, not only in execute_trade()
- Portfolio row lock (SELECT ... FOR UPDATE) is taken by the 2d triggers, so direct SQL is safe too;
  execute_trade() does not lock; the triggers do. Relies on READ COMMITTED (default isolation level)
- Trade update/delete: replay history, reject if cash or shares ever < 0
- Trade updates: only shares and price can change
- Cash transactions cannot be updated or deleted
- trade_audit: no FKs; columns include operation, changed_at, changed_by.
  Intentional snapshot table (copies old trade columns), so not strict 3NF; justify in report
  (history must survive deletion of the trade/portfolio, and must show values as they were)
- Money NUMERIC(14,2); prices NUMERIC(12,2) rounded on load
- Starting cash > 0 and <= 10,000,000; per-transaction deposit cap (CHECK)
- Email unique case-insensitive: unique index on LOWER(email)
- Portfolio and watchlist names unique per investor
- FK actions: investor -> portfolio/watchlist CASCADE; portfolio -> trade/cash_transaction CASCADE;
  watchlist -> watchlist_item CASCADE; stock -> daily_price/watchlist_item CASCADE;
  FKs to stock.ticker use ON UPDATE CASCADE
- trade has NO direct FK to stock. Instead FK (ticker, trade_date) -> daily_price (ticker, price_date)
  ON DELETE RESTRICT ON UPDATE CASCADE: guarantees stock exists AND has a price that day.
  Deleting a stock with trades is blocked (its daily_price cascade hits this RESTRICT);
  ticker renames flow stock -> daily_price -> trade
- Name constraints (chk_..., fk_..., uq_...) so Python can map errors to friendly messages
- Simplifications: no login, no dividends/fees, whole shares, splits not handled
- P/L uses average cost; returns exclude deposits/withdrawals
- Secondary indexes justified in SQL comments (bonus)
## db/ layout
- db/schema/: CREATE TABLE files, numbered in run order (01_, 02_, ...)
- db/views/: views (v_holdings, v_cash_balance, ...)
- db/programmability/: functions, procedures, triggers
- db/dump/: final pg_dump, cheng_final_project.sql
