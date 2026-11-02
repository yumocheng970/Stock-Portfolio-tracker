# Trigger 2d: date order and "never below zero"

File: `db/programmability/04_balance_checks.sql` · Tests: "bal ..." in `db/tests/test_schema.sql`

| Piece | Kind | Job |
|-------|------|-----|
| `fn_portfolio_history(id)` | SQL function | Every event of a portfolio, in order, with running cash and shares |
| `fn_check_portfolio_history(id)` | PL/pgSQL | Raises at the **first** point where cash or shares < 0 |
| `trg_trade_date_order`, `trg_cash_txn_date_order` | BEFORE INSERT | Lock the portfolio; check the date |
| `trg_trade_history_check` (INSERT/UPDATE/DELETE), `trg_cash_txn_history_check` (INSERT) | AFTER | Lock the portfolio; replay the history |

Error names (Python reads `e.diag.constraint_name`):
- `trg_date_before_start`
- `trg_date_before_latest`
- `trg_cash_txn_future_date`
- `trg_cash_never_negative`
- `trg_shares_never_negative`

## 1. The replay: running totals with window functions / 重放：用窗口函数计算累计值

### Tiny example / 小例子
Start 1000. d1 BUY 5 @ 100, d2 SELL 5 @ 100, d3 BUY 9 @ 100.

| date | event | cash_delta | cash_after | share_delta | shares_after |
|------|-------|-----------:|-----------:|------------:|-------------:|
| d1 | BUY 5  | −500 | 500  | +5 | 5 |
| d2 | SELL 5 | +500 | 1000 | −5 | 0 |
| d3 | BUY 9  | −900 | 100  | +9 | 9 |

Delete the d2 SELL and replay:

| date | event | cash_after | shares_after |
|------|-------|-----------:|-------------:|
| d1 | BUY 5 | 500 | 5 |
| d3 | BUY 9 | **−400** ← first negative | 14 |

→ `trg_cash_never_negative`, DETAIL `Cash would be -400.00 on 2024-01-04, after trade N (BUY 9 BALT @ 100.00).`

### How the SQL works / SQL 如何工作

```sql
WITH events AS (
    SELECT txn_date, 0 AS event_order, ... FROM cash_transaction ...   -- cash rows
    UNION ALL
    SELECT trade_date, 1, ...            FROM trade ...                -- trade rows
)
SELECT ...,
       p.starting_cash + SUM(cash_delta) OVER w_all    AS cash_after,
       SUM(share_delta)                  OVER w_ticker AS shares_after
...
WINDOW w_all    AS (ORDER BY event_date, event_order, event_id ROWS UNBOUNDED PRECEDING),
       w_ticker AS (PARTITION BY ticker ORDER BY ... ROWS UNBOUNDED PRECEDING)
```

**EN:**
- `UNION ALL` stacks cash rows and trade rows into one list of events with the same columns. Each row gets a `cash_delta` (+deposit, −withdrawal, −buy, +sell) and a `share_delta` (+buy, −sell).
- `event_order` 0 for cash and 1 for trades puts cash transactions first on the same date.
- `SUM(...) OVER (ORDER BY ...)` is a **window function**. Unlike `GROUP BY`, it doesn't collapse rows: each row keeps its own values and also gets "the sum of all rows up to here". That's a running total.
- `ROWS UNBOUNDED PRECEDING` means "from the first row up to the current row". Without it, PostgreSQL's default frame (`RANGE`) would include rows that tie on the ORDER BY key. Our key is unique, so the result is the same, but `ROWS` states the intent.
- `PARTITION BY ticker` restarts the running total for each ticker, so AAPL shares and BALT shares are counted separately. Cash rows have `ticker NULL`, form their own partition and are ignored for shares.
- `fn_check_portfolio_history` keeps only the rows where something is negative and takes the first one in history order (`ORDER BY … LIMIT 1`). That row's date and amount go into DETAIL. A BUY or WITHDRAWAL can only lower cash and a SELL can only lower shares, so one event never breaks both rules.

**中文：**
- `UNION ALL` 把现金记录和交易记录叠成一张列结构相同的"事件表"。每行有 `cash_delta`（存款 +、取款 −、买入 −、卖出 +）和 `share_delta`（买入 +、卖出 −）。
- `event_order` 现金为 0、交易为 1，所以同一天现金交易排在前面。
- `SUM(...) OVER (ORDER BY ...)` 是**窗口函数**。它和 `GROUP BY` 不同，不会把行合并：每一行保留自己的数据，同时得到"从第一行到当前行的总和"，也就是累计值。
- `ROWS UNBOUNDED PRECEDING` 的意思是"从第一行到当前行"。不写的话，默认框架（`RANGE`）会把排序键相同的行一起算进去。我们的排序键是唯一的，结果一样，但写 `ROWS` 意图更清楚。
- `PARTITION BY ticker` 让每只股票的累计值分开计算（AAPL 和 BALT 互不影响）。现金行的 `ticker` 是 NULL，自成一组，计算持股时被忽略。
- `fn_check_portfolio_history` 只保留出现负数的行，并按历史顺序取第一行（`ORDER BY … LIMIT 1`），把它的日期和金额写进 DETAIL。买入或取款只会减少现金，卖出只会减少持股，所以一个事件不会同时违反两条规则。

