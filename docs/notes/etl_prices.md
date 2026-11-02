# ETL A: real prices

Files:
- `etl/load_prices.py`: the loader
- `etl/db.py`: connection helper
- `data/tickers.csv`: ticker list
- `tests/test_clean_prices.py`: pytest
- `db/tests/check_prices.sql`: read-only checks
- `Makefile`

## How to run it / 如何运行

```bash
cd ~/projects/5200/Stock-Portfolio-tracker
conda activate spt
cp .env.example .env          # first time only; .env is git-ignored
make test                     # rebuild portfolio_tracker_test, SQL tests + pytest
make load-prices              # load / refresh real prices into portfolio_tracker
make check-prices             # read-only checks on the real data
```
**EN:** Without make, the same commands are `python -m etl.load_prices`, `python -m pytest`, and `psql portfolio_tracker -f db/tests/check_prices.sql`.
**中文：** 不用 make 时，对应的命令是 `python -m etl.load_prices`、`python -m pytest`、`psql portfolio_tracker -f db/tests/check_prices.sql`。

### Tiny example of a run / 运行示例
First run:
```
INFO    AAPL    1464 inserted, 0 skipped (2021-01-01 .. 2026-11-01)
...
Rows inserted:         38064
```
Second run on the same day:
```
INFO    AAPL       0 inserted, 0 skipped (2026-10-31 .. 2026-11-01)
...
Rows inserted:         0
```

---

## 1. Imports / 导入

```python
import csv, logging, math, sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
import yfinance as yf
from etl.db import connect
```

**EN:**
- `import x` loads a module, i.e. another Python file or library. `from x import y` loads just the name `y`, so you can write `date(...)` instead of `datetime.date(...)`. `import yfinance as yf` gives the module a short nickname.
- The first group is the **standard library**, which comes with Python:
  - `csv` reads CSV files.
  - `logging` prints messages with a level such as INFO or WARNING.
  - `math.isnan` checks for "not a number".
  - `sys.exit` sets the program's exit code.
  - `date` / `timedelta` represent a day and a length of time, so `date.today() - timedelta(days=1)` is yesterday.
  - `Decimal` is exact decimal arithmetic. Money should never be a float (0.1 + 0.2 = 0.30000000000000004).
  - `Path` handles file paths.
- Then the installed libraries (`yfinance`), then our own module (`etl.db`).
- `from etl.db import connect` works because `etl/` contains an `__init__.py`, which makes it a **package**. That's why we run `python -m etl.load_prices` (run the module by name) rather than `python etl/load_prices.py`. The `-m` form makes Python start from the repo root, so it can find `etl`.

**中文：**
- `import x` 加载一个模块（另一个 Python 文件或库）；`from x import y` 只引入名字 `y`，于是可以写 `date(...)` 而不是 `datetime.date(...)`。`import yfinance as yf` 给模块起一个简短的别名。
- 第一组是 **标准库**（Python 自带）：
  - `csv` 读取 CSV 文件。
  - `logging` 按级别（INFO、WARNING）打印信息。
  - `math.isnan` 判断是不是"非数字"。
  - `sys.exit` 设置程序的退出码。
  - `date` / `timedelta` 表示日期和时间长度，`date.today() - timedelta(days=1)` 就是昨天。
  - `Decimal` 是精确的十进制运算。金额绝对不能用 float（0.1 + 0.2 = 0.30000000000000004）。
  - `Path` 用来处理文件路径。
- 然后是安装的库（`yfinance`），最后是我们自己的模块（`etl.db`）。
- `from etl.db import connect` 能工作，是因为 `etl/` 里有 `__init__.py`，使它成为一个**包**。所以要用 `python -m etl.load_prices`（按模块名运行），而不是 `python etl/load_prices.py`：`-m` 让 Python 从仓库根目录开始查找，才能找到 `etl`。

## 2. Constants and paths / 常量和路径

```python
TICKER_CSV = Path(__file__).resolve().parent.parent / "data" / "tickers.csv"
FIRST_DATE = date(2021, 1, 1)
CENT = Decimal("0.01")
log = logging.getLogger("load_prices")
```

