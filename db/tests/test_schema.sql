-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Schema tests for 01_reference_tables.sql and 02_portfolio_tables.sql,
-- plus programmability/01_trade_validation.sql (trigger)
-- Rebuild first if needed: psql portfolio_tracker -f db/reset.sql
-- Run: psql portfolio_tracker -q -f db/tests/test_schema.sql
-- Everything runs in one transaction that is ROLLED BACK at the end,
-- so the database is left unchanged.
-- =====================================================================

\set ON_ERROR_STOP on
-- Hide the empty result row each SELECT pg_temp.xxx(...) prints;
-- the report at the end shows the results.
\o /dev/null
SET client_min_messages = warning;   -- hide NOTICEs (e.g. "truncate cascades to ...")
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

-- DETAIL text of the error the statement raises (NULL if it succeeds).
-- The statement's changes are always undone.
CREATE FUNCTION pg_temp.error_detail(p_sql TEXT) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_detail TEXT;
BEGIN
    EXECUTE p_sql;
    RAISE EXCEPTION '__no_error__';
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM = '__no_error__' THEN
        RETURN NULL;
    END IF;
    GET STACKED DIAGNOSTICS v_detail = PG_EXCEPTION_DETAIL;
    RETURN v_detail;
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
        (pg_temp.pf('Alice Growth'), 'WITHDRAWAL', 1000, '2024-01-02') $q$);
SELECT pg_temp.expect_ok('cash_transaction: deposit = 10,000,000 (cap) allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'DEPOSIT', 10000000, '2024-01-02') $q$);
-- No CHECK caps withdrawals; the balance trigger (04_balance_checks.sql) does
SELECT pg_temp.expect_error('cash_transaction: withdrawal > cash rejected by balance trigger',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Alice Growth'), 'WITHDRAWAL', 20000000, '2024-01-02') $q$,
    'trg_cash_never_negative');
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
-- trigger trg_cash_txn_immutable (db/programmability/02_cash_txn_immutable.sql)
-- Insert-only; cascade deletes are tested in the FK section below.
-- =====================================================================
SELECT pg_temp.expect_ok('trg cash: INSERT still works',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bob Growth'), 'DEPOSIT', 250, '2024-01-02') $q$);
SELECT pg_temp.expect_error('trg cash: UPDATE amount rejected',
    $q$ UPDATE cash_transaction SET amount = 999
        WHERE portfolio_id = pg_temp.pf('Bob Growth') $q$, 'trg_cash_txn_immutable');
SELECT pg_temp.expect_error('trg cash: UPDATE txn_type rejected',
    $q$ UPDATE cash_transaction SET txn_type = 'WITHDRAWAL'
        WHERE portfolio_id = pg_temp.pf('Bob Growth') $q$, 'trg_cash_txn_immutable');
SELECT pg_temp.expect_error('trg cash: direct DELETE rejected',
    $q$ DELETE FROM cash_transaction
        WHERE portfolio_id = pg_temp.pf('Bob Growth') $q$, 'trg_cash_txn_immutable');
SELECT pg_temp.check('trg cash: Bob''s deposit unchanged after rejected UPDATE/DELETE',
    (SELECT count(*) = 1 AND bool_and(amount = 250 AND txn_type = 'DEPOSIT')
     FROM cash_transaction WHERE portfolio_id = pg_temp.pf('Bob Growth')));
SELECT pg_temp.expect_error('trg cash: TRUNCATE cash_transaction rejected',
    $q$ TRUNCATE cash_transaction $q$, 'trg_cash_txn_no_truncate');
-- Documents the trade-off: truncate triggers also fire on CASCADE targets
SELECT pg_temp.expect_error('trg cash: TRUNCATE portfolio CASCADE also rejected',
    $q$ TRUNCATE portfolio CASCADE $q$, 'trg_cash_txn_no_truncate');
SELECT pg_temp.check('trg cash: cash rows still there after rejected TRUNCATEs',
    (SELECT count(*) = 4 FROM cash_transaction));

-- =====================================================================
-- trade
-- Error tests below use 2024-01-03 (Alice Growth's latest event date):
-- an earlier date would hit trg_date_before_latest first.
-- =====================================================================
SELECT pg_temp.expect_ok('trade: valid BUY and SELL',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY',  10, 185.00, '2024-01-02'),
        (pg_temp.pf('Alice Growth'), 'AAPL', 'SELL',  5, 184.00, '2024-01-03'),
        (pg_temp.pf('Bob Growth'),   'MSFT', 'BUY',   3, 370.00, '2024-01-02') $q$);
SELECT pg_temp.expect_error('trade: bad trade_type',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'HOLD', 1, 185, '2024-01-03') $q$,
    'chk_trade_type');
SELECT pg_temp.expect_error('trade: shares = 0',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 0, 185, '2024-01-03') $q$,
    'chk_trade_shares');
SELECT pg_temp.expect_error('trade: negative shares',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'SELL', -1, 185, '2024-01-03') $q$,
    'chk_trade_shares');
SELECT pg_temp.expect_error('trade: fractional shares (INTEGER column)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', '1.5', 185, '2024-01-03') $q$,
    '22P02');
-- Weekend date on purpose: on a trading day the BEFORE trigger runs
-- first and reports trg_trade_price_in_range instead (tested below).
SELECT pg_temp.expect_error('trade: price = 0',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Growth'), 'AAPL', 'BUY', 1, 0, '2024-01-06') $q$,
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
        VALUES (pg_temp.pf('Alice Growth'), 'ZZZZ', 'BUY', 1, 185, '2024-01-03') $q$,
    'fk_trade_daily_price');

