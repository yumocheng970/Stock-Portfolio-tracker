-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Rebuild the whole database from scratch, in the correct order.
-- WARNING: drops every table, so ALL DATA IS LOST.
-- Run from anywhere:  psql portfolio_tracker -f db/reset.sql
-- =====================================================================

-- Stop at the first error instead of running the remaining files.
\set ON_ERROR_STOP on
-- Hide "drop cascades to ..." NOTICEs; warnings and errors still show.
SET client_min_messages = warning;

-- One transaction: if any file fails, everything is rolled back and
-- the database keeps its previous state. (DDL is transactional in PostgreSQL.)
BEGIN;

-- \ir = include a file, path relative to THIS file's folder
\ir schema/01_reference_tables.sql
\ir schema/02_portfolio_tables.sql

-- Views (db/views/) go here

-- Functions, procedures, triggers
\ir programmability/01_trade_validation.sql
\ir programmability/02_cash_txn_immutable.sql
\ir programmability/03_trade_audit.sql

COMMIT;
