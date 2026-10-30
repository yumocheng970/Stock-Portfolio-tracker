-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Part 1: reference & market-data tables
-- Target: PostgreSQL 14+
-- =====================================================================

-- Dev convenience: lets you re-run this file while testing.
DROP TABLE IF EXISTS daily_price, stock, investor, exchange, sector CASCADE;

-- ---------------------------------------------------------------------
-- sector: lookup table (Technology, Healthcare, ...)
-- ---------------------------------------------------------------------
CREATE TABLE sector (
    sector_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sector_name  VARCHAR(50) NOT NULL,
    CONSTRAINT uq_sector_name            UNIQUE (sector_name),
    CONSTRAINT chk_sector_name_not_blank CHECK (btrim(sector_name) <> '')
);

-- ---------------------------------------------------------------------
-- exchange: lookup table (NASDAQ, NYSE, ...)
-- ---------------------------------------------------------------------
CREATE TABLE exchange (
    exchange_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exchange_name  VARCHAR(50) NOT NULL,
    CONSTRAINT uq_exchange_name            UNIQUE (exchange_name),
    CONSTRAINT chk_exchange_name_not_blank CHECK (btrim(exchange_name) <> '')
);

-- ---------------------------------------------------------------------
-- investor
-- ---------------------------------------------------------------------
CREATE TABLE investor (
    investor_id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    email         VARCHAR(254) NOT NULL,
    created_date  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_investor_name_not_blank CHECK (btrim(name) <> ''),
    -- Basic shape check only: something@something.something, no spaces
    CONSTRAINT chk_investor_email_format
        CHECK (email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')
);

-- Case-insensitive uniqueness: 'Yumo@x.com' and 'yumo@x.com' collide.
-- A plain UNIQUE(email) would treat them as different, so we use an
-- expression index instead. It also speeds up login-style lookups
-- written as WHERE LOWER(email) = LOWER(%s).
CREATE UNIQUE INDEX uq_investor_email_lower ON investor (LOWER(email));

-- ---------------------------------------------------------------------
-- stock: one row per ticker. The S&P 500 (^GSPC) is a row with
-- security_type = 'INDEX' and no sector/exchange.
-- ---------------------------------------------------------------------
CREATE TABLE stock (
    ticker         VARCHAR(10)  PRIMARY KEY,
    company_name   VARCHAR(100) NOT NULL,
    security_type  VARCHAR(5)   NOT NULL DEFAULT 'STOCK',
    sector_id      INTEGER,                 -- nullable (index has none)
    exchange_id    INTEGER,                 -- nullable (index has none)

    -- Uppercase letters/digits/dot/hyphen, optional leading ^ for indexes
    -- e.g. AAPL, BRK-B, ^GSPC
    CONSTRAINT chk_stock_ticker_format
        CHECK (ticker ~ '^\^?[A-Z0-9.-]{1,9}$'),
    CONSTRAINT chk_stock_company_not_blank
        CHECK (btrim(company_name) <> ''),
    CONSTRAINT chk_stock_security_type
        CHECK (security_type IN ('STOCK', 'INDEX')),
    -- An index must not have a sector or exchange
    CONSTRAINT chk_stock_index_unclassified
        CHECK (security_type = 'STOCK'
               OR (sector_id IS NULL AND exchange_id IS NULL)),

    -- RESTRICT: can't delete a sector/exchange that stocks still use.
    -- No ON UPDATE clause: identity keys are never updated.
    CONSTRAINT fk_stock_sector FOREIGN KEY (sector_id)
        REFERENCES sector (sector_id) ON DELETE RESTRICT,
    CONSTRAINT fk_stock_exchange FOREIGN KEY (exchange_id)
        REFERENCES exchange (exchange_id) ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------
-- daily_price: weak entity of stock, identified by (ticker, price_date)
-- Prices rounded to 2 decimals on load (rounding keeps low <= open etc.)
-- ---------------------------------------------------------------------
CREATE TABLE daily_price (
    ticker      VARCHAR(10)   NOT NULL,
    price_date  DATE          NOT NULL,
    open        NUMERIC(12,2) NOT NULL,
    high        NUMERIC(12,2) NOT NULL,
    low         NUMERIC(12,2) NOT NULL,
    close       NUMERIC(12,2) NOT NULL,
    volume      BIGINT        NOT NULL,

    CONSTRAINT pk_daily_price PRIMARY KEY (ticker, price_date),

    -- Weak entity: prices die with their stock.
    -- ON UPDATE CASCADE: handles ticker renames (e.g. FB -> META).
    CONSTRAINT fk_daily_price_stock FOREIGN KEY (ticker)
        REFERENCES stock (ticker) ON DELETE CASCADE ON UPDATE CASCADE,

    CONSTRAINT chk_daily_price_positive CHECK (low > 0),
    -- low is the minimum and high is the maximum of the day
    CONSTRAINT chk_daily_price_range
        CHECK (low <= open AND low <= close AND high >= open AND high >= close),
    CONSTRAINT chk_daily_price_volume CHECK (volume >= 0)
);