-- =====================================================================
-- trigger trg_trade_validate (db/programmability/01_trade_validation.sql)
-- AAPL 2024-01-02: low 183.89, high 188.44
-- =====================================================================

-- (a) price within low..high
SELECT pg_temp.expect_ok('trg (a): price = day low allowed',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 183.89, '2024-01-02') $q$);
SELECT pg_temp.expect_ok('trg (a): price = day high allowed',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 188.44, '2024-01-02') $q$);
SELECT pg_temp.expect_error('trg (a): price 1 cent below low',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 183.88, '2024-01-02') $q$,
    'trg_trade_price_in_range');
SELECT pg_temp.expect_error('trg (a): price 1 cent above high',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 188.45, '2024-01-02') $q$,
    'trg_trade_price_in_range');
SELECT pg_temp.expect_error('trg (a): price = 0 on a trading day (trigger runs before CHECK)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 0, '2024-01-02') $q$,
    'trg_trade_price_in_range');
SELECT pg_temp.expect_error('trg (a): uses the trade date''s range, not another day''s',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), 'AAPL', 'BUY', 1, 188.00, '2024-01-03') $q$,
    'trg_trade_price_in_range');
SELECT pg_temp.expect_error('trg (a): checked on UPDATE too',
    $q$ UPDATE trade SET price = 500
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    'trg_trade_price_in_range');

-- (b) no INDEX trading (price 4745.00 is inside ^GSPC's range that day)
SELECT pg_temp.expect_error('trg (b): BUY ^GSPC rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), '^GSPC', 'BUY', 1, 4745.00, '2024-01-02') $q$,
    'trg_trade_not_index');
SELECT pg_temp.expect_error('trg (b): SELL ^GSPC rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Max'), '^GSPC', 'SELL', 1, 4745.00, '2024-01-02') $q$,
    'trg_trade_not_index');

-- (c) UPDATE: only shares and price may change
SELECT pg_temp.expect_ok('trg (c): UPDATE shares allowed',
    $q$ UPDATE trade SET shares = 12
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$);
SELECT pg_temp.expect_ok('trg (c): UPDATE price (in range) allowed',
    $q$ UPDATE trade SET price = 186.00
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$);
SELECT pg_temp.expect_ok('trg (c): UPDATE setting columns to the same value allowed',
    $q$ UPDATE trade SET trade_date = trade_date, ticker = ticker
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$);
SELECT pg_temp.expect_error('trg (c): UPDATE trade_date rejected',
    $q$ UPDATE trade SET trade_date = '2024-01-03'
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    'trg_trade_immutable_cols');
SELECT pg_temp.expect_error('trg (c): UPDATE trade_type rejected',
    $q$ UPDATE trade SET trade_type = 'SELL'
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    'trg_trade_immutable_cols');
SELECT pg_temp.expect_error('trg (c): UPDATE portfolio_id rejected',
    $q$ UPDATE trade SET portfolio_id = pg_temp.pf('Alice Max')
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    'trg_trade_immutable_cols');
SELECT pg_temp.expect_error('trg (c): UPDATE ticker directly rejected',
    $q$ UPDATE trade SET ticker = 'MSFT'
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    'trg_trade_immutable_cols');
SELECT pg_temp.expect_error('trg (c): UPDATE trade_id rejected (GENERATED ALWAYS)',
    $q$ UPDATE trade SET trade_id = 999999
        WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY' $q$,
    '428C9');
SELECT pg_temp.check('trg (c): rejected updates left the BUY row as 12 @ 186.00 on 2024-01-02',
    (SELECT shares = 12 AND price = 186.00 AND trade_date = '2024-01-02' AND ticker = 'AAPL'
     FROM trade WHERE portfolio_id = pg_temp.pf('Alice Growth') AND trade_type = 'BUY'));
-- (Ticker change via stock rename cascade is tested in the FK section below.)

-- Remove the 2 boundary trades so later counts are unaffected
-- (expect_ok, not a bare DELETE: a broken audit trigger then shows up
-- as one FAIL instead of stopping the whole script)
SELECT pg_temp.expect_ok('cleanup: delete the 2 boundary trades',
    $q$ DELETE FROM trade WHERE portfolio_id = pg_temp.pf('Alice Max') $q$);

-- =====================================================================
-- trigger trg_trade_audit (db/programmability/03_trade_audit.sql)
-- Uses its own portfolio 'Alice Audit' so audit counts are isolated.
-- AAPL 2024-01-02: low 183.89, high 188.44; 2024-01-03: 183.43..185.88
-- =====================================================================
SELECT pg_temp.expect_ok('trg audit: setup portfolio Alice Audit',
    $q$ INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
        VALUES (pg_temp.inv('alice@example.com'), 'Alice Audit', 100000, '2024-01-02') $q$);
CREATE TEMP TABLE audit_ids AS SELECT pg_temp.pf('Alice Audit') AS pf_id;

-- INSERT: no audit row
SELECT pg_temp.expect_ok('trg audit: INSERT a trade (4 @ 185.00)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Audit'), 'AAPL', 'BUY', 4, 185.00, '2024-01-02') $q$);
SELECT pg_temp.check('trg audit: INSERT writes NO audit row',
    NOT EXISTS (SELECT 1 FROM trade_audit a JOIN audit_ids s ON a.portfolio_id = s.pf_id));

-- UPDATE: one row with the OLD values
SELECT pg_temp.expect_ok('trg audit: UPDATE to 6 @ 186.00',
    $q$ UPDATE trade SET shares = 6, price = 186.00
        WHERE portfolio_id = pg_temp.pf('Alice Audit') $q$);
