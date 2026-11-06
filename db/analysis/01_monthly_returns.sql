-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Analysis query 1: monthly return of each portfolio vs the S&P 500
--
-- SELECT * FROM fn_monthly_returns();                       -- all portfolios, all months
-- SELECT * FROM fn_monthly_returns(5);                      -- one portfolio
-- SELECT * FROM fn_monthly_returns(5, '2025-01-01', '2025-12-01');  -- months Jan..Dec 2025
--
-- Value at a date d = cash after all events <= d
--                   + SUM(shares held on d x latest close <= d)
-- Period of a month: period_start = 1st of the month (start_date in the
-- first month); period_end = last day of the month (today in the
-- current month, so the last month can be partial).
-- start_value = previous month's end_value (starting_cash in the first month)
--
-- Return = Modified Dietz, so deposits/withdrawals are not gains:
--   R = (V_end - V_start - F) / (V_start + SUM(w_i x F_i))
--   F   = net flow (deposits - withdrawals) in the period
--   w_i = (period_end - flow_date + 1) / (period_end - period_start + 1)
--         (a flow counts from the start of its day: cash comes before
--         trades on the same day, so a deposit can be spent that day)
-- S&P return = ^GSPC close(latest <= period_end) / previous month's one - 1.
-- First month base: latest ^GSPC close BEFORE start_date (matches
-- V_start = cash at the start of start_date); if there is none, the open
-- of the first price day on or after start_date.
-- Cumulative = compounded product of (1 + R), from the first month shown.
-- All percentages are rounded to 2 decimals only for display.
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_monthly_returns(
    p_portfolio_id  INTEGER DEFAULT NULL,    -- NULL = all portfolios
    p_from_month    DATE    DEFAULT NULL,    -- any day of the month; NULL = first month
    p_to_month      DATE    DEFAULT NULL     -- any day of the month; NULL = current month
)
RETURNS TABLE (
    portfolio_id          INTEGER,
    portfolio_name        VARCHAR(100),
    month                 DATE,       -- first day of the month
    period_start          DATE,
    period_end            DATE,
    start_value           NUMERIC,
    end_value             NUMERIC,
    net_flow              NUMERIC,    -- deposits - withdrawals in the period
    portfolio_return_pct  NUMERIC,
    spx_return_pct        NUMERIC,
    excess_return_pct     NUMERIC,    -- portfolio - S&P, in percentage points
    cum_portfolio_pct     NUMERIC,
    cum_spx_pct           NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH params AS (
        -- Last month to compute: p_to_month's month, never after the current month
        SELECT LEAST(date_trunc('month', COALESCE(p_to_month, CURRENT_DATE)),
                     date_trunc('month', CURRENT_DATE))::date AS last_month
    ),
    pf AS (
        -- Chosen portfolios that have started, with the S&P base of the first month
        SELECT p.portfolio_id, p.portfolio_name, p.starting_cash, p.start_date,
               COALESCE(
                   (SELECT dp.close FROM daily_price dp          -- latest close before start_date
                    WHERE dp.ticker = '^GSPC' AND dp.price_date < p.start_date
                    ORDER BY dp.price_date DESC LIMIT 1),
                   (SELECT dp.open FROM daily_price dp           -- fallback: first open from start_date
                    WHERE dp.ticker = '^GSPC' AND dp.price_date >= p.start_date
                    ORDER BY dp.price_date LIMIT 1)) AS spx_base
        FROM portfolio p
        WHERE p.start_date <= CURRENT_DATE
          AND (p_portfolio_id IS NULL OR p.portfolio_id = p_portfolio_id)
    ),
    months AS (
        -- One row per portfolio and month, from start_date's month to last_month
        SELECT pf.portfolio_id, m::date AS month,
               GREATEST(m::date, pf.start_date)                          AS period_start,
               LEAST((m + INTERVAL '1 month - 1 day')::date, CURRENT_DATE) AS period_end
        FROM pf
        CROSS JOIN params
        CROSS JOIN LATERAL generate_series(date_trunc('month', pf.start_date),
                                           params.last_month,
                                           INTERVAL '1 month') AS m
    ),
    events AS (
        -- Every cash transaction (event_order 0) and trade (1), once per portfolio
        SELECT pf.portfolio_id, h.event_date, h.event_order, h.ticker,
               h.cash_delta, h.share_delta
        FROM pf
        CROSS JOIN LATERAL fn_portfolio_history(pf.portfolio_id) h
    ),
    month_cash AS (
        -- Cash at period_end, net flow and weighted flow inside the period
        SELECT m.portfolio_id, m.month,
               pf.starting_cash + COALESCE(SUM(e.cash_delta), 0) AS cash_end,
               COALESCE(SUM(e.cash_delta)
                        FILTER (WHERE e.event_order = 0 AND e.event_date >= m.period_start), 0)
                   AS net_flow,
               COALESCE(SUM(e.cash_delta * (m.period_end - e.event_date + 1)
                                         / (m.period_end - m.period_start + 1))
                        FILTER (WHERE e.event_order = 0 AND e.event_date >= m.period_start), 0)
                   AS weighted_flow
        FROM months m
        JOIN pf ON pf.portfolio_id = m.portfolio_id
        LEFT JOIN events e ON e.portfolio_id = m.portfolio_id
                          AND e.event_date <= m.period_end
        GROUP BY m.portfolio_id, m.month, pf.starting_cash
    ),
    month_positions AS (
        -- Shares of each ticker held at period_end
        SELECT m.portfolio_id, m.month, m.period_end, e.ticker,
               SUM(e.share_delta) AS shares
        FROM months m
        JOIN events e ON e.portfolio_id = m.portfolio_id
                     AND e.event_date <= m.period_end
                     AND e.ticker IS NOT NULL
        GROUP BY m.portfolio_id, m.month, m.period_end, e.ticker
        HAVING SUM(e.share_delta) > 0
    ),
    month_stock AS (
        SELECT mp.portfolio_id, mp.month, SUM(mp.shares * c.close) AS stock_value
        FROM month_positions mp
        -- Latest close on or before period_end (primary key index)
        CROSS JOIN LATERAL (
            SELECT dp.close FROM daily_price dp
            WHERE dp.ticker = mp.ticker AND dp.price_date <= mp.period_end
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) c
        GROUP BY mp.portfolio_id, mp.month
    ),
    monthly AS (
        SELECT m.portfolio_id, pf.portfolio_name, m.month, m.period_start, m.period_end,
               -- LAG = the previous row's value in the window (previous month)
               COALESCE(LAG(mc.cash_end + COALESCE(ms.stock_value, 0)) OVER w,
                        pf.starting_cash)                    AS start_value,
               mc.cash_end + COALESCE(ms.stock_value, 0)     AS end_value,
               mc.net_flow, mc.weighted_flow,
               COALESCE(LAG(spx.close) OVER w, pf.spx_base)  AS spx_start,
               spx.close                                     AS spx_end
        FROM months m
        JOIN pf              ON pf.portfolio_id = m.portfolio_id
        JOIN month_cash mc   ON mc.portfolio_id = m.portfolio_id AND mc.month = m.month
        LEFT JOIN month_stock ms ON ms.portfolio_id = m.portfolio_id AND ms.month = m.month
        -- Latest ^GSPC close on or before period_end (primary key index)
        LEFT JOIN LATERAL (
            SELECT dp.close FROM daily_price dp
            WHERE dp.ticker = '^GSPC' AND dp.price_date <= m.period_end
            ORDER BY dp.price_date DESC
            LIMIT 1
        ) spx ON true
        WINDOW w AS (PARTITION BY m.portfolio_id ORDER BY m.month)
    ),
    returns AS (
        -- The from-month filter must come AFTER the LAG above (a WHERE in
        -- the same SELECT runs before window functions, and the first
        -- shown month would lose its start_value)
        SELECT mo.*,
               (mo.end_value - mo.start_value - mo.net_flow)
                   / NULLIF(mo.start_value + mo.weighted_flow, 0) AS r_p,
               mo.spx_end / NULLIF(mo.spx_start, 0) - 1           AS r_spx
        FROM monthly mo
        WHERE p_from_month IS NULL OR mo.month >= date_trunc('month', p_from_month)
    )
    SELECT r.portfolio_id, r.portfolio_name, r.month, r.period_start, r.period_end,
           r.start_value, r.end_value, r.net_flow,
           ROUND(100 * r.r_p, 2),
           ROUND(100 * r.r_spx, 2),
           ROUND(100 * (r.r_p - r.r_spx), 2),
           -- Compounded: (1+r1)(1+r2)... - 1 = EXP(LN(1+r1) + LN(1+r2) + ...) - 1,
           -- a running SUM because PostgreSQL has no product aggregate
           ROUND(100 * (EXP(SUM(LN(CASE WHEN 1 + r.r_p   > 0 THEN 1 + r.r_p   END)) OVER c) - 1), 2),
           ROUND(100 * (EXP(SUM(LN(CASE WHEN 1 + r.r_spx > 0 THEN 1 + r.r_spx END)) OVER c) - 1), 2)
    FROM returns r
    WINDOW c AS (PARTITION BY r.portfolio_id ORDER BY r.month ROWS UNBOUNDED PRECEDING)
    ORDER BY r.portfolio_id, r.month;
$$;