## 2. Why the replay is an AFTER trigger / 为什么重放用 AFTER 触发器

**EN:** The replay has to see the table **after** the change: after the inserted row exists, the updated row has its new shares, or the deleted row is gone. A BEFORE trigger runs before that. If the AFTER trigger raises, PostgreSQL rolls back the whole statement, including the row change and the `trg_trade_audit` row written by the other AFTER trigger. That's why rejected changes leave no audit rows (tests "rejected … wrote NO trade_audit rows").

**中文：** 重放必须看到修改**之后**的表：插入的行已经存在、修改的行已是新股数、删除的行已经消失。BEFORE 触发器在这之前执行。如果 AFTER 触发器报错，PostgreSQL 会回滚整个语句，包括行的修改和另一个 AFTER 触发器 `trg_trade_audit` 写入的审计行，所以被拒绝的修改不会留下审计记录（测试 "rejected … wrote NO trade_audit rows"）。

## 3. Date order (BEFORE INSERT) / 日期顺序（BEFORE INSERT）

**EN:**
- One function, `fn_event_date_order`, serves both tables. `TG_TABLE_NAME` says which table fired it.
- It uses `IF` instead of `CASE` to read `NEW.trade_date` / `NEW.txn_date`, because only the branch that actually runs is evaluated, and `cash_transaction` has no `trade_date`.
- Checks, in order:
  1. date < `start_date` → `trg_date_before_start`
  2. date < `GREATEST(latest trade date, latest cash date)` → `trg_date_before_latest`. `GREATEST` ignores NULLs, and a new portfolio gives NULL, so nothing fires.
  3. cash only: date > `CURRENT_DATE` → `trg_cash_txn_future_date`
- Only INSERT is checked: trigger 1 already forbids changing `trade_date`, and cash transactions can't be updated at all.
- In a multi-row INSERT, each row's BEFORE trigger sees the rows inserted before it in the same statement, so rows out of order are rejected (test "multi-row INSERT out of order").

**中文：**
- 一个函数 `fn_event_date_order` 同时服务两张表，`TG_TABLE_NAME` 表示是哪张表触发的。
- 用 `IF` 而不是 `CASE` 读取 `NEW.trade_date` / `NEW.txn_date`，因为只有实际执行的分支才会被求值，而 `cash_transaction` 没有 `trade_date` 列。
- 检查顺序：
  1. 日期 < `start_date` → `trg_date_before_start`
  2. 日期 < `GREATEST(最新交易日期, 最新现金日期)` → `trg_date_before_latest`。`GREATEST` 忽略 NULL；新 portfolio 得到 NULL，不会报错。
  3. 仅现金：日期 > `CURRENT_DATE` → `trg_cash_txn_future_date`
- 只检查 INSERT：触发器 1 已经禁止修改 `trade_date`，现金交易则完全不能修改。
- 一条语句插入多行时，每一行的 BEFORE 触发器都能看到同一语句中之前插入的行，所以顺序错乱的行会被拒绝（测试 "multi-row INSERT out of order"）。

## 4. The lock: why two concurrent trades can't both pass / 锁：为什么两个并发交易不会都通过

Timeline. The portfolio has 1000 cash; A buys 800 and B buys 500 (this was actually run with two psql sessions):

```
A: BEGIN; INSERT BUY 800  -> BEFORE trigger: SELECT ... FOR UPDATE  (A gets the lock)
                          -> AFTER trigger: replay, cash 200 >= 0, OK
B:        INSERT BUY 500  -> BEFORE trigger: SELECT ... FOR UPDATE  ... WAITS for A
A: COMMIT                                                      (lock released)
B:                        -> lock acquired; next query sees A's trade
                          -> AFTER trigger: replay, cash 1000 - 800 - 500 = -300 -> ERROR
```

**EN:**
- `FOR UPDATE` locks the portfolio row until the end of the transaction, so a second transaction on the **same** portfolio waits. Other portfolios aren't affected.
- Without the lock, B's replay wouldn't see A's uncommitted trade. Both would pass, and cash would end at −300.
- This relies on **READ COMMITTED**, PostgreSQL's default: each new query takes a fresh snapshot, so once B gets the lock, its replay sees A's committed row. Under REPEATABLE READ, B would keep its old snapshot and this would not be enough.
- UPDATE/DELETE have no BEFORE date trigger, so the AFTER trigger takes the lock too. Locking again in the same transaction does nothing.

**中文：**
- `FOR UPDATE` 锁住 portfolio 行直到事务结束，所以对**同一个** portfolio 的第二个事务必须等待；其他 portfolio 不受影响。
- 如果没有锁，B 重放时看不到 A 尚未提交的交易，两个都会通过，最终现金变成 −300。
- 这依赖 **READ COMMITTED**（PostgreSQL 默认隔离级别）：每条新查询都取新的快照，所以 B 拿到锁后，重放能看到 A 已提交的行。如果是 REPEATABLE READ，B 会继续用旧快照，这种做法就不够了。
- UPDATE/DELETE 没有 BEFORE 日期触发器，所以 AFTER 触发器也会加锁；同一事务中重复加锁没有任何效果。

