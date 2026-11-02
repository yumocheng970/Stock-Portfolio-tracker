# v_holdings

File: `db/views/02_v_holdings.sql` · Tests: "hold ..." in `db/tests/test_schema.sql`

| Piece | Job |
|-------|-----|
| `fn_position_history(portfolio_id)` | One row per trade: the position state after it (full precision) |
| `v_holdings` | One row per (portfolio, ticker) ever traded: the state after its last trade (rounded) |

`v_holdings` columns:
- `portfolio_id`, `ticker`
- `shares_held`, `avg_cost`, `cost_basis`, `realized_pl`
- `is_open`, `trade_count`, `last_trade_date`

## Average cost rules / 平均成本规则

```
BUY  q @ p : avg = (shares * avg + q * p) / (shares + q)      realized unchanged
SELL q @ p : avg unchanged                                    realized += q * (p - avg)
```

### Tiny example / 小例子: BUY 10 @ 100, SELL 5 @ 150, BUY 5 @ 200

| # | trade | shares_after | avg_cost_after | realized (this trade) | realized total |
|---|-------|-------------:|---------------:|----------------------:|---------------:|
| 0 | (empty start) | 0 | 0 | 0 | 0 |
| 1 | BUY 10 @ 100  | 10 | 100 | 0   | 0   |
| 2 | SELL 5 @ 150  | 5  | 100 | 250 | 250 |
| 3 | BUY 5 @ 200   | 10 | (5·100 + 5·200)/10 = **150** | 0 | **250** |

## 1. Why a simple SUM can't compute average cost / 为什么简单的 SUM 算不出平均成本

**EN:**
- The naive formula "total buy cost / total shares bought" gives 2000 / 15 = **133.33** for the example. That's wrong: the 5 shares sold at step 2 were sold at the average cost **at that time** (100), and the later BUY @ 200 can't change that.
- **The order matters, and `SUM`/`AVG` ignore order.** The same three trades in another order give a different answer:
  - BUY 10 @ 100, BUY 5 @ 200, SELL 5 → avg **133.33**
  - BUY 10 @ 100, SELL 5, BUY 5 @ 200 → avg **150.00**
- **Even a running window `SUM` fails.** A SELL removes cost in proportion to the current position: `cost_basis × (1 − q / shares)`. That's a multiplication by a value that depends on the state before the trade. A running SUM can only add fixed amounts, and there's no fixed amount to add here.
- So each trade has to be processed **after** the previous one, using its result.
- The test "(demo) naive SUM formula gives 133.33" proves the main test (avg 150.00) would catch the naive formula.

**中文：**
- 简单公式"买入总成本 / 买入总股数"在例子中得到 2000 / 15 = **133.33**，这是错的：第 2 步卖出的 5 股是按**当时**的平均成本（100）卖出的，之后 @ 200 的买入不能改变这一点。
- **顺序很重要，而 `SUM`/`AVG` 不考虑顺序。** 同样三笔交易换一个顺序，结果就不同：
  - BUY 10 @ 100、BUY 5 @ 200、SELL 5 → 平均成本 **133.33**
  - BUY 10 @ 100、SELL 5、BUY 5 @ 200 → 平均成本 **150.00**
- **窗口函数的累计 `SUM` 也不行。** 卖出会按当前持仓**按比例**减少成本：`成本 × (1 − q / 持股)`。这是乘以一个依赖交易前状态的值，而累计 SUM 只能加上固定的数，这里没有固定的数可加。
- 所以每笔交易必须在上一笔**之后**、基于上一笔的结果来计算。
- 测试 "(demo) naive SUM formula gives 133.33" 证明主测试（平均成本 150.00）能抓住这个错误公式。

## 2. How the recursive CTE handles the order / 递归 CTE 如何处理顺序

```sql
WITH RECURSIVE ordered AS (
    SELECT ..., ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date, trade_id) AS seq
    FROM trade WHERE portfolio_id = p_portfolio_id
),
walk AS (
    SELECT DISTINCT ticker, 0 AS seq, 0 AS shares_after, 0 AS avg_cost_after, ...   -- anchor
    FROM ordered
    UNION ALL
    SELECT o.ticker, o.seq, <new shares>, <new avg>, ...                             -- one step
    FROM walk w JOIN ordered o ON o.ticker = w.ticker AND o.seq = w.seq + 1
)
```

