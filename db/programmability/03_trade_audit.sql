-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 3: audit log for trades
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- trg_trade_audit       : copies the OLD row into trade_audit on UPDATE/DELETE
-- trg_trade_no_truncate : blocks TRUNCATE (it would skip the audit)
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_trade_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- audit_id, changed_at and changed_by fill in from their defaults
    INSERT INTO trade_audit
        (operation, trade_id, portfolio_id, ticker, trade_type, shares, price, trade_date)
    VALUES
        (TG_OP, OLD.trade_id, OLD.portfolio_id, OLD.ticker, OLD.trade_type, OLD.shares, OLD.price, OLD.trade_date);

    RETURN NULL;
END;
$$;

CREATE OR REPLACE TRIGGER trg_trade_audit
    AFTER UPDATE OR DELETE ON trade
    FOR EACH ROW
    EXECUTE FUNCTION fn_trade_audit();

-- Row-level triggers don't fire on TRUNCATE, so block it separately.
-- Otherwise TRUNCATE trade would delete trades with no audit rows.

CREATE OR REPLACE FUNCTION fn_trade_no_truncate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'trade cannot be truncated'
        USING ERRCODE    = 'check_violation',
              CONSTRAINT = 'trg_trade_no_truncate',
              HINT       = 'Use db/reset.sql to rebuild the database.';

END;
$$;

CREATE OR REPLACE TRIGGER trg_trade_no_truncate
    BEFORE TRUNCATE ON trade
    FOR EACH STATEMENT
    EXECUTE FUNCTION fn_trade_no_truncate();
