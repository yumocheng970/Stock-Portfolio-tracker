-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- View 1: v_cash_balance - current cash of every portfolio
-- Run AFTER db/schema/ files (normally via db/reset.sql)
--
-- cash_balance = starting_cash + deposits - withdrawals - buys + sells
-- (buys/sells = shares * price). Cash is derived, never stored.
--
-- Avoiding join fan-out: each child table is first aggregated to ONE
-- row per portfolio (CTEs below), and only then joined to portfolio.
-- Joining the raw tables would pair every cash row with every trade
-- row of the same portfolio and multiply the sums.
-- =====================================================================

CREATE OR REPLACE VIEW v_cash_balance AS
WITH cash_totals AS (
    -- one row per portfolio that has cash transactions
    SELECT portfolio_id,
           SUM(amount) FILTER (WHERE txn_type = 'DEPOSIT')    AS deposits,
           SUM(amount) FILTER (WHERE txn_type = 'WITHDRAWAL') AS withdrawals
    FROM cash_transaction
    GROUP BY portfolio_id
),
trade_totals AS (
    -- one row per portfolio that has trades
    SELECT portfolio_id,
           SUM(shares * price) FILTER (WHERE trade_type = 'BUY')  AS buys,
           SUM(shares * price) FILTER (WHERE trade_type = 'SELL') AS sells
    FROM trade
    GROUP BY portfolio_id
)
SELECT p.portfolio_id,
       p.investor_id,
       p.portfolio_name,
       p.starting_cash,
       -- COALESCE: NULL when the portfolio has no matching rows
       COALESCE(c.deposits,    0) AS deposits,
       COALESCE(c.withdrawals, 0) AS withdrawals,
       COALESCE(t.buys,        0) AS buys,
       COALESCE(t.sells,       0) AS sells,
       p.starting_cash
         + COALESCE(c.deposits,    0)
         - COALESCE(c.withdrawals, 0)
         - COALESCE(t.buys,        0)
         + COALESCE(t.sells,       0) AS cash_balance
FROM portfolio p
-- LEFT JOIN keeps portfolios with no cash transactions / no trades
LEFT JOIN cash_totals  c ON c.portfolio_id = p.portfolio_id
LEFT JOIN trade_totals t ON t.portfolio_id = p.portfolio_id;
