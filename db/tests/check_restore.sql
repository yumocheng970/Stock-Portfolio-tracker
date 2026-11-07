-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Behaviour checks on a database RESTORED from the dump: the triggers
-- and procedures don't just exist, they still enforce the rules.
-- Uses the restored sample data. Everything runs in one transaction that
-- is ROLLED BACK, so the database is unchanged.
-- Run by `make verify-dump`; exits non-zero if any check fails.
-- =====================================================================
\set ON_ERROR_STOP on
\o /dev/null
SET client_min_messages = warning;
BEGIN;

CREATE TEMP TABLE restore_check (no SERIAL, label TEXT, passed BOOLEAN, detail TEXT);

-- The statement must fail with error name p_expected (e.diag.constraint_name).
CREATE FUNCTION pg_temp.expect_error(p_label TEXT, p_sql TEXT, p_expected TEXT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_constraint TEXT;
BEGIN
    EXECUTE p_sql;
    RAISE EXCEPTION '__no_error__';
EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
    INSERT INTO restore_check (label, passed, detail)
    VALUES (p_label, v_constraint = p_expected,
            CASE WHEN SQLERRM = '__no_error__' THEN 'succeeded but should have failed'
                 ELSE COALESCE(v_constraint, '-') || ': ' || SQLERRM END);
END $$;

CREATE FUNCTION pg_temp.check(p_label TEXT, p_cond BOOLEAN) RETURNS void
LANGUAGE sql AS $$
    INSERT INTO restore_check (label, passed, detail) VALUES (p_label, COALESCE(p_cond, false), '');
$$;

-- Test subject: portfolio 1 trading AAPL on its latest price date
-- (the latest date is >= every sample event, so the date-order trigger is satisfied)
CREATE TEMP TABLE subject AS
SELECT 1 AS pid, 'AAPL'::text AS ticker, dp.price_date AS d, dp.close,
       (SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = 1) AS cash
FROM daily_price dp WHERE dp.ticker = 'AAPL' ORDER BY dp.price_date DESC LIMIT 1;

-- 1. execute_trade + trg_cash_never_negative: BUY more than the cash allows
SELECT pg_temp.expect_error('execute_trade: BUY above the cash balance is rejected',
    format('CALL execute_trade(%s, %L, ''BUY'', %s, %L, NULL, NULL)',
           pid, ticker, ceil(cash / close)::int + 1, d), 'trg_cash_never_negative')
FROM subject;
-- 2. trg_shares_never_negative: SELL more than held
SELECT pg_temp.expect_error('execute_trade: SELL more shares than held is rejected',
    format('CALL execute_trade(%s, %L, ''SELL'', %s, %L, NULL, NULL)',
           pid, ticker,
           COALESCE((SELECT shares_held FROM v_holdings WHERE portfolio_id = pid AND ticker = s.ticker), 0) + 1,
           d), 'trg_shares_never_negative')
FROM subject s;
-- 3. trg_trade_validate: no trading an INDEX
SELECT pg_temp.expect_error('execute_trade: trading ^GSPC is rejected',
    format('CALL execute_trade(%s, ''^GSPC'', ''BUY'', 1, %L, NULL, NULL)',
           pid, (SELECT max(price_date) FROM daily_price WHERE ticker = '^GSPC')),
    'trg_trade_not_index')
FROM subject;
-- 4. trg_cash_txn_immutable / trg_trade_no_truncate
SELECT pg_temp.expect_error('cash_transaction: UPDATE is rejected',
    'UPDATE cash_transaction SET amount = amount + 1', 'trg_cash_txn_immutable');
SELECT pg_temp.expect_error('trade: TRUNCATE is rejected',
    'TRUNCATE trade', 'trg_trade_no_truncate');
-- 5. record_cash_transaction: withdrawing more than the cash is rejected
SELECT pg_temp.expect_error('record_cash_transaction: WITHDRAWAL above the cash balance is rejected',
    format('CALL record_cash_transaction(%s, ''WITHDRAWAL'', %s, CURRENT_DATE, NULL)', pid, cash + 1),
    'trg_cash_never_negative')
FROM subject;

-- 6. A valid trade works, gets a NEW id (identity continues after the restored
--    rows), and updating it writes a trade_audit row
DO $$
DECLARE
    s subject%ROWTYPE;
    v_id INTEGER;
BEGIN
    SELECT * INTO s FROM subject;
    CALL execute_trade(s.pid, s.ticker, 'BUY', 1, s.d, NULL, v_id);
    PERFORM pg_temp.check('execute_trade: valid BUY 1 share succeeds with a new trade_id',
        v_id > (SELECT max(trade_id) FROM trade WHERE trade_id <> v_id)
        AND (SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = s.pid) = s.cash - s.close);
    UPDATE trade SET shares = 2 WHERE trade_id = v_id;
    PERFORM pg_temp.check('trg_trade_audit: UPDATE of the new trade is logged',
        EXISTS (SELECT 1 FROM trade_audit
                WHERE trade_id = v_id AND operation = 'UPDATE' AND shares = 1));
END $$;

-- 7. Views and analysis functions return rows
SELECT pg_temp.check('views and analysis functions return rows',
    EXISTS (SELECT 1 FROM v_cash_balance) AND EXISTS (SELECT 1 FROM v_holdings)
    AND EXISTS (SELECT 1 FROM fn_monthly_returns(1)) AND EXISTS (SELECT 1 FROM fn_sector_allocation(1))
    AND EXISTS (SELECT 1 FROM fn_top_movers('2021-01-04')) AND EXISTS (SELECT 1 FROM fn_holding_pl(1)));

\o
\pset footer off
SELECT no AS "#", CASE WHEN passed THEN 'PASS' ELSE '** FAIL **' END AS result, label, detail
FROM restore_check ORDER BY no;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM restore_check WHERE NOT passed) THEN
        RAISE EXCEPTION '% restore check(s) failed', (SELECT count(*) FROM restore_check WHERE NOT passed);
    END IF;
END $$;
ROLLBACK;
