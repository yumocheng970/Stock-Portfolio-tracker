-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Schema tests for 01_reference_tables.sql and 02_portfolio_tables.sql
-- Run: psql portfolio_tracker -q -f db/tests/test_schema.sql
-- Everything runs in one transaction that is ROLLED BACK at the end,
-- so the database is left unchanged.
-- =====================================================================

\set ON_ERROR_STOP on
-- Hide the empty result row each SELECT pg_temp.xxx(...) prints;
-- the report at the end shows the results.
\o /dev/null
BEGIN;

-- ---------------------------------------------------------------------
-- Test harness
-- ---------------------------------------------------------------------
CREATE TEMP TABLE test_result (
    test_no  SERIAL,
    label    TEXT,
    passed   BOOLEAN,
    detail   TEXT
);

-- Statement must succeed.
CREATE FUNCTION pg_temp.expect_ok(p_label TEXT, p_sql TEXT) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE p_sql;
    INSERT INTO test_result (label, passed, detail) VALUES (p_label, true, 'ok');
EXCEPTION WHEN OTHERS THEN
    INSERT INTO test_result (label, passed, detail)
    VALUES (p_label, false, 'unexpected error: ' || SQLERRM);
END $$;

-- Statement must fail, and the error must name p_expected
-- (a constraint name, or a SQLSTATE such as 23502 for NOT NULL).
CREATE FUNCTION pg_temp.expect_error(p_label TEXT, p_sql TEXT, p_expected TEXT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_constraint TEXT;
    v_state      TEXT;
BEGIN
    EXECUTE p_sql;
    -- Reaching here means no error. Raise one ourselves so the
    -- statement's changes are undone, then report it as a failure.
    RAISE EXCEPTION '__no_error__';
EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME,
                            v_state      = RETURNED_SQLSTATE;
    IF SQLERRM = '__no_error__' THEN
        INSERT INTO test_result (label, passed, detail)
        VALUES (p_label, false, 'succeeded but should have failed');
    ELSE
        INSERT INTO test_result (label, passed, detail)
        VALUES (p_label,
                v_constraint = p_expected OR v_state = p_expected,
                'got ' || COALESCE(NULLIF(v_constraint, ''), v_state));
    END IF;
END $$;

-- Condition must be true.
CREATE FUNCTION pg_temp.check(p_label TEXT, p_cond BOOLEAN) RETURNS void
LANGUAGE sql AS $$
    INSERT INTO test_result (label, passed, detail)
    VALUES (p_label, COALESCE(p_cond, false), CASE WHEN p_cond THEN 'ok' ELSE 'condition false' END);
$$;

-- Look up generated IDs by their unique names (identity values are
-- not predictable because sequences are not rolled back).
CREATE FUNCTION pg_temp.inv(p_email TEXT) RETURNS INTEGER LANGUAGE sql AS
    $$ SELECT investor_id FROM investor WHERE email = p_email $$;
CREATE FUNCTION pg_temp.pf(p_name TEXT) RETURNS INTEGER LANGUAGE sql AS
    $$ SELECT portfolio_id FROM portfolio WHERE portfolio_name = p_name $$;
CREATE FUNCTION pg_temp.wl(p_name TEXT) RETURNS INTEGER LANGUAGE sql AS
    $$ SELECT watchlist_id FROM watchlist WHERE watchlist_name = p_name $$;

-- =====================================================================
-- sector
-- =====================================================================
SELECT pg_temp.expect_ok('sector: valid insert',
    $q$ INSERT INTO sector (sector_name) VALUES ('Technology'), ('Healthcare') $q$);
SELECT pg_temp.expect_error('sector: duplicate name',
    $q$ INSERT INTO sector (sector_name) VALUES ('Technology') $q$, 'uq_sector_name');
SELECT pg_temp.expect_error('sector: blank name',
    $q$ INSERT INTO sector (sector_name) VALUES ('   ') $q$, 'chk_sector_name_not_blank');
SELECT pg_temp.expect_error('sector: NULL name',
    $q$ INSERT INTO sector (sector_name) VALUES (NULL) $q$, '23502');
SELECT pg_temp.expect_error('sector: explicit id rejected (GENERATED ALWAYS)',
    $q$ INSERT INTO sector (sector_id, sector_name) VALUES (999, 'Energy') $q$, '428C9');

-- =====================================================================
-- exchange
-- =====================================================================
SELECT pg_temp.expect_ok('exchange: valid insert',
    $q$ INSERT INTO exchange (exchange_name) VALUES ('NASDAQ'), ('NYSE') $q$);
SELECT pg_temp.expect_error('exchange: duplicate name',
    $q$ INSERT INTO exchange (exchange_name) VALUES ('NYSE') $q$, 'uq_exchange_name');
SELECT pg_temp.expect_error('exchange: blank name',
    $q$ INSERT INTO exchange (exchange_name) VALUES ('') $q$, 'chk_exchange_name_not_blank');

-- =====================================================================
-- investor
-- =====================================================================
SELECT pg_temp.expect_ok('investor: valid insert',
    $q$ INSERT INTO investor (name, email) VALUES
        ('Alice', 'alice@example.com'), ('Bob', 'bob@example.com') $q$);
SELECT pg_temp.check('investor: created_date defaults to now()',
    (SELECT created_date IS NOT NULL FROM investor WHERE email = 'alice@example.com'));
SELECT pg_temp.expect_error('investor: blank name',
    $q$ INSERT INTO investor (name, email) VALUES (' ', 'c@example.com') $q$,
    'chk_investor_name_not_blank');
SELECT pg_temp.expect_error('investor: email without @',
    $q$ INSERT INTO investor (name, email) VALUES ('C', 'not-an-email') $q$,
    'chk_investor_email_format');
SELECT pg_temp.expect_error('investor: email with space',
    $q$ INSERT INTO investor (name, email) VALUES ('C', 'c d@example.com') $q$,
    'chk_investor_email_format');
SELECT pg_temp.expect_error('investor: email without dot in domain',
    $q$ INSERT INTO investor (name, email) VALUES ('C', 'c@example') $q$,
    'chk_investor_email_format');
SELECT pg_temp.expect_error('investor: duplicate email, different case',
    $q$ INSERT INTO investor (name, email) VALUES ('Alice2', 'ALICE@Example.com') $q$,
    'uq_investor_email_lower');

-- =====================================================================
-- stock
-- =====================================================================
SELECT pg_temp.expect_ok('stock: valid STOCK with sector/exchange',
    $q$ INSERT INTO stock (ticker, company_name, sector_id, exchange_id)
        SELECT t, n, s.sector_id, e.exchange_id
        FROM (VALUES ('AAPL', 'Apple Inc.'), ('MSFT', 'Microsoft'),
                     ('NVDA', 'NVIDIA'), ('BRK-B', 'Berkshire Hathaway B')) v(t, n)
        CROSS JOIN sector s CROSS JOIN exchange e
        WHERE s.sector_name = 'Technology' AND e.exchange_name = 'NASDAQ' $q$);
SELECT pg_temp.check('stock: security_type defaults to STOCK',
    (SELECT security_type = 'STOCK' FROM stock WHERE ticker = 'AAPL'));
SELECT pg_temp.expect_ok('stock: valid INDEX ^GSPC with no sector/exchange',
    $q$ INSERT INTO stock (ticker, company_name, security_type)
        VALUES ('^GSPC', 'S&P 500', 'INDEX') $q$);
SELECT pg_temp.expect_error('stock: duplicate ticker',
    $q$ INSERT INTO stock (ticker, company_name) VALUES ('AAPL', 'Dup') $q$, 'stock_pkey');
SELECT pg_temp.expect_error('stock: lowercase ticker',
    $q$ INSERT INTO stock (ticker, company_name) VALUES ('aapl', 'X') $q$,
    'chk_stock_ticker_format');
SELECT pg_temp.expect_error('stock: ticker too long (10 chars, no ^)',
    $q$ INSERT INTO stock (ticker, company_name) VALUES ('ABCDEFGHIJ', 'X') $q$,
    'chk_stock_ticker_format');
SELECT pg_temp.expect_error('stock: ticker with space',
    $q$ INSERT INTO stock (ticker, company_name) VALUES ('AB C', 'X') $q$,
    'chk_stock_ticker_format');
SELECT pg_temp.expect_error('stock: blank company name',
    $q$ INSERT INTO stock (ticker, company_name) VALUES ('XYZ', '  ') $q$,
    'chk_stock_company_not_blank');
SELECT pg_temp.expect_error('stock: bad security_type',
    $q$ INSERT INTO stock (ticker, company_name, security_type) VALUES ('SPY', 'SPDR', 'ETF') $q$,
    'chk_stock_security_type');
SELECT pg_temp.expect_error('stock: INDEX with a sector',
    $q$ INSERT INTO stock (ticker, company_name, security_type, sector_id)
        SELECT '^DJI', 'Dow Jones', 'INDEX', sector_id FROM sector WHERE sector_name = 'Technology' $q$,
    'chk_stock_index_unclassified');
SELECT pg_temp.expect_error('stock: INDEX with an exchange',
    $q$ INSERT INTO stock (ticker, company_name, security_type, exchange_id)
        SELECT '^DJI', 'Dow Jones', 'INDEX', exchange_id FROM exchange WHERE exchange_name = 'NYSE' $q$,
    'chk_stock_index_unclassified');
SELECT pg_temp.expect_error('stock: unknown sector_id',
    $q$ INSERT INTO stock (ticker, company_name, sector_id) VALUES ('XYZ', 'X', -1) $q$,
    'fk_stock_sector');
SELECT pg_temp.expect_error('stock: unknown exchange_id',
    $q$ INSERT INTO stock (ticker, company_name, exchange_id) VALUES ('XYZ', 'X', -1) $q$,
    'fk_stock_exchange');
SELECT pg_temp.expect_error('sector: delete while used by stock (RESTRICT)',
    $q$ DELETE FROM sector WHERE sector_name = 'Technology' $q$, 'fk_stock_sector');
SELECT pg_temp.expect_error('exchange: delete while used by stock (RESTRICT)',
    $q$ DELETE FROM exchange WHERE exchange_name = 'NASDAQ' $q$, 'fk_stock_exchange');
SELECT pg_temp.expect_ok('sector: delete unused sector',
    $q$ DELETE FROM sector WHERE sector_name = 'Healthcare' $q$);

-- =====================================================================
-- daily_price
-- =====================================================================
SELECT pg_temp.expect_ok('daily_price: valid insert',
    $q$ INSERT INTO daily_price (ticker, price_date, open, high, low, close, volume) VALUES
        ('AAPL',  '2024-01-02', 187.15, 188.44, 183.89, 185.64, 82488700),
        ('AAPL',  '2024-01-03', 184.22, 185.88, 183.43, 184.25, 58414500),
        ('MSFT',  '2024-01-02', 373.86, 375.90, 366.77, 370.87, 25258600),
        ('NVDA',  '2024-01-02', 49.24,  49.30,  47.59,  48.17,  411254000),
        ('^GSPC', '2024-01-02', 4745.20, 4754.33, 4722.67, 4742.83, 0) $q$);
SELECT pg_temp.expect_ok('daily_price: open = high = low = close allowed',
    $q$ INSERT INTO daily_price VALUES ('MSFT', '2024-01-03', 10, 10, 10, 10, 0) $q$);
SELECT pg_temp.expect_ok('daily_price: 3-decimal price rounds to 2',
    $q$ INSERT INTO daily_price VALUES ('BRK-B', '2024-01-02', 100.005, 100.005, 100.005, 100.005, 1) $q$);
SELECT pg_temp.check('daily_price: 100.005 stored as 100.01',
    (SELECT close = 100.01 FROM daily_price WHERE ticker = 'BRK-B'));
SELECT pg_temp.expect_error('daily_price: duplicate (ticker, date)',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-02', 1, 1, 1, 1, 1) $q$, 'pk_daily_price');
SELECT pg_temp.expect_error('daily_price: unknown ticker',
    $q$ INSERT INTO daily_price VALUES ('ZZZZ', '2024-01-02', 1, 1, 1, 1, 1) $q$,
    'fk_daily_price_stock');
SELECT pg_temp.expect_error('daily_price: low = 0',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-04', 0, 0, 0, 0, 1) $q$,
    'chk_daily_price_positive');
SELECT pg_temp.expect_error('daily_price: close above high',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-04', 10, 11, 9, 12, 1) $q$,
    'chk_daily_price_range');
SELECT pg_temp.expect_error('daily_price: open below low',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-04', 8, 11, 9, 10, 1) $q$,
    'chk_daily_price_range');
SELECT pg_temp.expect_error('daily_price: negative volume',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-04', 10, 11, 9, 10, -1) $q$,
    'chk_daily_price_volume');
SELECT pg_temp.expect_error('daily_price: NULL close',
    $q$ INSERT INTO daily_price VALUES ('AAPL', '2024-01-04', 10, 11, 9, NULL, 1) $q$, '23502');

-- =====================================================================
-- portfolio
-- =====================================================================
SELECT pg_temp.expect_ok('portfolio: valid insert',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date) VALUES
        (pg_temp.inv('alice@example.com'), 'Alice Growth', 100000, '2024-01-02'),
        (pg_temp.inv('bob@example.com'),   'Bob Growth',   50000,  '2024-01-02') $q$);
SELECT pg_temp.expect_ok('portfolio: starting_cash = 10,000,000 (upper bound) allowed',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'Alice Max', 10000000, '2024-01-02') $q$);
SELECT pg_temp.expect_ok('portfolio: same name for a different investor allowed',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('bob@example.com'), 'Alice Max', 1, '2024-01-02') $q$);
SELECT pg_temp.expect_error('portfolio: duplicate name for same investor',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'Alice Growth', 1, '2024-01-02') $q$,
    'uq_portfolio_investor_name');
