# App 2: portfolios / 投资组合

Menu: Investor home → 1 Portfolios → List / Create / Choose → **Portfolio home**:
Summary, Buy, Sell, Deposit cash, Withdraw cash, Rename, Delete.
菜单：投资者主页 → 1 Portfolios → 列表 / 新建 / 选择 → **组合主页**：汇总、买入、卖出、存入、取出、改名、删除。

Run / 运行: `python -m app` (exit with 0 / 用 0 退出).

Files / 文件:
- new / 新增：`app/menus/portfolio_menu.py`, `tests/test_app_portfolio.py`
- changed / 修改：`app/data_access.py` (portfolio, hints, dates, procedures), `app/inputs.py` (`ask_decimal`, `ask_date`), `app/session.py` (chosen portfolio)

---

## 1. Hints, not rules / 只提示，不强制
**EN:** Before a trade the app prints helpful facts, but **Python never decides** whether the trade is allowed:
```
Buy
  Cash available: 10,000.00
  New events must be dated on or after 2025-03-07.
Ticker: DEMO      DEMO: Demo Corp (STOCK), you hold 0 shares, latest price 2025-03-07
Trade date (YYYY-MM-DD) [Enter = 2025-03-07]:    2025-03-07: low 90.00, high 110.00, close 107.00
Price (Enter = that day's close):
  !! Not enough cash. Cash would be -98070.00 on 2025-03-07, after trade 109 (BUY 1000 DEMO @ 107.00).
```
The last line comes from the database. The trigger refuses, `errors.friendly_message` takes our sentence "Not enough cash." and adds the trigger's DETAIL. If Python also checked the cash, the rule would exist twice, and the two versions could disagree, for example about the same-day ordering of cash transactions before trades.

**中文：** 交易前程序会显示有用的信息，但**由数据库而不是 Python 决定**能否交易。最后一行来自数据库：触发器拒绝后，`errors.friendly_message` 用我们的句子 "Not enough cash." 再加上触发器的 DETAIL。如果 Python 也检查现金，规则就写了两遍，两边可能不一致（例如同一天"先现金交易后股票交易"的顺序）。

## 2. The date default (decided) / 日期默认值（已决定）
**EN:**
- At **every** date prompt, Enter = the latest price date, or the portfolio's latest allowed date if that is later.
- In SQL (`da.default_event_date`):
  ```sql
  SELECT GREATEST((SELECT max(price_date) FROM daily_price),
                  (SELECT start_date FROM portfolio WHERE portfolio_id = %(id)s),
                  (SELECT max(trade_date) FROM trade WHERE portfolio_id = %(id)s),
                  (SELECT max(txn_date) FROM cash_transaction WHERE portfolio_id = %(id)s))
  ```
  `GREATEST` ignores NULLs, so with no portfolio (`id` = None → NULL) it is just the latest price date.
- **Why not today?** Prices load only up to yesterday, and new events can't be before the latest event. A deposit dated today would make every later trade need a date ≥ today, and today has no price yet, so trading is blocked until the next load.
- **Example:** prices end on 2025-03-07. A new portfolio gets start date 2025-03-07, and its first buy defaults to 2025-03-07 too, a day with prices. This is a test.

**中文：**
- **所有**日期输入：直接回车 = 最新价格日期；如果组合最近一次事件的日期更晚，就用那个日期。SQL 见上（`GREATEST` 忽略 NULL）。
- **为什么不用今天？** 价格只加载到昨天，新事件又不能早于最近一次事件。今天的一笔存款会让之后的交易都必须 ≥ 今天，而今天还没有价格，所以在下次加载价格之前都无法交易。
- **例子：** 价格到 2025-03-07 为止。新组合的开始日期默认是 2025-03-07，第一笔买入的日期默认也是 2025-03-07，那天有价格。这是一个测试。

---

## 3. New Python features / 新的 Python 知识点

