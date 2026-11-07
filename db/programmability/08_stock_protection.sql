-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 8: protect the benchmark index ^GSPC
-- Run AFTER db/schema/ files (normally via db/reset.sql or db/apply.sql)
--
-- trg_stock_benchmark_protected (BEFORE UPDATE OR DELETE on stock, row-level):
--   ^GSPC can't be deleted and its ticker can't be changed.
--   Editing its company name is allowed.
-- Why: fn_monthly_returns (db/analysis/01_monthly_returns.sql) looks the
-- benchmark up by the ticker '^GSPC'.
--   - A rename would silently leave the S&P 500 column empty.
--   - A delete would cascade away all its prices: no trade can reference
--     an index, so the RESTRICT FK on trades never stops it.
-- Other stocks are not affected (their rename / delete rules are the FKs).
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_stock_benchmark_protected()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_blocked  BOOLEAN := false;
BEGIN
    -- Separate IFs: NEW has no row on DELETE, so NEW.ticker is only read for UPDATE
    IF OLD.ticker = '^GSPC' THEN
        IF TG_OP = 'DELETE' THEN
            v_blocked := true;
        ELSIF NEW.ticker IS DISTINCT FROM OLD.ticker THEN
            v_blocked := true;
        END IF;
    END IF;

    IF v_blocked THEN
        RAISE EXCEPTION 'The benchmark ^GSPC cannot be %',
                        CASE TG_OP WHEN 'DELETE' THEN 'deleted' ELSE 'renamed' END
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_stock_benchmark_protected',
                  DETAIL     = 'The monthly report compares every portfolio with ^GSPC.';
    END IF;

    -- BEFORE trigger: returning OLD lets a DELETE go ahead, NEW an UPDATE
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_stock_benchmark_protected
    BEFORE UPDATE OR DELETE ON stock
    FOR EACH ROW
    EXECUTE FUNCTION fn_stock_benchmark_protected();