**EN:**
- `__file__` is the path of this .py file.
- `.resolve()` makes it absolute.
- Each `.parent` goes up one folder: `etl/` → repo root.
- `/` joins path parts. It's not division here; `Path` objects redefine `/`.
- The script therefore finds the CSV no matter which folder you run it from.
- UPPER_CASE names are a convention for "constants, don't change".

**中文：**
- `__file__` 是当前 .py 文件的路径。
- `.resolve()` 把它变成绝对路径。
- 每个 `.parent` 向上一层：`etl/` → 仓库根目录。
- `/` 用来拼接路径（这里不是除法，`Path` 对象重新定义了 `/`）。
- 所以无论从哪个目录运行，脚本都能找到 CSV。
- 全大写的名字是一种约定，表示"常量，不要修改"。

## 3. `.env` and connecting / `.env` 与连接数据库 (`etl/db.py`)

```python
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

def connect(autocommit=True):
    load_dotenv(ENV_FILE)
    params = {"dbname": os.getenv("DB_NAME", "portfolio_tracker"), "user": os.getenv("DB_USER"), ...}
    params = {key: value for key, value in params.items() if value}
    return psycopg.connect(**params, autocommit=autocommit)
```

**EN:**
- **`.env`:** a text file of `NAME=value` lines. `load_dotenv` copies them into the process's environment variables, and `os.getenv("DB_NAME", default)` reads one, falling back to the default if it isn't set.
  - `.env` is in `.gitignore`, so a password put there is never committed. `.env.example` is the committed template with no secrets.
  - The script never prints connection settings, only `conn.info.dbname`.
- **`def connect(autocommit=True):`** defines a function. `autocommit=True` is a default argument: you may call `connect()` or `connect(autocommit=False)`.
- **`{key: value for key, value in params.items() if value}`** is a *dict comprehension*. It builds a new dictionary and keeps only the settings that aren't empty. With an empty setting, libpq uses its own default instead (for example, no password → peer authentication).
- **`psycopg.connect(**params, ...)`:** `**params` unpacks the dict into keyword arguments, the same as writing `psycopg.connect(dbname="portfolio_tracker", host="/var/run/postgresql", autocommit=True)`.
- **Why `DB_HOST=/var/run/postgresql`:** a host that starts with `/` means "Unix socket in this folder". Ubuntu's PostgreSQL puts its socket there, but conda's libpq looks in `/tmp`. The first run failed with "No such file or directory" until this was set.
- **Why `autocommit=True`:** every statement commits on its own, unless it's inside a `with conn.transaction():` block, which commits once at the end or rolls back on error. Without autocommit, psycopg opens a transaction on the first statement and nothing is saved until `conn.commit()`. Mixing that with `conn.transaction()` blocks is a common bug: they quietly become savepoints inside the never-committed outer transaction.

**中文：**
- **`.env`：** 由 `NAME=value` 行组成的文本文件。`load_dotenv` 把它们复制到进程的环境变量中，`os.getenv("DB_NAME", 默认值)` 读取其中一个，没有设置时使用默认值。
  - `.env` 在 `.gitignore` 里，所以放在里面的密码永远不会被提交；`.env.example` 是提交到仓库的模板，不含任何秘密。
  - 脚本从不打印连接参数，只打印 `conn.info.dbname`。
- **`def connect(autocommit=True):`** 定义一个函数。`autocommit=True` 是默认参数：可以调用 `connect()`，也可以调用 `connect(autocommit=False)`。
- **`{key: value for key, value in params.items() if value}`** 是*字典推导式*：生成一个新字典，只保留非空的设置。为空的设置会使用 libpq 自己的默认值（例如没有密码 → peer 认证）。
- **`psycopg.connect(**params, ...)`：** `**params` 把字典展开成关键字参数，等同于 `psycopg.connect(dbname="portfolio_tracker", host="/var/run/postgresql", autocommit=True)`。
- **为什么 `DB_HOST=/var/run/postgresql`：** 以 `/` 开头的 host 表示"这个目录下的 Unix socket"。Ubuntu 的 PostgreSQL 把 socket 放在那里，而 conda 的 libpq 默认去 `/tmp` 找。第一次运行就因为 "No such file or directory" 失败，设置后才解决。
- **为什么 `autocommit=True`：** 每条语句单独提交，除非它在 `with conn.transaction():` 块中，块结束时统一提交，出错则回滚。如果不用 autocommit，psycopg 会在第一条语句时开启事务，直到 `conn.commit()` 之前什么都不会保存；再和 `conn.transaction()` 块混用，就是常见的 bug：这些块会悄悄变成那个永远没提交的外层事务里的保存点。