SELECT pg_temp.expect_error('portfolio: blank name',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), '  ', 1, '2024-01-02') $q$,
    'chk_portfolio_name_not_blank');
SELECT pg_temp.expect_error('portfolio: starting_cash = 0',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'P0', 0, '2024-01-02') $q$,
    'chk_portfolio_starting_cash');
SELECT pg_temp.expect_error('portfolio: starting_cash > 10,000,000',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'P1', 10000000.01, '2024-01-02') $q$,
    'chk_portfolio_starting_cash');
SELECT pg_temp.expect_error('portfolio: unknown investor',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (-1, 'P2', 1, '2024-01-02') $q$, 'fk_portfolio_investor');
SELECT pg_temp.expect_error('portfolio: NULL start_date',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'P3', 1, NULL) $q$, '23502');

-- =====================================================================
-- cash_transaction
-- =====================================================================
SELECT pg_temp.expect_ok('cash_transaction: valid deposit and withdrawal',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date) VALUES
        (pg_temp.pf('Alice Growth'), 'DEPOSIT',    5000, '2024-01-02'),
        (pg_temp.pf('Alice Growth'), 'WITHDRAWAL', 1000, '2024-01-03') $q$);
SELECT pg_temp.expect_ok('cash_transaction: deposit = 10,000,000 (cap) allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'DEPOSIT', 10000000, '2024-01-03') $q$);
SELECT pg_temp.expect_ok('cash_transaction: withdrawal > cap passes CHECK (balance trigger later)',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'WITHDRAWAL', 20000000, '2024-01-03') $q$);
SELECT pg_temp.expect_error('cash_transaction: deposit > cap',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'DEPOSIT', 10000000.01, '2024-01-03') $q$,
    'chk_cash_deposit_cap');
