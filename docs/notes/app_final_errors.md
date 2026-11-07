# Final app step: unexpected errors, the log file, startup problems / 最后一步：意外错误、日志文件、启动问题

What the user sees / 用户看到的:
```
  !! Something went wrong. Details were saved to logs/app.log (error 3f9a1c).
```
and the same menu again. In `logs/app.log`:
然后回到同一个菜单。`logs/app.log` 里记录的是：
```
2026-11-07 16:20:11,532 ERROR error 3f9a1c in Portfolio: Growth > Rebalance: division by zero
Traceback (most recent call last):
  File ".../app/menu.py", line 41, in run_menu
    result = function(session)
  ...
ZeroDivisionError: division by zero
```
- Debug mode / 调试模式：`APP_DEBUG=1 python -m app` also prints the traceback on screen / 也会在屏幕上打印 traceback。
- Startup problems / 启动问题：exit code / 退出码 2 = can't connect / 连不上，3 = database missing / 数据库不存在，4 = schema missing (dump not restored) / 没有表（未恢复 dump），1 = unexpected error outside a menu / 菜单之外的意外错误。

Files / 文件：
- new / 新增：`app/error_log.py`, `tests/test_app_unexpected.py` (12)
- changed / 修改：`app/menu.py` (the catch / 捕获点), `app/__main__.py` (startup checks, exit codes / 启动检查、退出码), `app/data_access.py` (`missing_schema_objects`), `tests/conftest.py` (logs → temp folder / 日志写到临时文件夹), `.gitignore` (`logs/`), `README.md`

---

## 1. The `logging` module / logging 模块
**EN:** Python's standard `logging` has three parts that work together:

| Part | In our code | Job |
|---|---|---|
| **Logger** | `logging.getLogger("app")` | What the program calls: `logger.error(...)`. Named, so the app's messages are separate from other libraries'. |
| **Handler** | `RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3)` | *Where* records go: here a file that is rotated when it gets too big. |
| **Formatter** | `logging.Formatter("%(asctime)s %(levelname)s %(message)s")` | *How* each line looks: time, level (ERROR), message. |

```python
logger.error("error %s in %s: %s", error_id, action, error, exc_info=error)
```
- **`%s` placeholders + arguments**, not an f-string: logging fills them in only if the record is actually written. This is the usual logging style.
- **`exc_info=error`** attaches the exception, so the handler writes the **full traceback** under the line. That's what makes the log useful for finding the bug.
- **`logger.propagate = False`:** records stop at our logger and are not also passed to the "root" logger (which might print them on screen).
- **`setup_logging` removes old handlers first:** calling it twice would otherwise attach two handlers, and every line would be written twice.

**中文：** Python 标准库的 `logging` 由三部分配合工作：
- **Logger（记录器）**：程序调用的对象 `logger.error(...)`。它有名字（"app"），所以本程序的日志和其他库的日志分开。
- **Handler（处理器）**：决定记录写到*哪里*。这里是一个文件，太大时会轮换。
- **Formatter（格式器）**：决定每行*长什么样*：时间、级别（ERROR）、消息。

- 用 `%s` 占位符加参数，而不是 f-string：只有真正写日志时才会填进去，这是 logging 的惯用写法。
- **`exc_info=error`** 把异常附上，处理器就会在这一行下面写出**完整的 traceback**，日志也因此才有助于找到 bug。
- **`propagate = False`**：记录到我们的 logger 就停止，不再交给"根"logger（它可能会打印到屏幕上）。
- `setup_logging` 先移除旧的 handler：否则调用两次就会挂上两个 handler，每行写两遍。

### `RotatingFileHandler`: a log that can't grow forever / 不会无限增长的日志
**EN:**
- When `app.log` would grow past `maxBytes` (1 MB), the handler renames it to `app.log.1` (the old `.1` becomes `.2`, and so on), deletes anything past `backupCount` (3), and starts a new `app.log`.
- So the logs never take more than about 4 MB. A test uses `max_bytes=2000` to see it happen.

**中文：**
- `app.log` 超过 `maxBytes`（1 MB）时，处理器把它改名为 `app.log.1`（原来的 `.1` 变成 `.2`，依此类推），删除超过 `backupCount`（3 个）的旧文件，再开一个新的 `app.log`。
- 所以日志最多约占 4 MB。有一个测试用 `max_bytes=2000` 看它确实会轮换。

## 2. Catching "everything", but not quite / 捕获"所有"错误，但不是全部
**EN:**
```python
try:
    result = function(session)
except (KeyboardInterrupt, EOFError):
    raise                    # Ctrl+C / Ctrl+D: the user wants to leave
except Exception as error:   # anything else is a bug
    report_unexpected(error, f"{heading} > {label}", getattr(session, "conn", None))
    continue
```
- **The exception hierarchy:** `except Exception` catches almost all errors but **not** `KeyboardInterrupt` (Ctrl+C), because that inherits from `BaseException`, not `Exception`.
- **`EOFError` (Ctrl+D) *is* an `Exception`,** so without the first `except` it would be swallowed and Ctrl+D would no longer exit. That's why it is re-raised explicitly. The order matters: the first matching `except` wins.
- **Why `run_menu`:** every menu action passes through it, so one catch covers the whole app. Nested menus each have their own `run_menu`, so the user returns to the menu where the action failed.
- **`getattr(session, "conn", None)`** reads `session.conn`, or gives `None` when `session` has no `conn` (some tests pass `session=None`).