## 4. Cleaning a row / 清洗一行数据 (`clean_price_row`)

```python
def clean_price_row(ticker, price_date, open_, high, low, close, volume):
    if any(is_missing(v) for v in (open_, high, low, close, volume)):
        return None, "missing value"
    o, h, l, c = (to_cents(v) for v in (open_, high, low, close))
    ...
    if not (l <= o and l <= c and h >= o and h >= c):
        return None, f"range broken: open {o}, ..."
    return (ticker, price_date, o, h, l, c, vol), None
```

**EN:**
- **Returning two values:** `return row, None` actually returns a *tuple* `(row, None)`. The caller unpacks it with `row, reason = clean_price_row(...)`. The convention: exactly one of the two is `None`.
- **`open_` with an underscore:** `open` is a built-in Python function, so the trailing `_` avoids hiding it.
- **`any(... for v in ...)`:** `any` is True if at least one item is True. The `(... for v in ...)` part is a *generator expression*, a lazy loop written inside parentheses.
- **`o, h, l, c = (...)`** unpacks four values at once.
- **`f"... {o} ..."`** is an f-string: `{o}` is replaced by the value of `o`. These are only used for messages, **never for SQL** (see section 6).
- **`to_cents`:** `Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)`.
  - `str()` comes first because `Decimal(100.005)` would copy the float's binary error (100.00499…) and round down to 100.00. `Decimal("100.005")` rounds correctly to 100.01. The unit test `test_to_cents_rounds_half_up_without_float_error` checks this.
- **Same checks as the database, after rounding:** the DB sees the rounded values, so we check those. Rounding never changes the order of two numbers (if low ≤ open before rounding, the same holds after), but the rounded values are what the CHECK constraints actually test.
- **Why check in Python at all?** One bad row would make `executemany` fail for the whole ticker. Checking first lets us skip and log just that row (`WARNING  NVDA   skip 2024-…: range broken …`).
- `is_missing` uses `try: … except TypeError:` because `math.isnan("abc")` raises an error instead of returning False.

**中文：**
- **返回两个值：** `return row, None` 实际上返回一个*元组* `(row, None)`，调用者用 `row, reason = clean_price_row(...)` 拆开。约定：两者中恰好有一个是 `None`。
- **`open_` 带下划线：** `open` 是 Python 的内置函数，加 `_` 避免把它覆盖掉。
- **`any(... for v in ...)`：** 只要有一项为 True，`any` 就返回 True。`(... for v in ...)` 是*生成器表达式*，一种写在括号里的惰性循环。
- **`o, h, l, c = (...)`** 一次拆出四个值。
- **`f"... {o} ..."`** 是 f-string：`{o}` 会被替换成 `o` 的值。只用于提示信息，**绝对不要用于 SQL**（见第 6 节）。
- **`to_cents`：** `Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)`。
  - 先 `str()` 是因为 `Decimal(100.005)` 会带上 float 的二进制误差（100.00499……），结果被舍成 100.00；`Decimal("100.005")` 才能正确进位到 100.01。单元测试 `test_to_cents_rounds_half_up_without_float_error` 检查的就是这一点。
- **与数据库相同的检查，在四舍五入之后进行：** 数据库看到的是四舍五入后的值，所以我们检查这些值。四舍五入不会改变两个数的大小顺序（四舍五入前 low ≤ open，之后依然成立），但 CHECK 约束检查的正是四舍五入后的值。
- **为什么还要在 Python 里检查？** 只要有一行坏数据，`executemany` 就会让整只股票的插入失败。先检查，就能只跳过并记录这一行（`WARNING  NVDA   skip 2024-…: range broken …`）。
- `is_missing` 用 `try: … except TypeError:`，因为 `math.isnan("abc")` 会直接报错，而不是返回 False。