### `Decimal` for money / 用 `Decimal` 表示金额 (`inputs.ask_decimal`)
**EN:**
- `float` is binary and can't store most decimal fractions exactly: `0.1 + 0.2` gives `0.30000000000000004`.
- `Decimal("0.1") + Decimal("0.2")` gives exactly `Decimal("0.3")`. PostgreSQL `NUMERIC` is also exact, and psycopg returns NUMERIC values as `Decimal`, so money stays exact end to end.
- Build it from a **string**, not a float: `Decimal(0.1)` copies the float's error.
- `Decimal("abc")` raises **`decimal.InvalidOperation`**, not ValueError, so that is what `ask_decimal` catches.
- `Decimal("NaN")` and `Decimal("Infinity")` are valid Decimals, so `amount.is_finite()` rejects them.
- `amount.as_tuple().exponent` is the power of ten of the last digit: `1.234` → −3. `< -2` means more than 2 decimals.

**中文：**
- `float` 是二进制的，大多数十进制小数无法精确表示：`0.1 + 0.2` 得到 `0.30000000000000004`。
- `Decimal("0.1") + Decimal("0.2")` 恰好等于 `0.3`。PostgreSQL 的 `NUMERIC` 也是精确的，psycopg 把 NUMERIC 读成 `Decimal`，所以金额从头到尾都是精确的。
- 要用**字符串**创建：`Decimal(0.1)` 会把 float 的误差也带进来。
- `Decimal("abc")` 抛出的是 **`InvalidOperation`**，不是 ValueError，所以 `ask_decimal` 捕获的是它。
- `Decimal("NaN")`、`Decimal("Infinity")` 也是合法的 Decimal，用 `is_finite()` 排除。
- `as_tuple().exponent` 是最后一位的十的幂次：`1.234` → −3，`< -2` 就是超过两位小数。

### Dates / 日期 (`inputs.ask_date`)
**EN:**
- `from datetime import date`. `date.fromisoformat("2025-03-14")` returns `date(2025, 3, 14)`. A bad format **or an impossible day** (`2025-02-30`) raises `ValueError`, and `ask_date` re-asks.
- `default.isoformat()` turns a date back into `"2025-03-07"` for the prompt.
- psycopg converts Python `date` ↔ PostgreSQL `DATE` automatically.

**中文：**
- `date.fromisoformat("2025-03-14")` 得到 `date(2025, 3, 14)`。格式不对**或者日期不存在**（`2025-02-30`）都会抛出 `ValueError`，`ask_date` 就再问一次。
- `isoformat()` 把日期变回文字，显示在提示里。
- psycopg 会自动在 Python 的 `date` 和 PostgreSQL 的 `DATE` 之间转换。

### Conditional expression / 条件表达式
**EN:** `hint = f" [Enter = {default.isoformat()}]" if default else ""` means: *value_if_true* `if` *condition* `else` *value_if_false*, an if/else that produces a value in one line. The same pattern is used in `verb = "Buy" if trade_type == "BUY" else "Sell"`.
**中文：** `A if 条件 else B`：条件成立取 A，否则取 B，一行写完的 if/else，结果是一个值。

### One function, two menu items / 一个函数，两个菜单项 (`lambda`)
**EN:**
```python
("Buy",  lambda s: trade(s, "BUY")),
("Sell", lambda s: trade(s, "SELL")),
```
`run_menu` calls each item as `function(session)`, with exactly one argument. The `lambda` is a tiny function that takes the session and calls `trade` with one extra fixed argument. So Buy and Sell share all their code: the prompts, the hints and the message.
**中文：** `run_menu` 调用菜单项时只传一个参数 `function(session)`。`lambda` 是一个接收 session、再多带一个固定参数去调用 `trade` 的小函数。这样买入和卖出共用全部代码（提示、信息、结果显示）。