**中文：**
- **异常的继承关系：** `except Exception` 能捕获几乎所有错误，但**不包括** `KeyboardInterrupt`（Ctrl+C），因为它继承自 `BaseException`，而不是 `Exception`。
- **`EOFError`（Ctrl+D）却*是* `Exception`**，如果没有第一个 `except`，它会被吞掉，Ctrl+D 就不能退出了，所以要显式地重新抛出。顺序很重要：第一个匹配的 `except` 生效。
- **为什么放在 `run_menu`：** 每个菜单操作都经过它，一处捕获就覆盖整个程序。嵌套菜单各有自己的 `run_menu`，所以用户会回到出错时所在的那个菜单。
- **`getattr(session, "conn", None)`** 读取 `session.conn`；`session` 没有 `conn` 时得到 `None`（有些测试传 `session=None`）。

## 3. Error id, debug mode, cleanup / 错误编号、调试模式、清理
**EN:**
- **`secrets.token_hex(3)`** gives 3 random bytes as 6 hex characters, e.g. `3f9a1c`. Short enough to read out, unique enough to find in the log. (`secrets` is the module meant for random tokens.)
- **`traceback.print_exception(error)`** prints the same traceback Python prints for an uncaught error (to stderr). Only when `os.environ.get("APP_DEBUG") == "1"`.
- **`recover_connection(conn)`:** `conn.info.transaction_status` says whether a transaction is open (`IDLE` = none). If one is open or failed, `conn.rollback()`. Normally every `with conn.transaction():` has already rolled back, so this is just a safety net, and errors during it (a broken connection) are ignored.

**中文：**
- **`secrets.token_hex(3)`**：3 个随机字节，写成 6 个十六进制字符，例如 `3f9a1c`。短到能念出来，又足够在日志里找到它（`secrets` 是专门用来生成随机令牌的模块）。
- **`traceback.print_exception(error)`**：打印和 Python 遇到未捕获错误时一样的 traceback（输出到 stderr），只在 `APP_DEBUG=1` 时打印。
- **`recover_connection`**：`transaction_status` 表示有没有打开的事务（`IDLE` = 没有）。如果有打开或失败的事务就 `rollback()`。通常 `with conn.transaction():` 已经回滚了，这只是保险；过程中出错（连接已断）会被忽略。

## 4. Startup problems and exit codes / 启动问题与退出码
**EN:**
- **`sys.exit(main())`:** `main()` returns a number, and `sys.exit` makes it the program's **exit code**. The shell shows it with `echo $?`: 0 = success, anything else = a kind of failure.
- **Can't connect vs no database:** psycopg raises `OperationalError` for both, and connection errors have **no SQLSTATE** (`e.sqlstate` is `None`, because no session exists yet; checked). So the server's text decides: `database "x" does not exist` → code 3; anything else → code 2 with the server's one-line reason (e.g. "No such file or directory" when the server isn't running).
- **Empty database:** `da.missing_schema_objects` checks `to_regclass('public.investor')` (NULL when the table doesn't exist) for the 11 tables and 2 views, and `pg_proc` for 3 routines. If anything is missing → code 4, "the dump hasn't been restored", plus the restore command.

**中文：**
- **`sys.exit(main())`**：`main()` 返回一个数字，`sys.exit` 把它作为程序的**退出码**。在 shell 里用 `echo $?` 查看：0 表示成功，其他数字表示各种失败。
- **连不上 vs 没有数据库：** 两种情况 psycopg 都抛出 `OperationalError`，而且连接错误**没有 SQLSTATE**（还没建立会话，`e.sqlstate` 是 `None`，已验证）。所以用服务器返回的文字来判断：`database "x" does not exist` → 退出码 3；其他情况 → 退出码 2，并显示服务器给出的一行原因（例如服务器没运行时是 "No such file or directory"）。
- **空数据库：** `missing_schema_objects` 用 `to_regclass` 检查 11 张表和 2 个视图（表不存在时返回 NULL），用 `pg_proc` 检查 3 个例程。缺任何一个 → 退出码 4，提示"dump 还没有恢复"，并给出恢复命令。

## 5. Tests / 测试
**EN:**
- 12 new tests:
  - a menu action raises `RuntimeError("boom")` → the friendly line with an id, no traceback on screen; the log has the id, "Test > Explode", "Traceback" and "RuntimeError: boom"; the menu came back
  - `APP_DEBUG=1` shows the traceback
  - Ctrl+D / Ctrl+C still leave (parametrized)
  - an open transaction is rolled back (mock connection)
  - `recover_connection` cases (idle / broken / None)
  - rotation (`app.log.1` exists, size ≤ 2 KB, at most 2 backups)
  - logs are never in the repo
  - startup: real connection attempts that change nothing (a missing socket dir → 2, a missing DB → 3, `postgres` → 4)
  - the test DB has the whole schema
- An **autouse fixture** (`conftest.log_to_tmp_path`) sends every test's log to its own temporary folder. Using `tmp_path_factory`, not the test's `tmp_path`, keeps the chart tests' `tmp_path` empty.
- Totals: 343 SQL + 229 pytest. Manual check: the three startup messages, `echo $?` = 2 / 3 / 4, and a normal read-only session exits 0. Fingerprint unchanged.

**中文：**
- 新增 12 个测试，覆盖上方英文列表中的情况。
- 一个**自动使用的 fixture**（`conftest.log_to_tmp_path`）把每个测试的日志写到它自己的临时文件夹。用的是 `tmp_path_factory`，而不是测试的 `tmp_path`，这样图表测试的 `tmp_path` 仍然是空的。
- 合计：SQL 343 个 + pytest 229 个。手动检查了三种启动错误的提示，`echo $?` 分别是 2 / 3 / 4；正常的只读运行退出码为 0。指纹不变。
