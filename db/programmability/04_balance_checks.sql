-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Programmability 4: date order and "never below zero" balance checks
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- fn_portfolio_history(id)       : running cash and shares, event by event
-- fn_check_portfolio_history(id) : raises if cash or any ticker's shares
--                                  ever goes below zero in that history
-- trg_trade_date_order,
-- trg_cash_txn_date_order        : BEFORE INSERT, new events in date order
-- trg_trade_history_check,
-- trg_cash_txn_history_check     : AFTER the change, replay the history
--
-- History order: date; on the same date cash transactions before
-- trades; then id.
--
-- Errors (check_violation + constraint name, like the other triggers):
--   trg_date_before_start       date before the portfolio's start_date
--   trg_date_before_latest      date before the portfolio's latest event
--   trg_cash_txn_future_date    cash transaction dated after today
--   trg_cash_never_negative     cash < 0 at some point in the history
--   trg_shares_never_negative   shares of a ticker < 0 at some point
--
-- Concurrency: both triggers lock the portfolio row (FOR UPDATE), so two
-- transactions changing the same portfolio run their checks one after
-- the other. Relies on READ COMMITTED (PostgreSQL's default): after
-- waiting for the lock, the next query sees the other transaction's
-- committed rows.
-- =====================================================================

-- ---------------------------------------------------------------------
-- History of one portfolio: one row per cash transaction or trade,
-- with the running cash and running shares (per ticker) after it.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_portfolio_history(p_portfolio_id INTEGER)
RETURNS TABLE (
    event_date    DATE,
    event_order   INTEGER,        -- 0 = cash transaction, 1 = trade
    event_id      INTEGER,        -- cash_txn_id or trade_id
    event_label   TEXT,
    ticker        VARCHAR(10),    -- NULL for cash transactions
    cash_delta    NUMERIC,
    share_delta   INTEGER,
    cash_after    NUMERIC,
    shares_after  BIGINT          -- shares of this ticker after the event
)
LANGUAGE sql
STABLE
AS $$
    WITH events AS (
        SELECT c.txn_date    AS event_date,
               0             AS event_order,
               c.cash_txn_id AS event_id,
               format('cash transaction %s (%s %s)',
                      c.cash_txn_id, c.txn_type, c.amount) AS event_label,
               NULL::VARCHAR(10) AS ticker,
               CASE c.txn_type WHEN 'DEPOSIT' THEN c.amount ELSE -c.amount END AS cash_delta,
               0             AS share_delta
        FROM cash_transaction c
        WHERE c.portfolio_id = p_portfolio_id

        UNION ALL

        SELECT t.trade_date,
               1,
               t.trade_id,
               format('trade %s (%s %s %s @ %s)',
                      t.trade_id, t.trade_type, t.shares, t.ticker, t.price),
               t.ticker,
               -- BUY spends cash and adds shares; SELL does the opposite
               CASE t.trade_type WHEN 'BUY' THEN -(t.shares * t.price) ELSE t.shares * t.price END,
               CASE t.trade_type WHEN 'BUY' THEN t.shares ELSE -t.shares END
        FROM trade t
        WHERE t.portfolio_id = p_portfolio_id
    )
    SELECT e.event_date, e.event_order, e.event_id, e.event_label, e.ticker,
           e.cash_delta, e.share_delta,
           p.starting_cash + SUM(e.cash_delta) OVER w_all    AS cash_after,
           SUM(e.share_delta)                  OVER w_ticker AS shares_after
    FROM events e
    JOIN portfolio p ON p.portfolio_id = p_portfolio_id
    -- ROWS UNBOUNDED PRECEDING = running total from the first row up to
    -- and including the current row, in the history order
    WINDOW w_all    AS (ORDER BY e.event_date, e.event_order, e.event_id
                        ROWS UNBOUNDED PRECEDING),
           w_ticker AS (PARTITION BY e.ticker
                        ORDER BY e.event_date, e.event_order, e.event_id
                        ROWS UNBOUNDED PRECEDING)
    ORDER BY e.event_date, e.event_order, e.event_id;
$$;

-- ---------------------------------------------------------------------
-- Raise an error at the FIRST point where cash or shares go below zero.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_portfolio_history(p_portfolio_id INTEGER)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_bad RECORD;
BEGIN
    SELECT * INTO v_bad
    FROM fn_portfolio_history(p_portfolio_id) h
    WHERE h.cash_after < 0
       OR (h.ticker IS NOT NULL AND h.shares_after < 0)
    ORDER BY h.event_date, h.event_order, h.event_id
    LIMIT 1;

    IF NOT FOUND THEN
        RETURN;   -- history is valid
    END IF;

    -- A BUY or WITHDRAWAL can only lower cash; a SELL can only lower
    -- shares. So one event never breaks both rules.
    IF v_bad.cash_after < 0 THEN
        RAISE EXCEPTION 'Not enough cash: this change makes the cash balance negative'
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_cash_never_negative',
                  DETAIL     = format('Cash would be %s on %s, after %s.',
                                      v_bad.cash_after, v_bad.event_date, v_bad.event_label),
                  HINT       = 'Cash must be >= 0 at every point in the history '
                               '(same day: cash transactions before trades).';
    ELSE
        RAISE EXCEPTION 'Not enough shares: this change makes the % holding negative', v_bad.ticker
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_shares_never_negative',
                  DETAIL     = format('%s shares would be %s on %s, after %s.',
                                      v_bad.ticker, v_bad.shares_after,
                                      v_bad.event_date, v_bad.event_label),
                  HINT       = 'You cannot sell more shares than you hold at that date.';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------
-- BEFORE INSERT on trade and cash_transaction: date order.
-- One function for both tables; TG_TABLE_NAME says which one fired it.
--
-- One exemption, for restore_trade() (07_restore_trade.sql): re-inserting
-- a deleted trade EXACTLY as it was (same trade_id and same values as that
-- trade's LATEST trade_audit row, which is a DELETE) skips only the
-- "before the latest event" check. The start-date check, the BEFORE
-- validation trigger (price range, no INDEX), the FK and the AFTER
-- history replay (cash / shares never negative) all still run.
-- The exemption is defined by the data, not by a session flag, so no
-- other insert can claim it: a normal insert gets a NEW trade_id from the
-- identity, and no audit row has that id.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_event_date_order()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_date        DATE;
    v_start_date  portfolio.start_date%TYPE;
    v_latest      DATE;
    v_is_restore  BOOLEAN := false;
BEGIN
    -- IF, not CASE: NEW.trade_date doesn't exist on cash_transaction,
    -- and only the branch that runs is evaluated.
    IF TG_TABLE_NAME = 'trade' THEN
        v_date := NEW.trade_date;
    ELSE
        v_date := NEW.txn_date;
    END IF;

    -- Lock the portfolio row until COMMIT/ROLLBACK. A second
    -- transaction on the same portfolio waits here.
    SELECT start_date INTO v_start_date
    FROM portfolio
    WHERE portfolio_id = NEW.portfolio_id
    FOR UPDATE;

    -- Unknown portfolio: leave it to the FK
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    IF v_date < v_start_date THEN
        RAISE EXCEPTION 'Date % is before the portfolio start date', v_date
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_date_before_start',
                  DETAIL     = format('Portfolio %s starts on %s.', NEW.portfolio_id, v_start_date);
    END IF;

    -- GREATEST ignores NULLs (a portfolio with no events gives NULL,
    -- and "v_date < NULL" is NULL, so nothing is raised)
    SELECT GREATEST((SELECT max(trade_date) FROM trade
                     WHERE portfolio_id = NEW.portfolio_id),
                    (SELECT max(txn_date) FROM cash_transaction
                     WHERE portfolio_id = NEW.portfolio_id))
    INTO v_latest;

    -- Restore of a deleted trade? (Inside IF: NEW.trade_id doesn't exist
    -- on cash_transaction.) The row-value comparison (a, b) = (c, d)
    -- compares all six columns at once.
    IF TG_TABLE_NAME = 'trade' THEN
        SELECT a.operation = 'DELETE'
               AND (a.portfolio_id, a.ticker, a.trade_type, a.shares, a.price, a.trade_date)
                 = (NEW.portfolio_id, NEW.ticker, NEW.trade_type, NEW.shares, NEW.price, NEW.trade_date)
        INTO v_is_restore
        FROM trade_audit a
        WHERE a.trade_id = NEW.trade_id
        ORDER BY a.audit_id DESC          -- the trade's latest audit row
        LIMIT 1;
        v_is_restore := COALESCE(v_is_restore, false);   -- no audit row: not a restore
    END IF;

    IF v_date < v_latest AND NOT v_is_restore THEN
        RAISE EXCEPTION 'Date % is before the latest event in this portfolio', v_date
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_date_before_latest',
                  DETAIL     = format('Latest event of portfolio %s is on %s.',
                                      NEW.portfolio_id, v_latest),
                  HINT       = 'Enter events in date order (the same date is allowed).';
    END IF;

    IF TG_TABLE_NAME = 'cash_transaction' AND v_date > CURRENT_DATE THEN
        RAISE EXCEPTION 'Cash transaction date % is in the future', v_date
            USING ERRCODE    = 'check_violation',
                  CONSTRAINT = 'trg_cash_txn_future_date',
                  DETAIL     = format('Today is %s.', CURRENT_DATE);
    END IF;

    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------
-- AFTER INSERT/UPDATE/DELETE: replay the portfolio's history.
-- AFTER, so the replay sees the table as it is after the change.
-- Raising here rolls back the whole statement (and its audit rows).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_portfolio_history_check()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id  INTEGER;
BEGIN
    -- On DELETE there is no NEW row, only OLD
    IF TG_OP = 'DELETE' THEN
        v_portfolio_id := OLD.portfolio_id;
    ELSE
        v_portfolio_id := NEW.portfolio_id;
    END IF;

    -- Lock again (no-op if this transaction already holds it).
    -- UPDATE/DELETE have no BEFORE lock, so this is their lock.
    PERFORM 1 FROM portfolio WHERE portfolio_id = v_portfolio_id FOR UPDATE;

    -- Portfolio already gone: this row is part of a cascade delete
    -- (portfolio or investor deleted). Nothing left to check.
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    PERFORM fn_check_portfolio_history(v_portfolio_id);
    RETURN NULL;   -- return value of an AFTER trigger is ignored
END;
$$;

-- ---------------------------------------------------------------------
-- Triggers
-- BEFORE triggers on the same table run in name order:
-- trg_trade_date_order runs before trg_trade_validate.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TRIGGER trg_trade_date_order
    BEFORE INSERT ON trade
    FOR EACH ROW
    EXECUTE FUNCTION fn_event_date_order();

CREATE OR REPLACE TRIGGER trg_cash_txn_date_order
    BEFORE INSERT ON cash_transaction
    FOR EACH ROW
    EXECUTE FUNCTION fn_event_date_order();

CREATE OR REPLACE TRIGGER trg_trade_history_check
    AFTER INSERT OR UPDATE OR DELETE ON trade
    FOR EACH ROW
    EXECUTE FUNCTION fn_portfolio_history_check();

-- Only INSERT: UPDATE/DELETE of cash transactions are blocked by
-- trg_cash_txn_immutable, and cascade deletes need no check.
CREATE OR REPLACE TRIGGER trg_cash_txn_history_check
    AFTER INSERT ON cash_transaction
    FOR EACH ROW
    EXECUTE FUNCTION fn_portfolio_history_check();
