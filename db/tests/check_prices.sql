-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Read-only checks on the REAL price data, after running the loader.
-- Run: make check-prices
-- or:  psql portfolio_tracker -f db/tests/check_prices.sql
-- READ ONLY transaction: this script cannot change anything.
-- =====================================================================

\set ON_ERROR_STOP on
BEGIN READ ONLY;

\pset footer off
WITH checks (check_no, label, passed, detail) AS (
    SELECT 1, 'every stock has price rows',
           NOT EXISTS (SELECT 1 FROM stock s
                       WHERE NOT EXISTS (SELECT 1 FROM daily_price dp WHERE dp.ticker = s.ticker)),
           (SELECT string_agg(s.ticker, ', ') FROM stock s
            WHERE NOT EXISTS (SELECT 1 FROM daily_price dp WHERE dp.ticker = s.ticker))
    UNION ALL
    SELECT 2, '^GSPC is an INDEX with no sector/exchange and has rows',
           EXISTS (SELECT 1 FROM stock
                   WHERE ticker = '^GSPC' AND security_type = 'INDEX'
                     AND sector_id IS NULL AND exchange_id IS NULL)
           AND EXISTS (SELECT 1 FROM daily_price WHERE ticker = '^GSPC'),
           (SELECT count(*) || ' rows' FROM daily_price WHERE ticker = '^GSPC')
    UNION ALL
    -- 10-for-1 split on 2024-06-10: split-adjusted closes stay close together
    SELECT 3, 'NVDA: no ~10x jump between 2024-06-07 and 2024-06-10 closes',
           (SELECT b.close / a.close BETWEEN 0.8 AND 1.25
            FROM daily_price a, daily_price b
            WHERE a.ticker = 'NVDA' AND a.price_date = '2024-06-07'
              AND b.ticker = 'NVDA' AND b.price_date = '2024-06-10'),
           (SELECT a.close || ' -> ' || b.close
            FROM daily_price a, daily_price b
            WHERE a.ticker = 'NVDA' AND a.price_date = '2024-06-07'
              AND b.ticker = 'NVDA' AND b.price_date = '2024-06-10')
    UNION ALL
    SELECT 4, 'dates between 2021-01-01 and yesterday',
           (SELECT min(price_date) >= '2021-01-01' AND max(price_date) < CURRENT_DATE FROM daily_price),
           (SELECT min(price_date) || ' .. ' || max(price_date) FROM daily_price)
    UNION ALL
    SELECT 5, 'every stock starts in the first week of 2021',
           NOT EXISTS (SELECT 1 FROM daily_price GROUP BY ticker HAVING min(price_date) > '2021-01-08'),
           (SELECT string_agg(ticker || ' from ' || first_date, ', ')
            FROM (SELECT ticker, min(price_date) AS first_date FROM daily_price
                  GROUP BY ticker HAVING min(price_date) > '2021-01-08') late)
)
SELECT check_no AS "#", CASE WHEN passed THEN 'PASS' ELSE '** FAIL **' END AS result,
       label, detail
FROM checks ORDER BY check_no;

-- Per-ticker overview
SELECT s.ticker, s.security_type, sec.sector_name, ex.exchange_name,
       count(dp.price_date) AS days, min(dp.price_date) AS first_day, max(dp.price_date) AS last_day
FROM stock s
LEFT JOIN sector   sec ON sec.sector_id   = s.sector_id
LEFT JOIN exchange ex  ON ex.exchange_id  = s.exchange_id
LEFT JOIN daily_price dp ON dp.ticker = s.ticker
GROUP BY s.ticker, s.security_type, sec.sector_name, ex.exchange_name
ORDER BY sec.sector_name NULLS LAST, s.ticker;

ROLLBACK;
