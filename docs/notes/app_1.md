# App 1: CLI foundation + investor / 命令行程序基础 + 投资者

Design (CRUD matrix, menu tree, roadmap): `docs/app_design.md`.
设计文档（CRUD 矩阵、菜单树、路线图）：`docs/app_design.md`。

## How to run / 如何运行
```bash
conda activate spt
make run            # real database portfolio_tracker
make run-test-db    # test database (empty; `make test` wipes it again)
# same as:  python -m app      /   DB_NAME=portfolio_tracker_test python -m app
```
Type a number and press Enter. `0` = back (exit in the main menu). Ctrl+C or Ctrl+D quits cleanly at any time.
输入数字后按回车。`0` = 返回（在主菜单是退出）。任何时候按 Ctrl+C 或 Ctrl+D 都能正常退出。

Tiny example session / 小例子：
```
=== Main menu ===            =1=>   === Investors ===   =2=>   New investor
  1) Choose / create investor          Name: Demo User
  2) Market data                       Email: demo@example.com
  3) Admin                             Created investor 35: Demo User
  0) Exit                       ==>  === Investor home: Demo User ===  (Portfolios, Watchlists, Profile)
```
A duplicate email in another case prints:
`!! That email is already used by another investor (emails are case-insensitive).`
用不同大小写重复注册同一个邮箱，会显示上面这句友好提示。

---

## The layers / 分层
```
app/menus/*.py   →   app/data_access.py   →   PostgreSQL (constraints, triggers)
(screens, no SQL)    (ALL SQL)               (ALL rules)
        ↑ errors.safe_call() turns a refused action into a friendly message
```
**EN:** Each layer has one job. The menus decide *what to ask and show*. `data_access` decides *which SQL to run*. The database decides *what is allowed*. So the email rule is written once, in the CHECK constraint, and the app just shows its message.
**中文：** 每层只做一件事：菜单决定*问什么、显示什么*；`data_access` 决定*执行哪条 SQL*；数据库决定*什么是允许的*。所以邮箱规则只写一次（在 CHECK 约束里），程序只负责显示它的提示。

---

## `app/__main__.py`: entry point / 入口
**EN:**
- `python -m app` runs the package `app` as a program, and Python executes `app/__main__.py`. Running it from the repo root means `import app...` and `import etl...` both work.
- It connects with `etl.db.connect()`, the same `.env` settings as the ETL scripts. `DB_NAME` in the environment wins over `.env`, which is how `make run-test-db` picks the test DB. It prints which database is in use, so you always know whether it's real or test data.
- `with conn:` closes the connection at the end, even after an error. This is a **context manager**: `with x:` runs setup code at the start and cleanup code at the end, guaranteed.
- `try: … except (KeyboardInterrupt, EOFError):` means Ctrl+C or Ctrl+D ends with "Goodbye." instead of a traceback.
- `if __name__ == "__main__": main()` runs `main()` only when the file is executed, not when it is imported.

**中文：**
- `python -m app` 把 `app` 包当作程序运行，Python 执行 `app/__main__.py`。从仓库根目录运行，`import app...` 和 `import etl...` 都能找到。
- 用 `etl.db.connect()` 连接，和 ETL 一样读取 `.env`。环境变量 `DB_NAME` 优先于 `.env`，`make run-test-db` 就是这样连到测试库的。程序会打印当前数据库名，避免分不清真实库和测试库。
- `with conn:` 在结束时一定会关闭连接，即使出错也一样。这叫**上下文管理器**：`with x:` 保证开头做准备、结尾做清理。
- `except (KeyboardInterrupt, EOFError)`：Ctrl+C / Ctrl+D 时显示 "Goodbye."，而不是报错信息。
- `if __name__ == "__main__":` 只有直接运行这个文件时才调用 `main()`，被 import 时不会。

## `app/session.py`: current state / 当前状态
**EN:**
- `@dataclass class Session` holds the connection and the chosen investor ("logged in"). `@dataclass` writes `__init__` for us from the annotated fields: `Session(conn)` sets `conn` and leaves `investor_id=None`.
- `int | None` is a type hint meaning "an int or None". Python doesn't enforce it; it's documentation.
- One `Session` object is passed to every menu function, so no global variables are needed.

**中文：**
- `@dataclass class Session` 保存连接和当前选中的投资者（相当于"已登录"）。`@dataclass` 会根据带类型注解的字段自动生成 `__init__`：`Session(conn)` 设置 `conn`，`investor_id` 默认为 `None`。
- `int | None` 是类型提示，意思是"整数或 None"。Python 不强制检查，只是说明。
- 同一个 `Session` 对象传给每个菜单函数，所以不需要全局变量。

