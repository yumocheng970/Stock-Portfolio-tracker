-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 7: restore_trade() - put a deleted trade back exactly
-- as it was, from its trade_audit DELETE row
-- Run AFTER db/schema/ files (normally via db/reset.sql or db/apply.sql)
--
-- CALL restore_trade(audit_id, NULL);
--   last param -> INOUT, returns the restored trade_id (= the ORIGINAL id)
--
-- The trade keeps its original trade_id (OVERRIDING SYSTEM VALUE), so it
-- also keeps its place among same-day trades in the history replay
-- (order: date, cash before trades, id). The identity sequence is not
-- touched: the old id is below its current value, so there is no clash.
--
-- Date order: the restored trade is usually older than the portfolio's
-- latest event. fn_event_date_order (04_balance_checks.sql) skips ONLY
-- that check for an exact re-insert of the trade's latest DELETE audit
-- row. Everything else still applies and its errors pass through:
-- start date, price within the day's range, no INDEX, the daily_price FK,
-- and the history replay (trg_cash_never_negative / trg_shares_never_negative).
-- A restore is an INSERT, so it adds no trade_audit row (that table logs
-- UPDATE and DELETE only); the DELETE row stays as history.
-- No COMMIT and no own lock: the triggers lock the portfolio.
--
-- Errors added here:
--   exec_missing_input           audit id is NULL
--   exec_audit_not_found         no trade_audit row with that id
--   exec_restore_not_delete      the audit row is an UPDATE, not a DELETE
--   exec_trade_already_restored  the trade exists (already restored)
--   exec_restore_not_latest      a newer audit row exists for that trade
--                                (restore the newest DELETE instead)
-- =====================================================================

CREATE OR REPLACE PROCEDURE restore_trade(
    p_audit_id        INTEGER,
    INOUT p_trade_id  INTEGER DEFAULT NULL    -- output: the restored trade_id
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_audit   trade_audit%ROWTYPE;
    v_newest  INTEGER;
BEGIN
    IF p_audit_id IS NULL THEN
        RAISE EXCEPTION 'Missing restore input: audit_id'
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_missing_input',
                  DETAIL     = 'Missing: audit_id.';
    END IF;

    SELECT * INTO v_audit FROM trade_audit WHERE audit_id = p_audit_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No audit row %', p_audit_id
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_audit_not_found',
                  DETAIL     = format('There is no audit row %s.', p_audit_id);
    END IF;

    IF v_audit.operation <> 'DELETE' THEN
        RAISE EXCEPTION 'Audit row % is an %, not a DELETE', p_audit_id, v_audit.operation
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_restore_not_delete',
                  DETAIL     = format('Audit row %s records an %s of trade %s.',
                                      p_audit_id, v_audit.operation, v_audit.trade_id);
    END IF;

    IF EXISTS (SELECT 1 FROM trade WHERE trade_id = v_audit.trade_id) THEN
        RAISE EXCEPTION 'Trade % exists', v_audit.trade_id
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_trade_already_restored',
                  DETAIL     = format('Trade %s is already back in the portfolio.', v_audit.trade_id);
    END IF;

    SELECT max(audit_id) INTO v_newest FROM trade_audit WHERE trade_id = v_audit.trade_id;
    IF v_newest <> p_audit_id THEN
        RAISE EXCEPTION 'Audit row % is not the latest for trade %', p_audit_id, v_audit.trade_id
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_restore_not_latest',
                  DETAIL     = format('Trade %s changed again later (audit row %s); restore from its newest DELETE row.',
                                      v_audit.trade_id, v_newest);
    END IF;

    -- OVERRIDING SYSTEM VALUE: write the original id into the GENERATED ALWAYS column
    INSERT INTO trade (trade_id, portfolio_id, ticker, trade_type, shares, price, trade_date)
    OVERRIDING SYSTEM VALUE
    VALUES (v_audit.trade_id, v_audit.portfolio_id, v_audit.ticker, v_audit.trade_type,
            v_audit.shares, v_audit.price, v_audit.trade_date);

    p_trade_id := v_audit.trade_id;
END;
$$;