SELECT pg_temp.expect_error('cash_transaction: bad txn_type',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'TRANSFER', 1, '2024-01-03') $q$,
    'chk_cash_txn_type');
SELECT pg_temp.expect_error('cash_transaction: lowercase txn_type',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'deposit', 1, '2024-01-03') $q$,
    'chk_cash_txn_type');
SELECT pg_temp.expect_error('cash_transaction: amount = 0',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'DEPOSIT', 0, '2024-01-03') $q$,
    'chk_cash_amount_positive');
SELECT pg_temp.expect_error('cash_transaction: negative withdrawal amount',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'WITHDRAWAL', -5, '2024-01-03') $q$,
    'chk_cash_amount_positive');
SELECT pg_temp.expect_error('cash_transaction: unknown portfolio',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (-1, 'DEPOSIT', 1, '2024-01-03') $q$, 'fk_cash_portfolio');

-- =====================================================================
-- trade
-- =====================================================================
SELECT pg_temp.expect_ok('trade: valid BUY and SELL',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY',  10, 185.00, '2024-01-02'),
        (pg_temp.pf('Alice Growth'), 'AAPL', 'SELL',  5, 184.00, '2024-01-03'),
        (pg_temp.pf('Bob Growth'),   'MSFT', 'BUY',   3, 370.00, '2024-01-02') $q$);