**EN:**
- **Step 1, number the trades.** `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date, trade_id)` gives each ticker's trades the numbers 1, 2, 3, … in history order: by date, then by `trade_id`. That's the same order the balance replay uses. `PARTITION BY ticker` numbers each ticker separately, so two tickers never mix (test "hold two").
- **Step 2, walk.** `WITH RECURSIVE` runs in rounds:
  - The **anchor** (before `UNION ALL`) runs once and creates an empty position (seq 0) for every ticker.
  - The **recursive part** (after `UNION ALL`) then runs again and again. Each round joins the rows from the *previous* round (`walk w`) with the *next* trade (`o.seq = w.seq + 1`) and applies the BUY or SELL formula to `w`'s state.
  - It stops when no row has a next trade.
  - The result is one row per trade, each built from the row before it. That's how state is carried forward in order, which SUM can't do.
- `w.seq + 1` is what makes the order exact. Trade 3 can only be joined to the output of trade 2.
- **Types:** both halves of a recursive `UNION ALL` must have exactly the same column types, so the anchor uses casts such as `0::BIGINT` and `NULL::NUMERIC(12,2)`.
- **Same date:** the test "hold same day" (BUY then SELL on the same day) proves `trade_id` breaks ties. Counting the SELL first would give realized 500 instead of 0.

**中文：**
- **第 1 步，编号。** `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date, trade_id)` 按历史顺序（先日期、后 `trade_id`，与余额重放相同）给每只股票的交易编号 1、2、3……。`PARTITION BY ticker` 让每只股票单独编号，两只股票不会混在一起（测试 "hold two"）。
- **第 2 步，逐笔推进。** `WITH RECURSIVE` 分轮执行：
  - **锚点**（`UNION ALL` 之前）只执行一次，为每只股票生成一个空持仓（seq 0）。
  - **递归部分**（`UNION ALL` 之后）反复执行：每一轮把*上一轮*的结果行（`walk w`）和*下一笔*交易（`o.seq = w.seq + 1`）连接起来，在 `w` 的状态上应用 BUY 或 SELL 公式。
  - 没有下一笔交易时停止。
  - 结果是每笔交易一行，每行都由前一行计算而来。这就是按顺序传递状态的方法，SUM 做不到。
- `w.seq + 1` 保证顺序准确：第 3 笔交易只能接在第 2 笔的结果后面。
- **类型：** 递归 `UNION ALL` 两部分的列类型必须完全相同，所以锚点要写 `0::BIGINT`、`NULL::NUMERIC(12,2)` 这样的转换。
- **同一天：** 测试 "hold same day"（同一天先 BUY 后 SELL）证明 `trade_id` 决定同日顺序。如果先算 SELL，已实现盈亏会是 500 而不是 0。

## 3. Fresh start after 0 shares needs no special case / 清仓后重新开始不需要特殊处理

**EN:** When shares are 0, the BUY formula becomes `(0 × old_avg + q × p) / (0 + q) = p`. The old average is multiplied by 0 and disappears. Example (test "hold reset"): BUY 10 @ 100, SELL 10 @ 120 (realized 200), then BUY 5 @ 200 → avg **200**, not 150.

**中文：** 持股为 0 时，BUY 公式变成 `(0 × 旧平均成本 + q × p) / (0 + q) = p`，旧平均成本乘以 0 后自然消失。例子（测试 "hold reset"）：BUY 10 @ 100，SELL 10 @ 120（已实现 200），再 BUY 5 @ 200 → 平均成本 **200**，而不是 150。

## 4. Precision / 精度

**EN:**
- Inside `fn_position_history`, values stay at full `NUMERIC` precision. For example, 2000 / 15 = 133.3333333333…
- Only `v_holdings` rounds to 2 decimals. Rounding at every step would build up errors over many trades.
- `cost_basis` is computed from the unrounded average: BUY 10 @ 100 + BUY 5 @ 200 → `avg_cost` shows 133.33, but `cost_basis` = **2000.00**, which is what was actually paid. Using the rounded average would give 133.33 × 15 = 1999.95 (test "hold precision").

