-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Read-only checks on the REAL sample data, after `make seed`.
-- Run: make check-sample-data
-- or:  psql portfolio_tracker -f db/tests/check_sample_data.sql
-- READ ONLY transaction: this script cannot change anything.
-- =====================================================================

\set ON_ERROR_STOP on
BEGIN READ ONLY;

\pset footer off
WITH
-- Last state of every portfolio according to the balance replay
replay_cash AS (
    SELECT DISTINCT ON (p.portfolio_id) p.portfolio_id, h.cash_after
    FROM portfolio p
    CROSS JOIN LATERAL fn_portfolio_history(p.portfolio_id) h
    ORDER BY p.portfolio_id, h.event_date DESC, h.event_order DESC, h.event_id DESC
),
replay_shares AS (
    SELECT DISTINCT ON (p.portfolio_id, h.ticker) p.portfolio_id, h.ticker, h.shares_after
    FROM portfolio p
    CROSS JOIN LATERAL fn_portfolio_history(p.portfolio_id) h
    WHERE h.ticker IS NOT NULL
    ORDER BY p.portfolio_id, h.ticker, h.event_date DESC, h.event_order DESC, h.event_id DESC
),
latest_close AS (
    SELECT DISTINCT ON (ticker) ticker, close
    FROM daily_price ORDER BY ticker, price_date DESC
),
-- Trades per portfolio, counting the ones the audit demo deleted
trade_counts AS (
    SELECT p.portfolio_id,
           (SELECT count(*) FROM trade t WHERE t.portfolio_id = p.portfolio_id)
         + (SELECT count(*) FROM trade_audit a
            WHERE a.portfolio_id = p.portfolio_id AND a.operation = 'DELETE') AS n
    FROM portfolio p
),
checks (check_no, label, passed, detail) AS (
    SELECT 1, 'sample data exists (investors, portfolios, trades)',
           (SELECT count(*) FROM investor) > 0 AND (SELECT count(*) FROM trade) > 0,
           (SELECT count(*) FROM investor) || ' investors, '
             || (SELECT count(*) FROM portfolio) || ' portfolios, '
             || (SELECT count(*) FROM trade) || ' trades, '
             || (SELECT count(*) FROM cash_transaction) || ' cash txns'
    UNION ALL
    SELECT 2, 'every v_cash_balance.cash_balance >= 0',
           NOT EXISTS (SELECT 1 FROM v_cash_balance WHERE cash_balance < 0),
           'lowest: ' || (SELECT min(cash_balance) FROM v_cash_balance)
    UNION ALL
    SELECT 3, 'every v_holdings.shares_held >= 0',
           NOT EXISTS (SELECT 1 FROM v_holdings WHERE shares_held < 0),
           (SELECT count(*) FILTER (WHERE is_open) || ' open, '
                   || count(*) FILTER (WHERE NOT is_open) || ' closed positions' FROM v_holdings)
    UNION ALL
    SELECT 4, 'replay final cash = v_cash_balance for every portfolio',
           NOT EXISTS (SELECT 1 FROM v_cash_balance v
                       LEFT JOIN replay_cash r USING (portfolio_id)
                       WHERE COALESCE(r.cash_after, v.starting_cash) <> v.cash_balance),
           NULL
    UNION ALL
    SELECT 5, 'replay final shares = v_holdings for every portfolio and ticker',
           NOT EXISTS (SELECT 1 FROM replay_shares r
                       FULL JOIN v_holdings v USING (portfolio_id, ticker)
                       WHERE r.shares_after IS DISTINCT FROM v.shares_held),
           NULL
    UNION ALL
    SELECT 6, 'at least one watchlist item has latest close >= target_price',
           EXISTS (SELECT 1 FROM watchlist_item w JOIN latest_close c USING (ticker)
                   WHERE c.close >= w.target_price),
           (SELECT count(*) || ' of ' || (SELECT count(*) FROM watchlist_item) || ' items reached'
            FROM watchlist_item w JOIN latest_close c USING (ticker)
            WHERE c.close >= w.target_price)
    UNION ALL
    SELECT 7, 'trade_audit has UPDATE and DELETE rows',
           EXISTS (SELECT 1 FROM trade_audit WHERE operation = 'UPDATE')
           AND EXISTS (SELECT 1 FROM trade_audit WHERE operation = 'DELETE'),
           (SELECT string_agg(operation || ' ' || n, ', ' ORDER BY operation)
            FROM (SELECT operation, count(*) AS n FROM trade_audit GROUP BY operation) a)
    UNION ALL
    SELECT 8, 'every portfolio has 20-60 trades (incl. the ones deleted by the audit demo)',
           NOT EXISTS (SELECT 1 FROM trade_counts WHERE n NOT BETWEEN 20 AND 60),
           (SELECT 'min ' || min(n) || ', max ' || max(n) FROM trade_counts)
    UNION ALL
    SELECT 9, 'no portfolio ever traded ^GSPC (or any INDEX)',
           NOT EXISTS (SELECT 1 FROM trade t JOIN stock s USING (ticker) WHERE s.security_type = 'INDEX'),
           NULL
)
SELECT check_no AS "#", CASE WHEN passed THEN 'PASS' ELSE '** FAIL **' END AS result,
       label, detail
FROM checks ORDER BY check_no;

-- Fingerprint of all seeded data (ids included, now() timestamps excluded).
-- Two runs of `make reseed` with the same seed must print the same value.
SELECT md5(concat_ws('#',
    (SELECT string_agg(concat_ws('|', investor_id, name, email), ',' ORDER BY investor_id) FROM investor),
    (SELECT string_agg(concat_ws('|', portfolio_id, investor_id, portfolio_name, starting_cash, start_date),
                       ',' ORDER BY portfolio_id) FROM portfolio),
    (SELECT string_agg(concat_ws('|', cash_txn_id, portfolio_id, txn_type, amount, txn_date),
                       ',' ORDER BY cash_txn_id) FROM cash_transaction),
    (SELECT string_agg(concat_ws('|', trade_id, portfolio_id, ticker, trade_type, shares, price, trade_date),
                       ',' ORDER BY trade_id) FROM trade),
    (SELECT string_agg(concat_ws('|', watchlist_id, investor_id, watchlist_name), ',' ORDER BY watchlist_id)
     FROM watchlist),
    (SELECT string_agg(concat_ws('|', watchlist_id, ticker, target_price), ',' ORDER BY watchlist_id, ticker)
     FROM watchlist_item),
    (SELECT string_agg(concat_ws('|', audit_id, operation, trade_id, portfolio_id, ticker, trade_type,
                                 shares, price, trade_date), ',' ORDER BY audit_id) FROM trade_audit)
)) AS sample_data_fingerprint;

ROLLBACK;