SELECT pg_temp.check('trg audit: UPDATE writes 1 row: UPDATE, OLD 4 @ 185.00, same trade_id',
    (SELECT count(*) = 1
            AND bool_and(a.operation = 'UPDATE' AND a.shares = 4 AND a.price = 185.00
                         AND a.trade_id = t.trade_id AND a.ticker = 'AAPL'
                         AND a.trade_date = '2024-01-02' AND a.changed_by = current_user)
     FROM trade_audit a
     JOIN audit_ids s ON a.portfolio_id = s.pf_id
     JOIN trade t     ON t.portfolio_id = s.pf_id));
SELECT pg_temp.check('trg audit: the trade itself now holds the NEW values 6 @ 186.00',
    (SELECT shares = 6 AND price = 186.00 FROM trade WHERE portfolio_id = pg_temp.pf('Alice Audit')));

-- Rejected UPDATE: no audit row (whole statement rolled back)
SELECT pg_temp.expect_error('trg audit: UPDATE rejected by trg_trade_validate (price 500)',
    $q$ UPDATE trade SET price = 500 WHERE portfolio_id = pg_temp.pf('Alice Audit') $q$,
    'trg_trade_price_in_range');
SELECT pg_temp.expect_error('trg audit: UPDATE rejected by trg_trade_validate (trade_date)',
    $q$ UPDATE trade SET trade_date = '2024-01-03' WHERE portfolio_id = pg_temp.pf('Alice Audit') $q$,
    'trg_trade_immutable_cols');
SELECT pg_temp.check('trg audit: rejected UPDATEs write NO audit row (still 1)',
    (SELECT count(*) = 1 FROM trade_audit a JOIN audit_ids s ON a.portfolio_id = s.pf_id));

-- DELETE: one row with operation DELETE
SELECT pg_temp.expect_ok('trg audit: INSERT a second trade (2 @ 184.00 on 2024-01-03)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Audit'), 'AAPL', 'BUY', 2, 184.00, '2024-01-03') $q$);
CREATE TEMP TABLE audit_deleted AS
    SELECT trade_id FROM trade
    WHERE portfolio_id = pg_temp.pf('Alice Audit') AND trade_date = '2024-01-03';
SELECT pg_temp.expect_ok('trg audit: DELETE the second trade',
    $q$ DELETE FROM trade WHERE trade_id = (SELECT trade_id FROM audit_deleted) $q$);
SELECT pg_temp.check('trg audit: DELETE writes 1 row: DELETE, OLD 2 @ 184.00',
    (SELECT count(*) = 1
            AND bool_and(a.operation = 'DELETE' AND a.shares = 2 AND a.price = 184.00
                         AND a.trade_date = '2024-01-03')
     FROM trade_audit a JOIN audit_deleted d ON a.trade_id = d.trade_id));

-- Portfolio delete: one DELETE row per trade, and they survive
SELECT pg_temp.expect_ok('trg audit: INSERT a third trade (1 @ 184.50 on 2024-01-03)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Alice Audit'), 'AAPL', 'BUY', 1, 184.50, '2024-01-03') $q$);
CREATE TEMP TABLE audit_cascaded AS
    SELECT trade_id FROM trade WHERE portfolio_id = pg_temp.pf('Alice Audit');
SELECT pg_temp.check('trg audit: portfolio has 2 trades before delete',
    (SELECT count(*) = 2 FROM audit_cascaded));
SELECT pg_temp.expect_ok('trg audit: delete portfolio Alice Audit',
    $q$ DELETE FROM portfolio WHERE portfolio_name = 'Alice Audit' $q$);
SELECT pg_temp.check('trg audit: cascade writes exactly 1 DELETE row per trade (2)',
    (SELECT count(*) = 2 AND count(DISTINCT a.trade_id) = 2
     FROM trade_audit a JOIN audit_cascaded c ON a.trade_id = c.trade_id
     WHERE a.operation = 'DELETE'));   -- the first trade also has its earlier UPDATE row
SELECT pg_temp.check('trg audit: all 4 audit rows survive the portfolio (no FK)',
    (SELECT count(*) = 4 FROM trade_audit a JOIN audit_ids s ON a.portfolio_id = s.pf_id)
    AND NOT EXISTS (SELECT 1 FROM portfolio p JOIN audit_ids s ON p.portfolio_id = s.pf_id));

-- TRUNCATE guard
SELECT pg_temp.expect_error('trg audit: TRUNCATE trade rejected',
    $q$ TRUNCATE trade $q$, 'trg_trade_no_truncate');
SELECT pg_temp.check('trg audit: trades still there after rejected TRUNCATE',
    EXISTS (SELECT 1 FROM trade));

-- =====================================================================
-- view v_cash_balance (db/views/01_v_cash_balance.sql)
-- Fictional stock CASHT (own price rows, so AAPL row counts used by
-- later tests are unchanged):
--   2024-01-02: low 180.00, high 190.00    2024-01-03: low 185.00, high 195.00
-- =====================================================================
SELECT pg_temp.expect_ok('view cash: setup stock CASHT, prices and 3 portfolios',
    $q$
    INSERT INTO stock (ticker, company_name) VALUES ('CASHT', 'Cash Test Corp');
    INSERT INTO daily_price VALUES
        ('CASHT', '2024-01-02', 185.00, 190.00, 180.00, 186.00, 1000),
        ('CASHT', '2024-01-03', 188.00, 195.00, 185.00, 190.00, 1000);
    INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date) VALUES
        (pg_temp.inv('alice@example.com'), 'Cash Empty',   25000.00, '2024-01-02'),
        (pg_temp.inv('alice@example.com'), 'Cash Example', 100000.00, '2024-01-02'),
        (pg_temp.inv('alice@example.com'), 'Cash Fanout',  50000.00, '2024-01-02');
    $q$);

