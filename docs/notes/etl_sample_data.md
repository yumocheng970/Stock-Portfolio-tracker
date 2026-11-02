# ETL B: sample users

Files:
- `etl/simulate.py`: pure simulation, unit-tested
- `etl/seed_sample_data.py`: the seeder
- `db/programmability/06_record_cash_transaction.sql`: the new procedure
- `tests/test_simulate.py`: pytest
- `db/tests/check_sample_data.sql`: read-only checks
- `Makefile`: `seed`, `reseed`, `check-sample-data`

## How to run it / 如何运行

```bash
cd ~/projects/5200/Stock-Portfolio-tracker
conda activate spt
make test               # test DB: SQL tests + pytest
make load-prices        # ETL A, if prices aren't loaded yet
make seed               # add sample users (refuses if investors already exist)
make reseed             # delete ALL users + audit rows, reset ids, seed again
make check-sample-data  # read-only checks + fingerprint
```
**EN:** The same seeder with other options: `python -m etl.seed_sample_data --replace --seed 1`.
**中文：** 同一个脚本也可以带其他参数运行：`python -m etl.seed_sample_data --replace --seed 1`。

### Result with seed 5200 / 种子 5200 的结果
**EN:**
- 15 investors, 30 portfolios, 93 cash transactions, 1,158 trades (1,155 after the audit demo deleted 3), 20 watchlists, 89 items, 31 targets reached.
- trade_audit has 3 UPDATE + 3 DELETE rows.
- The fingerprint is `ea1746ea9890df106c8c9c8df1e38c28` on every run. Seed 1 gives a different one.
- Seeding takes under 1 s.

**中文：**
- 15 位投资者、30 个 portfolio、93 笔现金交易、1,158 笔交易（审计演示删除 3 笔后为 1,155 笔）、20 个关注列表、89 个条目、31 个目标价已达到。
- trade_audit 中有 3 条 UPDATE 和 3 条 DELETE 记录。
- 每次运行指纹都是 `ea1746ea9890df106c8c9c8df1e38c28`；种子 1 得到不同的指纹。
- 整个生成过程不到 1 秒。

---

## 1. The new procedure `record_cash_transaction()` / 新的存储过程

```sql
CALL record_cash_transaction(portfolio_id, 'deposit', 500, '2024-01-02', NULL);   -- returns p_cash_txn_id
```
**EN:**
- It works exactly like `execute_trade()`: trim + uppercase `txn_type`, then `exec_missing_input` (the same name, so Python needs one message) if anything is missing, then one `INSERT … RETURNING`.
- Every other error passes through unchanged: `trg_cash_never_negative`, `trg_date_before_latest`, `trg_date_before_start`, `trg_cash_txn_future_date`, `chk_cash_txn_type`, `chk_cash_amount_positive`, `chk_cash_deposit_cap`, `fk_cash_portfolio`.
- 17 SQL tests ("rcash: …").

**中文：**
- 与 `execute_trade()` 的做法完全相同：先去空格并把 `txn_type` 转大写；缺少输入时报 `exec_missing_input`（同一个名字，Python 只需要一条提示）；最后执行一次 `INSERT … RETURNING`。
- 其他错误都原样传出：`trg_cash_never_negative`、`trg_date_before_latest`、`trg_date_before_start`、`trg_cash_txn_future_date`、`chk_cash_txn_type`、`chk_cash_amount_positive`、`chk_cash_deposit_cap`、`fk_cash_portfolio`。
- 共有 17 个 SQL 测试（"rcash: …"）。

## 2. `etl/simulate.py`: the simulation / 模拟

### 2a. `@dataclass(frozen=True)`
```python
@dataclass(frozen=True)
class Event:
    date: date
    kind: str                      # 'CASH' or 'TRADE'
    type: str                      # DEPOSIT / WITHDRAWAL / BUY / SELL
    ticker: str | None = None
    ...
```
**EN:**
- `class` defines a new type. `@dataclass` is a *decorator*: it writes the boring parts for you, such as `__init__` (so you can call `Event(day, "CASH", "DEPOSIT", amount=...)`), a readable printout, and `==`, which compares all fields. The tests rely on that `==` in `run(42) == run(42)`.
- `frozen=True` means an Event can't be changed after it's created (the test `test_event_is_frozen` checks this). Fewer surprises.
- `str | None = None` is a type hint ("a string or None") with a default value. Python doesn't enforce hints; they're documentation.