## 5. Reading the CSV / 读取 CSV (`read_tickers`)

```python
with open(csv_path, newline="", encoding="utf-8") as f:
    for line_no, rec in enumerate(csv.DictReader(f), start=2):
        ticker = rec["ticker"].strip().upper()
        sector = rec["sector"].strip() or None
```

**EN:**
- **`with open(...) as f:`** opens the file and closes it automatically when the block ends, even after an error. The same `with` pattern is used for connections, cursors and transactions.
- **`csv.DictReader`** turns each line into a dict keyed by the header: `rec["ticker"]`, `rec["sector"]`, and so on.
- **`enumerate(..., start=2)`** gives a counter with each item. It starts at 2 because line 1 is the header, so error messages show the real line number.
- **`.strip().upper()`** chains string methods: remove surrounding spaces, then uppercase.
- **`x or None`:** an empty string counts as "false", so `"" or None` gives `None` (SQL NULL), while `"Technology" or None` gives `"Technology"`.
- **`raise ValueError(...)`** stops the program with an error message. A broken CSV should stop the load before anything is inserted.

**中文：**
- **`with open(...) as f:`** 打开文件，代码块结束时自动关闭，即使出错也会关闭。连接、游标和事务也使用同样的 `with` 写法。
- **`csv.DictReader`** 把每一行变成以表头为键的字典：`rec["ticker"]`、`rec["sector"]` 等。
- **`enumerate(..., start=2)`** 给每一项附带一个计数器。从 2 开始，因为第 1 行是表头，这样错误信息能显示真实的行号。
- **`.strip().upper()`** 链式调用字符串方法：先去掉两端空格，再转大写。
- **`x or None`：** 空字符串被视为"假"，所以 `"" or None` 得到 `None`（SQL 的 NULL），而 `"Technology" or None` 得到 `"Technology"`。
- **`raise ValueError(...)`** 带着错误信息停止程序。CSV 有问题时应在插入任何数据之前就停止。

## 6. `executemany` and insert-only / `executemany` 与只插入

```python
def insert_prices(conn, rows):
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO daily_price (ticker, price_date, open, high, low, close, volume)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (ticker, price_date) DO NOTHING""",
            rows,
        )
        return cur.rowcount
```

**EN:**
- **`%s` placeholders:** psycopg sends the SQL and the values **separately**, so a value can never be run as SQL. This prevents SQL injection, and it also converts types for us: a Python `Decimal` becomes `NUMERIC` and a `date` becomes `DATE`. Never build SQL with f-strings or `+`.
- **`executemany(sql, rows)`** runs the same statement once for each tuple in `rows`, about 1,464 per ticker. psycopg 3 *pipelines* them, sending them in batches instead of waiting for a reply each time, so 38,064 rows took about 9 s including the downloads.
- **`with conn.transaction(), conn.cursor() as cur:`** opens two `with` blocks in one line. All rows of one ticker are committed together; if anything fails, that ticker is rolled back and the next one still loads.
- **Insert-only, in two layers:**
  1. `last_stored_date` + `start = last + 1 day`: only new dates are downloaded.
  2. `ON CONFLICT (ticker, price_date) DO NOTHING`: if a row already exists anyway, the database silently keeps the old one. It is never updated or duplicated.
  - I tested this on the test DB: inserting 2 existing rows (one with different prices) plus 1 new one gave `rowcount` **1**, and the old close stayed 10.50.
- **`cur.rowcount`:** in psycopg 3, after `executemany` this is the **total** number of rows inserted. Rows skipped by `ON CONFLICT` count as 0.
- **The stock rows work the same way:** `ON CONFLICT (ticker) DO NOTHING`. Changing a company name in the CSV later won't update the DB, which is consistent with insert-only.

