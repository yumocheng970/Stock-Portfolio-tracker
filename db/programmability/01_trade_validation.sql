-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 1: row-level validation trigger on trade
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- Rules checked BEFORE INSERT OR UPDATE of each trade row:
--   (a) price is between that day's low and high
--   (b) the security is not an INDEX (e.g. ^GSPC cannot be traded)
--   (c) on UPDATE, only shares and price may change
--
-- Errors use SQLSTATE 23514 (check_violation) plus a constraint name,
-- like a real CHECK constraint. Python reads the name from
-- e.diag.constraint_name and maps it to a friendly message:
--   trg_trade_price_in_range   rule (a)
--   trg_trade_not_index        rule (b)
--   trg_trade_immutable_cols   rule (c)
--
-- Order of checks inside PostgreSQL for one row:
--   BEFORE trigger (this) -> NOT NULL / CHECK / UNIQUE -> FKs (end of statement)
-- So if no stock or no price row exists, this trigger lets the row
-- through and fk_trade_daily_price reports the problem.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_trade_validate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_security_type  stock.security_type%TYPE;
    v_low            daily_price.low%TYPE;
    v_high           daily_price.high%TYPE;
BEGIN
    -- -----------------------------------------------------------------
    -- (c) UPDATE may change only shares and price
    -- -----------------------------------------------------------------
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.portfolio_id, NEW.trade_type, NEW.trade_date)
           IS DISTINCT FROM
           (OLD.portfolio_id, OLD.trade_type, OLD.trade_date) THEN
            RAISE EXCEPTION 'Only shares and price of a trade can be changed'
                USING ERRCODE    = 'check_violation',
                      CONSTRAINT = 'trg_trade_immutable_cols',
                      DETAIL     = format('Trade %s: portfolio, type and date are fixed.',
                                          OLD.trade_id),
                      HINT       = 'Delete the trade and enter a new one instead.';
        END IF;

        -- A ticker change is allowed only as part of a stock rename
        -- (ON UPDATE CASCADE from stock -> daily_price -> trade).
        -- During a rename the old ticker no longer exists in stock;
        -- in a direct UPDATE of trade it still does.
        IF NEW.ticker IS DISTINCT FROM OLD.ticker
           AND EXISTS (SELECT 1 FROM stock WHERE ticker = OLD.ticker) THEN
            RAISE EXCEPTION 'Only shares and price of a trade can be changed'
                USING ERRCODE    = 'check_violation',
                      CONSTRAINT = 'trg_trade_immutable_cols',
                      DETAIL     = format('Trade %s: ticker %s cannot be changed to %s.',
                                          OLD.trade_id, OLD.ticker, NEW.ticker),
                      HINT       = 'Delete the trade and enter a new one instead.';
        END IF;
    END IF;

    -- -----------------------------------------------------------------
    -- Look up the security type and that day's range in one query.
    -- LEFT JOIN: a stock with no price row that day still returns
    -- its security_type (with NULL low/high).
    -- -----------------------------------------------------------------
    SELECT s.security_type, dp.low, dp.high
      INTO v_security_type, v_low, v_high
      FROM stock s
      LEFT JOIN daily_price dp
             ON dp.ticker = s.ticker
            AND dp.price_date = NEW.trade_date
     WHERE s.ticker = NEW.ticker;

    -- Unknown ticker: leave it to fk_trade_daily_price
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    -- -----------------------------------------------------------------
    -- (b) no trading an INDEX
    -- -----------------------------------------------------------------
    IF v_security_type = 'INDEX' THEN
        RAISE EXCEPTION '% is an index and cannot be traded', NEW.ticker
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_trade_not_index',
                  HINT       = 'Indexes can be added to a watchlist, but not bought or sold.';
    END IF;

    -- -----------------------------------------------------------------
    -- (a) price within the day's low..high
    -- v_low IS NULL means no price row that day: leave it to the FK.
    -- NEW.price IS NULL: the NOT NULL constraint reports it.
    -- -----------------------------------------------------------------
    IF v_low IS NOT NULL AND NEW.price NOT BETWEEN v_low AND v_high THEN
        RAISE EXCEPTION 'Price % is outside the % range on %', NEW.price, NEW.ticker, NEW.trade_date
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_trade_price_in_range',
                  DETAIL     = format('Allowed range: %s to %s.', v_low, v_high);
    END IF;

    RETURN NEW;   -- BEFORE trigger: returning NEW lets the row be written
END;
$$;

-- FOR EACH ROW: runs once per inserted/updated row, with NEW/OLD set.
-- CREATE OR REPLACE TRIGGER (PostgreSQL 14+) makes this file re-runnable.
CREATE OR REPLACE TRIGGER trg_trade_validate
    BEFORE INSERT OR UPDATE ON trade
    FOR EACH ROW
    EXECUTE FUNCTION fn_trade_validate();
