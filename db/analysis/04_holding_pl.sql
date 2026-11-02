-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Analysis query 4: realized vs unrealized P/L per holding, as of a date
--
-- SELECT * FROM fn_holding_pl();                  -- all portfolios, today
-- SELECT * FROM fn_holding_pl(5, '2025-06-30');   -- one portfolio, a past date
--
-- Position state (shares, average cost, realized P/L) comes from
-- fn_position_history (db/views/02_v_holdings.sql), using only trades
-- on or before as_of. v_holdings itself always includes ALL trades, so
-- a past as_of would mix in later trades. With the default date (today)
-- the numbers equal v_holdings.
--   unrealized = shares_held x close(as_of) - cost_basis
--   close(as_of) = the ticker's latest close on or before as_of
-- Closed positions (shares 0) are included: unrealized 0, realized kept.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_holding_pl(
    p_portfolio_id  INTEGER DEFAULT NULL,    -- NULL = all portfolios
    p_as_of         DATE    DEFAULT NULL     -- NULL = today (CURRENT_DATE)
)
RETURNS TABLE (
    portfolio_id    INTEGER,
    portfolio_name  VARCHAR(100),
    ticker          VARCHAR(10),
    shares_held     BIGINT,
    avg_cost        NUMERIC,
    cost_basis      NUMERIC,
    close_date      DATE,
    close           NUMERIC(12,2),
    market_value    NUMERIC,
    unrealized_pl   NUMERIC,
    realized_pl     NUMERIC,
    total_pl        NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT COALESCE(p_as_of, CURRENT_DATE) AS as_of
    ),
    last_state AS (
        -- Position after the last trade on or before as_of, per ticker
        SELECT DISTINCT ON (p.portfolio_id, h.ticker)
               p.portfolio_id, p.portfolio_name, h.ticker,
               h.shares_after, h.avg_cost_after, h.realized_pl_total,
               CASE WHEN h.shares_after > 0
                    THEN ROUND(h.shares_after * h.avg_cost_after, 2) ELSE 0 END AS cost_basis
        FROM portfolio p
        CROSS JOIN params
        CROSS JOIN LATERAL fn_position_history(p.portfolio_id) h
        WHERE (p_portfolio_id IS NULL OR p.portfolio_id = p_portfolio_id)
          AND h.trade_date <= params.as_of
        ORDER BY p.portfolio_id, h.ticker, h.trade_seq DESC
    )
    SELECT ls.portfolio_id, ls.portfolio_name, ls.ticker,
           ls.shares_after,
           CASE WHEN ls.shares_after > 0 THEN ROUND(ls.avg_cost_after, 2) END,   -- NULL when closed
           ls.cost_basis,
           c.price_date,
           c.close,
           ls.shares_after * c.close                     AS market_value,
           ls.shares_after * c.close - ls.cost_basis     AS unrealized_pl,
           ROUND(ls.realized_pl_total, 2)                AS realized_pl,
           ls.shares_after * c.close - ls.cost_basis
             + ROUND(ls.realized_pl_total, 2)            AS total_pl
    FROM last_state ls
    CROSS JOIN params
    -- Latest close on or before as_of (primary key index). A traded ticker
    -- always has one, because it was traded on a priced day <= as_of.
    CROSS JOIN LATERAL (
        SELECT dp.price_date, dp.close FROM daily_price dp
        WHERE dp.ticker = ls.ticker AND dp.price_date <= params.as_of
        ORDER BY dp.price_date DESC
        LIMIT 1
    ) c
    ORDER BY ls.portfolio_id, ls.ticker;
$$;
