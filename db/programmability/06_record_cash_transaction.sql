-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 6: record_cash_transaction() - the app's single entry
-- point for a deposit or withdrawal (same style as execute_trade())
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- CALL record_cash_transaction(portfolio_id, txn_type, amount, txn_date, NULL);
--   last param -> INOUT, returns the new cash_txn_id
--
-- The procedure only normalizes txn_type (trim + uppercase), reports
-- missing input, and INSERTs. Everything else is enforced by the
-- triggers and constraints on cash_transaction, and their errors pass
-- through unchanged (date order, future date, cash never negative,
-- txn type, positive amount, deposit cap, unknown portfolio).
-- No COMMIT: the caller controls the transaction.
--
-- Error added here (same name as in execute_trade(), so Python has one
-- "missing input" message):
--   exec_missing_input   a required input is NULL or blank
-- =====================================================================

CREATE OR REPLACE PROCEDURE record_cash_transaction(
    p_portfolio_id       INTEGER,
    p_txn_type           TEXT,
    p_amount             NUMERIC,
    p_txn_date           DATE,
    INOUT p_cash_txn_id  INTEGER DEFAULT NULL   -- output: the new cash_txn_id
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_txn_type  TEXT;
    v_missing   TEXT[];
BEGIN
    -- ' deposit ' -> 'DEPOSIT'; a blank string becomes NULL (= missing)
    v_txn_type := NULLIF(upper(btrim(p_txn_type)), '');

    v_missing := array_remove(ARRAY[
        CASE WHEN p_portfolio_id IS NULL THEN 'portfolio_id' END,
        CASE WHEN v_txn_type     IS NULL THEN 'txn_type'     END,
        CASE WHEN p_amount       IS NULL THEN 'amount'       END,
        CASE WHEN p_txn_date     IS NULL THEN 'txn_date'     END
    ], NULL);

    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'Missing cash transaction input: %', array_to_string(v_missing, ', ')
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_missing_input',
                  DETAIL     = format('Missing: %s.', array_to_string(v_missing, ', '));
    END IF;

    INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
    VALUES (p_portfolio_id, v_txn_type, p_amount, p_txn_date)
    RETURNING cash_txn_id INTO p_cash_txn_id;
END;
$$;