SELECT pg_temp.expect_error('trade: bad trade_type',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'HOLD', 1, 185, '2024-01-02') $q$,
    'chk_trade_type');
SELECT pg_temp.expect_error('trade: shares = 0',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 0, 185, '2024-01-02') $q$,
    'chk_trade_shares');
SELECT pg_temp.expect_error('trade: negative shares',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'SELL', -1, 185, '2024-01-02') $q$,
    'chk_trade_shares');
SELECT pg_temp.expect_error('trade: fractional shares (INTEGER column)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', '1.5', 185, '2024-01-02') $q$,
    '22P02');
SELECT pg_temp.expect_error('trade: price = 0',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 1, 0, '2024-01-02') $q$,
    'chk_trade_price');
SELECT pg_temp.expect_error('trade: unknown portfolio',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (-1, 'AAPL', 'BUY', 1, 185, '2024-01-02') $q$, 'fk_trade_portfolio');
SELECT pg_temp.expect_error('trade: date with no price data (weekend)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 1, 185, '2024-01-06') $q$,
    'fk_trade_daily_price');
SELECT pg_temp.expect_error('trade: unknown ticker',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'ZZZZ', 'BUY', 1, 185, '2024-01-02') $q$,
    'fk_trade_daily_price');

-- =====================================================================
-- watchlist
-- =====================================================================
SELECT pg_temp.expect_ok('watchlist: valid insert',
    $q$ INSERT INTO watchlist (investor_id, watchlist_name) VALUES
        (pg_temp.inv('alice@example.com'), 'Alice Tech'),
        (pg_temp.inv('bob@example.com'),   'Bob Watch') $q$);