-- No activity: balance = starting cash, parts are 0 (not NULL)
SELECT pg_temp.check('view cash: no activity -> cash_balance = starting_cash (25000.00)',
    (SELECT cash_balance = 25000.00 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Empty')));
SELECT pg_temp.check('view cash: no activity -> all 4 parts are 0, not NULL',
    (SELECT deposits = 0 AND withdrawals = 0 AND buys = 0 AND sells = 0
     FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Empty')));

-- Worked example: 100000 + 5000 - 2000 - 10*186.00 + 5*190.00 = 102090.00
SELECT pg_temp.expect_ok('view cash: setup example (deposit, withdrawal, BUY, SELL)',
    $q$
    INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date) VALUES
        (pg_temp.pf('Cash Example'), 'DEPOSIT',    5000.00, '2024-01-02'),
        (pg_temp.pf('Cash Example'), 'WITHDRAWAL', 2000.00, '2024-01-02');
    INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Cash Example'), 'CASHT', 'BUY',  10, 186.00, '2024-01-02'),
        (pg_temp.pf('Cash Example'), 'CASHT', 'SELL',  5, 190.00, '2024-01-03');
    $q$);
SELECT pg_temp.check('view cash: example -> parts 5000 / 2000 / 1860 / 950',
    (SELECT deposits = 5000.00 AND withdrawals = 2000.00 AND buys = 1860.00 AND sells = 950.00
     FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Example')));
SELECT pg_temp.check('view cash: example -> cash_balance = 102090.00',
    (SELECT cash_balance = 102090.00 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Example')));

-- Fan-out: 2 deposits x 3 trades. Correct: deposits 3000, buys 186+374 = 560,
-- sells 190, balance 50000 + 3000 - 560 + 190 = 52630.00
SELECT pg_temp.expect_ok('view cash: setup fan-out (2 deposits, 3 trades, no withdrawals)',
    $q$
    INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date) VALUES
        (pg_temp.pf('Cash Fanout'), 'DEPOSIT', 1000.00, '2024-01-02'),
        (pg_temp.pf('Cash Fanout'), 'DEPOSIT', 2000.00, '2024-01-02');
    INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Cash Fanout'), 'CASHT', 'BUY',  1, 186.00, '2024-01-02'),
        (pg_temp.pf('Cash Fanout'), 'CASHT', 'BUY',  2, 187.00, '2024-01-02'),
        (pg_temp.pf('Cash Fanout'), 'CASHT', 'SELL', 1, 190.00, '2024-01-03');
    $q$);
SELECT pg_temp.check('view cash: fan-out -> deposits 3000 (not x3 = 9000)',
    (SELECT deposits = 3000.00 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Fanout')));
SELECT pg_temp.check('view cash: fan-out -> buys 560, sells 190 (not x2)',
    (SELECT buys = 560.00 AND sells = 190.00
     FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Fanout')));
SELECT pg_temp.check('view cash: fan-out -> withdrawals 0 when only deposits exist (FILTER gives NULL)',
    (SELECT withdrawals = 0 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Fanout')));
SELECT pg_temp.check('view cash: fan-out -> cash_balance = 52630.00',
    (SELECT cash_balance = 52630.00 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Fanout')));
-- Demonstrates the bug the view avoids: joining the raw tables
SELECT pg_temp.check('view cash: (demo) naive raw join WOULD give deposits 9000, buys 1120',
    (SELECT SUM(c.amount) = 9000.00
            AND SUM(t.shares * t.price) FILTER (WHERE t.trade_type = 'BUY') = 1120.00
     FROM portfolio p
     JOIN cash_transaction c ON c.portfolio_id = p.portfolio_id
     JOIN trade t            ON t.portfolio_id = p.portfolio_id
     WHERE p.portfolio_name = 'Cash Fanout'));

-- Whole view: exactly one row per portfolio, never a NULL balance
SELECT pg_temp.check('view cash: one row per portfolio, no NULL cash_balance',
    (SELECT count(*) FROM v_cash_balance) = (SELECT count(*) FROM portfolio)
    AND (SELECT count(DISTINCT portfolio_id) FROM v_cash_balance) = (SELECT count(*) FROM portfolio)
    AND NOT EXISTS (SELECT 1 FROM v_cash_balance WHERE cash_balance IS NULL));
-- The view reflects later changes (it is computed on every read)
SELECT pg_temp.expect_ok('view cash: UPDATE a trade price (186.00 -> 185.00)',
    $q$ UPDATE trade SET price = 185.00
        WHERE portfolio_id = pg_temp.pf('Cash Example') AND trade_type = 'BUY' $q$);
SELECT pg_temp.check('view cash: balance follows the update (+10.00 -> 102100.00)',
    (SELECT cash_balance = 102100.00 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Cash Example')));

-- =====================================================================
-- balance and date-order triggers (db/programmability/04_balance_checks.sql)
-- Fictional stock BALT: low 90, high 200 on 2024-01-02 .. 2024-01-05,
-- so prices 100 and 186 are valid on every one of those days.
-- d1 = 01-02, d2 = 01-03, d3 = 01-04, d4 = 01-05
-- =====================================================================
SELECT pg_temp.expect_ok('bal: setup stock BALT, prices, portfolios, investor Carol',
    $q$
    INSERT INTO stock (ticker, company_name) VALUES ('BALT', 'Balance Test Corp');
    INSERT INTO daily_price
        SELECT 'BALT', d::date, 100, 200, 90, 150, 1000
        FROM generate_series('2024-01-02'::date, '2024-01-05'::date, '1 day') AS d;
    INSERT INTO investor (name, email) VALUES ('Carol', 'carol@example.com');
    INSERT INTO portfolio (investor_id, portfolio_name, starting_cash, start_date)
    SELECT i.investor_id, v.name, v.cash, v.start::date
    FROM (VALUES ('alice@example.com', 'Bal Cash',     10000, '2024-01-02'),
                 ('alice@example.com', 'Bal Shares',   10000, '2024-01-02'),
                 ('alice@example.com', 'Bal Withdraw',  1000, '2024-01-02'),
                 ('alice@example.com', 'Bal Dates',    10000, '2024-01-03'),
                 ('alice@example.com', 'Bal SameDay',   1000, '2024-01-02'),
                 ('alice@example.com', 'Bal Delete',    1000, '2024-01-02'),
                 ('alice@example.com', 'Bal Update',    1000, '2024-01-02'),
                 ('alice@example.com', 'Bal Cascade',  10000, '2024-01-02'),
                 ('carol@example.com', 'Carol Main',   10000, '2024-01-02'))
         AS v(email, name, cash, start)
    JOIN investor i ON i.email = v.email;
    $q$);

-- Not enough cash for a BUY -------------------------------------------
SELECT pg_temp.expect_error('bal cash: start 10000, BUY 100 @ 186 (18600) rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Cash'), 'BALT', 'BUY', 100, 186, '2024-01-02') $q$,
    'trg_cash_never_negative');
SELECT pg_temp.check('bal cash: DETAIL says "Cash would be -8600.00 on 2024-01-02"',
    pg_temp.error_detail(
        $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
            VALUES (pg_temp.pf('Bal Cash'), 'BALT', 'BUY', 100, 186, '2024-01-02') $q$)
    LIKE 'Cash would be -8600.00 on 2024-01-02, after trade % (BUY 100 BALT @ 186.00).');
SELECT pg_temp.check('bal cash: rejected BUY left no trade row',
    NOT EXISTS (SELECT 1 FROM trade WHERE portfolio_id = pg_temp.pf('Bal Cash')));
SELECT pg_temp.expect_ok('bal cash: BUY 50 @ 200 = all 10000 allowed (cash 0)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Cash'), 'BALT', 'BUY', 50, 200, '2024-01-02') $q$);
SELECT pg_temp.check('bal cash: view shows cash_balance 0.00',
    (SELECT cash_balance = 0 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Bal Cash')));

-- Not enough shares for a SELL ----------------------------------------
SELECT pg_temp.expect_ok('bal shares: BUY 10 @ 100 on d1',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Shares'), 'BALT', 'BUY', 10, 100, '2024-01-02') $q$);
SELECT pg_temp.expect_error('bal shares: SELL 11 (holding 10) rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Shares'), 'BALT', 'SELL', 11, 100, '2024-01-03') $q$,
    'trg_shares_never_negative');
SELECT pg_temp.check('bal shares: DETAIL says "BALT shares would be -1 on 2024-01-03"',
    pg_temp.error_detail(
        $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
            VALUES (pg_temp.pf('Bal Shares'), 'BALT', 'SELL', 11, 100, '2024-01-03') $q$)
    LIKE 'BALT shares would be -1 on 2024-01-03, after trade % (SELL 11 BALT @ 100.00).');
SELECT pg_temp.expect_ok('bal shares: SELL exactly all 10 allowed',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Shares'), 'BALT', 'SELL', 10, 100, '2024-01-03') $q$);
SELECT pg_temp.expect_error('bal shares: SELL 1 more (holding 0) rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Shares'), 'BALT', 'SELL', 1, 100, '2024-01-03') $q$,
    'trg_shares_never_negative');
SELECT pg_temp.expect_error('bal shares: SELL a ticker never bought (AAPL) rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Shares'), 'AAPL', 'SELL', 1, 184, '2024-01-03') $q$,
    'trg_shares_never_negative');

-- Withdrawals ----------------------------------------------------------
SELECT pg_temp.expect_error('bal withdraw: WITHDRAWAL 1000.01 (cash 1000) rejected',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Withdraw'), 'WITHDRAWAL', 1000.01, '2024-01-02') $q$,
    'trg_cash_never_negative');
SELECT pg_temp.expect_ok('bal withdraw: WITHDRAWAL = cash (1000) allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Withdraw'), 'WITHDRAWAL', 1000, '2024-01-02') $q$);
SELECT pg_temp.check('bal withdraw: view shows cash_balance 0.00',
    (SELECT cash_balance = 0 FROM v_cash_balance WHERE portfolio_id = pg_temp.pf('Bal Withdraw')));

-- Date order (Bal Dates starts on d2 = 2024-01-03) ----------------------
SELECT pg_temp.expect_error('bal dates: trade before start_date rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Dates'), 'BALT', 'BUY', 1, 100, '2024-01-02') $q$,
    'trg_date_before_start');
SELECT pg_temp.expect_error('bal dates: cash transaction before start_date rejected',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Dates'), 'DEPOSIT', 1, '2024-01-02') $q$,
    'trg_date_before_start');
SELECT pg_temp.expect_ok('bal dates: trade on start_date allowed',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Dates'), 'BALT', 'BUY', 1, 100, '2024-01-03') $q$);
SELECT pg_temp.expect_ok('bal dates: trade on d3 allowed (latest is now d3)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Dates'), 'BALT', 'BUY', 1, 100, '2024-01-04') $q$);
SELECT pg_temp.expect_error('bal dates: trade before the latest event rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Dates'), 'BALT', 'BUY', 1, 100, '2024-01-03') $q$,
    'trg_date_before_latest');
SELECT pg_temp.expect_error('bal dates: cash transaction before the latest trade rejected',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Dates'), 'DEPOSIT', 1, '2024-01-03') $q$,
    'trg_date_before_latest');
SELECT pg_temp.expect_ok('bal dates: trade on the same date as the latest allowed',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal Dates'), 'BALT', 'BUY', 1, 100, '2024-01-04') $q$);
SELECT pg_temp.expect_ok('bal dates: cash transaction on the same date as the latest allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Dates'), 'DEPOSIT', 1, '2024-01-04') $q$);
SELECT pg_temp.expect_error('bal dates: cash transaction dated tomorrow rejected',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Dates'), 'DEPOSIT', 1, CURRENT_DATE + 1) $q$,
    'trg_cash_txn_future_date');
SELECT pg_temp.expect_ok('bal dates: cash transaction dated today allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal Dates'), 'DEPOSIT', 1, CURRENT_DATE) $q$);
SELECT pg_temp.expect_error('bal dates: multi-row INSERT out of order rejected (row 2 sees row 1)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Bal Cascade'), 'BALT', 'BUY', 1, 100, '2024-01-04'),
        (pg_temp.pf('Bal Cascade'), 'BALT', 'BUY', 1, 100, '2024-01-03') $q$,
    'trg_date_before_latest');

