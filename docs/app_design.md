# Python CLI app: design (Task 4)

A numbered-menu terminal app on top of the PostgreSQL database. Run it from the repo root:
`make run` (real database) or `make run-test-db` (test database).

## 1. Layers / 分层

```
menus (app/menus/*.py)   what the user sees: numbered menus, prompts, tables. NO SQL.
   │  calls
data_access.py           ALL SQL. One function per action, each in its own transaction.
   │  psycopg
PostgreSQL               ALL business rules: CHECK / FK / UNIQUE constraints, triggers,
                         execute_trade(), record_cash_transaction()
```
Side modules:
- `errors.py` turns a database error into a friendly message, by constraint or trigger name.
- `inputs.py` asks for input and re-asks while the input is invalid; it also does typed confirmations.
- `menu.py` is the reusable numbered menu.
- `display.py` prints tables with tabulate.
- `session.py` holds the current state (the connection and the chosen investor).

**Rules**
- **Rules live only in the database.** The app checks only the *shape* of input (not empty, a number, not too long). Whether an email is valid, cash is enough or a date is allowed is decided by the database. The app shows the database's error as a friendly message. So a rule is never written twice, and the two versions can never disagree.
- **Every database action is one transaction** (`with conn.transaction():`). On error it is rolled back, the friendly message is shown and the user is back at the menu. No raw traceback for database errors.
- **Errors are mapped by name.** Every constraint and trigger error has a name (`chk_…`, `fk_…`, `uq_…`, `trg_…`, `exec_…`). `errors.MESSAGES` has a message for every name in the database, and a test reads the catalog, so a new constraint without a message fails the tests.
- **Deletes need a typed confirmation.** The user types the record's email or name, not "y". Before asking, the app shows what the delete will cascade to.

## 2. CRUD matrix

C = create, R = read, U = update, D = delete. "—" = not offered, on purpose.

| Table | C | R | U | D | Notes |
|---|---|---|---|---|---|
| investor | ✓ | ✓ | name, email | ✓ typed confirmation | Delete cascades to portfolios, trades, cash transactions and watchlists (trades are kept in trade_audit). |
| portfolio | ✓ | ✓ | rename | ✓ typed confirmation | Starting cash and start date are fixed once created. |
| trade | ✓ via `CALL execute_trade()` | ✓ | shares, price | ✓ | Every U/D is replayed by the balance triggers and copied to trade_audit. Extra: **restore a deleted trade** from trade_audit. |
| cash_transaction | ✓ via `CALL record_cash_transaction()` | ✓ | — | — | **By design.** `trg_cash_txn_immutable` makes the ledger append-only, like accounting: a mistake is fixed with an opposite transaction (a wrong deposit → a withdrawal of the same amount). The app explains this when asked. |
| watchlist | ✓ | ✓ | rename | ✓ | Delete cascades to its items. |
| watchlist_item | ✓ | ✓ | target price | ✓ | ^GSPC may be watched (only trading an INDEX is blocked). |
| stock | ✓ admin (also downloads its prices) | ✓ | company name, sector | ✓ only if it has no trades | `fk_trade_daily_price` RESTRICT blocks deleting a traded stock. |
| sector, exchange | — | ✓ | — | — | Lookup tables. |
| daily_price | ✓ refresh (insert-only loader) | ✓ price history | — | — | Prices are facts from Yahoo; never edited by hand. |
| trade_audit | — | ✓ | — | — | Written only by the trigger. |

## 3. Menu tree

```
Main
├─ 1 Choose / create investor          (acts as login, no password)
│   ├─ 1 List investors
│   ├─ 2 Create investor               (then chosen automatically)
│   ├─ 3 Choose investor  ──►  Investor home: <name>
│   │                            ├─ 1 Portfolios        (App 2)
│   │                            ├─ 2 Watchlists        (App 4)
│   │                            ├─ 3 Profile: view / edit name / edit email / delete
│   │                            └─ 0 Back
│   └─ 0 Back
├─ 2 Market data                       (App 6: price history, refresh prices)
├─ 3 Admin                             (App 6: stocks, sectors, exchanges)
└─ 0 Exit
```
Items that aren't built yet print "coming in a later step".

Portfolios (App 2): List my portfolios / Create portfolio / Choose portfolio → **Portfolio home**:
1 Summary, 2 Buy, 3 Sell, 4 Trade history, 5 Reports, 6 Deposit cash, 7 Withdraw cash,
8 Rename portfolio, 9 Delete portfolio.

Market data (Main → 2): 1 Top movers, 2 List stocks (optional sector filter), 3 Price history
(Enter = the last 30 price days). Admin (Main → 3): 1 Add a stock (downloads its prices; all or nothing),
2 Edit a stock, 3 Rename a ticker, 4 Delete a stock, 5 Refresh all prices, 6 List sectors,
7 List exchanges. ^GSPC can't be deleted or renamed (trigger).

Reports (App 5): 1 Monthly return vs S&P 500 (from/to months; Enter at "to" = the month of the
latest price date), 2 Sector allocation (as of a date, cash included), 3 P/L per holding (as of a
date, open and closed, with totals). Market data (Main → 2): Top movers (start/end dates).

Watchlists (App 4): 1 List my watchlists (items, targets reached), 2 Create watchlist, 3 Choose
watchlist → **Watchlist home**: 1 List items, 2 Add item (indexes allowed), 3 Edit target (Enter = keep,
`none` = clear), 4 Remove item, 5 Rename watchlist, 6 Delete watchlist (type its name);
4 Targets reached (all my watchlists, analysis query 5).

Trade history (App 3): 1 List trades (optional ticker filter), 2 Edit a trade (shares/price),
3 Delete a trade (type its ID), 4 Audit log, 5 Restore a deleted trade (`CALL restore_trade`).

**Date prompts (all of them):** Enter = the latest price date, or the portfolio's latest allowed
date if that is later. The prompt shows that default and the available price range
("prices: 2021-01-04 to 2026-10-30"). Not "today": prices load only up to yesterday, and new events
can't be before the portfolio's latest event, so "today" would block trading until the next load.

## 4. Roadmap

| Step | Content |
|---|---|
| **App 1** (done) | Foundation (layers, errors, inputs, menu, display, `make run`) + investor CRUD |
| **App 2** (done) | Portfolio: create / rename / delete, cash (deposit, withdraw), trades (buy, sell via `execute_trade`), holdings and balance |
| **App 3** (done) | Trade history, edit / delete a trade, audit log, restore a deleted trade from trade_audit |
| **App 4** (done) | Watchlists and items, targets reached (query 5) |
| **App 5** (done) | Reports: monthly return vs S&P 500 (query 1), sector allocation (2), top movers (3), P/L per holding (4) |
| **App 6** (done) | Market data (price history, refresh prices) and Admin (add a stock + download its prices, edit, delete) |
| Extras | **PNG charts (done: portfolio vs S&P 500, sector allocation, top movers; + CSV of the data)**; CSV trade import (all-or-nothing, one transaction); rebalance to target % |
| **Final step, before submission** | Replace raw tracebacks with a friendly "unexpected error" message + a log file. Until then, a Python bug (not a database error) still shows its traceback, so bugs stay visible during development. |
