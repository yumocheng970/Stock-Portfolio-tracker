# execute_trade()

File: `db/programmability/05_execute_trade.sql` · Tests: "exec: ..." in `db/tests/test_schema.sql`

```sql
CALL execute_trade(portfolio_id, ticker, trade_type, shares, trade_date, price, NULL);
--                                                                       ^ NULL = use that day's close
--                                                                              ^ INOUT: gets the new trade_id
```

## Tiny example / 小例子

```sql
CALL execute_trade(12, ' balt ', 'buy', 5, '2024-01-03', NULL, NULL);
```
```
 p_trade_id
------------
         57
```
**EN:** The procedure stored the trade as `BALT` / `BUY` / 5 shares @ **150.00**, that day's close, because no price was given, and returned the new id 57.
**中文：** 存入的交易是 `BALT` / `BUY` / 5 股 @ **150.00**（没有给价格，所以使用当天收盘价），并返回新的 id 57。

## What it does, in order / 执行步骤

| Step | What | Error if it fails |
|------|------|-------------------|
| 1 | Normalize: `upper(btrim(...))`; blank → NULL | – |
| 2 | Required inputs present? | `exec_missing_input`, DETAIL `Missing: shares, trade_date.` |
| 3 | No price → look up the close for (ticker, date) | `exec_no_price_data` |
| 4 | `INSERT INTO trade … RETURNING trade_id INTO p_trade_id` | errors from triggers and constraints, unchanged (see below) |

**Errors that pass through from step 4, without being re-checked:**

| Error | Comes from |
|-------|------------|
| `trg_date_before_start`, `trg_date_before_latest` | 2d date trigger |
| `trg_trade_not_index`, `trg_trade_price_in_range` | trigger 1 |
| `chk_trade_type`, `chk_trade_shares`, `chk_trade_price` | CHECK constraints |
| `fk_trade_portfolio`, `fk_trade_daily_price` | foreign keys |
| `trg_cash_never_negative`, `trg_shares_never_negative` | 2d replay |

**EN:**
- **Why only two new errors?** Every other rule already lives in the database, and duplicating it would mean two places to keep in sync.
- Step 2 is needed because a NOT NULL error (SQLSTATE 23502) has **no constraint name**, so Python couldn't map it to a friendly message.
- Step 3 is needed because without a price there would be nothing to insert, so the FK can't report the problem.
- The procedure has no lock of its own: the 2d triggers lock the portfolio row.

**中文：**
- **为什么只新增两个错误？** 其他规则已经在数据库里了，重复写就要维护两份一致的逻辑。
- 第 2 步是必要的：NOT NULL 错误（SQLSTATE 23502）**没有约束名**，Python 无法映射成友好提示。
- 第 3 步是必要的：没有价格就没有值可以插入，外键也就无法报告这个问题。
- 过程本身不加锁：2d 触发器已经锁住了 portfolio 行。

### Two small PL/pgSQL tricks / 两个小技巧
**EN:**
- `NULLIF(upper(btrim(p_ticker)), '')`:
  - `btrim` removes spaces at both ends.
  - `upper` makes the text uppercase.
  - `NULLIF(x, '')` turns an empty string into NULL, so `'   '` counts as "missing".
- `array_remove(ARRAY[CASE WHEN … THEN 'shares' END, …], NULL)`:
  - Each `CASE` without `ELSE` gives NULL when the input is present.
  - `array_remove` drops those NULLs, so the array holds only the missing names, and one error can list them all.

**中文：**
- `NULLIF(upper(btrim(p_ticker)), '')`：
  - `btrim` 去掉两端空格。
  - `upper` 转成大写。
  - `NULLIF(x, '')` 把空字符串变成 NULL，所以 `'   '` 算作"缺少"。
- `array_remove(ARRAY[CASE WHEN … THEN 'shares' END, …], NULL)`：
  - 没有 `ELSE` 的 `CASE` 在输入存在时得到 NULL。
  - `array_remove` 去掉这些 NULL，数组里只剩缺少的名字，一个错误就能全部列出。

## FUNCTION vs PROCEDURE / 函数与存储过程的区别

| | FUNCTION | PROCEDURE |
|---|---|---|
| How to call | `SELECT f(...)`, can be used inside any query | `CALL p(...)`, a statement of its own |
| Result | a return value (`RETURNS ...`) | no return value; results come back through `INOUT`/`OUT` parameters |
| Transactions | can't `COMMIT`/`ROLLBACK` | **can** `COMMIT`, but only when called outside a transaction block |
| Typical use | compute something (`fn_portfolio_history`) | perform an action (`execute_trade`) |

**EN:**
- We use a PROCEDURE because a trade is an **action**, not a value used inside a query.
- `INOUT p_trade_id` is how a procedure hands back a result: you pass `NULL`, and `CALL` returns a one-row result with the new value.
- We deliberately **don't** COMMIT inside it. The caller decides when the transaction ends, so the Python app can, for example, do a deposit and a trade together and commit both at once.
- I checked that a COMMIT inside a procedure fails with "invalid transaction termination" when it runs inside a transaction block, which is exactly how psycopg calls it by default. All the tests run inside one transaction, so they would fail if someone added a COMMIT.
- **CALL arguments can't contain subqueries** (`CALL execute_trade((SELECT ...), ...)` is an error). Pass values, or functions like `pg_temp.pf(...)`.