SELECT pg_temp.expect_error('watchlist: duplicate name for same investor',
    $q$ INSERT INTO watchlist (investor_id, watchlist_name)
        VALUES (pg_temp.inv('alice@example.com'), 'Alice Tech') $q$,
    'uq_watchlist_investor_name');
SELECT pg_temp.expect_error('watchlist: blank name',
    $q$ INSERT INTO watchlist (investor_id, watchlist_name)
        VALUES (pg_temp.inv('alice@example.com'), '') $q$,
    'chk_watchlist_name_not_blank');
SELECT pg_temp.expect_error('watchlist: unknown investor',
    $q$ INSERT INTO watchlist (investor_id, watchlist_name) VALUES (-1, 'W') $q$,
    'fk_watchlist_investor');

-- =====================================================================
-- watchlist_item
-- =====================================================================
SELECT pg_temp.expect_ok('watchlist_item: valid insert (NULL and positive target)',
    $q$ INSERT INTO watchlist_item (watchlist_id, ticker, target_price) VALUES
        (pg_temp.wl('Alice Tech'), 'AAPL', NULL),
        (pg_temp.wl('Alice Tech'), 'NVDA', 50.00),
        (pg_temp.wl('Alice Tech'), '^GSPC', NULL),
        (pg_temp.wl('Bob Watch'),  'NVDA', 45.00) $q$);
SELECT pg_temp.expect_error('watchlist_item: duplicate (watchlist, ticker)',
    $q$ INSERT INTO watchlist_item (watchlist_id, ticker)
        VALUES (pg_temp.wl('Alice Tech'), 'AAPL') $q$, 'pk_watchlist_item');