### A CALL with an INOUT parameter / 带 INOUT 参数的 CALL (`da.execute_trade`)
**EN:**
```python
row = _fetch_one(conn, "CALL execute_trade(%s, %s, %s, %s, %s, %s, NULL)", (...))
new_id = row["p_trade_id"]
```
A procedure's INOUT parameter comes back as **one result row**, with the parameter's name as the column name. We pass NULL in, and the procedure sets it to the new trade id. Then `get_trade` reads the trade back, so the app can show the price actually used (the close, when you pressed Enter). Both run in the same `with conn.transaction():`.
**中文：** 存储过程的 INOUT 参数会作为**一行结果**返回，列名就是参数名。我们传入 NULL，过程把它设为新的交易 id。然后用 `get_trade` 读回这笔交易，显示实际成交价（回车时就是收盘价）。两步在同一个事务里。

### `sum()` with a start value / 带初始值的 `sum()`
**EN:** `sum((row["market_value"] for row in holdings), Decimal("0"))`. The first argument is a **generator expression**, like a list comprehension in `( )`: it produces the values one by one without building a list. The second argument is the start value. Without it, an empty portfolio gives the int `0`, which wouldn't print as money (`0.00`).
**中文：** 第一个参数是**生成器表达式**（像放在圆括号里的列表推导式，逐个产生值，不建列表）；第二个参数是初始值。没有它的话，空组合的和是整数 `0`，显示不成金额格式 `0.00`。

### Keyword dict parameters in SQL / SQL 中的字典参数
**EN:** `%(id)s` with `{"id": portfolio_id}`: the same value is used four times in `default_event_date` but written once. If `portfolio_id` is `None`, psycopg sends NULL, and `WHERE portfolio_id = NULL` matches nothing, so those subqueries give NULL and `GREATEST` ignores them.
**中文：** `%(id)s` 配 `{"id": …}`：同一个值用了四次，只写一遍。`None` 会变成 NULL，`= NULL` 什么都匹配不到，子查询得到 NULL，被 `GREATEST` 忽略。

### Choosing only your own portfolio / 只能选自己的组合
**EN:** `chosen = [row for row in rows if row["portfolio_id"] == portfolio_id]` is a list comprehension with a **filter** (`if …`). The ID must be one of *this investor's* portfolios, so typing someone else's ID gives "You have no portfolio with ID …".
**中文：** 带**过滤条件**的列表推导式。输入的 ID 必须是*当前投资者自己*的组合，输入别人的 ID 会提示 "You have no portfolio with ID …"。

---

## 4. Tests / 测试 (16 new; 70 pytest + 319 SQL in total)
**EN:**
- The `setup` fixture builds on the `conn` fixture, so **fixtures can use other fixtures**. It adds stock PFT1 with a week of prices, an investor and a portfolio of 10,000, all rolled back afterwards.
- `refused(func, *args)` is a helper: it expects a database error and returns the friendly message.
- Covered:
  - list values; duplicate name → uq message
  - buy at the close, with the summary equal to `v_cash_balance` / `v_holdings`
  - price outside low..high (DETAIL "90.00 to 115.00")
  - overdraw ("Cash would be -90000.00 on 2025-03-03")
  - oversell ("PFT1 shares would be -1")
  - deposit; withdrawal larger than the cash ("-0.01")
  - date before the latest event
  - hints (`price_on`, `ticker_context`, price range)
  - **default dates let a new portfolio trade**; the default follows a later event
  - rename and duplicate rename
  - delete summary counts, cascade, 2 DELETE rows in trade_audit
  - `ask_decimal` / `ask_date` re-asking
- Also run by hand on the test DB: a full scripted session (create → buy → overdraw → oversell → deposit → over-withdraw → summary → delete).

**中文：**
- `setup` fixture 建立在 `conn` fixture 之上（**fixture 可以使用其他 fixture**）：一只有一周价格的股票 PFT1、一个投资者、一个 10,000 的组合，测试结束后全部回滚。
- `refused(func, *args)` 是辅助函数：期望数据库报错，返回友好提示。
- 覆盖的内容见上方英文列表：重名、按收盘价买入并与视图核对、价格超出范围、透支、卖超、存取款、日期早于最近事件、提示信息、**默认日期能让新组合正常交易**、改名、删除及级联、输入函数的重新询问。
- 另外在测试库上手动跑了一遍完整的脚本化操作。

