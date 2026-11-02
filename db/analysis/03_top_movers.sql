-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Analysis query 3: top gainers and top losers over a period
--
-- SELECT * FROM fn_top_movers('2025-01-01');                 -- to today, top 5
-- SELECT * FROM fn_top_movers('2025-01-01', '2025-06-30', 3);
--
-- For every STOCK (never the index): % change from the first close on
-- or after p_start to the last close on or before p_end (both inside
-- the period, on two different days).
-- Gainers: pct > 0, ranked highest first. Losers: pct < 0, lowest first.
-- A 0% stock is neither.
-- Ties: RANK() gives tied stocks the same rank and skips the next one
-- (1, 1, 3). "rank <= p_limit" keeps ALL tied stocks, so the result can
-- have more than p_limit rows per side. Ranking uses the exact %, and
-- pct_change is rounded only for display.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_top_movers(
    p_start  DATE,
    p_end    DATE    DEFAULT NULL,    -- NULL = today (CURRENT_DATE)
    p_limit  INTEGER DEFAULT 5
)
RETURNS TABLE (
    direction     TEXT,               -- 'GAINER' or 'LOSER'
    rank          BIGINT,
    ticker        VARCHAR(10),
    company_name  VARCHAR(100),
    start_date    DATE,
    start_close   NUMERIC(12,2),
    end_date      DATE,
    end_close     NUMERIC(12,2),
    pct_change    NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        SELECT p_start AS start_d,
               COALESCE(p_end, CURRENT_DATE) AS end_d
    ),
    moves AS (
        SELECT s.ticker, s.company_name,
               f.price_date AS start_date, f.close AS start_close,
               l.price_date AS end_date,   l.close AS end_close,
               (l.close - f.close) / f.close AS change      -- exact, used for ranking
        FROM stock s
        CROSS JOIN params
        -- first close in the period (primary key index: ticker, price_date)
        CROSS JOIN LATERAL (
            SELECT dp.price_date, dp.close FROM daily_price dp
            WHERE dp.ticker = s.ticker AND dp.price_date BETWEEN params.start_d AND params.end_d
            ORDER BY dp.price_date
            LIMIT 1
        ) f
        -- last close in the period
        CROSS JOIN LATERAL (
            SELECT dp.price_date, dp.close FROM daily_price dp
            WHERE dp.ticker = s.ticker AND dp.price_date BETWEEN params.start_d AND params.end_d
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) l
        WHERE s.security_type = 'STOCK'
          AND l.price_date > f.price_date      -- need two different days
    ),
    ranked AS (
        SELECT 'GAINER' AS direction, RANK() OVER (ORDER BY m.change DESC) AS rnk, m.*
        FROM moves m WHERE m.change > 0
        UNION ALL
        SELECT 'LOSER', RANK() OVER (ORDER BY m.change ASC), m.*
        FROM moves m WHERE m.change < 0
    )
    SELECT r.direction, r.rnk, r.ticker, r.company_name,
           r.start_date, r.start_close, r.end_date, r.end_close,
           ROUND(100 * r.change, 2) AS pct_change
    FROM ranked r
    WHERE r.rnk <= p_limit
    ORDER BY r.direction, r.rnk, r.ticker;
$$;
