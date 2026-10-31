# CS 5200 Project: Paper-Trading Portfolio Tracker

## How to work with me
- I must understand and be able to explain all code (course requires my own work).
- Work in small steps. One table / function / feature at a time.
- Before writing code, explain the plan in English and Chinese. After writing, explain what each part does.
- Do not generate the whole project at once. Stop after each step and wait for me.
- I'm learning Python: explain Python syntax clearly.
- Be direct; point out design problems.
- Ask before running anything with sudo, DROP DATABASE, or deleting files.

## Environment
- WSL (Ubuntu) on Windows 11; Linux user `ethan`; conda `base` is active
- Repo: ~/projects/5200/Stock-Portfolio-tracker (app/, db/, etl/, data/, docs/, tests/)
- analytics_cpp/ is out of scope (C++ dropped from proposal); ignore it
- PostgreSQL 16 in WSL, database `portfolio_tracker`, role `ethan`
- Always rebuild with reset.sql: `psql portfolio_tracker -f db/reset.sql` (drops all data).
  Never run schema files one at a time: 01 alone silently drops Part 2's FKs.
  Every new schema/view/programmability file must be added to db/reset.sql.
- Run tests with: `psql portfolio_tracker -q -f db/tests/test_schema.sql` (rolled back, DB unchanged)
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
- db/tests/test_schema.sql: constraint/cascade tests for 01+02 (runs in a rolled-back transaction)
Next: triggers (db/programmability/)

## Design decisions
- Holdings and cash derived via views (v_holdings, v_cash_balance), never stored
- Cash = starting cash + deposits - withdrawals - buys + sells
- portfolio has start_date (simulation start) separate from created_date; all trades/cash txns >= start_date
- New trade/cash txn date >= portfolio's latest trade/cash txn date (>=, not >)
- Same-day ordering: cash transactions before trades
- Buy fails if not enough cash; sell fails if not enough shares; withdrawal fails if > cash
- Trade price within that day's low/high; trade date must have price data
- Row-level rules (price range, not INDEX, valid date) in BEFORE INSERT OR UPDATE trigger, not only in execute_trade()
- execute_trade() locks the portfolio row (SELECT ... FOR UPDATE)
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