-- Same day: cash transactions before trades -----------------------------
SELECT pg_temp.expect_error('bal same day: BUY 15 @ 100 on d2 with cash 1000 rejected',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'BALT', 'BUY', 15, 100, '2024-01-03') $q$,
    'trg_cash_never_negative');
SELECT pg_temp.expect_ok('bal same day: DEPOSIT 1000 on d2',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'DEPOSIT', 1000, '2024-01-03') $q$);
SELECT pg_temp.expect_ok('bal same day: same BUY on d2 now allowed (deposit counts first)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'BALT', 'BUY', 15, 100, '2024-01-03') $q$);
SELECT pg_temp.expect_ok('bal same day: SELL 15 @ 100 on d3 (cash 500 -> 2000)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'BALT', 'SELL', 15, 100, '2024-01-04') $q$);
-- Consequence of the ordering rule: a WITHDRAWAL on d3 is replayed BEFORE
-- d3's SELL, even though it was entered after it, so it can't use the
-- SELL's proceeds (cash at that point is 500).
SELECT pg_temp.expect_error('bal same day: WITHDRAWAL 2000 on d3 rejected (counts before the d3 SELL)',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'WITHDRAWAL', 2000, '2024-01-04') $q$,
    'trg_cash_never_negative');
SELECT pg_temp.expect_ok('bal same day: WITHDRAWAL 500 on d3 allowed',
    $q$ INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date)
        VALUES (pg_temp.pf('Bal SameDay'), 'WITHDRAWAL', 500, '2024-01-04') $q$);

