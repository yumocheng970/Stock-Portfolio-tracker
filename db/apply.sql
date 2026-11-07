-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Create or replace every object that holds NO data: views, functions,
-- procedures, triggers, analysis functions, secondary indexes.
-- Every file here is idempotent (CREATE OR REPLACE / IF NOT EXISTS) and
-- contains no DROP TABLE, so it is safe on a database with real data.
--
-- Used two ways:
--   db/reset.sql includes this file after creating the tables
--   make apply-db runs it alone on portfolio_tracker (data untouched):
--     psql --single-transaction -d portfolio_tracker -f db/apply.sql
--
-- Limitation: CREATE OR REPLACE FUNCTION can't change a function's
-- return columns; that needs a DROP FUNCTION first.
-- =====================================================================

\set ON_ERROR_STOP on
-- Hide NOTICEs such as "index ... already exists, skipping"
SET client_min_messages = warning;

-- Views (before programmability: functions/triggers use them)
\ir views/01_v_cash_balance.sql
\ir views/02_v_holdings.sql

-- Functions, procedures, triggers
\ir programmability/01_trade_validation.sql
\ir programmability/02_cash_txn_immutable.sql
\ir programmability/03_trade_audit.sql
\ir programmability/04_balance_checks.sql
\ir programmability/05_execute_trade.sql
\ir programmability/06_record_cash_transaction.sql
\ir programmability/07_restore_trade.sql
\ir programmability/08_stock_protection.sql

-- Analysis queries (they use the views and fn_portfolio_history)
\ir analysis/00_indexes.sql
\ir analysis/01_monthly_returns.sql
\ir analysis/02_sector_allocation.sql
\ir analysis/03_top_movers.sql
\ir analysis/04_holding_pl.sql
\ir analysis/05_watchlist_targets.sql
