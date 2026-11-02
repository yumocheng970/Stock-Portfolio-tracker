# v_cash_balance

File: `db/views/01_v_cash_balance.sql` · Tests: "view cash: ..." in `db/tests/test_schema.sql` · Commit: `e26e818`

One row per portfolio: `starting_cash, deposits, withdrawals, buys, sells, cash_balance`.

```
cash_balance = starting_cash + deposits - withdrawals - buys + sells    (buys/sells = shares * price)
```

## Tiny example / 小例子

Portfolio 1: starting_cash 1000, **2 deposits** (100, 200), **3 trades** (BUY 50, BUY 30, SELL 40, each already shares × price).
Correct cash = 1000 + 300 − 80 + 40 = **1260**.

## What join fan-out is / 什么是连接扇出（fan-out）

**EN:** If you join the raw tables (`portfolio JOIN cash_transaction JOIN trade`), PostgreSQL pairs **every** cash row with **every** trade row of the same portfolio: 2 × 3 = 6 rows.

| deposit | trade   |
|---------|---------|
| 100     | BUY 50  |
| 100     | BUY 30  |
| 100     | SELL 40 |
| 200     | BUY 50  |
| 200     | BUY 30  |
| 200     | SELL 40 |

Then `SUM(deposit)` = 900 (each deposit counted 3 times) and `SUM(buys)` = 160 (each buy counted 2 times), so the balance is wrong. The join "fans out" into more rows than there are real records. Test "(demo) naive raw join" runs this wrong join on purpose and confirms it gives 9000 instead of 3000.

**中文：** 如果直接连接原始表（`portfolio JOIN cash_transaction JOIN trade`），PostgreSQL 会把同一个 portfolio 的**每一条**现金记录和**每一笔**交易两两配对：2 × 3 = 6 行（见上表）。于是 `SUM(存款)` = 900（每笔存款算了 3 次），`SUM(买入)` = 160（每笔买入算了 2 次），余额就错了。这就是"扇出"：连接产生的行数比真实记录多。测试 "(demo) naive raw join" 故意运行这种错误连接，结果是 9000 而不是 3000。

## How the view avoids it / 视图如何避免

```sql
WITH cash_totals AS (SELECT portfolio_id, SUM(...) ... GROUP BY portfolio_id),
     trade_totals AS (SELECT portfolio_id, SUM(...) ... GROUP BY portfolio_id)
SELECT ... FROM portfolio p
LEFT JOIN cash_totals  c ON c.portfolio_id = p.portfolio_id
LEFT JOIN trade_totals t ON t.portfolio_id = p.portfolio_id;
```

**EN:**
- **Aggregate first, join second.**
  - `cash_totals` turns the 2 deposits into 1 row: (portfolio 1, deposits 300).
  - `trade_totals` turns the 3 trades into 1 row: (portfolio 1, buys 80, sells 40).
- Now each join matches at most **one** row: 1 × 1 × 1 = 1 row, so nothing is multiplied.
- `WITH … AS (…)` is a CTE, a named subquery that you can read like a temporary table.
- `SUM(x) FILTER (WHERE …)` sums only the rows matching the condition, so one pass over the table gives both deposits and withdrawals.

**中文：**
- **先汇总，再连接。**
  - `cash_totals` 把 2 笔存款变成 1 行：(portfolio 1, 存款 300)。
  - `trade_totals` 把 3 笔交易变成 1 行：(portfolio 1, 买入 80, 卖出 40)。
- 现在每次连接最多只匹配**一行**：1 × 1 × 1 = 1 行，没有任何重复相乘。
- `WITH … AS (…)` 是 CTE，即一个有名字的子查询，可以当作临时表来理解。
- `SUM(x) FILTER (WHERE …)` 只对满足条件的行求和，所以扫描一次表就能同时得到存款和取款。

## Why COALESCE is needed (two separate reasons) / 为什么需要 COALESCE（两个不同原因）

**EN:**
1. **LEFT JOIN with no match.** A new portfolio has no row in `cash_totals`, so `c.deposits` is NULL. In SQL, `1000 + NULL` = **NULL**, so the balance would be NULL, not 1000. `COALESCE(c.deposits, 0)` means "use the first value that isn't NULL", which turns NULL into 0.
2. **FILTER with no matching rows.** A portfolio with deposits but no withdrawals *does* have a `cash_totals` row, but `SUM(...) FILTER (WHERE txn_type = 'WITHDRAWAL')` sums zero rows, and SQL's `SUM` of zero rows is **NULL**, not 0.

