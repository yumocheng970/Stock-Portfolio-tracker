-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Analysis query 5: watchlist items whose latest close >= target_price
--
-- SELECT * FROM fn_watchlist_targets_reached();      -- all investors, today
-- SELECT * FROM fn_watchlist_targets_reached(3);     -- one investor
--
-- latest close = the ticker's latest close on or before p_as_of
-- (default: today, i.e. the latest close loaded). Items without a target_price never
-- appear: "close >= NULL" is NULL, and WHERE keeps only TRUE rows.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_watchlist_targets_reached(
    p_investor_id  INTEGER DEFAULT NULL,    -- NULL = all investors
    p_as_of        DATE    DEFAULT NULL     -- NULL = today (CURRENT_DATE)
)
RETURNS TABLE (
    investor_id       INTEGER,
    investor_name     VARCHAR(100),
    watchlist_id      INTEGER,
    watchlist_name    VARCHAR(100),
    ticker            VARCHAR(10),
    target_price      NUMERIC(12,2),
    close_date        DATE,
    latest_close      NUMERIC(12,2),
    pct_above_target  NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT COALESCE(p_as_of, CURRENT_DATE) AS as_of
    )
    SELECT i.investor_id, i.name, w.watchlist_id, w.watchlist_name,
           wi.ticker, wi.target_price, c.price_date, c.close,
           ROUND(100 * (c.close - wi.target_price) / wi.target_price, 2) AS pct_above_target
    FROM watchlist_item wi
    JOIN watchlist w ON w.watchlist_id = wi.watchlist_id
    JOIN investor i  ON i.investor_id  = w.investor_id
    CROSS JOIN params
    -- Latest close on or before as_of (primary key index)
    CROSS JOIN LATERAL (
        SELECT dp.price_date, dp.close FROM daily_price dp
        WHERE dp.ticker = wi.ticker AND dp.price_date <= params.as_of
        ORDER BY dp.price_date DESC
        LIMIT 1
    ) c
    WHERE c.close >= wi.target_price
      AND (p_investor_id IS NULL OR i.investor_id = p_investor_id)
    ORDER BY pct_above_target DESC, i.name, w.watchlist_name, wi.ticker;
$$;
