-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Inventory of a database, one "name|value" line each. READ-ONLY.
-- `make verify-dump` runs it on portfolio_tracker AND on the database
-- restored from db/dump/cheng_final_project.sql, then diffs the two
-- outputs: no difference = the dump restored everything.
--   1. row count of each of the 11 tables
--   2. every table, view, function, procedure, trigger, index, constraint
--   3. identity sequences (so new rows after a restore get fresh ids)
--   4. md5 of every row of the reference tables, the views and the
--      analysis functions (the sample-data fingerprint covers the rest)
-- =====================================================================
\set ON_ERROR_STOP on

-- 1. Row counts
SELECT 'rows ' || t || '|' || n FROM (VALUES
    ('sector',           (SELECT count(*) FROM sector)),
    ('exchange',         (SELECT count(*) FROM exchange)),
    ('investor',         (SELECT count(*) FROM investor)),
    ('stock',            (SELECT count(*) FROM stock)),
    ('daily_price',      (SELECT count(*) FROM daily_price)),
    ('portfolio',        (SELECT count(*) FROM portfolio)),
    ('cash_transaction', (SELECT count(*) FROM cash_transaction)),
    ('trade',            (SELECT count(*) FROM trade)),
    ('watchlist',        (SELECT count(*) FROM watchlist)),
    ('watchlist_item',   (SELECT count(*) FROM watchlist_item)),
    ('trade_audit',      (SELECT count(*) FROM trade_audit))
) AS v(t, n);

-- 2. Objects in schema public
SELECT 'tables|' || string_agg(relname, ',' ORDER BY relname)
FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r';
SELECT 'views|' || string_agg(relname, ',' ORDER BY relname)
FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'v';
SELECT 'indexes|' || string_agg(relname, ',' ORDER BY relname)
FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'i';
-- prokind: f = function, p = procedure
SELECT 'routines ' || prokind::text || '|' || count(*) || ' ' || string_agg(proname, ',' ORDER BY proname)
FROM pg_proc WHERE pronamespace = 'public'::regnamespace
GROUP BY prokind ORDER BY prokind;
-- tgenabled 'O' = enabled
SELECT 'triggers|' || count(*) || ' '
       || string_agg(tgrelid::regclass::text || '.' || tgname || ':' || tgenabled::text, ',' ORDER BY tgrelid::regclass::text, tgname)
FROM pg_trigger WHERE NOT tgisinternal;
SELECT 'constraints|' || count(*) || ' ' || string_agg(conname, ',' ORDER BY conname)
FROM pg_constraint WHERE connamespace = 'public'::regnamespace;

-- 3. Identity sequences: the next id must continue after the restored rows
SELECT 'sequence ' || sequencename || '|' || COALESCE(last_value::text, 'unused')
FROM pg_sequences WHERE schemaname = 'public' ORDER BY sequencename;

-- 4. Content digests (row text sorted, so row order doesn't matter)
SELECT 'md5 sector|'      || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM sector t;
SELECT 'md5 exchange|'    || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM exchange t;
SELECT 'md5 stock|'       || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM stock t;
SELECT 'md5 daily_price|' || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM daily_price t;
SELECT 'md5 v_cash_balance|' || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM v_cash_balance t;
SELECT 'md5 v_holdings|'     || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM v_holdings t;
SELECT 'md5 fn_monthly_returns|'   || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM fn_monthly_returns() t;
SELECT 'md5 fn_sector_allocation|' || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM fn_sector_allocation() t;
SELECT 'md5 fn_top_movers|'        || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM fn_top_movers('2021-01-04') t;
SELECT 'md5 fn_holding_pl|'        || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM fn_holding_pl() t;
SELECT 'md5 fn_watchlist_targets_reached|'
       || md5(string_agg(t::text, ',' ORDER BY t::text)) FROM fn_watchlist_targets_reached() t;
