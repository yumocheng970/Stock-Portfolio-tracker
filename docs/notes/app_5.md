# App 5: reports / 报表

Menu: Portfolio home → **5 Reports** → 1 Monthly return vs S&P 500, 2 Sector allocation, 3 P/L per holding. Main menu → **2 Market data** → 1 Top movers.
菜单：组合主页 → **5 Reports** → 月度收益对比标普 500 / 行业配置 / 每只持仓的盈亏。主菜单 → **2 Market data** → 涨跌幅榜。

Files / 文件:
- new / 新增：`app/menus/reports_menu.py`, `app/menus/market_menu.py`, `app/menus/common.py` (shared prompts moved here / 共用的输入函数搬到这里), `tests/test_app_reports.py` (21 tests)
- changed / 修改：`app/data_access.py` (4 wrappers / 4 个包装函数), `app/display.py` (`format_pct`, `round2`, `percent=`), `app/inputs.py` (`ask_month`), the menus (Reports, Market data)

Each report shows exactly what its SQL function returns (a test per report). Python only formats it and adds the summary line.
每个报表显示的就是对应 SQL 函数返回的内容（每个报表一个测试）；Python 只负责格式化和加上汇总行。

---

## New Python features only / 只讲新的 Python 知识点

### 1. The sign in a format spec / 格式说明里的正负号: `f"{value:+.2f} %"`
**EN:**
- After the `:` comes the **format spec**: `+` = always show the sign, `.2f` = 2 decimals.
- `12.3` → `"+12.30 %"` and `-1` → `"-1.00 %"`.
- `format_pct(value, signed=False)` leaves out the `+` for shares of a whole (sector allocation: `"54.30 %"`).
- `None` → `"n/a"` (a month whose return can't be computed).

**中文：**
- `:` 后面是**格式说明**：`+` 表示总是显示正负号，`.2f` 表示两位小数。
- `12.3` → `"+12.30 %"`，`-1` → `"-1.00 %"`。
- 占整体的比例（行业配置）用 `signed=False`，不加 `+`：`"54.30 %"`。
- `None` 显示为 `"n/a"`（某个月的收益无法计算时）。

### 2. Rounding half up / 四舍五入（而不是"银行家舍入"）: `Decimal.quantize`
**EN:**
- A test found that Python formats `Decimal("12.345")` with `.2f` as **`12.34`**. That is "round half to even" (banker's rounding): an exact half goes to the even digit.
- PostgreSQL's `ROUND` and our price loader round half **up** (`12.35`).
- `display.round2` makes the app do the same:
  ```python
  from decimal import ROUND_HALF_UP, Decimal
  Decimal("12.345").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)   # Decimal("12.35")
  ```
  `quantize(Decimal("0.01"))` means "round to the same number of places as 0.01", which is 2 decimals.

**中文：**
- 测试发现 Python 用 `.2f` 格式化 `Decimal("12.345")` 得到 **`12.34`**。这叫"四舍六入五成双"（银行家舍入）：正好是 5 时舍入到偶数。
- PostgreSQL 的 `ROUND` 和价格加载程序都是**四舍五入**（`12.35`）。
- `display.round2` 让程序与数据库一致：`quantize(Decimal("0.01"))` 表示"舍入到和 0.01 一样的位数"，也就是两位小数。

### 3. Date arithmetic / 日期运算: `timedelta`
**EN:**
- `from datetime import timedelta`. `timedelta(days=30)` is a *length of time*, not a date.
- `date - timedelta` gives another date: `date(2026, 10, 30) - timedelta(days=30)` → `date(2026, 9, 30)`. That is the default start date for top movers.
- Comparing dates works with `<` like numbers: `if end < start:`.

**中文：**
- `timedelta(days=30)` 表示*一段时间*，不是日期。
- 日期减去 timedelta 得到另一个日期：`date(2026, 10, 30) - timedelta(days=30)` → `date(2026, 9, 30)`，这就是涨跌幅榜默认的开始日期。
- 日期之间可以像数字一样用 `<` 比较。

### 4. `date.replace` and `strftime` / 替换日期字段与格式化
**EN:**
- `prices["last"].replace(day=1)` returns a **new** date with only the day changed: `2026-10-30` → `2026-10-01`, the first day of the latest price month (the to-month default). Dates can't be changed in place; `replace` makes a copy.
- `row["month"].strftime("%Y-%m")` → `"2026-10"`. `%Y` = 4-digit year, `%m` = 2-digit month.

**中文：**
- `replace(day=1)` 返回一个只改了"日"的**新**日期：`2026-10-30` → `2026-10-01`，即最新价格所在月份的第一天（"到哪个月"的默认值）。日期本身不能修改，`replace` 是复制一份。
- `strftime("%Y-%m")` 把日期格式化成 `"2026-10"`：`%Y` 四位年份，`%m` 两位月份。

### 5. `x or default` / 用 `or` 给默认值
**EN:**
```python
to_month = ask_month("To month", to_text) or to_default
```
- `a or b` gives `a` if `a` is "truthy", otherwise `b`.
- `ask_month` returns `None` for Enter, and `None` is falsy, so Enter → `to_default`. A typed month (a date) is truthy, so it is kept.
- Careful: `0`, `""` and empty lists are falsy too, so use this only when those can't be real answers.

**中文：**
- `a or b`：`a` 为"真值"就取 `a`，否则取 `b`。
- 直接回车时 `ask_month` 返回 `None`（假值），于是得到默认值；输入的月份（一个日期）是真值，保持不变。
- 注意：`0`、`""`、空列表也是假值，只有在它们不可能是正常答案时才能这样写。

### 6. A dict comprehension / 字典推导式 (`pl_totals`)
**EN:**
```python
{key: sum((row[key] for row in rows), Decimal("0"))
 for key in ("unrealized_pl", "realized_pl", "total_pl")}
```
- Like a list comprehension, but it builds a **dict**: `{key: value for …}`. One line gives all three totals.
- `Decimal("0")` as `sum`'s start value keeps the totals exact Decimals (see App 2).

**中文：**
- 和列表推导式类似，但生成的是**字典**：`{键: 值 for …}`，一行算出三个合计。
- `sum` 的初始值用 `Decimal("0")`，合计仍是精确的 Decimal（见 App 2）。

### 7. Testing a whole menu screen / 测试一整个菜单画面: monkeypatch + capsys
**EN:**
```python
fake_input(monkeypatch, ["", ""])          # Enter at "As of", Enter at "press Enter"
reports_menu.pl_report(session)            # the real menu function, on the test DB
assert "No holdings yet as of 2025-06-30." in capsys.readouterr().out
```
- `monkeypatch` replaces `input()` with prepared answers, and `capsys` captures everything printed. The menu function runs unchanged.
- `monkeypatch.setattr(da, "top_movers", must_not_be_called)` temporarily replaces a data-access function with one that fails the test if it is called. That proves the "end before start" check stops *before* the database. pytest puts the original back after the test.

**中文：**
- `monkeypatch` 把 `input()` 换成预先准备好的答案，`capsys` 捕获所有打印的内容，菜单函数本身完全不改。
- `monkeypatch.setattr(da, "top_movers", must_not_be_called)` 临时把一个数据访问函数换成"一旦被调用就让测试失败"的函数，证明"结束日期早于开始日期"的检查在访问数据库**之前**就停下了。测试结束后 pytest 会自动恢复原函数。

### 8. Avoiding a circular import / 避免循环导入
**EN:**
- `portfolio_menu` imports `reports_menu` (for its menu item), and the reports need `ask_event_date`, which used to live in `portfolio_menu`. Two modules importing each other is a **circular import**, and Python may find one of them only half loaded.
- The fix: the shared prompts moved to `app/menus/common.py`, which imports no menu module. `portfolio_menu` imports them from there, so `from app.menus.portfolio_menu import ask_ticker` (used by older tests) still works.

**中文：**
- `portfolio_menu` 导入 `reports_menu`（为了菜单项），而报表又需要原来写在 `portfolio_menu` 里的 `ask_event_date`。两个模块互相导入叫**循环导入**，Python 可能会遇到其中一个只加载了一半。
- 解决办法：把共用的输入函数搬到 `app/menus/common.py`，它不导入任何菜单模块。`portfolio_menu` 从那里导入，所以旧测试里的 `from app.menus.portfolio_menu import ask_ticker` 仍然可用。

---

## Tests / 测试
**EN:**
- 21 new pytest tests:
  - the 4 wrappers equal their SQL functions
  - the cumulative line = the last row (+ "beat" / "trailed" verdicts)
  - the to-month default = the latest price month (the current month never appears)
  - P/L totals = the sum of the rows, with a closed position
  - an empty portfolio gets messages, not errors
  - sector allocation before the start date
  - top movers: end before start (the DB is never called), a normal range with an empty losers side, the default dates
  - `format_pct`, `ask_month`, rounding half up
- Totals: 338 SQL + 128 pytest.
- Also run read-only on the real DB (fingerprint unchanged).

**中文：**
- 新增 21 个 pytest 测试，覆盖上面列出的情况。
- 合计：SQL 338 个 + pytest 128 个。
- 另外在真实库上用只读模式运行过（指纹不变）。