**中文：**
- 在 `fn_position_history` 内部，所有值都保持 `NUMERIC` 的完整精度，例如 2000 / 15 = 133.3333333333……
- 只有 `v_holdings` 输出时才四舍五入到 2 位小数。如果每一步都四舍五入，交易多了误差会不断累积。
- `cost_basis` 用未四舍五入的平均成本计算：BUY 10 @ 100 + BUY 5 @ 200 → `avg_cost` 显示 133.33，但 `cost_basis` = **2000.00**，正是实际付出的金额。用四舍五入后的平均成本会得到 133.33 × 15 = 1999.95（测试 "hold precision"）。

## 5. Closed positions / 已清仓的持仓

**EN:** A position that has been fully sold stays in the view, because analysis query 4 needs its realized P/L. It's marked as:
- `shares_held = 0`, `is_open = false`
- `avg_cost = NULL`: there's no position, so an average cost would be meaningless and shouldn't be shown as a number
- `cost_basis = 0`
- `realized_pl` kept

The app shows current holdings with `WHERE is_open`. A portfolio with no trades has no rows: holdings exist only for tickers that were traded.

**中文：** 全部卖出的持仓仍然留在视图中，因为分析查询 4 需要它的已实现盈亏。标记方式：
- `shares_held = 0`、`is_open = false`
- `avg_cost = NULL`：没有持仓，平均成本没有意义，不应显示为数字
- `cost_basis = 0`
- 保留 `realized_pl`

程序显示当前持仓时用 `WHERE is_open`。没有交易的 portfolio 没有任何行：只有交易过的股票才有持仓记录。

## 6. Why a function + LATERAL instead of one big view / 为什么用函数 + LATERAL

**EN:** `v_holdings` is `portfolio p CROSS JOIN LATERAL fn_position_history(p.portfolio_id)`. `LATERAL` lets the function use `p.portfolio_id` from the row on its left. With `WHERE portfolio_id = 5`, PostgreSQL first finds that one portfolio row (via `portfolio_pkey`) and then walks only its trades (via `idx_trade_portfolio_date`), as `EXPLAIN` confirmed. A view containing the recursive CTE directly would walk **every** portfolio first, because filters aren't pushed into a recursive CTE.

**中文：** `v_holdings` 是 `portfolio p CROSS JOIN LATERAL fn_position_history(p.portfolio_id)`。`LATERAL` 让函数可以使用左边那一行的 `p.portfolio_id`。加上 `WHERE portfolio_id = 5` 时，PostgreSQL 先通过 `portfolio_pkey` 找到这一个 portfolio，再通过 `idx_trade_portfolio_date` 只处理它的交易（`EXPLAIN` 已确认）。如果直接把递归 CTE 写在视图里，就会先处理**所有** portfolio，因为过滤条件不会被下推到递归 CTE 里。

## 7. Where unrealized P/L will go / 未实现盈亏放在哪里

**EN:** Unrealized P/L needs a price on a chosen date, so it isn't part of this view. Later, a query or function joins `v_holdings` (open rows only) with `daily_price` on that date:
`market_value = shares_held × close` and `unrealized_pl = market_value − cost_basis`.
That's why `cost_basis` is kept exact.

**中文：** 未实现盈亏需要某个日期的价格，所以不放在这个视图里。之后由一个查询或函数把 `v_holdings`（只取持仓中的行）与该日期的 `daily_price` 连接：
`市值 = shares_held × close`，`未实现盈亏 = 市值 − cost_basis`。
这也是 `cost_basis` 要保持精确的原因。

## Tests / 测试

| Case | Expected |
|------|----------|
| BUY 10 @ 100, SELL 5 @ 150, BUY 5 @ 200 | shares 10, avg 150.00, realized 250.00, cost_basis 1500.00 |
| (demo) naive SUM formula | 133.33, so the case above catches it |
| BUY 10 @ 100, SELL 10 @ 120, BUY 5 @ 200 | shares 5, avg 200.00 (fresh), realized 200.00 |
| BUY 10 @ 100, SELL 10 @ 150 | row kept: is_open false, avg NULL, cost_basis 0, realized 500.00 |
| Two tickers | BALT 5 / 100.00 / 100.00; HLDT 2 / 150.00 / 80.00 |
| Same-day BUY then SELL | avg 150.00, realized 0.00 |
| BUY 10 @ 100 + BUY 5 @ 200 | avg 133.33, cost_basis 2000.00 |
| No trades | no rows |
| Cross-check | shares = balance replay, for every portfolio and ticker |