**中文：**
- **`%s` 占位符：** psycopg 把 SQL 和值**分开**发送，所以值永远不会被当作 SQL 执行。这能防止 SQL 注入，还会自动转换类型：Python 的 `Decimal` 变成 `NUMERIC`，`date` 变成 `DATE`。绝对不要用 f-string 或 `+` 拼 SQL。
- **`executemany(sql, rows)`** 对 `rows` 中的每个元组执行一次同一条语句（每只股票约 1,464 次）。psycopg 3 会把它们*流水线化*，分批发送而不是每次等待回复，所以连同下载在内，38,064 行只用了约 9 秒。
- **`with conn.transaction(), conn.cursor() as cur:`** 在一行里打开两个 `with` 块。一只股票的所有行一起提交；任何一处失败，这只股票就整体回滚，下一只照常加载。
- **只插入，分两层保证：**
  1. `last_stored_date` + `start = last + 1 天`：只下载新的日期。
  2. `ON CONFLICT (ticker, price_date) DO NOTHING`：即使某行已经存在，数据库也会默默保留旧行，永远不会更新或重复。
  - 我在测试库上验证过：插入 2 条已有记录（其中一条价格不同）加 1 条新记录，`rowcount` 为 **1**，旧的收盘价仍然是 10.50。
- **`cur.rowcount`：** 在 psycopg 3 中，`executemany` 之后它是实际插入的**总**行数，被 `ON CONFLICT` 跳过的行算作 0。
- **股票行同理：** `ON CONFLICT (ticker) DO NOTHING`。以后在 CSV 里改公司名不会更新数据库，这与"只插入"的原则一致。

## 7. The main loop and error handling / 主循环与错误处理 (`main`)

```python
for t in tickers:
    symbol = t["ticker"]
    last = last_stored_date(conn, symbol)
    start = last + timedelta(days=1) if last else FIRST_DATE
    if start > yesterday:
        continue
    try:
        raw = download_prices(symbol, start, yesterday)
    except Exception as e:
        log.error("%-6s download failed: %s", symbol, e)
        failed.append(symbol)
        continue
    ...
```

**EN:**
- **`a if cond else b`** is Python's one-line if/else. Here it means "the day after the last stored date, or 2021-01-01 if nothing is stored yet".
- **`continue`** skips the rest of the loop body and moves on to the next ticker.
- **`try: … except Exception as e:`:** if the download raises any error (network, Yahoo change, rate limit), we log it, remember the ticker in `failed`, and **carry on with the next ticker** instead of crashing. At the end, `return 1 if failed else 0`, and `sys.exit(main())` turns that into the exit code, so `make` notices a failure.
- **Errors we deliberately don't catch:** a broken CSV (`ValueError`) or a wrong DB connection stop the whole script. Those aren't per-ticker problems.
- **`log.info("%-6s %5d inserted", symbol, n)`:** logging uses `%` placeholders. `%-6s` means a string left-aligned in 6 characters, and `%5d` an integer right-aligned in 5, which keeps the columns lined up. The levels are INFO for progress, WARNING for skipped rows, and ERROR for failed tickers.
- **Up to yesterday:** `yesterday = date.today() - timedelta(days=1)`. Today's bar can still change during market hours, and an insert-only loader could never fix it later (your decision). yfinance's `end` is *exclusive*, so `download_prices` passes `yesterday + 1 day`.
- **`if __name__ == "__main__": sys.exit(main())`:** `__name__` is `"__main__"` only when the file is run directly. When pytest *imports* the file to test `clean_price_row`, `main()` doesn't run, so there's no download and no DB access.

**中文：**
- **`a if 条件 else b`** 是 Python 的单行 if/else。这里表示"最后存储日期的下一天；如果还没有存储任何数据，就用 2021-01-01"。
- **`continue`** 跳过本轮循环剩下的部分，直接处理下一只股票。
- **`try: … except Exception as e:`：** 下载出现任何错误（网络、Yahoo 变更、限流）时，记录日志，把股票代码加入 `failed`，然后**继续处理下一只股票**，而不是让程序崩溃。最后 `return 1 if failed else 0`，`sys.exit(main())` 把它变成退出码，`make` 就能发现失败。
- **故意不捕获的错误：** CSV 有问题（`ValueError`）或数据库连接错误会停止整个脚本，因为它们不是单只股票的问题。
- **`log.info("%-6s %5d inserted", symbol, n)`：** logging 使用 `%` 占位符：`%-6s` 表示左对齐、占 6 个字符的字符串，`%5d` 表示右对齐、占 5 位的整数，让各列对齐。级别有：INFO 表示进度，WARNING 表示跳过的行，ERROR 表示失败的股票。
- **只到昨天：** `yesterday = date.today() - timedelta(days=1)`。今天的K线在交易时段还会变化，而只插入的加载器以后无法修正它（这是你的决定）。yfinance 的 `end` 是*不包含*的，所以 `download_prices` 传入 `yesterday + 1 天`。
- **`if __name__ == "__main__": sys.exit(main())`：** 只有直接运行这个文件时，`__name__` 才是 `"__main__"`。pytest *导入*这个文件来测试 `clean_price_row` 时，`main()` 不会运行，所以既不下载数据，也不访问数据库。

