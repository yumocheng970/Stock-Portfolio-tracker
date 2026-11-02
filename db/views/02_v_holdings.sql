-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- View 2: v_holdings - shares, average cost, cost basis, realized P/L
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- Average cost method, trades in order (trade_date, trade_id):
--   BUY  q @ p : avg = (shares * avg + q * p) / (shares + q)
--   SELL q @ p : avg unchanged; realized P/L += q * (p - avg)
-- After shares reach 0, the next BUY starts fresh automatically:
--   (0 * old_avg + q * p) / (0 + q) = p
--
-- Average cost depends on the ORDER of trades, so it can't be a SUM.
-- fn_position_history walks each ticker's trades one by one with a
-- recursive CTE; v_holdings keeps the last state of each position.
--
-- Closed positions (shares 0) stay in the view: is_open = false,
-- avg_cost NULL, cost_basis 0, realized_pl kept.
--
-- Unrealized P/L is not here (it needs a price date). Later:
--   shares_held * close on that date - cost_basis
-- cost_basis is kept exact for that reason (not avg_cost * shares).
-- =====================================================================

-- ---------------------------------------------------------------------
-- One row per trade of a portfolio, with the position state after it.
-- Values are kept at full precision; v_holdings rounds for output.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_position_history(p_portfolio_id INTEGER)
RETURNS TABLE (
    ticker             VARCHAR(10),
    trade_seq          BIGINT,         -- 1, 2, 3, ... per ticker
    trade_id           INTEGER,
    trade_date         DATE,
    trade_type         VARCHAR(4),
    shares             INTEGER,
    price              NUMERIC(12,2),
    shares_after       BIGINT,
    avg_cost_after     NUMERIC,
    realized_pl        NUMERIC,        -- P/L of this trade (0 for a BUY)
    realized_pl_total  NUMERIC         -- running total for this ticker
)
LANGUAGE sql
STABLE
AS $$
    WITH RECURSIVE ordered AS (
        -- Number each ticker's trades in history order
        SELECT t.ticker,
               ROW_NUMBER() OVER (PARTITION BY t.ticker
                                  ORDER BY t.trade_date, t.trade_id) AS seq,
               t.trade_id, t.trade_date, t.trade_type, t.shares, t.price
        FROM trade t
        WHERE t.portfolio_id = p_portfolio_id
    ),
    walk AS (
        -- Anchor: an empty position (seq 0) for each ticker.
        -- Explicit casts: both halves of a recursive UNION must have
        -- exactly the same column types.
        SELECT DISTINCT o.ticker,
               0::BIGINT            AS seq,
               NULL::INTEGER        AS trade_id,
               NULL::DATE           AS trade_date,
               NULL::VARCHAR(4)     AS trade_type,
               NULL::INTEGER        AS shares,
               NULL::NUMERIC(12,2)  AS price,
               0::BIGINT            AS shares_after,
               0::NUMERIC           AS avg_cost_after,
               0::NUMERIC           AS realized_pl,
               0::NUMERIC           AS realized_pl_total
        FROM ordered o

        UNION ALL

        -- Recursive step: apply trade number seq + 1 to the previous state w
        SELECT o.ticker, o.seq, o.trade_id, o.trade_date, o.trade_type, o.shares, o.price,
               CASE o.trade_type
                    WHEN 'BUY' THEN w.shares_after + o.shares
                    ELSE            w.shares_after - o.shares
               END,
               CASE o.trade_type
                    WHEN 'BUY' THEN (w.shares_after * w.avg_cost_after + o.shares * o.price)
                                    / (w.shares_after + o.shares)
                    ELSE            w.avg_cost_after
               END,
               CASE o.trade_type
                    WHEN 'SELL' THEN o.shares * (o.price - w.avg_cost_after)
                    ELSE             0
               END,
               w.realized_pl_total
                 + CASE o.trade_type
                        WHEN 'SELL' THEN o.shares * (o.price - w.avg_cost_after)
                        ELSE             0
                   END
        FROM walk w
        JOIN ordered o ON o.ticker = w.ticker
                      AND o.seq    = w.seq + 1
    )
    SELECT w.ticker, w.seq, w.trade_id, w.trade_date, w.trade_type, w.shares, w.price,
           w.shares_after, w.avg_cost_after, w.realized_pl, w.realized_pl_total
    FROM walk w
    WHERE w.seq > 0                    -- drop the empty anchor rows
    ORDER BY w.ticker, w.seq;
$$;

-- ---------------------------------------------------------------------
-- One row per (portfolio, ticker) ever traded: the state after its
-- last trade. LATERAL: with WHERE portfolio_id = X, the function runs
-- only for that portfolio.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_holdings AS
SELECT DISTINCT ON (p.portfolio_id, h.ticker)
       p.portfolio_id,
       h.ticker,
       h.shares_after                                AS shares_held,
       CASE WHEN h.shares_after > 0
            THEN ROUND(h.avg_cost_after, 2) END      AS avg_cost,      -- NULL when closed
       CASE WHEN h.shares_after > 0
            THEN ROUND(h.shares_after * h.avg_cost_after, 2)
            ELSE 0 END                               AS cost_basis,
       ROUND(h.realized_pl_total, 2)                 AS realized_pl,
       h.shares_after > 0                            AS is_open,
       h.trade_seq                                   AS trade_count,
       h.trade_date                                  AS last_trade_date
FROM portfolio p
CROSS JOIN LATERAL fn_position_history(p.portfolio_id) h
-- DISTINCT ON keeps the FIRST row of each (portfolio, ticker) group in
-- this order, i.e. the one with the highest trade_seq (the last trade)
ORDER BY p.portfolio_id, h.ticker, h.trade_seq DESC;