-- Delete in the middle of the history ------------------------------------
-- start 1000; d1 BUY 5 @ 100 (cash 500); d2 SELL 5 @ 100 (cash 1000);
-- d3 BUY 9 @ 100 (cash 100). Without the d2 SELL, d3 cash = 500 - 900 = -400.
SELECT pg_temp.expect_ok('bal delete: setup d1 BUY 5, d2 SELL 5, d3 BUY 9 (all @ 100)',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Bal Delete'), 'BALT', 'BUY',  5, 100, '2024-01-02'),
        (pg_temp.pf('Bal Delete'), 'BALT', 'SELL', 5, 100, '2024-01-03'),
        (pg_temp.pf('Bal Delete'), 'BALT', 'BUY',  9, 100, '2024-01-04') $q$);
SELECT pg_temp.expect_error('bal delete: deleting the d2 SELL rejected (d3 cash -400)',
    $q$ DELETE FROM trade WHERE portfolio_id = pg_temp.pf('Bal Delete')
        AND trade_type = 'SELL' $q$,
    'trg_cash_never_negative');
SELECT pg_temp.check('bal delete: DETAIL says "Cash would be -400.00 on 2024-01-04"',
    pg_temp.error_detail(
        $q$ DELETE FROM trade WHERE portfolio_id = pg_temp.pf('Bal Delete')
            AND trade_type = 'SELL' $q$)
    LIKE 'Cash would be -400.00 on 2024-01-04, after trade % (BUY 9 BALT @ 100.00).');
SELECT pg_temp.expect_error('bal delete: deleting the d1 BUY rejected (d2 SELL has no shares)',
    $q$ DELETE FROM trade WHERE portfolio_id = pg_temp.pf('Bal Delete')
        AND trade_date = '2024-01-02' $q$,
    'trg_shares_never_negative');
SELECT pg_temp.check('bal delete: all 3 trades still there',
    (SELECT count(*) = 3 FROM trade WHERE portfolio_id = pg_temp.pf('Bal Delete')));
SELECT pg_temp.check('bal delete: rejected DELETEs wrote NO trade_audit rows',
    NOT EXISTS (SELECT 1 FROM trade_audit WHERE portfolio_id = pg_temp.pf('Bal Delete')));
SELECT pg_temp.expect_ok('bal delete: deleting the d3 BUY (last event) allowed',
    $q$ DELETE FROM trade WHERE portfolio_id = pg_temp.pf('Bal Delete')
        AND trade_date = '2024-01-04' $q$);
SELECT pg_temp.check('bal delete: allowed DELETE wrote 1 audit row',
    (SELECT count(*) = 1 FROM trade_audit
     WHERE portfolio_id = pg_temp.pf('Bal Delete') AND operation = 'DELETE'));

