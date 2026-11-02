-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 5: execute_trade() - the app's single entry point
-- for making a trade
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- CALL execute_trade(portfolio_id, ticker, trade_type, shares,
--                    trade_date, price, NULL);
--   price NULL  -> use that day's close
--   last param  -> INOUT, returns the new trade_id
--
-- The procedure only:
--   - normalizes text input (trim + uppercase)
--   - reports missing input (NOT NULL errors carry no constraint name)
--   - looks up the close when no price is given
--   - INSERTs the trade
-- All other rules are enforced by the triggers and constraints on
-- trade (date order, price range, no INDEX, cash/shares >= 0, lock).
-- Their errors pass through unchanged. No COMMIT: the caller controls
-- the transaction.
--
-- Errors added here (check_violation + constraint name):
--   exec_missing_input   a required input is NULL or blank
--   exec_no_price_data   no price given and no daily_price row that day
-- =====================================================================

CREATE OR REPLACE PROCEDURE execute_trade(
    p_portfolio_id    INTEGER,
    p_ticker          TEXT,
    p_trade_type      TEXT,
    p_shares          INTEGER,
    p_trade_date      DATE,
    p_price           NUMERIC DEFAULT NULL,   -- NULL = use that day's close
    INOUT p_trade_id  INTEGER DEFAULT NULL    -- output: the new trade_id
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_ticker      TEXT;
    v_trade_type  TEXT;
    v_price       NUMERIC;
    v_missing     TEXT[];
BEGIN
    -- ' balt ' -> 'BALT'; a blank string becomes NULL (= missing)
    v_ticker     := NULLIF(upper(btrim(p_ticker)), '');
    v_trade_type := NULLIF(upper(btrim(p_trade_type)), '');

    -- Collect the names of all missing inputs, so one error lists them all.
    -- CASE without ELSE gives NULL; array_remove drops those NULLs.
    v_missing := array_remove(ARRAY[
        CASE WHEN p_portfolio_id IS NULL THEN 'portfolio_id' END,
        CASE WHEN v_ticker       IS NULL THEN 'ticker'       END,
        CASE WHEN v_trade_type   IS NULL THEN 'trade_type'   END,
        CASE WHEN p_shares       IS NULL THEN 'shares'       END,
        CASE WHEN p_trade_date   IS NULL THEN 'trade_date'   END
    ], NULL);

    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'Missing trade input: %', array_to_string(v_missing, ', ')
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'exec_missing_input',
                  DETAIL     = format('Missing: %s.', array_to_string(v_missing, ', '));
    END IF;

    -- No price given: use that day's close
    IF p_price IS NULL THEN
        SELECT dp.close INTO v_price
        FROM daily_price dp
        WHERE dp.ticker = v_ticker
          AND dp.price_date = p_trade_date;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'No price data for % on %', v_ticker, p_trade_date
                USING ERRCODE    = 'check_violation',
                      CONSTRAINT = 'exec_no_price_data',
                      DETAIL     = format('No price for %s on %s (not a trading day, or unknown ticker).',
                                          v_ticker, p_trade_date),
                      HINT       = 'Choose a trading day, or give a price.';
        END IF;
    ELSE
        v_price := p_price;
    END IF;

    -- The triggers on trade check everything else; RETURNING ... INTO
    -- puts the new id into the INOUT parameter.
    INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
    VALUES (p_portfolio_id, v_ticker, v_trade_type, p_shares, v_price, p_trade_date)
    RETURNING trade_id INTO p_trade_id;
END;
$$;