**中文：**
- `class` 定义一个新类型。`@dataclass` 是*装饰器*：它自动写好重复的代码，比如 `__init__`（于是可以写 `Event(day, "CASH", "DEPOSIT", amount=...)`）、可读的打印形式，以及比较所有字段的 `==`。测试 `run(42) == run(42)` 就依赖这个 `==`。
- `frozen=True` 表示 Event 创建后不能修改（测试 `test_event_is_frozen` 会检查），减少意外。
- `str | None = None` 是类型提示（"字符串或 None"）加默认值。Python 不会强制检查类型提示，它们相当于文档。

### 2b. Picking the days / 选日子
```python
trade_days = sorted(rng.sample(trading_days, min(n_trades, len(trading_days))))
cash_days = sorted(rng.sample(trading_days, min(n_cash, len(trading_days))))
plan = [(d, 0) for d in cash_days] + [(d, 1) for d in trade_days]
plan.sort()
```
**EN:**
- `rng.sample(list, k)` picks k **different** items, so there's at most one trade per day.
- `[(d, 0) for d in cash_days]` is a *list comprehension*: it builds a list of tuples in one line.
- `plan.sort()` sorts tuples item by item: first by date, then 0 before 1. That puts **cash before trades on the same day**, which is exactly the order the DB replay uses (your rule).

**中文：**
- `rng.sample(list, k)` 选出 k 个**不同**的元素，所以每天最多一笔交易。
- `[(d, 0) for d in cash_days]` 是*列表推导式*：一行代码生成一个元组列表。
- `plan.sort()` 按元组逐项排序：先按日期，再让 0 排在 1 前面。于是**同一天现金在交易之前**，正好与数据库重放的顺序一致（你的规则）。

### 2c. Walking forward with state / 带状态逐日推进
```python
cash = starting_cash
holdings = {}                      # ticker -> shares held
for day, order in plan:
    if order == 0:
        event = _cash_event(rng, day, cash)
        cash += event.amount if event.type == "DEPOSIT" else -event.amount
    else:
        event = _trade_event(rng, day, cash, holdings, closes, tickers)
        ...
```
**EN:**
- `for day, order in plan:` unpacks each tuple into two variables.
- `cash` and `holdings` are the **state**. Each event is chosen *from the current state* and then changes it, the same idea as the recursive CTE in v_holdings.
- **The invariants** (the rules the code never breaks):
  - **BUY:** `budget = cash × (5–25)%`, then `shares = budget // price` (`//` is integer division, so it rounds down). That's never more than the cash. If it gives 0 shares, it buys 1 share *only if* `cash >= price`.
  - **SELL:** only tickers in `held` (shares > 0), and `rng.randint(1, holdings[ticker])` shares, so never more than held.
  - **WITHDRAWAL:** only when cash ≥ 1,000, and at most 30% of the cash.
  - If nothing is affordable and nothing is held, `_trade_event` returns `None` and the day is skipped. This never happened with real data (at least 23 trades per portfolio).
- **`Decimal` everywhere:** the closes come from the DB as `Decimal`, so `shares * price` is exactly what the DB computes. With floats, a portfolio could be 0.0000001 below zero in the DB but not in Python.
- **`sorted(...)` around dict data:** `held = sorted(...)` because `rng.choice` must always see the items in the same order, or the same seed could give different results.
- Function names starting with `_` (`_cash_event`) are "internal helpers" by convention, not meant to be called from outside the module.