## 5. Cascade deletes still work / 级联删除仍然可用

**EN:**
- `DELETE FROM portfolio` (or from investor) removes the portfolio row first. Then the FK's `ON DELETE CASCADE` deletes its trades one by one, and the AFTER trigger fires for each of them.
- By then the portfolio row is gone, so `PERFORM 1 … FOR UPDATE` finds nothing (`NOT FOUND`) and the trigger returns without replaying. Otherwise, deleting the BUY before the SELL could look like "shares < 0" halfway through.
- Audit rows are still written for every trade (test "2 DELETE audit rows written").

**中文：**
- `DELETE FROM portfolio`（或删除 investor）会先删除 portfolio 行，然后外键的 `ON DELETE CASCADE` 逐条删除它的交易，每删一条都会触发 AFTER 触发器。
- 这时 portfolio 行已经不存在，`PERFORM 1 … FOR UPDATE` 找不到行（`NOT FOUND`），触发器直接返回，不做重放。否则先删 BUY、后删 SELL 的中间状态可能被误判为"持股 < 0"。
- 每笔交易仍然会写入审计记录（测试 "2 DELETE audit rows written"）。

## 6. Design choice: one replay for everything / 设计选择：所有情况共用一个重放

**EN:**
- INSERT, UPDATE and DELETE all use the same check, so there's no separate shortcut that could disagree with it.
- The cost is one pass over that portfolio's events per changed row, using `idx_trade_portfolio_date` and `idx_cash_portfolio_date`. That's fine for paper trading.
- **Possible later optimization:** statement-level triggers with transition tables, so an UPDATE of many rows replays each portfolio once instead of once per row.
- `v_cash_balance` is not used by the check, because it only has totals and not the running history. The test "last cash_after = v_cash_balance" uses it as an independent cross-check.

**中文：**
- INSERT、UPDATE、DELETE 都使用同一个检查，没有可能与它不一致的单独捷径。
- 代价是每修改一行，就要扫描一遍该 portfolio 的所有事件（会使用 `idx_trade_portfolio_date` 和 `idx_cash_portfolio_date`），对模拟交易来说没问题。
- **以后可能的优化：** 用语句级触发器加过渡表（transition tables），让一次修改多行的 UPDATE 对每个 portfolio 只重放一次，而不是每行一次。
- 检查不使用 `v_cash_balance`，因为它只有总额，没有累计的历史过程。测试 "last cash_after = v_cash_balance" 用它做独立的交叉验证。

## 7. Behaviour to mention in the report / 报告中值得说明的行为

1. **Same day, cash before trades / 同一天现金优先于交易**
   - **EN:** A withdrawal entered after a same-day SELL can't use that SELL's proceeds, because it's replayed before the SELL (test "WITHDRAWAL 2000 on d3 rejected"). **Decision: keep this rule.** It gives one fixed, simple order for every day.
   - **中文：** 在同一天 SELL 之后录入的取款，不能使用这笔 SELL 的收入，因为重放时取款排在 SELL 前面（测试 "WITHDRAWAL 2000 on d3 rejected"）。**决定：保留这条规则**，每一天都有一个固定、简单的顺序。
2. **Each statement is checked on its own / 每条语句单独检查**
   - **EN:** The check runs at the end of every statement, not at COMMIT. Two statements that are only valid together (for example, changing two trades one after the other) must be done in an order where each step is valid.
   - **中文：** 检查在每条语句结束时进行，而不是在 COMMIT 时。两条只有放在一起才合法的语句（例如先后修改两笔交易），必须按每一步都合法的顺序执行。
3. **Errors on a trading day / 交易日上的报错顺序**
   - **EN:** BEFORE triggers run in name order: `trg_trade_date_order` runs before `trg_trade_validate`. So a trade that is both too early and outside the price range reports the date error.
   - **中文：** BEFORE 触发器按名称顺序执行：`trg_trade_date_order` 先于 `trg_trade_validate`。所以一笔日期太早、价格又超出区间的交易，报的是日期错误。

## Changes to old tests / 对旧测试的修改

**EN:**
- Alice Growth's cash rows moved to 2024-01-02, so that her trades (01-02, 01-03) come after them.
- The 20M withdrawal now expects `trg_cash_never_negative`.
- Trade error tests moved from 01-02 to 01-03, so the date check doesn't fire first.
- The "cash rows still there" count changed from 5 to 4.

**中文：**
- Alice Growth 的现金记录改到 2024-01-02，让她的交易（01-02、01-03）排在它们之后。
- 2000 万的取款现在预期报 `trg_cash_never_negative`。
- 交易错误测试的日期从 01-02 改为 01-03，避免日期检查先报错。
- "现金记录仍然存在"的数量从 5 改为 4。