SELECT pg_temp.expect_error('watchlist_item: target_price = 0',
    $q$ INSERT INTO watchlist_item (watchlist_id, ticker, target_price)
        VALUES (pg_temp.wl('Alice Tech'), 'MSFT', 0) $q$, 'chk_watchlist_target_positive');
SELECT pg_temp.expect_error('watchlist_item: unknown watchlist',
    $q$ INSERT INTO watchlist_item (watchlist_id, ticker) VALUES (-1, 'AAPL') $q$,
    'fk_watchlist_item_watchlist');
SELECT pg_temp.expect_error('watchlist_item: unknown ticker',
    $q$ INSERT INTO watchlist_item (watchlist_id, ticker)
        VALUES (pg_temp.wl('Alice Tech'), 'ZZZZ') $q$, 'fk_watchlist_item_stock');

-- =====================================================================
-- trade_audit
-- =====================================================================
SELECT pg_temp.expect_ok('trade_audit: valid UPDATE and DELETE snapshots',
    $q$ INSERT INTO trade_audit (operation, trade_id, portfolio_id, ticker, trade_type,
                                 shares, price, trade_date) VALUES
        ('UPDATE', 1, pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 10, 185, '2024-01-02'),
        ('DELETE', 2, pg_temp.pf('Alice Growth'), 'AAPL', 'SELL', 5, 184, '2024-01-03') $q$);
SELECT pg_temp.check('trade_audit: changed_at and changed_by defaults filled',
    (SELECT bool_and(changed_at IS NOT NULL AND changed_by = current_user) FROM trade_audit));
SELECT pg_temp.expect_ok('trade_audit: no FK, so a nonexistent trade/portfolio is allowed',
    $q$ INSERT INTO trade_audit (operation, trade_id, portfolio_id, ticker, trade_type,
                                 shares, price, trade_date)
        VALUES ('DELETE', -99, -99, 'GONE', 'BUY', 1, 1, '2000-01-01') $q$);
SELECT pg_temp.expect_error('trade_audit: operation INSERT not allowed',
    $q$ INSERT INTO trade_audit (operation, trade_id, portfolio_id, ticker, trade_type,
                                 shares, price, trade_date)
        VALUES ('INSERT', 1, 1, 'AAPL', 'BUY', 1, 1, '2024-01-02') $q$,
    'chk_trade_audit_operation');

-- =====================================================================
-- FK actions: RESTRICT and CASCADE
-- =====================================================================

-- stock -> daily_price CASCADE is blocked by trade -> daily_price RESTRICT
SELECT pg_temp.expect_error('stock with trades: delete blocked',
    $q$ DELETE FROM stock WHERE ticker = 'AAPL' $q$, 'fk_trade_daily_price');
SELECT pg_temp.expect_error('daily_price used by a trade: delete blocked',
    $q$ DELETE FROM daily_price WHERE ticker = 'AAPL' AND price_date = '2024-01-02' $q$,
    'fk_trade_daily_price');
SELECT pg_temp.expect_ok('daily_price not used by any trade: delete allowed',
    $q$ DELETE FROM daily_price WHERE ticker = 'MSFT' AND price_date = '2024-01-03' $q$);

-- stock without trades: delete cascades to daily_price and watchlist_item
SELECT pg_temp.expect_ok('stock without trades (NVDA): delete allowed',
    $q$ DELETE FROM stock WHERE ticker = 'NVDA' $q$);
SELECT pg_temp.check('  -> NVDA daily_price rows cascaded away',
    NOT EXISTS (SELECT 1 FROM daily_price WHERE ticker = 'NVDA'));
SELECT pg_temp.check('  -> NVDA watchlist_item rows cascaded away (both watchlists)',
    NOT EXISTS (SELECT 1 FROM watchlist_item WHERE ticker = 'NVDA'));