**中文：**
- `for day, order in plan:` 把每个元组拆成两个变量。
- `cash` 和 `holdings` 就是**状态**。每个事件都根据*当前状态*决定，然后再更新状态，和 v_holdings 里递归 CTE 的思路一样。
- **不变式**（代码永远遵守的规则）：
  - **买入：** `预算 = 现金 × (5–25)%`，`股数 = 预算 // 价格`（`//` 是整除，向下取整），所以永远不会超过现金。如果算出 0 股，*只有在* `cash >= price` 时才买 1 股。
  - **卖出：** 只从 `held`（持股 > 0）中选股票，股数是 `rng.randint(1, holdings[ticker])`，所以永远不会超过持有量。
  - **取款：** 只有现金 ≥ 1,000 时才取，且最多取现金的 30%。
  - 如果既买不起也没有持股，`_trade_event` 返回 `None`，这一天跳过。用真实数据时从未发生（每个 portfolio 至少 23 笔交易）。
- **处处使用 `Decimal`：** 收盘价从数据库取出时就是 `Decimal`，所以 `shares * price` 与数据库的计算完全一致。如果用 float，可能出现数据库里差 0.0000001 变成负数、而 Python 里没有的情况。
- **对字典数据加 `sorted(...)`：** `held = sorted(...)`，因为 `rng.choice` 必须每次看到相同顺序的元素，否则同一个种子可能得到不同结果。
- 以 `_` 开头的函数名（如 `_cash_event`）按约定表示"内部辅助函数"，不打算在模块外调用。

## 3. Reproducibility / 可重复性: `random.Random(seed)` and Faker