## `app/data_access.py`: ALL the SQL / 全部 SQL
**EN:**
- **One transaction per function:** `with conn.transaction():`. The connection is in autocommit mode, so this block *is* the transaction: it commits at the end, or rolls back if an exception leaves the block. Inside another transaction (the tests) it becomes a **savepoint**.
- **Parameters, never string formatting:** `cur.execute("... WHERE investor_id = %s", (investor_id,))`. psycopg sends the value separately, so input like `'; DROP TABLE investor; --` is just text (no SQL injection). `(investor_id,)` is a tuple with one element; the comma makes it a tuple. A dict works too: `%(id)s` with `{"id": 5}`, which is handy when the same value is used several times (`investor_delete_summary`).
- **`dict_row`:** rows come back as dicts, so the code reads `row["email"]` instead of `row[2]`.
- **`RETURNING`:** INSERT/UPDATE/DELETE return the affected id, in the same statement. No row back means nothing matched, so the function raises **`NotFoundError`**, our own exception class (`class NotFoundError(Exception)`).
- **`update_investor(conn, id, name=None, email=None)`:** **keyword arguments with defaults**. `SET name = COALESCE(%s, name)` keeps the old value when the parameter is NULL (Python `None`). So one function edits the name, the email, or both.
- `_fetch_all` / `_fetch_one` start with `_`: by convention, "internal helper, not for other modules".

**中文：**
- **每个函数一个事务：** `with conn.transaction():`。连接是自动提交模式，所以这个代码块*就是*事务：正常结束就提交；有异常离开代码块就回滚。如果外面已经有事务（测试中），它就变成一个**保存点（savepoint）**。
- **用参数，绝不拼接字符串：** `cur.execute("... WHERE investor_id = %s", (investor_id,))`。psycopg 把值单独发送，所以像 `'; DROP TABLE investor; --` 这样的输入只是普通文本（防 SQL 注入）。`(investor_id,)` 是只有一个元素的元组，逗号使它成为元组。也可以用字典：`%(id)s` 配 `{"id": 5}`，同一个值用多次时很方便。
- **`dict_row`：** 每行是字典，代码写 `row["email"]`，而不是 `row[2]`。
- **`RETURNING`：** INSERT/UPDATE/DELETE 在同一条语句里返回受影响的 id。如果没有返回行，说明没找到，函数就抛出我们自己的异常类 **`NotFoundError`**。
- **`update_investor(..., name=None, email=None)`：** 带默认值的**关键字参数**。`COALESCE(%s, name)`：参数是 NULL（Python 的 `None`）时保留原值。所以一个函数可以只改名字、只改邮箱，或两个都改。
- `_fetch_all` / `_fetch_one` 以 `_` 开头，按惯例表示"内部辅助函数，其他模块不要用"。

## `app/errors.py`: friendly messages / 友好提示
**EN:**
- `MESSAGES` is a **dict** from rule name to sentence, covering all 61 names in the database. psycopg puts the name of the violated rule in `error.diag.constraint_name`. Our triggers set it too (`USING CONSTRAINT = 'trg_…'`), which is why every trigger was written that way.
- `friendly_message(error)` works in order:
  1. `NotFoundError` → its own text
  2. connection lost → "restart"
  3. a known name → the sentence, plus the database's DETAIL for `trg_`/`exec_` errors (e.g. "Not enough cash. Cash would be -50.00 on 2025-01-03 …")
  4. no name → by **SQLSTATE**, the 5-character error code (`23502` NOT NULL → "Email is required.", using `diag.column_name`)
  5. otherwise the database's own text
- `safe_call(func, *args, **kwargs)` calls `func` with whatever arguments it was given. `*args` collects positional arguments into a tuple and `**kwargs` collects keyword arguments into a dict; writing them again in the call passes them on. It returns a pair **`(ok, result)`**, and the menus unpack it: `ok, rows = safe_call(...)`. On a database error it prints `!! message` and returns `(False, None)`. The transaction was already rolled back by `with conn.transaction()`.
- **Example:** `safe_call(da.create_investor, conn, "Bob", "BOB@x.com")` while bob@x.com exists → psycopg raises `UniqueViolation` with `constraint_name = "uq_investor_email_lower"` → it prints "!! That email is already used …" and returns `(False, None)`.

**中文：**
- `MESSAGES` 是从规则名到提示语的**字典**，覆盖数据库里全部 61 个名字。psycopg 把被违反规则的名字放在 `error.diag.constraint_name`。我们的触发器也会设置它（`USING CONSTRAINT = 'trg_…'`），这正是当初这样写触发器的原因。
- `friendly_message(error)` 按顺序处理：
  1. `NotFoundError` 用它自己的文字
  2. 连接断开时提示重启
  3. 已知名字用对应的句子，`trg_`/`exec_` 错误再加上数据库的 DETAIL（例如 "Cash would be -50.00 on …"）
  4. 没有名字时按 **SQLSTATE**（5 位错误代码）处理，例如 23502 NOT NULL → "Email is required."
  5. 其他情况显示数据库原文