-- Update in the middle of the history ------------------------------------
-- start 1000; d1 BUY 10 @ 100 (cash 0); d2 SELL 10 @ 100 (cash 1000)
SELECT pg_temp.expect_ok('bal update: setup d1 BUY 10 @ 100, d2 SELL 10 @ 100',
    $q$ INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Bal Update'), 'BALT', 'BUY',  10, 100, '2024-01-02'),
        (pg_temp.pf('Bal Update'), 'BALT', 'SELL', 10, 100, '2024-01-03') $q$);
SELECT pg_temp.expect_error('bal update: BUY 10 -> 5 shares rejected (d2 SELL 10 > 5 held)',
    $q$ UPDATE trade SET shares = 5
        WHERE portfolio_id = pg_temp.pf('Bal Update') AND trade_type = 'BUY' $q$,
    'trg_shares_never_negative');
SELECT pg_temp.expect_error('bal update: BUY price 100 -> 101 rejected (d1 cash -10)',
    $q$ UPDATE trade SET price = 101
        WHERE portfolio_id = pg_temp.pf('Bal Update') AND trade_type = 'BUY' $q$,
    'trg_cash_never_negative');
SELECT pg_temp.check('bal update: DETAIL says "Cash would be -10.00 on 2024-01-02"',
    pg_temp.error_detail(
        $q$ UPDATE trade SET price = 101
            WHERE portfolio_id = pg_temp.pf('Bal Update') AND trade_type = 'BUY' $q$)
    LIKE 'Cash would be -10.00 on 2024-01-02, %');
SELECT pg_temp.expect_error('bal update: SELL 10 -> 11 shares rejected',
    $q$ UPDATE trade SET shares = 11
        WHERE portfolio_id = pg_temp.pf('Bal Update') AND trade_type = 'SELL' $q$,
    'trg_shares_never_negative');
SELECT pg_temp.check('bal update: rejected UPDATEs wrote NO trade_audit rows',
    NOT EXISTS (SELECT 1 FROM trade_audit WHERE portfolio_id = pg_temp.pf('Bal Update')));
SELECT pg_temp.check('bal update: trades unchanged (BUY 10 @ 100, SELL 10 @ 100)',
    (SELECT bool_and(shares = 10 AND price = 100) AND count(*) = 2
     FROM trade WHERE portfolio_id = pg_temp.pf('Bal Update')));
SELECT pg_temp.expect_ok('bal update: SELL 10 -> 9 shares allowed',
    $q$ UPDATE trade SET shares = 9
        WHERE portfolio_id = pg_temp.pf('Bal Update') AND trade_type = 'SELL' $q$);
SELECT pg_temp.check('bal update: allowed UPDATE wrote 1 audit row (OLD shares 10)',
    (SELECT count(*) = 1 AND bool_and(operation = 'UPDATE' AND shares = 10)
     FROM trade_audit WHERE portfolio_id = pg_temp.pf('Bal Update')));

-- Cascades still work ------------------------------------------------------
-- During a cascade the portfolio row is already deleted, so the AFTER
-- trigger finds nothing to lock and skips the replay (deleting the BUY
-- before the SELL must not be reported as "shares < 0").
SELECT pg_temp.expect_ok('bal cascade: setup deposit, BUY 10, SELL 10 (and same for Carol)',
    $q$
    INSERT INTO cash_transaction (portfolio_id, txn_type, amount, txn_date) VALUES
        (pg_temp.pf('Bal Cascade'), 'DEPOSIT', 500, '2024-01-02'),
        (pg_temp.pf('Carol Main'),  'DEPOSIT', 500, '2024-01-02');
    INSERT INTO trade (portfolio_id, ticker, trade_type, shares, price, trade_date) VALUES
        (pg_temp.pf('Bal Cascade'), 'BALT', 'BUY',  10, 100, '2024-01-02'),
        (pg_temp.pf('Bal Cascade'), 'BALT', 'SELL', 10, 100, '2024-01-03'),
        (pg_temp.pf('Carol Main'),  'BALT', 'BUY',  10, 100, '2024-01-02'),
        (pg_temp.pf('Carol Main'),  'BALT', 'SELL', 10, 100, '2024-01-03');
    $q$);
CREATE TEMP TABLE bal_ids AS
    SELECT pg_temp.pf('Bal Cascade') AS cascade_pf,
           pg_temp.pf('Carol Main')  AS carol_pf,
           pg_temp.inv('carol@example.com') AS carol_id;
SELECT pg_temp.expect_ok('bal cascade: delete portfolio Bal Cascade',
    $q$ DELETE FROM portfolio WHERE portfolio_name = 'Bal Cascade' $q$);
SELECT pg_temp.check('bal cascade:   -> its trades and cash transactions are gone',
    NOT EXISTS (SELECT 1 FROM trade t JOIN bal_ids b ON t.portfolio_id = b.cascade_pf)
    AND NOT EXISTS (SELECT 1 FROM cash_transaction c JOIN bal_ids b ON c.portfolio_id = b.cascade_pf));
SELECT pg_temp.check('bal cascade:   -> 2 DELETE audit rows written',
    (SELECT count(*) = 2 FROM trade_audit a JOIN bal_ids b ON a.portfolio_id = b.cascade_pf
     WHERE a.operation = 'DELETE'));
SELECT pg_temp.expect_ok('bal cascade: delete investor Carol',
    $q$ DELETE FROM investor WHERE email = 'carol@example.com' $q$);
SELECT pg_temp.check('bal cascade:   -> Carol''s portfolio, trades and cash are gone',
    NOT EXISTS (SELECT 1 FROM portfolio p JOIN bal_ids b ON p.investor_id = b.carol_id)
    AND NOT EXISTS (SELECT 1 FROM trade t JOIN bal_ids b ON t.portfolio_id = b.carol_pf)
    AND NOT EXISTS (SELECT 1 FROM cash_transaction c JOIN bal_ids b ON c.portfolio_id = b.carol_pf));

