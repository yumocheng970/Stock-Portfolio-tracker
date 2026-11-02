-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Analysis query 2: sector allocation % per portfolio, as of a date
--
-- SELECT * FROM fn_sector_allocation();                  -- all portfolios, latest date
-- SELECT * FROM fn_sector_allocation(5, '2025-06-30');   -- one portfolio, a past date
-- SELECT * FROM fn_sector_allocation(5, NULL, false);    -- stocks only, no cash row
--
-- market value of a sector = SUM(shares x close), using each ticker's
-- latest close on or before as_of. Shares and cash are as of that date
-- (only events up to as_of count).
-- Cash is its own row ('Cash') by default, so pct is a share of the
-- TOTAL portfolio value; p_include_cash = false gives stocks only.
-- pct is rounded to 2 decimals, so a portfolio's rows may sum to
-- 99.99 or 100.01; market_value is exact.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_sector_allocation(
    p_portfolio_id  INTEGER DEFAULT NULL,    -- NULL = all portfolios
    p_as_of         DATE    DEFAULT NULL,    -- NULL = latest price date
    p_include_cash  BOOLEAN DEFAULT true
)
RETURNS TABLE (
    portfolio_id    INTEGER,
    portfolio_name  VARCHAR(100),
    as_of           DATE,
    sector_name     VARCHAR(50),
    market_value    NUMERIC,
    pct             NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT COALESCE(p_as_of, (SELECT max(dp.price_date) FROM daily_price dp)) AS as_of
    ),
    pf AS (
        -- Portfolios that exist on as_of (simulation already started)
        SELECT p.portfolio_id, p.portfolio_name, p.starting_cash, params.as_of
        FROM portfolio p CROSS JOIN params
        WHERE p.start_date <= params.as_of
          AND (p_portfolio_id IS NULL OR p.portfolio_id = p_portfolio_id)
    ),
    positions AS (
        -- Shares held on as_of: a plain SUM is fine (order doesn't matter for shares)
        SELECT t.portfolio_id, t.ticker,
               SUM(CASE t.trade_type WHEN 'BUY' THEN t.shares ELSE -t.shares END) AS shares
        FROM trade t
        JOIN pf ON pf.portfolio_id = t.portfolio_id
        WHERE t.trade_date <= pf.as_of
        GROUP BY t.portfolio_id, t.ticker
        HAVING SUM(CASE t.trade_type WHEN 'BUY' THEN t.shares ELSE -t.shares END) > 0
    ),
    stock_values AS (
        SELECT pos.portfolio_id,
               COALESCE(sec.sector_name, 'Unclassified')::VARCHAR(50) AS sector_name,
               SUM(pos.shares * c.close) AS market_value
        FROM positions pos
        JOIN pf          ON pf.portfolio_id = pos.portfolio_id
        JOIN stock s     ON s.ticker = pos.ticker
        LEFT JOIN sector sec ON sec.sector_id = s.sector_id
        -- Latest close on or before as_of (uses the primary key).
        -- A held ticker always has one: it was traded on a priced day <= as_of.
        CROSS JOIN LATERAL (
            SELECT dp.close FROM daily_price dp
            WHERE dp.ticker = pos.ticker AND dp.price_date <= pf.as_of
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) c
        GROUP BY pos.portfolio_id, COALESCE(sec.sector_name, 'Unclassified')
    ),
    cash AS (
        -- Cash on as_of = running cash after the last event on or before as_of
        SELECT pf.portfolio_id,
               'Cash'::VARCHAR(50) AS sector_name,
               COALESCE(h.cash_after, pf.starting_cash) AS market_value
        FROM pf
        LEFT JOIN LATERAL (
            SELECT h.cash_after FROM fn_portfolio_history(pf.portfolio_id) h
            WHERE h.event_date <= pf.as_of
            ORDER BY h.event_date DESC, h.event_order DESC, h.event_id DESC
            LIMIT 1
        ) h ON true
        WHERE p_include_cash
    ),
    all_rows AS (
        SELECT * FROM stock_values
        UNION ALL
        SELECT * FROM cash
    )
    SELECT r.portfolio_id, pf.portfolio_name, pf.as_of, r.sector_name, r.market_value,
           -- window SUM: the portfolio's total value, next to every row
           ROUND(100 * r.market_value
                 / NULLIF(SUM(r.market_value) OVER (PARTITION BY r.portfolio_id), 0), 2) AS pct
    FROM all_rows r
    JOIN pf ON pf.portfolio_id = r.portfolio_id
    ORDER BY r.portfolio_id, (r.sector_name = 'Cash'), r.market_value DESC, r.sector_name;
$$;