`LEFT JOIN` (instead of `JOIN`) is what keeps portfolios with no activity in the result at all. A plain `JOIN` would drop them.

**中文：**
1. **LEFT JOIN 没有匹配：** 新 portfolio 在 `cash_totals` 里没有行，`c.deposits` 是 NULL。SQL 中 `1000 + NULL` = **NULL**，余额就会是 NULL 而不是 1000。`COALESCE(c.deposits, 0)` 的意思是"取第一个非 NULL 的值"，把 NULL 变成 0。
2. **FILTER 没有匹配的行：** 有存款但没有取款的 portfolio *有* `cash_totals` 行，但 `SUM(...) FILTER (WHERE txn_type = 'WITHDRAWAL')` 是对零行求和，SQL 中对零行 `SUM` 的结果是 **NULL** 而不是 0。

用 `LEFT JOIN`（而不是 `JOIN`）才能让没有任何活动的 portfolio 出现在结果里；普通 `JOIN` 会把它们丢掉。

## Design notes / 设计说明

1. **The balance is the current one, not "as of a date" / 余额是当前值，不是某一天的值**
   - **EN:** That's enough for `execute_trade()`: the rule "new date ≥ the portfolio's latest date" means a new trade always comes after everything already recorded. It is **not** enough for replaying trade updates and deletes ("cash never < 0 at any point"). That needs a running total in date order, probably `SUM(...) OVER (ORDER BY date, ...)`, with cash transactions before trades on the same day.
   - **中文：** 对 `execute_trade()` 来说足够：规则"新日期 ≥ 该 portfolio 的最新日期"意味着新交易总是排在所有已有记录之后。但对修改/删除交易时的历史重放（"现金在任何时刻都不能 < 0"）**不够**：那需要按日期顺序的累计和，可能用窗口函数 `SUM(...) OVER (ORDER BY date, ...)`，并且同一天现金交易排在交易之前。
2. **Filtering one portfolio is fast / 查询单个 portfolio 很快**
   - **EN:** `WHERE portfolio_id = X` on the view is pushed into both CTEs and uses `idx_trade_portfolio_date` and `idx_cash_portfolio_date`. This is evidence for the index justification in the report. Check it with `EXPLAIN SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = 5;` (on empty tables, run `SET enable_seqscan = off;` first to see the index plan).
   - **中文：** 对视图加 `WHERE portfolio_id = X` 时，条件会被下推到两个 CTE 里，并使用 `idx_trade_portfolio_date` 和 `idx_cash_portfolio_date`，可以作为报告中索引设计的证据。用 `EXPLAIN SELECT cash_balance FROM v_cash_balance WHERE portfolio_id = 5;` 查看（空表时先执行 `SET enable_seqscan = off;` 才能看到索引计划）。
3. **No type cast / 不做类型转换**
   - **EN:** The columns are plain `NUMERIC`, which psycopg returns as Python `Decimal`. I didn't cast to `NUMERIC(14,2)`: total deposits have no cap (only each deposit does), so a cast could make the view throw an overflow error.
   - **中文：** 各列是普通 `NUMERIC`，psycopg 返回 Python 的 `Decimal`。没有转换成 `NUMERIC(14,2)`：存款总额没有上限（只有单笔存款有上限），转换可能导致视图报溢出错误。
4. **Test data / 测试数据**
   - **EN:** The tests use the fictional stock `CASHT` because no AAPL test day has a range that includes 190.00. Adding an AAPL row would break the rename test, which expects 2 AAPL price rows.
   - **中文：** 测试使用虚构股票 `CASHT`，因为 AAPL 的测试日期里没有一天的价格区间包含 190.00；给 AAPL 加行会破坏改名测试（它要求 AAPL 正好有 2 行价格）。

## Tests / 测试

| Case | Expected |
|------|----------|
| No activity (start 25000) | balance 25000.00, all parts 0 (not NULL) |
| 100000 + dep 5000 − wd 2000 − BUY 10 @ 186 + SELL 5 @ 190 | 102090.00 |
| Fan-out: 2 deposits × 3 trades | deposits 3000, buys 560, sells 190, withdrawals 0, balance 52630.00 |
| Naive raw join (demo) | deposits 9000, buys 1120 (shows the bug) |
| Whole view | exactly 1 row per portfolio, no NULL balance |
| Update a trade price 186 → 185 | balance follows (102100.00) |
