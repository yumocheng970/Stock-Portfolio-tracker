# Analysis queries 1–5

Files in `db/analysis/`:

| File | Function | Query |
|---|---|---|
| `00_indexes.sql` | (`idx_daily_price_date` dropped) | secondary indexes; see point 3 |
| `01_monthly_returns.sql` | `fn_monthly_returns(portfolio_id, from_month, to_month)` | 1 |
| `02_sector_allocation.sql` | `fn_sector_allocation(portfolio_id, as_of, include_cash)` | 2 |
| `03_top_movers.sql` | `fn_top_movers(start, end, limit)` | 3 |
| `04_holding_pl.sql` | `fn_holding_pl(portfolio_id, as_of)` | 4 |
| `05_watchlist_targets.sql` | `fn_watchlist_targets_reached(investor_id, as_of)` | 5 |

**EN:** Every parameter after the first can be omitted. A NULL date means **today** (`CURRENT_DATE`), and a NULL id means **all**. Closes are always the latest close on or before that date, so with the default you get the latest price loaded (yesterday's close), while today's cash transactions still count.
**中文：** 第一个之后的参数都可以省略。日期为 NULL 表示**今天**（`CURRENT_DATE`），id 为 NULL 表示**全部**。收盘价总是取该日期当天或之前的最新收盘价，所以使用默认值时得到已加载的最新价格（昨天的收盘价），而今天的现金交易仍会计入。

```sql
SELECT * FROM fn_monthly_returns(1);                 -- portfolio 1, every month to today
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

### 3. The index `idx_daily_price_date ON daily_price (price_date)`: added, measured, dropped / 索引：添加、测量、删除
> **Final status: DROPPED** (with query 1). The analysis functions default to `CURRENT_DATE` and never run `max(price_date)`. Query 1 also looks up month-end closes **per ticker** (and for ^GSPC), which uses the primary key. Proof: `EXPLAIN ANALYZE SELECT * FROM fn_monthly_returns()` on the real DB, with the index still present, used `pk_daily_price` 4 times and `idx_daily_price_date` 0 times. An unused index only costs disk space and slows every price insert, so `00_indexes.sql` now runs `DROP INDEX IF EXISTS`. `check_prices.sql` still runs `max(price_date)`, but a 2 ms Seq Scan in a manual check is fine.
> **最终状态：已删除**（在查询 1 时决定）。分析函数默认用 `CURRENT_DATE`，从不执行 `max(price_date)`。查询 1 也是**按股票**（以及 ^GSPC）查找月末收盘价，走的是主键。证据：在真实数据库上（索引还在时）执行 `EXPLAIN ANALYZE SELECT * FROM fn_monthly_returns()`，`pk_daily_price` 用了 4 次，`idx_daily_price_date` 0 次。没人用的索引只会占空间、拖慢每次插入价格，所以 `00_indexes.sql` 现在执行 `DROP INDEX IF EXISTS`。`check_prices.sql` 仍会执行 `max(price_date)`，但手动检查里 2 ms 的顺序扫描没有问题。

The original reasoning and measurement, kept for the report / 原来的理由和测量结果（留给报告）：

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

## Query 1: monthly return vs the S&P 500 / 月收益率与标普 500 对比 (`fn_monthly_returns`)

```sql
SELECT * FROM fn_monthly_returns();                              -- all portfolios, all months
SELECT * FROM fn_monthly_returns(3, '2025-04-01', '2025-10-01'); -- portfolio 3, Apr..Oct 2025
```
Columns: `month` (1st day), `period_start`, `period_end`, `start_value`, `end_value`, `net_flow`, `portfolio_return_pct`, `spx_return_pct`, `excess_return_pct`, `cum_portfolio_pct`, `cum_spx_pct`.
Months can be given as any day of the month (`'2025-04-17'` means April).

### The period and the values / 区间与市值
**EN:**
- **Value at a date d** = cash after all events up to d + SUM(shares held on d × the latest close on or before d). A Saturday month end therefore uses Friday's close.
- **period_start** = the 1st of the month, or `start_date` in the first month (a partial month). **period_end** = the last day of the month, or **today** in the current month (also partial).
- **start_value** = the previous month's `end_value`, or `starting_cash` in the first month (the value at the start of `start_date`, before any trade).

**中文：**
- **某日 d 的市值** = 截至 d 所有事件之后的现金 + SUM(d 日持有的股数 × d 当天或之前的最新收盘价)。所以月末如果是周六，就用周五的收盘价。
- **period_start** = 当月 1 号；第一个月则是 `start_date`（不完整的月）。**period_end** = 当月最后一天；当前月则是**今天**（也不完整）。
- **start_value** = 上个月的 `end_value`；第一个月是 `starting_cash`（`start_date` 开始时、任何交易之前的市值）。

### The formula: Modified Dietz / 公式：修正 Dietz 法
```
R = (V_end − V_start − F) / (V_start + Σ w_i · F_i)
F   = net flow = deposits − withdrawals in the period
w_i = (period_end − flow_date + 1) / D,    D = period_end − period_start + 1  (days)
```
**EN:**
- The **numerator** is the real gain: the change in value minus the money you put in. A deposit raises `V_end` by the same amount as `F`, so it cancels out and is not counted as a gain.
- The **denominator** is the average capital that was at work. A flow counts only for the fraction of the month it was in the portfolio. `w_i` counts days from the **start** of the flow day, because cash transactions come before trades on the same day.
- **Worked example** (also an SQL test): start 10,000 on 2025-05-01, BUY 100 AR1 @ 100 that day. DEPOSIT 3,100 on 05-16. Close at month end 110.
  - V_end = 100 × 110 + 3,100 = 14,100; F = 3,100; D = 31; w = (31 − 16 + 1)/31 = 16/31
  - R = (14,100 − 10,000 − 3,100) / (10,000 + 3,100 × 16/31) = 1,000 / 11,600 = **8.62 %**

  | Method / 方法 | Calculation / 计算 | Result / 结果 |
  |---|---|---|
  | Naive (deposit counted as gain) / 朴素法（存款算作收益） | 4,100 / 10,000 | 41.00 % ✗ |
  | Flows at end of month / 资金流算在月末 | 1,000 / 10,000 | 10.00 % |
  | Flows at start of month / 资金流算在月初 | 1,000 / 13,100 | 7.63 % |
  | **Modified Dietz** / **修正 Dietz** | 1,000 / 11,600 | **8.62 %** |

  Why not 10 %? The stock gained 10 %, but the 3,100 sat as cash for half the month and earned nothing, so the average capital (11,600) earned 1,000.
- **Rejected:** the true time-weighted return. It needs a full valuation on every flow date, which means more lookups and is harder to explain. Modified Dietz is the standard monthly approximation.

**中文：**
- **分子**是真正的收益：市值变化减去投入的钱。存款让 `V_end` 增加的金额正好等于 `F`，两者相互抵消，所以存款不算收益。
- **分母**是期间平均投入的资本。一笔资金流只按它在组合里的那部分时间计算。`w_i` 从资金流当天的**开始**算起，因为同一天现金交易排在交易之前。
- **算例**（也是一个 SQL 测试）：见上方的数字。为什么不是 10 %？股票涨了 10 %，但那 3,100 有半个月是闲置现金，没有收益，所以平均资本 11,600 赚了 1,000。
- **没有采用：** 真正的时间加权收益率。它需要在每次资金流当天对整个组合估值，查询更多，也更难解释。修正 Dietz 是常用的按月近似方法。

### S&P 500 return / 标普 500 收益率
**EN:** `spx_return = close(latest ≤ period_end) / close(latest ≤ previous month end) − 1`, over the same months as the portfolio. In the first month the base is the latest ^GSPC close **before** `start_date`, which matches V_start = cash at the start of that day. If no earlier close exists (data starts that day, as for the real portfolio starting 2021-01-04), the base is the **open** of the first price day ≥ `start_date`. `excess_return_pct` = portfolio − S&P, in percentage points.
**中文：** `spx_return = close(≤ period_end 的最新) / close(≤ 上月末的最新) − 1`，月份与组合相同。第一个月的基准是 `start_date` **之前**最新的 ^GSPC 收盘价，对应 V_start = 当天开始时的现金。如果没有更早的收盘价（数据从当天才开始，例如 2021-01-04 开始的那个真实 portfolio），就用 `start_date` 当天或之后第一个价格日的**开盘价**。`excess_return_pct` = 组合 − 标普，单位是百分点。

### Window functions used / 用到的窗口函数
**EN:**
- **`LAG(x) OVER (PARTITION BY portfolio_id ORDER BY month)`** gives the previous row's value inside the same portfolio, which is the previous month here. It provides `start_value` (the previous `end_value`) and `spx_start` (the previous month-end close). The first row has no previous row, so LAG returns NULL and `COALESCE` substitutes `starting_cash` / `spx_base`.
- **The filter must come after LAG.** In one SELECT, `WHERE` runs *before* window functions. If `month >= p_from_month` were in the same SELECT as LAG, the first shown month would have no previous row and would wrongly get `starting_cash`. So LAG runs in the CTE `monthly`, and the next CTE (`returns`) filters. (Test: from = June still shows start_value 11,000.)
- **Cumulative return = a product,** (1+r₁)(1+r₂)… − 1, but PostgreSQL has no product aggregate. The trick is `ln(a·b) = ln a + ln b`, so the product is `EXP(SUM(LN(1 + r)) OVER (... ROWS UNBOUNDED PRECEDING)) − 1`, a running SUM like the one in `fn_portfolio_history`.
  - Example: 1.10 × 0.90 = exp(ln 1.10 + ln 0.90) = exp(0.09531 − 0.10536) = exp(−0.01005) = 0.99, so the cumulative return is **−1.00 %** (also a test).
  - `LN` of a value ≤ 0 is an error, so a CASE turns 1 + r ≤ 0 into NULL. The cumulative return starts at the first **shown** month.
- **`SUM(...) FILTER (WHERE ...)`** is an aggregate over only some rows. One GROUP BY gives the cash at period end (all events up to it), the net flow and the weighted flow (only cash transactions inside the period).

**中文：**
- **`LAG(x) OVER (PARTITION BY portfolio_id ORDER BY month)`** 取同一 portfolio 中上一行的值，这里就是上个月。用它得到 `start_value`（上个月的 `end_value`）和 `spx_start`（上月末收盘价）。第一行没有上一行，LAG 返回 NULL，`COALESCE` 换成 `starting_cash` / `spx_base`。
- **过滤必须放在 LAG 之后。** 在同一个 SELECT 里，`WHERE` 在窗口函数*之前*执行。如果把 `month >= p_from_month` 和 LAG 写在同一个 SELECT 里，显示的第一个月就没有上一行，会错误地用 `starting_cash`。所以 LAG 在 CTE `monthly` 里计算，下一个 CTE（`returns`）再过滤。（测试：from = 6 月时 start_value 仍是 11,000。）
- **累计收益是连乘**：(1+r₁)(1+r₂)… − 1，但 PostgreSQL 没有乘积聚合函数。技巧是 `ln(a·b) = ln a + ln b`，所以连乘 = `EXP(SUM(LN(1 + r)) OVER (... ROWS UNBOUNDED PRECEDING)) − 1`，和 `fn_portfolio_history` 里一样是累计 SUM。例：1.10 × 0.90 = exp(0.09531 − 0.10536) = 0.99，即 **−1.00 %**。`LN` 遇到 ≤ 0 的值会报错，所以用 CASE 把它变成 NULL。累计收益从**显示的**第一个月开始算。
- **`SUM(...) FILTER (WHERE ...)`** 是只对部分行的聚合。一次 GROUP BY 同时得到期末现金（截至期末的所有事件）、净资金流和加权资金流（只算期间内的现金交易）。

### CTE steps / CTE 步骤
`pf` (portfolios + S&P base) → `months` (`generate_series`, one row per month) → `events` (`fn_portfolio_history`, once per portfolio) → `month_cash` / `month_positions` / `month_stock` (values at period end) → `monthly` (LAG) → `returns` (filter, Dietz) → final SELECT (round, cumulative).
EN: Every price lookup is "latest close ≤ date" for one ticker, which uses the primary key (see point 3). All portfolios take about 20 ms on the real DB (1,361 rows).
中文：每次价格查找都是"某只股票 ≤ 某日的最新收盘价"，走主键（见第 3 点）。真实数据库上所有 portfolio 约 20 ms（1,361 行）。

### Real rows (portfolio 3) / 真实数据（portfolio 3）
```
   month    | start_value | end_value | net_flow |   r   |  spx  |  ex   |  cum  | cum_spx
 2025-04-01 |   137092.21 | 131819.75 |        0 | -3.85 | -0.76 | -3.08 | -3.85 |   -0.76
 2025-05-01 |   131819.75 | 148283.81 | 12000.00 |  3.36 |  6.15 | -2.80 | -0.62 |    5.34
 2025-06-01 |   148283.81 | 152004.89 |        0 |  2.51 |  4.96 | -2.45 |  1.88 |   10.57
 2025-09-01 |   158366.58 | 155933.21 | -4377.00 |  1.23 |  3.53 | -2.30 |  7.44 |   19.18
```
EN: Check of May by hand: the deposit is on 05-29, so w = 3/31. R = (148,283.81 − 131,819.75 − 12,000) / (131,819.75 + 12,000 × 3/31) = 4,464.06 / 132,981.04 = 3.36 %. A naive return would have been 12.49 %.
中文：手算验证 5 月：存款在 05-29，w = 3/31，R = 4,464.06 / 132,981.04 = 3.36 %。朴素算法会得到 12.49 %。

### Limitations / 限制
- A month whose denominator is 0 (everything withdrawn) gets a NULL return, and the cumulative return skips it (treated as 0 %). 分母为 0 的月份（全部取出）收益为 NULL，累计时跳过（当作 0 %）。
- Excess is rounded from the exact difference, so it can differ by 0.01 from (rounded portfolio − rounded S&P). 超额收益由精确差值再四舍五入，可能与"四舍五入后相减"差 0.01。
- The current month shows 0 % until prices are refreshed (the real DB now has prices only to 2026-10-30). 价格未更新时，当前月显示 0 %（真实数据库现在价格只到 2026-10-30）。

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
- **q1** (8 more tests, ticker AR1, May–June 2025): no flows +10 % vs S&P +10 %, excess 0; +10 % then −10 % gives a cumulative −1.00 %; a mid-month deposit gives Modified Dietz 8.62 % (not 41 %); from = June keeps start_value 11,000 and restarts the cumulative; default to = current month with no gaps; NULL portfolio = single calls; latest end_value = `v_cash_balance` + `fn_holding_pl` market value for every portfolio

Totals (after query 1): **319 SQL tests and 30 pytest tests, all passing.**

**中文：** 26 个新的 SQL 测试（"ana"、"q2"–"q5"）使用只在 2025 年有价格的虚构股票，所以这些时间段里没有其他测试数据。
- **q4：** 截至 d4、d2、d1 以及第一笔交易之前的值；已清仓持仓；默认日期 = 今天（收盘价取最新价格日期）；默认结果 = `v_holdings`
- **q3：** 含并列和跳过名次的排名；0% 被排除；`p_limit` 保留并列；首尾收盘价在区间内；单日区间；默认结束日期 = 今天；不包括指数
- **q2：** 数值和顺序；合计为 100；只算股票；开始日期之前；所有 portfolio 合计在 ±0.05 以内；总值为 0 的 portfolio；默认 as_of = 今天；每个 portfolio 的 Cash = `v_cash_balance`；今天的存款默认计入，但截至最新价格日期时不计入
- **q5：** 目标价 90 出现；100 和 NULL 不出现；默认日期 = 今天
- **q1**（新增 8 个测试，股票 AR1，2025 年 5–6 月）：无资金流 +10 % 对标普 +10 %，超额 0；+10 % 再 −10 % 累计 −1.00 %；月中存款的修正 Dietz 收益为 8.62 %（不是 41 %）；from = 6 月时 start_value 仍为 11,000，累计重新开始；默认 to = 当前月且没有缺月；NULL portfolio = 逐个调用的结果；每个 portfolio 最新的 end_value = `v_cash_balance` + `fn_holding_pl` 市值

合计（加上查询 1 之后）：**319 个 SQL 测试和 30 个 pytest 测试，全部通过。**
