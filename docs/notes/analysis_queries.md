# Analysis queries 2–5

Files in `db/analysis/`:

| File | Function | Query |
|---|---|---|
| `00_indexes.sql` | `idx_daily_price_date` | index for the "latest date" defaults |
| `02_sector_allocation.sql` | `fn_sector_allocation(portfolio_id, as_of, include_cash)` | 2 |
| `03_top_movers.sql` | `fn_top_movers(start, end, limit)` | 3 |
| `04_holding_pl.sql` | `fn_holding_pl(portfolio_id, as_of)` | 4 |
| `05_watchlist_targets.sql` | `fn_watchlist_targets_reached(investor_id, as_of)` | 5 |

**EN:** Every parameter after the first can be omitted. A NULL date means **today** (`CURRENT_DATE`), and a NULL id means **all**. Closes are always the latest close on or before that date, so with the default you get the latest price loaded (yesterday's close), while today's cash transactions still count.
**中文：** 第一个之后的参数都可以省略。日期为 NULL 表示**今天**（`CURRENT_DATE`），id 为 NULL 表示**全部**。收盘价总是取该日期当天或之前的最新收盘价，所以使用默认值时得到已加载的最新价格（昨天的收盘价），而今天的现金交易仍会计入。

```sql
SELECT * FROM fn_sector_allocation(1);               -- portfolio 1, today
SELECT * FROM fn_top_movers('2025-01-01');           -- 2025-01-01 .. today, top 5
SELECT * FROM fn_holding_pl(1, '2025-06-30');        -- portfolio 1 as of a past date
SELECT * FROM fn_watchlist_targets_reached();        -- all investors
```

## How Python will call them / Python 如何调用
```python
cur.execute("SELECT * FROM fn_holding_pl(%s, %s)", (portfolio_id, as_of))   # as_of = None -> today
rows = cur.fetchall()            # list of tuples, one per row
```
**EN:** Python's `None` becomes SQL `NULL`, so leaving a date empty in the menu means "today". The functions only read data and are `STABLE`, so they're safe to call at any time.
**中文：** Python 的 `None` 会变成 SQL 的 `NULL`，所以菜单里日期留空就表示"今天"。这些函数只读取数据，并声明为 `STABLE`，任何时候调用都是安全的。

---

## The shared building blocks / 共用的基本写法

### 1. The default date / 默认日期: today
```sql
WITH params AS (
    SELECT COALESCE(p_as_of, CURRENT_DATE) AS as_of
)
```
**EN:**
- `COALESCE(a, b)` returns the first value that isn't NULL, so if the caller passes no date, we use **today**. The `params` CTE computes it **once**, and every later part of the query uses `params.as_of`.
- **Decision (yours):** the default is today, not the latest *price* date. Prices load only up to yesterday, so with "latest price date" a deposit made today would be missing from query 2 while `v_cash_balance` already shows it. With today, the two always agree (a test checks every portfolio's Cash row against `v_cash_balance`).
- Closes don't change: "latest close on or before today" is still the latest price loaded (point 2).
- Example: on 2026-11-02, `fn_sector_allocation()` shows `as_of = 2026-11-02`, and `fn_holding_pl()` shows `close_date = 2026-10-30`.

**中文：**
- `COALESCE(a, b)` 返回第一个非 NULL 的值：调用者没传日期时，就用**今天**。`params` 这个 CTE 只计算**一次**，查询后面的部分都使用 `params.as_of`。
- **决定（你做的）：** 默认值是今天，而不是最新的*价格*日期。价格只加载到昨天，如果默认用"最新价格日期"，今天的存款就不会出现在查询 2 中，而 `v_cash_balance` 已经包含它。默认用今天，两者就始终一致（有测试逐个检查每个 portfolio 的 Cash 行与 `v_cash_balance` 是否相等）。
- 收盘价不受影响："今天或之前的最新收盘价"仍然是已加载的最新价格（第 2 点）。
- 例子：2026-11-02 时，`fn_sector_allocation()` 显示 `as_of = 2026-11-02`，`fn_holding_pl()` 显示 `close_date = 2026-10-30`。

### 2. "Latest close on or before a date", per ticker / 每只股票"某日或之前的最新收盘价"
```sql
CROSS JOIN LATERAL (
    SELECT dp.price_date, dp.close FROM daily_price dp
    WHERE dp.ticker = pos.ticker AND dp.price_date <= params.as_of
    ORDER BY dp.price_date DESC
    LIMIT 1
) c
```
**EN:**
- **`LATERAL`** lets the subquery use columns from the rows on its left (`pos.ticker`). It runs once per row, like a small function call.
- `ORDER BY … DESC LIMIT 1` gives the newest day on or before `as_of`. This handles weekends and holidays: asking "as of Saturday" gives Friday's close.
- **It's fast** because the primary key is `(ticker, price_date)`. PostgreSQL jumps to that ticker in the index and reads backwards one row (`Index Scan Backward using pk_daily_price`).
- **Tiny example:** AAPL has closes on Thu 230, Fri 232, and nothing on Sat. "As of Sat" gives the Fri row, 232.

**中文：**
- **`LATERAL`** 让子查询可以使用它左边行的列（`pos.ticker`），对每一行执行一次，就像一次小函数调用。
- `ORDER BY … DESC LIMIT 1` 取 `as_of` 当天或之前最新的一天。这样能处理周末和节假日："截至周六"得到周五的收盘价。
- **速度快**，因为主键是 `(ticker, price_date)`：PostgreSQL 在索引中直接跳到这只股票，向后读一行（`Index Scan Backward using pk_daily_price`）。
- **小例子：** AAPL 周四收盘 230，周五 232，周六没有数据。"截至周六"取到周五那一行，即 232。

### 3. The new index / 新索引: `idx_daily_price_date ON daily_price (price_date)`
> **Status update:** since the default changed to `CURRENT_DATE`, the analysis functions no longer run `max(price_date)`. The index still serves date-only lookups (e.g. `check_prices.sql`). Whether to keep it gets decided with query 1, which may look up month-end dates by `price_date` alone.
> **状态更新：** 默认日期改为 `CURRENT_DATE` 之后，分析函数不再执行 `max(price_date)`。索引仍可用于只按日期的查找（例如 `check_prices.sql`）。是否保留，在做查询 1 时决定（查询 1 可能只按 `price_date` 查找月末日期）。

**EN:**
- The *global* `max(price_date)` (formerly the default date) **can't** use the primary key, because `price_date` is its *second* column. An index sorted by ticker first can't quickly find the overall latest date.
- Measured on the real data (38,064 rows):

  | | plan | rows read | time |
  |---|---|---|---|
  | before | `Seq Scan on daily_price` | 38,064 | 1.98 ms |
  | after | `Index Only Scan Backward using idx_daily_price_date` | 1 | 0.10 ms |

- The table grows by 26 rows every trading day, so the sequential scan only gets slower over time. The per-ticker lookups (point 2) don't need a new index; the PK already serves them. The SQL comment says both things.

**中文：**
- *全局*的 `max(price_date)`（默认日期）**不能**使用主键，因为 `price_date` 是主键的*第二*列。一个先按 ticker 排序的索引，无法快速找到全表最新的日期。
- 在真实数据（38,064 行）上实测的结果见上表。
- 每个交易日表会增加 26 行，顺序扫描只会越来越慢。每只股票的查找（第 2 点）不需要新索引，主键已经足够。SQL 注释里写明了这两点。

---

## Query 2: sector allocation / 行业配置 (`fn_sector_allocation`)

**Tiny example / 小例子:** start cash 10,000; BUY 20 AN6 @ 100 (sector A) and BUY 10 AN7 @ 300 (sector B).

| sector | market value | pct |
|---|---:|---:|
| AnaSec B | 3,000.00 | 30.00 |
| AnaSec A | 2,000.00 | 20.00 |
| Cash | 5,000.00 | 50.00 |

**EN:**
- **Shares as of the date** = `SUM(+shares for BUY, −shares for SELL) WHERE trade_date <= as_of`. A plain SUM is fine for shares, because the order doesn't matter (it only matters for average *cost*). `HAVING … > 0` drops positions that were sold out.
- **Cash as of the date** = `cash_after` of the last `fn_portfolio_history` event on or before as_of (the same replay trigger 2d uses), or the starting cash if there were no events yet.
- **Decision (approved):** cash is its own row by default, so `pct` is a share of the **whole** portfolio. Otherwise a portfolio that's 90% cash would look 100% invested. `p_include_cash => false` gives the stocks-only split (40% / 60% in the example).
- **pct with a window function:** `SUM(market_value) OVER (PARTITION BY portfolio_id)` puts the portfolio's total next to every row without collapsing the rows. `NULLIF(total, 0)` turns a total of 0 into NULL, so a fully withdrawn, empty portfolio gives `pct NULL` instead of a division-by-zero error (a test covers this).
- **Rounding:** each pct is rounded to 2 decimals, so on the real data the 30 portfolios sum to between 99.98 and 100.02. `market_value` is exact.
- Portfolios that start after `as_of` aren't listed, and a stock with no sector shows as 'Unclassified'.

**中文：**
- **截至该日的持股** = `SUM(买入 +股数，卖出 −股数) WHERE trade_date <= as_of`。持股用普通的 SUM 就可以，因为顺序不影响结果（顺序只影响平均*成本*）。`HAVING … > 0` 去掉已经卖光的持仓。
- **截至该日的现金** = `fn_portfolio_history` 中 as_of 当天或之前最后一个事件的 `cash_after`（与触发器 2d 使用同一个重放），如果还没有任何事件，就是初始资金。
- **决定（已批准）：** 默认把现金作为单独一行，`pct` 是占**整个** portfolio 的比例。否则一个 90% 是现金的 portfolio 看起来会像 100% 投资了股票。`p_include_cash => false` 给出只算股票的比例（例子中是 40% / 60%）。
- **用窗口函数算 pct：** `SUM(market_value) OVER (PARTITION BY portfolio_id)` 把 portfolio 的总值放在每一行旁边，而不合并行。`NULLIF(total, 0)` 把总值 0 变成 NULL，所以现金全部取出、没有持仓的 portfolio 得到 `pct NULL`，而不是除以零报错（有测试覆盖）。
- **四舍五入：** 每个 pct 保留 2 位小数，所以真实数据中 30 个 portfolio 的合计在 99.98 到 100.02 之间。`market_value` 是精确的。
- 在 `as_of` 之后才开始的 portfolio 不会列出；没有行业的股票显示为 'Unclassified'。

## Query 3: top gainers and losers / 涨幅榜与跌幅榜 (`fn_top_movers`)

**Tiny example / 小例子** (the test):

| ticker | first close | last close | change | result |
|---|---:|---:|---:|---|
| AN1 | 100 | 150 | +50% | GAINER rank **1** |
| AN4 | 100 | 150 | +50% | GAINER rank **1** (tie) |
| AN8 | 100 | 130 | +30% | GAINER rank **3** (not 2) |
| AN3 | 100 | 100 | 0% | neither |
| AN2 | 100 | 80 | −20% | LOSER rank 1 |

### RANK vs DENSE_RANK vs ROW_NUMBER / 三种排名函数的区别

| pct | `ROW_NUMBER()` | `RANK()` | `DENSE_RANK()` |
|---:|---:|---:|---:|
| 50 | 1 | 1 | 1 |
| 50 | 2 | 1 | 1 |
| 30 | 3 | **3** | 2 |

**EN:**
- `ROW_NUMBER` always counts 1, 2, 3 and breaks ties arbitrarily, which is unfair to the second +50% stock.
- `RANK` gives ties the same number and then **skips** ("two stocks share 1st place, so the next one is 3rd"), the way sports rankings work.
- `DENSE_RANK` doesn't skip.
- We use **`RANK() … WHERE rank <= 5`**, so **all tied stocks are kept**, even if that means 6 rows (`p_limit 1` still returns both AN1 and AN4).
- Ranking uses the **exact** change; only the displayed `pct_change` is rounded, so rounding can't create a fake tie.
- **Decision (approved):** gainers must be > 0% and losers < 0%. In a market where everything went up, the "losers" list should be empty, not show the smallest gains.
- The first and last close are the first and last trading days **inside** `[start, end]`, found with the same LATERAL + primary-key pattern. A stock needs two different days, so a one-day period returns nothing. Only `security_type = 'STOCK'` counts, never ^GSPC.

**中文：**
- `ROW_NUMBER` 总是 1、2、3 地数，并列时随意排序，对第二只 +50% 的股票不公平。
- `RANK` 给并列的股票相同的名次，然后**跳过**后面的名次（"两只股票并列第 1，下一只是第 3"），和体育比赛的排名一样。
- `DENSE_RANK` 不跳过名次。
- 我们用 **`RANK() … WHERE rank <= 5`**，**并列的股票全部保留**，即使因此返回 6 行（`p_limit 1` 仍然同时返回 AN1 和 AN4）。
- 排名使用**精确的**涨跌幅，只有显示的 `pct_change` 才四舍五入，所以四舍五入不会制造假并列。
- **决定（已批准）：** 涨幅榜必须 > 0%，跌幅榜必须 < 0%。在所有股票都上涨的市场里，"跌幅榜"应该为空，而不是显示涨得最少的股票。
- 首尾收盘价是 `[start, end]` 区间**内**第一个和最后一个交易日的价格，用同样的 LATERAL + 主键写法查找。一只股票需要两个不同的交易日，所以只有一天的区间不返回任何结果。只统计 `security_type = 'STOCK'`，从不包括 ^GSPC。

## Query 4: realized vs unrealized P/L / 已实现与未实现盈亏 (`fn_holding_pl`)

**Tiny example / 小例子:** BUY 10 @ 100, SELL 5 @ 150, BUY 5 @ 200; close 180 on the as-of date.

| | value |
|---|---:|
| shares / avg cost / cost basis | 10 / 150.00 / 1,500.00 (from `v_holdings` logic) |
| market value | 10 × 180 = 1,800.00 |
| **unrealized** | 1,800 − 1,500 = **300.00** |
| **realized** | 5 × (150 − 100) = **250.00** |
| total | 550.00 |

**EN:**
- **Decision (approved), "as of" means as of:** the position comes from `fn_position_history` (the recursive average-cost walk), using only trades **on or before** `as_of`: `DISTINCT ON (portfolio, ticker) … ORDER BY trade_seq DESC` keeps each ticker's last state. `v_holdings` always contains **all** trades, so using it with a past date would mix future trades with past prices.
  - Test: as of d2 (before the second BUY) gives 5 shares, cost 500, realized 250.
  - With the default date, the result equals `v_holdings` (a test compares every row).
- `unrealized = shares × close − cost_basis`, using the **exact** cost basis (1,500.00, not avg 150 × 10 rounded), as planned in v_holdings.
- **Closed positions are included** (shares 0, unrealized 0, `avg_cost NULL`) because their realized P/L matters. On the real data, portfolio 5 sold all its AAPL for +28,955.84.

**中文：**
- **决定（已批准），"截至"就是截至：** 持仓状态来自 `fn_position_history`（递归计算平均成本），只使用 `as_of` **当天或之前**的交易：`DISTINCT ON (portfolio, ticker) … ORDER BY trade_seq DESC` 保留每只股票最后的状态。`v_holdings` 总是包含**全部**交易，如果配合过去的日期使用，就会把未来的交易和过去的价格混在一起。
  - 测试：截至 d2（第二次买入之前）得到 5 股、成本 500、已实现 250。
  - 使用默认日期时，结果与 `v_holdings` 完全一致（有测试逐行比较）。
- `未实现 = 持股 × 收盘价 − cost_basis`，使用**精确的**成本（1,500.00，而不是四舍五入的平均成本 150 × 10），这是在 v_holdings 时就计划好的。
- **已清仓的持仓也包括在内**（持股 0、未实现 0、`avg_cost NULL`），因为它们的已实现盈亏很重要。真实数据中，portfolio 5 卖光了 AAPL，盈利 +28,955.84。

## Query 5: watchlist targets reached / 已达到目标价的关注项 (`fn_watchlist_targets_reached`)

**Tiny example / 小例子:** three items all closing at 95, with targets 90 / 100 / NULL → only the target-90 item appears, at `(95 − 90) / 90 = 5.56%` above target.

**EN:** `WHERE c.close >= wi.target_price`. With a NULL target, the comparison is NULL (not TRUE), and `WHERE` keeps only TRUE rows, so items without a target drop out **automatically**, with no extra condition. On the real data, 31 of 89 items are reached, the same number the seeder reported.
**中文：** `WHERE c.close >= wi.target_price`。目标价为 NULL 时比较结果是 NULL（不是 TRUE），而 `WHERE` 只保留 TRUE 的行，所以没有目标价的条目**自动**被排除，不需要额外条件。真实数据中 89 个条目里有 31 个已达到，与生成脚本报告的数字一致。

---

## `db/apply.sql` vs `db/reset.sql` / 两个脚本的区别

**EN:**

| | `reset.sql` | `apply.sql` (`make apply-db`) |
|---|---|---|
| Drops tables | **yes**, all data lost | never |
| Creates | tables + everything in apply.sql | views, functions, procedures, triggers, analysis, indexes |
| Used on | `portfolio_tracker_test` (every `make test`) | `portfolio_tracker` (real data) |

- `reset.sql` now `\ir`s `apply.sql`, so there's **one list** of objects and the two can't drift apart.
- Every file in apply.sql is idempotent: `CREATE OR REPLACE` or `IF NOT EXISTS`.
- `--single-transaction` makes `make apply-db` all-or-nothing.
- Proof that it doesn't touch data: the sample-data fingerprint was `ea1746ea…` before and after.
- **Limitation:** `CREATE OR REPLACE FUNCTION` can't change a function's return columns; that needs a `DROP FUNCTION` first.

**中文：**
- `reset.sql` 现在用 `\ir` 包含 `apply.sql`，对象列表**只有一份**，两者不会不一致。
- apply.sql 中的每个文件都是幂等的：`CREATE OR REPLACE` 或 `IF NOT EXISTS`。
- `--single-transaction` 让 `make apply-db` 要么全部成功，要么全部不生效。
- 不会改动数据的证据：生成数据的指纹在执行前后都是 `ea1746ea…`。
- **限制：** `CREATE OR REPLACE FUNCTION` 不能修改函数的返回列，需要先 `DROP FUNCTION`。

## Earlier behaviour, now changed / 之前的行为（已修改）

**EN:** At first the default was the latest **price** date. Because prices load only up to yesterday, a cash transaction dated today was left out of query 2 until the next price load (Bal Dates showed 9,701 instead of `v_cash_balance`'s 9,702). You decided to default to `CURRENT_DATE` instead. The test now checks both sides: by default the deposit counts (9,702); with an explicit `as_of` of the latest price date it doesn't (9,701).
**中文：** 最初的默认值是最新的**价格**日期。因为价格只加载到昨天，今天的现金交易在下次加载价格之前不会被查询 2 计入（Bal Dates 显示 9,701，而 `v_cash_balance` 是 9,702）。你决定改为默认使用 `CURRENT_DATE`。现在测试两边都检查：默认时这笔存款计入（9,702）；显式指定 `as_of` 为最新价格日期时不计入（9,701）。

## Tests / 测试

**EN:** 26 new SQL tests ("ana", "q2"–"q5") use fictional tickers whose prices exist only in 2025, so no other test data is in those periods.
- **q4:** values as of d4, d2 and d1 and before the first trade; closed position; default = today (closes from the latest price date); default = `v_holdings`
- **q3:** ranks with ties and a skipped rank; 0% excluded; `p_limit` keeps ties; first and last close inside the period; one-day period; default end = today; no index
- **q2:** values and order; sums to 100; stocks-only; before the start; all portfolios ±0.05; zero-value portfolio; default as_of = today; Cash = `v_cash_balance` for every portfolio; a deposit dated today counts by default but not as of the latest price date
- **q5:** target 90 appears; 100 and NULL don't; default = today

Totals: **311 SQL tests and 30 pytest tests, all passing.**

**中文：** 26 个新的 SQL 测试（"ana"、"q2"–"q5"）使用只在 2025 年有价格的虚构股票，所以这些时间段里没有其他测试数据。
- **q4：** 截至 d4、d2、d1 以及第一笔交易之前的值；已清仓持仓；默认日期 = 今天（收盘价取最新价格日期）；默认结果 = `v_holdings`
- **q3：** 含并列和跳过名次的排名；0% 被排除；`p_limit` 保留并列；首尾收盘价在区间内；单日区间；默认结束日期 = 今天；不包括指数
- **q2：** 数值和顺序；合计为 100；只算股票；开始日期之前；所有 portfolio 合计在 ±0.05 以内；总值为 0 的 portfolio；默认 as_of = 今天；每个 portfolio 的 Cash = `v_cash_balance`；今天的存款默认计入，但截至最新价格日期时不计入
- **q5：** 目标价 90 出现；100 和 NULL 不出现；默认日期 = 今天

合计：**311 个 SQL 测试和 30 个 pytest 测试，全部通过。**