-- Cross-check: replay and view agree ---------------------------------------
SELECT pg_temp.check('bal history: last cash_after = v_cash_balance.cash_balance for every portfolio',
    NOT EXISTS (
        SELECT 1
        FROM v_cash_balance v
        CROSS JOIN LATERAL (
            SELECT h.cash_after FROM fn_portfolio_history(v.portfolio_id) h
            ORDER BY h.event_date DESC, h.event_order DESC, h.event_id DESC LIMIT 1
        ) last
        WHERE last.cash_after <> v.cash_balance));
SELECT pg_temp.check('bal history: Bal SameDay history in order (cash before trades on d2)',
    (SELECT array_agg(event_label ~ '^cash' ORDER BY event_date, event_order, event_id)
            = ARRAY[true, false, true, false]
     FROM fn_portfolio_history(pg_temp.pf('Bal SameDay'))));

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
-- Manual rows use fake ids (-98) so they don't mix with rows the
-- audit trigger writes for real portfolios.
SELECT pg_temp.expect_ok('trade_audit: valid UPDATE and DELETE snapshots (manual insert)',
    $q$ INSERT INTO trade_audit (operation, trade_id, portfolio_id, ticker, trade_type,
                                 shares, price, trade_date) VALUES
        ('UPDATE', -1, -98, 'AAPL', 'BUY', 10, 185, '2024-01-02'),
        ('DELETE', -2, -98, 'AAPL', 'SELL', 5, 184, '2024-01-03') $q$);
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
CREATE TEMP TABLE audit_before_rename AS
    SELECT COALESCE(max(audit_id), 0) AS max_id FROM trade_audit;
SELECT pg_temp.expect_ok('stock: rename ticker AAPL -> AAPLX',
    $q$ UPDATE stock SET ticker = 'AAPLX' WHERE ticker = 'AAPL' $q$);
SELECT pg_temp.check('  -> daily_price follows rename (2 rows)',
    (SELECT count(*) = 2 FROM daily_price WHERE ticker = 'AAPLX')
    AND NOT EXISTS (SELECT 1 FROM daily_price WHERE ticker = 'AAPL'));
SELECT pg_temp.check('  -> trade follows rename via daily_price (2 rows; trigger allows it)',
    (SELECT count(*) = 2 FROM trade WHERE ticker = 'AAPLX')
    AND NOT EXISTS (SELECT 1 FROM trade WHERE ticker = 'AAPL'));
SELECT pg_temp.check('  -> watchlist_item follows rename',
    EXISTS (SELECT 1 FROM watchlist_item WHERE ticker = 'AAPLX'));
SELECT pg_temp.check('  -> rename audited: 2 new UPDATE rows keeping the OLD ticker AAPL',
    (SELECT count(*) = 2 AND bool_and(a.operation = 'UPDATE' AND a.ticker = 'AAPL')
     FROM trade_audit a, audit_before_rename b
     WHERE a.audit_id > b.max_id));

-- watchlist -> watchlist_item CASCADE
SELECT pg_temp.expect_ok('watchlist: delete Bob Watch',
    $q$ DELETE FROM watchlist WHERE watchlist_name = 'Bob Watch' $q$);
SELECT pg_temp.check('  -> its items cascaded away; Alice''s items remain',
    (SELECT count(*) FROM watchlist_item) = 2);

-- portfolio -> trade / cash_transaction CASCADE; audit survives
CREATE TEMP TABLE saved_ids AS
    SELECT pg_temp.pf('Alice Growth') AS alice_pf,
           pg_temp.pf('Bob Growth')   AS bob_pf,
           pg_temp.inv('bob@example.com') AS bob_id;
SELECT pg_temp.expect_ok('portfolio: delete Alice Growth',
    $q$ DELETE FROM portfolio WHERE portfolio_name = 'Alice Growth' $q$);
SELECT pg_temp.check('  -> its trades cascaded away',
    NOT EXISTS (SELECT 1 FROM trade t JOIN saved_ids s ON t.portfolio_id = s.alice_pf));
SELECT pg_temp.check('  -> its cash transactions cascaded away (trg cash allows cascade)',
    NOT EXISTS (SELECT 1 FROM cash_transaction c JOIN saved_ids s ON c.portfolio_id = s.alice_pf));
SELECT pg_temp.check('  -> 1 DELETE audit row per cascaded trade (2), kept (no FK)',
    (SELECT count(*) = 2 FROM trade_audit a JOIN saved_ids s ON a.portfolio_id = s.alice_pf
     WHERE a.operation = 'DELETE'));
SELECT pg_temp.expect_ok('stock AAPLX: delete allowed once its trades are gone',
    $q$ DELETE FROM stock WHERE ticker = 'AAPLX' $q$);

-- investor -> portfolio / watchlist CASCADE (and onward to trades)
SELECT pg_temp.expect_ok('investor: delete Bob',
    $q$ DELETE FROM investor WHERE email = 'bob@example.com' $q$);
SELECT pg_temp.check('  -> Bob''s portfolios cascaded away',
    NOT EXISTS (SELECT 1 FROM portfolio p JOIN saved_ids s ON p.investor_id = s.bob_id));
SELECT pg_temp.check('  -> Bob''s cash transactions cascaded away (investor -> portfolio -> cash; trg cash allows it)',
    NOT EXISTS (SELECT 1 FROM cash_transaction c JOIN saved_ids s ON c.portfolio_id = s.bob_pf));
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