---

## 5. Polish after the first test run / 第一次试用后的改进
**EN:**
1. **Enter with no default says why.** `ask_date(..., no_default_reason="no prices are loaded yet")` prints "A date is required: no prices are loaded yet." instead of "Please type a real date".
2. **Dates without leading zeros.** `parse_date` uses a **regular expression** (`re` module):
   ```python
   DATE_PATTERN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
   match = DATE_PATTERN.fullmatch("2026-11-6")    # None if it doesn't match
   year, month, day = (int(part) for part in match.groups())   # ("2026", "11", "6") -> 2026, 11, 6
   date(year, month, day)                          # ValueError for 2025-2-30
   ```
   - `\d{4}` = exactly 4 digits, `\d{1,2}` = 1 or 2 digits, and `( )` = a group we can read back with `groups()`.
   - `fullmatch` requires the **whole** text to match, so `2026-1-5x` is rejected.
   - `r"..."` is a raw string: backslashes are kept as they are (needed for `\d`).
   - `date.fromisoformat` would reject `2026-11-6`, which is why we parse ourselves.
3. **Unknown ticker is asked again at once.** `ask_ticker(session)` loops until the ticker is in the stock list and is not an INDEX. Enter returns `None`, which means cancel. It is still only a hint: the database checks again in `execute_trade`.
4. **One line for the no-price error.** `errors.DETAIL_REPLACES_MESSAGE = {"exec_no_price_data", "exec_missing_input"}`. For these names only the DETAIL is shown ("No price for AAPL on 2026-10-03 (not a trading day, or unknown ticker)."), because it already says everything, more precisely. Other trigger errors still show message + DETAIL.
5. **Extra: read-only mode.** `make run-readonly` starts the app with `PGOPTIONS='-c default_transaction_read_only=on'`. **`PGOPTIONS`** is an environment variable that libpq (the C library under psycopg and psql) sends to the server when connecting: here it makes every transaction read-only. The start screen says "READ-ONLY mode", and any change gives "The database is in read-only mode: nothing was changed." (SQLSTATE 25006). It is safe for demos on real data.

New tests (16): `tests/test_app_polish.py`. **`@pytest.mark.parametrize`** runs one test function once per row of example inputs (3 good dates, 6 bad ones), and each row is reported as its own test.

**中文：**
1. **没有默认值时直接回车，会说明原因**："A date is required: no prices are loaded yet."，而不是"请输入正确的日期"。
2. **日期可以不补零**：`parse_date` 用**正则表达式**（`re` 模块）。`\d{4}` 表示 4 位数字，`\d{1,2}` 表示 1 到 2 位，括号是可以用 `groups()` 取回的分组；`fullmatch` 要求**整段**文字都匹配；`r"..."` 是原始字符串，反斜杠保持原样。`date.fromisoformat` 不接受 `2026-11-6`，所以我们自己解析。
3. **未知股票代码会立刻重新询问**：`ask_ticker` 一直循环，直到代码在股票表里、而且不是指数。直接回车返回 `None` 表示取消。这仍然只是提示，`execute_trade` 时数据库还会再检查。
4. **"没有价格"的错误只显示一行**：对 `DETAIL_REPLACES_MESSAGE` 里的名字只显示 DETAIL，因为它已经把事情说全了，而且更具体。其他触发器错误仍然显示"提示 + DETAIL"。
5. **额外：只读模式**。`make run-readonly` 用 `PGOPTIONS` 启动程序。`PGOPTIONS` 是一个环境变量，libpq（psycopg 和 psql 底层的 C 库）在连接时把它发给服务器，这里让每个事务都是只读的。开始界面会显示 READ-ONLY，任何修改都会得到友好提示（SQLSTATE 25006），适合用真实数据做演示。

新测试 16 个，在 `tests/test_app_polish.py`。**`@pytest.mark.parametrize`** 让同一个测试函数对每组示例输入各跑一次（3 个正确日期、6 个错误日期），每组都单独报告结果。