```python
rng = random.Random(args.seed)
fake = Faker("en_US")
fake.seed_instance(args.seed)
```
**EN:**
- `random.Random(seed)` creates **our own** random generator. The same seed always produces the same sequence of numbers. We don't use the global `random.random()`, because any library could also draw from that shared generator and shift our sequence.
- `fake.seed_instance(seed)` does the same for Faker's names.
- **Same data needs** the same seed, the same price data (the simulation stops at the fixed `SIM_END = 2026-10-30`, so later price refreshes don't matter), and the same Faker version (40.40.0). A different Faker version may produce other names.
- **How we proved it:** `check_sample_data.sql` prints an md5 *fingerprint* of every seeded row (ids included, `now()` timestamps excluded). Three runs gave the same value.

**中文：**
- `random.Random(seed)` 创建**我们自己的**随机数生成器：同一个种子永远产生同一串数字。不用全局的 `random.random()`，因为任何库都可能从这个共享的生成器取数，打乱我们的序列。
- `fake.seed_instance(seed)` 对 Faker 生成的名字做同样的事。
- **数据完全相同的前提：** 相同的种子、相同的价格数据（模拟在固定的 `SIM_END = 2026-10-30` 结束，所以以后刷新价格不影响）、相同的 Faker 版本（40.40.0）。Faker 版本不同，名字可能不同。
- **如何证明：** `check_sample_data.sql` 输出所有生成数据的 md5 *指纹*（包含 id，不含 `now()` 时间戳），三次运行结果相同。

## 4. `etl/seed_sample_data.py`, section by section / 逐段讲解

### 4a. Command-line arguments / 命令行参数 (`argparse`)
```python
parser = argparse.ArgumentParser(description="...")
parser.add_argument("--replace", action="store_true", help="...")
parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
args = parser.parse_args(argv)
```
**EN:**
- `argparse` reads options like `--replace --seed 1`. `action="store_true"` means a flag with no value: `args.replace` is `True` if it's given and `False` otherwise. `type=int` converts the text "1" into the number 1.
- You get `--help` for free: `python -m etl.seed_sample_data --help`.
- `main(argv=None)`: with `None`, argparse reads the real command line. A test could pass a list instead, such as `main(["--seed", "3"])`.

**中文：**
- `argparse` 读取 `--replace --seed 1` 这样的选项。`action="store_true"` 表示不带值的开关：给了就是 `args.replace = True`，否则为 `False`。`type=int` 把文本 "1" 转成数字 1。
- 自动获得 `--help`：`python -m etl.seed_sample_data --help`。
- `main(argv=None)`：为 `None` 时 argparse 读取真实的命令行；测试时可以传入列表，例如 `main(["--seed", "3"])`。

### 4b. Safe rerun / 安全重跑
```python
existing = conn.execute("SELECT count(*) FROM investor").fetchone()[0]
if existing and not args.replace:
    log.error("%s investors already exist. Use --replace ...", existing)
    return 1
```
**EN:**
- `conn.execute(...)` is a psycopg 3 shortcut: it creates a cursor, runs the SQL and returns the cursor, so `.fetchone()[0]` reads the first column of the first row.
- A plain `make seed` on a filled DB stops with exit code 1. **Nothing is deleted unless you ask for it.**

**中文：**
- `conn.execute(...)` 是 psycopg 3 的简写：创建游标、执行 SQL 并返回游标，`.fetchone()[0]` 读取第一行第一列。
- 数据库已有数据时，直接 `make seed` 会以退出码 1 停止。**除非你明确要求，否则什么都不会删除。**

### 4c. `--replace` (your decision) / `--replace`（你的决定）
```python
conn.execute("DELETE FROM investor")       # cascades: portfolios, trades, cash, watchlists
conn.execute("DELETE FROM trade_audit")    # incl. the DELETE rows the cascade just wrote
for table, column in IDENTITY_COLUMNS:
    conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN {} RESTART").format(
        sql.Identifier(table), sql.Identifier(column)))
```
**EN:**
- **Deleting investors cascades** down the FKs: portfolio → trade / cash_transaction, and watchlist → watchlist_item. Trigger 2b lets the cascade delete cash rows; trigger 2d skips its replay because the portfolio is already gone. The audit trigger writes one DELETE row per trade, and we remove those on the next line. Stocks and prices aren't touched.
- **`RESTART`** sets an identity column back to 1, so a rerun gets the same ids. That's only safe because all these tables are empty at this point.
- **`sql.SQL(...).format(sql.Identifier(...))`:** table names can't be `%s` parameters (parameters are only for *values*). `sql.Identifier` quotes a name safely. Never paste names into SQL with f-strings.

**中文：**
- **删除投资者会沿外键级联：** portfolio → trade / cash_transaction，watchlist → watchlist_item。触发器 2b 允许级联删除现金记录；触发器 2d 因为 portfolio 已不存在而跳过重放。审计触发器为每笔交易写一条 DELETE 记录，下一行就把它们清除。股票和价格不受影响。
- **`RESTART`** 把自增列重置为 1，重跑时得到相同的 id。只有在这些表此时都为空时才安全。
- **`sql.SQL(...).format(sql.Identifier(...))`：** 表名不能用 `%s` 参数（参数只能用于*值*）。`sql.Identifier` 会安全地给名字加引号。绝对不要用 f-string 把名字拼进 SQL。

### 4d. One transaction for everything / 全部放在一个事务里
```python
market = load_market(conn)            # checked BEFORE the transaction
if not market[1]:
    return 1
try:
    with conn.transaction():
        ... everything ...
except psycopg.Error as e:
    log.error("Seed rolled back. Database error [%s]: %s",
              e.diag.constraint_name or e.sqlstate, e.diag.message_primary)
    return 1
```
**EN:**
- `with conn.transaction():` commits at the end of the block, or **rolls back if an exception leaves the block**.
- So if the database rejects *anything* (a trigger error, a CHECK, a missing procedure), the whole seed disappears and the script exits 1. That's how "no rule violations were skipped" is *guaranteed*: there is no skip.
- This actually happened once during development. The real DB didn't have `record_cash_transaction()` yet, so the first CALL failed and nothing was left behind.
- **Pitfall avoided:** a `return` *inside* `with conn.transaction():` is a normal exit and would **commit**. With `--replace`, that would keep the deletes and seed nothing. That's why the "no prices" check runs before the transaction starts.
- `x or y` gives `y` when `x` is empty or None: the constraint name if there is one, otherwise the SQLSTATE code.

**中文：**
- `with conn.transaction():` 在代码块结束时提交；**如果有异常离开代码块，就回滚**。
- 所以只要数据库拒绝了*任何*操作（触发器错误、CHECK、缺少存储过程），整个生成过程都会撤销，脚本以退出码 1 结束。这就*保证*了"没有跳过任何违反规则的数据"：根本不存在跳过。
- 开发过程中真的发生过一次：真实数据库里还没有 `record_cash_transaction()`，第一次 CALL 失败后什么都没有留下。
- **避开的陷阱：** 在 `with conn.transaction():` *里面* `return` 是正常退出，会**提交**。如果用了 `--replace`，删除操作会被保留，却什么都没生成。所以"没有价格数据"的检查放在事务开始之前。
- `x or y` 在 `x` 为空或 None 时得到 `y`：有约束名就用约束名，否则用 SQLSTATE 代码。

### 4e. Investors, portfolios and CALLs / 投资者、portfolio 和 CALL
```python
first, last = fake.first_name(), fake.last_name()
local = re.sub(r"[^a-z.]", "", f"{first}.{last}".lower())
email = f"{local}{number}@example.com"
...
last_trade_id = conn.execute(
    "CALL execute_trade(%s, %s, %s, %s, %s, NULL, NULL)",
    (portfolio_id, e.ticker, e.type, e.shares, e.date)).fetchone()[0]
```
**EN:**
- `re.sub(pattern, "", text)` deletes every character that isn't a–z or a dot, so "O'Connor" becomes "oconnor".
- The number at the end makes every email unique. `example.com` is a domain reserved for examples, so these are never real people.
- `RETURNING investor_id` + `.fetchone()[0]` gives the new id, which we need for the portfolio rows.
- **Every trade goes through `CALL execute_trade(...)` with price NULL**, so the DB uses the close, exactly as the simulation did. All the triggers run on every trade: date order, price range, no INDEX, the cash/shares replay, and the lock. The seeder is effectively a 1,251-statement end-to-end test of the whole rule set.
- `.fetchone()[0]` after `CALL` reads the INOUT `p_trade_id`. We keep the last one per portfolio for the audit demo.

**中文：**
- `re.sub(pattern, "", text)` 删除所有不是 a–z 或点的字符，所以 "O'Connor" 变成 "oconnor"。
- 末尾的编号保证每个邮箱唯一。`example.com` 是专门保留给示例的域名，不会对应真实的人。
- `RETURNING investor_id` + `.fetchone()[0]` 得到新的 id，创建 portfolio 时要用。
- **每笔交易都通过 `CALL execute_trade(...)`，价格传 NULL**，数据库使用收盘价，与模拟时完全一致。每笔交易都会运行全部触发器：日期顺序、价格区间、禁止交易指数、现金/持股重放和加锁。这个生成脚本实际上是对整套规则进行的 1,251 条语句的端到端测试。
- `CALL` 之后的 `.fetchone()[0]` 读取 INOUT 参数 `p_trade_id`。我们保留每个 portfolio 的最后一个 id，供审计演示使用。

### 4f. Watchlists / 关注列表
**EN:**
- Each investor gets 1–2 watchlists, each with 3–6 tickers (^GSPC allowed: watching an index is fine).
- `rng.random()` gives a number from 0 to 1:
  - below 0.3: the target is 85–99% of the latest close, so it's already **reached**
  - below 0.8: the target is 105–130%, not reached yet
  - otherwise: no target (NULL)
- `ensure_one_reached_target` guarantees analysis query 5 has at least one result. With seed 5200, 31 of 89 items are reached.

**中文：**
- 每位投资者有 1–2 个关注列表，每个列表 3–6 只股票（允许 ^GSPC：关注指数没有问题）。
- `rng.random()` 产生 0 到 1 之间的数：
  - 小于 0.3：目标价是最新收盘价的 85–99%，**已经达到**
  - 小于 0.8：目标价是 105–130%，尚未达到
  - 其余：没有目标价（NULL）
- `ensure_one_reached_target` 保证分析查询 5 至少有一条结果。种子 5200 时，89 个条目中有 31 个已达到。

### 4g. Audit demo: why only the LAST event / 审计演示：为什么只改最后一个事件
```python
conn.execute("UPDATE trade SET shares = shares - 1 WHERE trade_id = %s", (trade_id,))
conn.execute("DELETE FROM trade WHERE trade_id = %s", (trade_id,))
```
**EN:**
- These are plain SQL statements, as you asked. Trigger 2c writes the trade_audit rows, and triggers 1 and 2d still check them.
- **Why only the last event of a portfolio?** Changing a trade in the *middle* of the history can make a later event invalid. For example, deleting a SELL whose cash paid for a later BUY: that's exactly the "delete history" test in the balance tests. With the last event, nothing comes after it:
  - **UPDATE a last BUY to 1 share fewer:** cash goes up, and no later SELL needs that share.
  - **DELETE a last trade:** the portfolio goes back to its state just before that trade, which was already valid.
- `rng.shuffle` picks the portfolios at random but reproducibly. `sorted(...)` first, so the shuffle always starts from the same order.

**中文：**
- 这些是普通的 SQL 语句（按你的要求）。触发器 2c 写入 trade_audit 记录，触发器 1 和 2d 照样检查。
- **为什么只改 portfolio 的最后一个事件？** 修改历史*中间*的交易可能让后面的事件失效，例如删除一笔 SELL，而它的现金支撑了后面的一笔 BUY，这正是余额测试里的 "delete history" 测试。最后一个事件之后没有任何事件：
  - **把最后一笔 BUY 减少 1 股：** 现金增加，后面也没有 SELL 需要这一股。
  - **删除最后一笔交易：** portfolio 回到这笔交易之前的状态，而那个状态本来就是合法的。
- `rng.shuffle` 随机但可重复地挑选 portfolio。先 `sorted(...)`，让打乱总是从相同的顺序开始。

### 4h. Summary output / 汇总输出
```python
print(f"{label + ':':22}{stats[key]}")
```
**EN:** `stats` is a `Counter`, a dict that starts every key at 0, so `stats["trades"] += 1` works without setting it up first. `{text:22}` pads the text to 22 characters so the numbers line up.
**中文：** `stats` 是 `Counter`，一种每个键默认为 0 的字典，所以 `stats["trades"] += 1` 不需要先初始化。`{text:22}` 把文本补齐到 22 个字符，让数字对齐。

## 5. Tests / 测试

| What | Where | Result |
|---|---|---|
| `record_cash_transaction()`: success, normalization, all pass-through errors, missing input | `test_schema.sql` "rcash" (test DB) | 17 new, 282 SQL total, all pass |
| Simulator: never spends more than cash or sells more than held (300 seeds × 3 start amounts), only sells what was bought, DB order, trade count, amounts, tickers, same/different seed, too little cash, frozen Event | `tests/test_simulate.py` | 14 new, 30 pytest total, all pass |
| Mutation check: a broken copy that over-buys | scratch copy | the invariant tests **fail**, as they should |
| After seeding: balances ≥ 0, shares ≥ 0, replay = views, a target is reached, audit has UPDATE + DELETE, 20–60 trades, no INDEX trades | `make check-sample-data` | 9/9 PASS |
| `make seed` twice | | second run refuses, exit 1 |
| `make reseed` twice | fingerprint | identical (`ea1746ea…`); `--seed 1` differs |

**EN (pytest):**
- `@pytest.mark.parametrize("starting_cash", [...])` runs the same test once per value: 3 tests from one function.
- `replay()` in the test file is an **independent** re-calculation. It doesn't reuse the simulator's code, so a bug in the simulator can't hide itself.

**中文（pytest）：**
- `@pytest.mark.parametrize("starting_cash", [...])` 对每个值各运行一次同一个测试，一个函数得到 3 个测试。
- 测试文件中的 `replay()` 是**独立**的重新计算，不复用模拟器的代码，所以模拟器的 bug 无法自我掩盖。