-- ON UPDATE CASCADE: rename AAPL -> AAPLX flows stock -> daily_price -> trade
-- and stock -> watchlist_item
SELECT pg_temp.expect_ok('stock: rename ticker AAPL -> AAPLX',
    $q$ UPDATE stock SET ticker = 'AAPLX' WHERE ticker = 'AAPL' $q$);
SELECT pg_temp.check('  -> daily_price follows rename (2 rows)',
    (SELECT count(*) = 2 FROM daily_price WHERE ticker = 'AAPLX')
    AND NOT EXISTS (SELECT 1 FROM daily_price WHERE ticker = 'AAPL'));
SELECT pg_temp.check('  -> trade follows rename via daily_price (2 rows)',
    (SELECT count(*) = 2 FROM trade WHERE ticker = 'AAPLX')
    AND NOT EXISTS (SELECT 1 FROM trade WHERE ticker = 'AAPL'));
SELECT pg_temp.check('  -> watchlist_item follows rename',
    EXISTS (SELECT 1 FROM watchlist_item WHERE ticker = 'AAPLX'));

-- watchlist -> watchlist_item CASCADE
SELECT pg_temp.expect_ok('watchlist: delete Bob Watch',
    $q$ DELETE FROM watchlist WHERE watchlist_name = 'Bob Watch' $q$);
SELECT pg_temp.check('  -> its items cascaded away; Alice''s items remain',
    (SELECT count(*) FROM watchlist_item) = 2);

-- portfolio -> trade / cash_transaction CASCADE; audit survives
CREATE TEMP TABLE saved_ids AS
    SELECT pg_temp.pf('Alice Growth') AS alice_pf, pg_temp.inv('bob@example.com') AS bob_id;
SELECT pg_temp.expect_ok('portfolio: delete Alice Growth',
    $q$ DELETE FROM portfolio WHERE portfolio_name = 'Alice Growth' $q$);
SELECT pg_temp.check('  -> its trades cascaded away',
    NOT EXISTS (SELECT 1 FROM trade t JOIN saved_ids s ON t.portfolio_id = s.alice_pf));
SELECT pg_temp.check('  -> its cash transactions cascaded away',
    NOT EXISTS (SELECT 1 FROM cash_transaction c JOIN saved_ids s ON c.portfolio_id = s.alice_pf));
SELECT pg_temp.check('  -> trade_audit rows kept (no FK)',
    (SELECT count(*) = 2 FROM trade_audit a JOIN saved_ids s ON a.portfolio_id = s.alice_pf));
SELECT pg_temp.expect_ok('stock AAPLX: delete allowed once its trades are gone',
    $q$ DELETE FROM stock WHERE ticker = 'AAPLX' $q$);

-- investor -> portfolio / watchlist CASCADE (and onward to trades)
SELECT pg_temp.expect_ok('investor: delete Bob',
    $q$ DELETE FROM investor WHERE email = 'bob@example.com' $q$);
SELECT pg_temp.check('  -> Bob''s portfolios cascaded away',
    NOT EXISTS (SELECT 1 FROM portfolio p JOIN saved_ids s ON p.investor_id = s.bob_id));
SELECT pg_temp.check('  -> Bob''s trades cascaded away (investor -> portfolio -> trade)',
    NOT EXISTS (SELECT 1 FROM trade WHERE ticker = 'MSFT'));
SELECT pg_temp.check('  -> Bob''s watchlists cascaded away',
    NOT EXISTS (SELECT 1 FROM watchlist w JOIN saved_ids s ON w.investor_id = s.bob_id));
SELECT pg_temp.check('  -> Alice untouched (her remaining portfolio and watchlist)',
    pg_temp.pf('Alice Max') IS NOT NULL AND pg_temp.wl('Alice Tech') IS NOT NULL);

-- =====================================================================
-- Report
-- =====================================================================
\o
\pset footer off
SELECT test_no AS "#", CASE WHEN passed THEN 'PASS' ELSE '** FAIL **' END AS result,
       label, detail
FROM test_result ORDER BY test_no;

SELECT count(*) FILTER (WHERE passed)     AS passed,
       count(*) FILTER (WHERE NOT passed) AS failed,
       count(*)                           AS total
FROM test_result;

ROLLBACK;