- `safe_call(func, *args, **kwargs)`：`*args` 把位置参数收集成元组，`**kwargs` 把关键字参数收集成字典，调用时再原样传给 `func`。返回一对值 **`(ok, result)`**，菜单这样拆开：`ok, rows = safe_call(...)`。数据库报错时打印 `!! 提示`，返回 `(False, None)`；事务已经被 `with conn.transaction()` 回滚了。

## `app/inputs.py`: asking until valid / 反复询问直到有效
**EN:**
- Each helper is a `while True:` loop. An invalid answer prints a hint and runs `continue` (ask again); a valid one leaves with `return`.
- `ask_int` uses `int(answer)` inside `try/except ValueError`, because `int("abc")` raises ValueError.
- `required=False` lets an empty answer return `None`, meaning "keep" or "cancel".
- `confirm_typed(expected, what)` is True only if the user types `expected` exactly (the investor's email).
- These check **shape only** (empty, number, length), never business rules.

**中文：**
- 每个函数都是 `while True:` 循环：输入无效就打印提示并 `continue`（再问一次），有效就 `return` 离开。
- `ask_int` 把 `int(answer)` 放在 `try/except ValueError` 里，因为 `int("abc")` 会抛出 ValueError。
- `required=False`：直接回车时返回 `None`，表示"保留"或"取消"。
- `confirm_typed`：只有完全一致地输入指定文字（投资者邮箱）才返回 True。
- 这里只检查**格式**（是否为空、是否是数字、长度），从不检查业务规则。

## `app/menu.py`: the reusable numbered menu / 可复用的编号菜单
**EN:**
- `run_menu(title, items, session)` takes `items`, a **list of (label, function) tuples**. **Functions are values** in Python: `investor_menu` without `()` is the function itself, so it can be stored in a list and called later with `function(session)`.
- `enumerate(items, start=1)` numbers the items 1, 2, 3, ….
- `for number, (label, _function) in …` **unpacks** each tuple. The leading `_` means "not used here".
- `title` can be a text or a function. `lambda s: f"Investor home: {s.investor_name}"` is a tiny unnamed function, so the heading updates after a rename. `callable(title)` checks which one it got.
- A menu function may `return "back"` to close the menu that called it. Deleting an investor uses this to leave the profile and the home menu at once.

**中文：**
- `run_menu(title, items, session)` 的 `items` 是 **(标签, 函数) 元组的列表**。在 Python 里**函数也是值**：不带 `()` 的 `investor_menu` 就是函数本身，可以放进列表，之后再用 `function(session)` 调用。
- `enumerate(items, start=1)` 给每项编号 1、2、3……。
- `for number, (label, _function) in …` 把元组**拆包**；`_` 开头表示"这里用不到"。
- `title` 可以是文字，也可以是函数：`lambda s: f"Investor home: {s.investor_name}"` 是一个小的匿名函数，改名后标题会随之更新。`callable(title)` 判断是哪一种。
- 菜单函数可以 `return "back"`，把调用它的菜单也关掉。删除投资者后，用它同时离开资料菜单和主页菜单。

## `app/display.py`: tables / 表格
**EN:**
- `print_table(rows, columns)` builds the header list and the body with **list comprehensions** (`[expr for x in items]`, a compact for-loop that builds a list) and calls `tabulate(...)`.
- `format_value` shows money (`Decimal`) as `12,345.60` (`f"{value:,.2f}"`: `,` = thousands separator, `.2f` = 2 decimals) and timestamps without seconds. It checks `datetime` **before** `date`, because a datetime is also a date (subclass).
- Number columns are right-aligned (`colalign`). `disable_numparse=True` stops tabulate from re-reading "100.50" as 100.5.

**中文：**
- `print_table(rows, columns)` 用**列表推导式**（`[表达式 for x in 列表]`，生成列表的简洁 for 循环）构造表头和内容，然后调用 `tabulate(...)`。
- `format_value`：金额（`Decimal`）显示成 `12,345.60`（`,` 是千位分隔符，`.2f` 是两位小数）；时间戳不显示秒。先判断 `datetime` 再判断 `date`，因为 datetime 也是 date（子类）。
- 数字列右对齐（`colalign`）；`disable_numparse=True` 防止 tabulate 把 "100.50" 变成 100.5。

## `app/menus/main_menu.py` and `app/menus/investor_menu.py` / 菜单
**EN:**
- **main_menu:** 1 Investors, 2 Market data and 3 Admin (`coming_soon` for now), 0 Exit.
- **investor_menu:**
  - List
  - Create: after creating, the investor is chosen automatically
  - Choose: shows the list, asks for an ID, Enter = cancel
- **Investor home:** Portfolios and Watchlists (coming soon), and Profile. Leaving the home calls `session.forget_investor()` ("log out").
- **Profile:** view, edit name, edit email, delete.
- **Delete steps:**
  1. Show what the cascade removes (`investor_delete_summary`).
  2. Ask for the email with `confirm_typed`.
  3. Delete, then `forget_investor()`.
  4. `return "back"`, so both menus close.
- Every database call has the form `ok, x = safe_call(da.function, session.conn, ...)`. The menus contain **no SQL and don't import psycopg**, and `tests/test_app_no_sql_in_menus.py` checks this.

**中文：**
- **main_menu：** 1 投资者，2 行情数据、3 管理（暂时是 `coming_soon`），0 退出。
- **investor_menu：**
  - 列表
  - 新建：建好后自动选中
  - 选择：先显示列表，再输入 ID，直接回车取消
- **投资者主页：** 投资组合、关注列表（以后实现）和个人资料。离开主页时调用 `forget_investor()`（相当于"登出"）。
- **个人资料：** 查看、改名字、改邮箱、删除。
- **删除步骤：**
  1. 显示级联会删掉什么。
  2. 用 `confirm_typed` 要求输入邮箱。
  3. 删除，然后 `forget_investor()`。
  4. `return "back"`，两层菜单一起关闭。
- 每次访问数据库都是 `ok, x = safe_call(da.函数, session.conn, ...)`。菜单里**没有 SQL，也不 import psycopg**，`tests/test_app_no_sql_in_menus.py` 会检查这一点。

---

## Tests / 测试 (24 new pytest tests; total 54 pytest + 319 SQL)
**EN:**
- `tests/conftest.py`: the **fixture** `conn`. A pytest fixture is a function whose value is passed to every test that has a parameter of that name.
  - It sets `DB_NAME` with `monkeypatch`, which is undone after the test.
  - It refuses any database except `portfolio_tracker_test`.
  - It runs the test inside `conn.transaction(force_rollback=True)`. `yield` hands the connection to the test, and the code after it (the rollback) runs when the test ends. So the database never changes.
- `test_app_data_access.py`: create / read / list, update (the other field kept), delete with cascade, NotFoundError, a duplicate email in another case → the `uq_investor_email_lower` message, `safe_call` prints it and the connection still works, bad email and blank name messages.
- `test_app_errors.py`: **catalog test**. One SQL query collects every name a database error can carry (constraints, unique indexes, and `CONSTRAINT = '…'` found in function source with `regexp_matches`).
  - Every name must have a message.
  - Every message key must exist in the database.
  - Checked by hand: deleting one message, or adding a misspelled one, makes the test fail with the name in the error.
- `test_app_inputs.py`: **`monkeypatch.setattr("builtins.input", …)`** replaces `input()` with a function that returns prepared answers, so re-asking can be tested without typing.
- `test_app_no_sql_in_menus.py`: the grep check written as a test (capital SQL keywords, `.execute(`, `import psycopg`). The shell equivalent `grep -nE '\b(SELECT|INSERT|UPDATE|DELETE|CALL)\b' app/menus/*.py` prints nothing.

**中文：**
- `conftest.py`：**fixture** `conn`。pytest 会把 fixture 的值传给参数同名的测试。
  - 用 `monkeypatch` 设置 `DB_NAME`（测试结束后自动恢复）。
  - 只允许连接 `portfolio_tracker_test`。
  - 在 `force_rollback=True` 的事务里运行测试：`yield` 把连接交给测试，测试结束后执行后面的回滚，所以数据库从不改变。
- `test_app_data_access.py`：增删改查、级联删除、NotFoundError、不同大小写的重复邮箱 → 友好提示、`safe_call` 打印提示后连接仍可用。
- `test_app_errors.py`：**目录测试**。用一条 SQL 从系统目录收集所有错误名（约束、唯一索引、函数源码里的 `CONSTRAINT = '…'`）。
  - 每个名字都必须有提示。
  - 每个提示的键都必须存在于数据库。
  - 手动验证过：删掉一条提示或加一个拼错的名字，测试都会失败并给出那个名字。
- `test_app_inputs.py`：用 `monkeypatch` 替换 `input()`，自动"输入"预先准备好的答案。
- `test_app_no_sql_in_menus.py`：把 grep 检查写成测试。

## Limitations / 限制
- No password: "choose investor" is the login. 没有密码，"选择投资者"就是登录。
- A Python bug still shows a traceback (on purpose until the final step in the roadmap). Python 程序错误仍会显示报错信息（按计划，最后一步再改）。
- Ids in the test DB start at 35 or so, because rolled-back tests still use up sequence values. That is harmless. 测试库里的 id 从 35 左右开始，因为回滚的测试也会消耗序列值，这没有影响。
