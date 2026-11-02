-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Secondary indexes for the analysis queries (bonus)
-- Here, not in db/schema/, so `make apply-db` can add them to the real
-- database without a reset. IF NOT EXISTS makes the file re-runnable.
-- =====================================================================

-- Every analysis function defaults its date to "the latest price date":
--     SELECT max(price_date) FROM daily_price [WHERE price_date <= ...]
-- The primary key (ticker, price_date) can't serve that: price_date is
-- its SECOND column, so PostgreSQL scans all rows (Seq Scan, 38k rows
-- for 26 tickers x ~6 years, growing every day). With this index it is
-- a one-row Index Only Scan Backward. Query 1 (monthly returns) will
-- also look up month-end dates by price_date alone.
--
-- Not needed: "latest close of ONE ticker on or before a date"
-- (WHERE ticker = x AND price_date <= d ORDER BY price_date DESC LIMIT 1)
-- already uses the primary key, because ticker is its first column.
CREATE INDEX IF NOT EXISTS idx_daily_price_date ON daily_price (price_date);
