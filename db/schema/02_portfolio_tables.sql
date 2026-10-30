-- =====================================================================
-- Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
-- Part 2: portfolio, cash, trades, watchlists, audit
-- Run AFTER 01_reference_tables.sql
-- =====================================================================

DROP TABLE IF EXISTS trade_audit, watchlist_item, watchlist,
                     trade, cash_transaction, portfolio CASCADE;

-- ---------------------------------------------------------------------
-- portfolio: one investor has many portfolios
-- start_date   = simulation start (when starting cash becomes available)
-- created_date = real-world time the row was created
-- ---------------------------------------------------------------------
CREATE TABLE portfolio (
    portfolio_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id     INTEGER       NOT NULL,
    portfolio_name  VARCHAR(100)  NOT NULL,
    starting_cash   NUMERIC(14,2) NOT NULL,
    start_date      DATE          NOT NULL,
    created_date    TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT chk_portfolio_name_not_blank CHECK (btrim(portfolio_name) <> ''),
    CONSTRAINT chk_portfolio_starting_cash
        CHECK (starting_cash > 0 AND starting_cash <= 10000000),
    -- Names unique per investor (two investors may both have "Growth")
    CONSTRAINT uq_portfolio_investor_name UNIQUE (investor_id, portfolio_name),

    CONSTRAINT fk_portfolio_investor FOREIGN KEY (investor_id)
        REFERENCES investor (investor_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- cash_transaction: deposits/withdrawals after the starting cash.
-- Insert-only (update/delete blocked by trigger in a later step).
-- ---------------------------------------------------------------------
CREATE TABLE cash_transaction (
    cash_txn_id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_id  INTEGER       NOT NULL,
    txn_type      VARCHAR(10)   NOT NULL,
    amount        NUMERIC(14,2) NOT NULL,
    txn_date      DATE          NOT NULL,

    CONSTRAINT chk_cash_txn_type CHECK (txn_type IN ('DEPOSIT', 'WITHDRAWAL')),
    -- Amount is always positive; txn_type gives the direction
    CONSTRAINT chk_cash_amount_positive CHECK (amount > 0),
    -- Per-transaction cap applies to deposits only. Withdrawals are
    -- limited by the cash balance instead (checked by trigger later).
    CONSTRAINT chk_cash_deposit_cap
        CHECK (txn_type <> 'DEPOSIT' OR amount <= 10000000),

    CONSTRAINT fk_cash_portfolio FOREIGN KEY (portfolio_id)
        REFERENCES portfolio (portfolio_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- trade: BUY/SELL of whole shares at a historical price.
-- FK (ticker, trade_date) -> daily_price guarantees the stock exists
-- AND has price data on that day (declarative "trading day" rule).
-- Price-within-range and "no INDEX trading" need other tables' columns,
-- so they are enforced by a trigger in a later step.
-- ---------------------------------------------------------------------
CREATE TABLE trade (
    trade_id      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_id  INTEGER       NOT NULL,
    ticker        VARCHAR(10)   NOT NULL,
    trade_type    VARCHAR(4)    NOT NULL,
    shares        INTEGER       NOT NULL,
    price         NUMERIC(12,2) NOT NULL,
    trade_date    DATE          NOT NULL,

    CONSTRAINT chk_trade_type   CHECK (trade_type IN ('BUY', 'SELL')),
    CONSTRAINT chk_trade_shares CHECK (shares > 0),          -- whole shares
    CONSTRAINT chk_trade_price  CHECK (price > 0),

    CONSTRAINT fk_trade_portfolio FOREIGN KEY (portfolio_id)
        REFERENCES portfolio (portfolio_id) ON DELETE CASCADE,
    -- RESTRICT: price rows used by a trade can't be deleted, so a stock
    -- with trades can't be deleted either (stock -> daily_price cascade
    -- is blocked here). ON UPDATE CASCADE follows ticker renames.
    CONSTRAINT fk_trade_daily_price FOREIGN KEY (ticker, trade_date)
        REFERENCES daily_price (ticker, price_date)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------
-- watchlist: one investor has many watchlists
-- ---------------------------------------------------------------------
CREATE TABLE watchlist (
    watchlist_id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id     INTEGER      NOT NULL,
    watchlist_name  VARCHAR(100) NOT NULL,
    created_date    TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_watchlist_name_not_blank CHECK (btrim(watchlist_name) <> ''),
    CONSTRAINT uq_watchlist_investor_name UNIQUE (investor_id, watchlist_name),

    CONSTRAINT fk_watchlist_investor FOREIGN KEY (investor_id)
        REFERENCES investor (investor_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- watchlist_item: M:N between watchlist and stock
-- ---------------------------------------------------------------------
CREATE TABLE watchlist_item (
    watchlist_id  INTEGER       NOT NULL,
    ticker        VARCHAR(10)   NOT NULL,
    added_date    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    target_price  NUMERIC(12,2),            -- optional

    CONSTRAINT pk_watchlist_item PRIMARY KEY (watchlist_id, ticker),
    -- NULL passes a CHECK automatically, so no "IS NULL OR" needed
    CONSTRAINT chk_watchlist_target_positive CHECK (target_price > 0),

    CONSTRAINT fk_watchlist_item_watchlist FOREIGN KEY (watchlist_id)
        REFERENCES watchlist (watchlist_id) ON DELETE CASCADE,
    CONSTRAINT fk_watchlist_item_stock FOREIGN KEY (ticker)
        REFERENCES stock (ticker) ON DELETE CASCADE ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------
-- trade_audit: OLD version of a trade, written by trigger on
-- UPDATE/DELETE. No FKs on purpose: the trade (or whole portfolio)
-- may no longer exist, and history must survive that.
-- ---------------------------------------------------------------------
CREATE TABLE trade_audit (
    audit_id      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    operation     VARCHAR(6)    NOT NULL,
    changed_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    changed_by    TEXT          NOT NULL DEFAULT current_user,
    -- snapshot of the old row
    trade_id      INTEGER       NOT NULL,
    portfolio_id  INTEGER       NOT NULL,
    ticker        VARCHAR(10)   NOT NULL,
    trade_type    VARCHAR(4)    NOT NULL,
    shares        INTEGER       NOT NULL,
    price         NUMERIC(12,2) NOT NULL,
    trade_date    DATE          NOT NULL,

    CONSTRAINT chk_trade_audit_operation CHECK (operation IN ('UPDATE', 'DELETE'))
);

-- ---------------------------------------------------------------------
-- Secondary indexes (bonus)
-- PostgreSQL does NOT auto-index foreign key columns.
-- ---------------------------------------------------------------------

-- Every cash-balance / holdings calculation and every history replay
-- reads one portfolio's trades in date order. This index serves the
-- filter (portfolio_id) and the sort (trade_date, trade_id) together.
CREATE INDEX idx_trade_portfolio_date
    ON trade (portfolio_id, trade_date, trade_id);

-- Same access pattern for cash transactions.
CREATE INDEX idx_cash_portfolio_date
    ON cash_transaction (portfolio_id, txn_date, cash_txn_id);

-- Not indexed on purpose: trade (ticker, trade_date). It would only
-- speed up deletes on daily_price, which never happen (insert-only).
