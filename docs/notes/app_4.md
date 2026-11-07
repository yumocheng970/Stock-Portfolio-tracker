# App 4: watchlists / 关注列表

Menu: Investor home → **2 Watchlists** → 1 List my watchlists, 2 Create, 3 Choose → **Watchlist home** (1 List items, 2 Add item, 3 Edit target, 4 Remove item, 5 Rename, 6 Delete), 4 Targets reached (all my watchlists).
菜单：投资者主页 → **2 Watchlists** → 列表 / 新建 / 选择 → **关注列表主页**（列出、添加、改目标价、移除、改名、删除）/ 已达目标价（我所有的关注列表）。

Files / 文件:
- new / 新增：`app/menus/watchlist_menu.py`, `tests/test_app_watchlist.py` (10 tests)
- changed / 修改：`app/data_access.py`, `app/inputs.py` (`CLEAR`), `app/session.py` (chosen watchlist), `app/menus/portfolio_menu.py` (`ask_ticker(..., allow_index=...)`), `app/menus/investor_menu.py`

"Reached" always comes from `fn_watchlist_targets_reached` (analysis query 5), so the screens and the report use one definition. `^GSPC` may be added: watching is fine, only trading an index is blocked.
"已达目标价"一律来自 `fn_watchlist_targets_reached`（分析查询 5），所以界面和报告用的是同一个定义。`^GSPC` 可以加入关注列表：关注没问题，只有交易指数被禁止。

---

## New Python features only / 只讲新的 Python 知识点

### 1. A sentinel object / 哨兵对象: `CLEAR = object()` (`app/inputs.py`)
**EN:**
- "Edit target" needs **three** different answers: Enter = keep, a number = set, `none` = clear.
- `None` already means "keep", and a number means "set", so "clear" needs a third value that can't be mistaken for either. `object()` creates a brand-new, unique object, and we keep it in the name `CLEAR`.
- `ask_decimal(..., clear_word="none")` returns that exact object when the user types `none` (in any case: `answer.lower()`).
- The caller checks it with **`is`**, which means "the very same object", not just "equal":
  ```python
  target = ask_decimal("New target (Enter = keep, 'none' = clear)", required=False, clear_word="none")
  if target is None:          # keep: don't call the database
      ...
  new_value = None if target is CLEAR else target   # CLEAR -> None -> NULL in the database
  ```
  Use `is` for `None` and for sentinels, and `==` for values.

**中文：**
- "修改目标价"需要**三种**不同的回答：回车 = 保留，数字 = 设置，`none` = 清除。
- `None` 已经表示"保留"，数字表示"设置"，所以"清除"需要第三种不会和它们混淆的值。`object()` 创建一个全新的、独一无二的对象，我们把它存在名字 `CLEAR` 里。
- 用户输入 `none`（大小写都可以，用了 `answer.lower()`）时，`ask_decimal` 返回的正是这个对象。
- 调用方用 **`is`** 判断，意思是"同一个对象"，而不只是"相等"。`None` 和哨兵用 `is`，普通的值用 `==`。

### 2. Copy a dict with one more key / 复制字典并加一个键: `{**row, "key": value}`
**EN:**
```python
rows = [{**row, "reached_text": reached_text(row["reached"])} for row in rows]
```
- `**row` inside `{ }` **unpacks** all key/value pairs of `row` into a new dict, and `"reached_text": …` adds one more.
- The original row is not changed. Example: `{**{"a": 1}, "b": 2}` → `{"a": 1, "b": 2}`.
- Used to turn the database's `True / False / NULL` into "yes" / "no" / "" for display only.

**中文：**
- 在 `{ }` 里写 `**row`，会把 `row` 的所有键值对**展开**到新字典里，再加上 `"reached_text": …` 这一项。
- 原来的字典不变。例：`{**{"a": 1}, "b": 2}` → `{"a": 1, "b": 2}`。
- 这里只是为了显示，把数据库的 `True / False / NULL` 变成 "yes" / "no" / ""。

### 3. `next()` with a default / 带默认值的 `next()`
**EN:**
```python
items = next((row["items"] for row in rows if row["watchlist_id"] == session.watchlist_id), 0)
```
- `next(generator, default)` returns the **first** value the generator produces, or `default` if it produces none.
- It finds one matching row without building a list, and doesn't crash when nothing matches.

**中文：** `next(生成器, 默认值)` 返回生成器产生的**第一个**值；一个都没有时返回默认值。这样不用建列表就能找到第一条匹配的行，找不到也不会报错。

### 4. Small helper with three outcomes / 三种结果的小函数
**EN:**
```python
def reached_text(reached):
    if reached is None:
        return ""
    return "yes" if reached else "no"
```
SQL `NULL` arrives in Python as `None`, so a SQL boolean can be `True`, `False` or `None`. "No target" (`None`) must not show as "no", which is why `is None` is checked first.

**中文：** SQL 的 `NULL` 到 Python 里是 `None`，所以 SQL 布尔值有三种可能：`True`、`False`、`None`。"没有目标价"（`None`）不能显示成 "no"，所以先判断 `is None`。

### 5. A keyword option that changes behaviour / 改变行为的关键字参数
**EN:** `ask_ticker(session, allow_index=False)` is the same function in two menus:
- **Portfolios:** the default `False` re-asks for an index, because indexes can't be traded.
- **Watchlists:** `allow_index=True` accepts one.

A **default value** keeps the old callers (Buy/Sell, and the App 2 tests) working without any change.

**中文：** `ask_ticker(session, allow_index=False)` 在两个菜单里共用：
- **投资组合：** 默认 `False`，遇到指数就重新询问，因为指数不能交易。
- **关注列表：** `allow_index=True`，接受指数。

因为参数有**默认值**，原来的调用（买入/卖出，以及 App 2 的测试）不用改动。

---

## Tests / 测试
**EN:**
- 10 new pytest tests (on the test DB, rolled back):
  - duplicate watchlist name → uq message (another investor may use the same name)
  - the same ticker twice → pk message
  - an index can be watched
  - an unknown ticker is re-asked, and the fk message if it reaches the DB
  - negative / zero target → chk message; clearing → NULL
  - `ask_decimal` keep / CLEAR / number
  - item list values (close, % vs target, reached yes/no/none) and the list counts
  - remove an item
  - rename, and delete with cascade (another investor can't delete it)
  - "targets reached" = `fn_watchlist_targets_reached`
- Totals: 338 SQL + 107 pytest.
- Also checked: a scripted UI session on the test DB, and read-only browsing on the real DB (fingerprint unchanged).

**中文：**
- 新增 10 个 pytest 测试（在测试库上，全部回滚），覆盖上面列出的情况。
- 合计：SQL 338 个 + pytest 107 个。
- 另外：在测试库上跑了脚本化的界面操作，在真实库上用只读模式浏览过（指纹不变）。