**中文：**
- 用 PROCEDURE 是因为交易是一个**动作**，而不是在查询中使用的值。
- `INOUT p_trade_id` 是存储过程返回结果的方式：传入 `NULL`，`CALL` 会返回一行，里面是新的值。
- 我们故意**不**在里面 COMMIT：由调用者决定事务何时结束，例如 Python 程序可以把存款和交易放在一起，一次提交。
- 我验证过：在事务块中执行时，存储过程里的 COMMIT 会报错 "invalid transaction termination"，而 psycopg 默认正是这样调用的。所有测试都在一个事务中运行，如果有人加了 COMMIT，测试会失败。
- **CALL 的参数不能包含子查询**（`CALL execute_trade((SELECT ...), ...)` 会报错）。请传值，或者传 `pg_temp.pf(...)` 这样的函数调用。

## How Python will call it (psycopg 3) / Python 如何调用

```python
import psycopg
from psycopg import errors

FRIENDLY = {
    "trg_cash_never_negative":  "Not enough cash for this trade.",
    "trg_shares_never_negative": "You don't hold enough shares to sell.",
    "trg_trade_not_index":      "Indexes can't be traded.",
    "trg_trade_price_in_range": "Price must be within that day's low and high.",
    "trg_date_before_latest":   "Trades must be entered in date order.",
    "exec_no_price_data":       "No price data for that ticker on that date.",
    "exec_missing_input":       "Please fill in all trade fields.",
    # ... chk_/fk_ names too
}

def make_trade(conn, portfolio_id, ticker, trade_type, shares, trade_date, price=None):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CALL execute_trade(%s, %s, %s, %s, %s, %s, NULL)",
                (portfolio_id, ticker, trade_type, shares, trade_date, price),
            )
            trade_id = cur.fetchone()[0]   # the INOUT p_trade_id
        conn.commit()
        return trade_id
    except (errors.CheckViolation, errors.ForeignKeyViolation) as e:
        conn.rollback()
        name = e.diag.constraint_name
        raise ValueError(FRIENDLY.get(name, e.diag.message_primary)) from e
```

**EN (Python syntax):**
- `%s` placeholders: psycopg sends the values separately from the SQL text, which prevents SQL injection. **Never** build SQL with f-strings.
- `price=None` gives the parameter a default value. Python `None` becomes SQL `NULL`, so the close is used.
- `cur.fetchone()[0]`: `fetchone()` returns one row as a tuple, and `[0]` is its first column, `p_trade_id`.
- `with conn.cursor() as cur:` closes the cursor automatically when the block ends.
- psycopg 3 starts a transaction automatically on the first statement. `conn.commit()` makes the trade permanent; `conn.rollback()` cancels it after an error.
- `except (A, B) as e:` catches either error type. `e.diag.constraint_name` is the constraint name we set with `USING CONSTRAINT = ...`.
- `FRIENDLY.get(name, default)` looks up the friendly text and falls back to PostgreSQL's own message.
- `raise ... from e` keeps the original error attached, which helps with debugging.

**中文（Python 语法）：**
- `%s` 占位符：psycopg 把值和 SQL 文本分开发送，可以防止 SQL 注入。**绝对不要**用 f-string 拼 SQL。
- `price=None` 给参数一个默认值。Python 的 `None` 会变成 SQL 的 `NULL`，于是使用收盘价。
- `cur.fetchone()[0]`：`fetchone()` 以元组形式返回一行，`[0]` 是第一列，也就是 `p_trade_id`。
- `with conn.cursor() as cur:` 在代码块结束时自动关闭游标。
- psycopg 3 在执行第一条语句时自动开始事务。`conn.commit()` 让交易永久生效；出错后用 `conn.rollback()` 取消。
- `except (A, B) as e:` 捕获两种错误中的任意一种。`e.diag.constraint_name` 就是我们用 `USING CONSTRAINT = ...` 设置的约束名。
- `FRIENDLY.get(name, default)` 查找友好提示，找不到时退回 PostgreSQL 自己的错误信息。
- `raise ... from e` 保留原始错误，方便调试。

## Tests / 测试

| Case | Expected |
|------|----------|
| Explicit price BUY 10 @ 120 | returned id = the new row with these values |
| No price, `' balt '` / `' buy '` | price 150.00 (close), stored as `BALT` / `BUY` |
| Views after 2 calls | cash 8050.00; holdings 15 shares, avg 130.00, cost_basis 1950.00 |
| Plain `CALL` statement | works; after SELL 1 → 14 shares, cash 8200.00 |
| Overdraw / ^GSPC / `hold` / shares 0 / weekend + price / bad portfolio | `trg_cash_never_negative` / `trg_trade_not_index` / `chk_trade_type` / `chk_trade_shares` / `fk_trade_daily_price` / `fk_trade_portfolio` |
| No price + weekend, no price + unknown ticker | `exec_no_price_data` |
| NULL shares, blank ticker, NULL trade_type | `exec_missing_input`; DETAIL lists all missing names |
| Rejected calls | no trade rows left |