## 8. yfinance details / yfinance 细节 (`download_prices`)

**EN:**
- `yf.Ticker(t).history(start, end, auto_adjust=False, actions=False)` returns a pandas DataFrame with one row per day, columns `Open, High, Low, Close, Adj Close, Volume`, and a New York-timezone date index. `ts.date()` keeps just the date.
- With **`auto_adjust=False`**, the OHLC prices are **split-adjusted but not dividend-adjusted**; `Adj Close` (which we ignore) also includes dividends. That's why NVDA shows 120.89 → 121.79 across its 10-for-1 split on 2024-06-10, not a ~10x jump (check 3 in `check_prices.sql`).
- **Known limitation:** if a stock splits *after* we've loaded it, Yahoo re-adjusts the old prices but our stored rows stay as they were, so the history would jump. Splits are out of scope (CLAUDE.md); the fix would be a reload for that ticker.
- `df.iterrows()` loops over the rows as `(index, row)` pairs. It's slow for millions of rows, but fine for about 1,500.

**中文：**
- `yf.Ticker(t).history(start, end, auto_adjust=False, actions=False)` 返回一个 pandas DataFrame：每天一行，列为 `Open, High, Low, Close, Adj Close, Volume`，索引是纽约时区的日期。`ts.date()` 只保留日期部分。
- **`auto_adjust=False`** 时，OHLC 价格**已按拆股调整，但没有按分红调整**（我们不用的 `Adj Close` 还包含了分红调整）。所以 NVDA 在 2024-06-10 一拆十前后是 120.89 → 121.79，而不是相差约 10 倍（`check_prices.sql` 的第 3 项检查）。
- **已知限制：** 如果某只股票在我们加载*之后*才拆股，Yahoo 会重新调整旧价格，而我们已存储的行保持不变，历史数据就会出现跳变。拆股不在项目范围内（见 CLAUDE.md），解决办法是重新加载这只股票。
- `df.iterrows()` 按 `(索引, 行)` 逐行遍历。对几百万行来说很慢，但约 1,500 行完全没问题。

## 9. Tests / 测试

| What | Where | Result |
|---|---|---|
| Cleaning and rounding (valid rows, half-up rounding, low > open, close > high, NaN, None, low rounds to 0, negative volume) and CSV parsing | `tests/test_clean_prices.py` (pytest, no DB or network) | 16 passed |
| All SQL tests on **portfolio_tracker_test** | `make test` | 265 passed; the run now exits with an error if any test fails |
| Every CSV ticker has prices; ^GSPC is an INDEX with rows; NVDA split; date range | `make check-prices` (READ ONLY, real DB) | 5/5 PASS |
| Second run inserts 0 rows | `make load-prices` again | `Rows inserted: 0` |
| `ON CONFLICT` keeps old rows, `rowcount` counts only new ones | manual check on the test DB | 1 inserted, old close unchanged |

**EN (pytest syntax):** each `def test_...():` is one test. `assert x == y` fails the test if it's false. `with pytest.raises(ValueError, match="..."):` passes only if the code inside raises that error with that text. `tmp_path` is a fresh temporary folder that pytest provides, used here to write small CSV files.
**中文（pytest 语法）：** 每个 `def test_...():` 是一个测试。`assert x == y` 不成立时测试失败。`with pytest.raises(ValueError, match="..."):` 只有当里面的代码抛出该错误且信息匹配时才通过。`tmp_path` 是 pytest 提供的全新临时目录，这里用来写入小 CSV 文件。
