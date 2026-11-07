# App 3: trade history, audit log, restore / 交易历史、审计日志、恢复

Menu: Portfolio home → **4 Trade history** → 1 List trades, 2 Edit a trade, 3 Delete a trade, 4 Audit log, 5 Restore a deleted trade.
菜单：组合主页 → **4 Trade history** → 1 列出交易，2 修改交易，3 删除交易，4 审计日志，5 恢复已删除的交易。

Files / 文件:
- new / 新增：`db/programmability/07_restore_trade.sql`, `app/menus/trade_history_menu.py`, `tests/test_app_trade_history.py`
- changed / 修改：`db/programmability/04_balance_checks.sql` (the exemption / 豁免), `db/apply.sql`, `db/tests/test_schema.sql` (+19 SQL tests), `app/data_access.py`, `app/errors.py`, `app/menus/portfolio_menu.py`, `Makefile` + `db/tests/verify_dump.sh` (`-P pager=off`)
- existing test changed / 修改的已有测试：`tests/test_app_portfolio.py::test_overdraw_message_includes_detail_amount` now expects `-90,000.00` (the new separators) / 现在期望 `-90,000.00`（新的千位分隔符）。

Applied to the real DB with `make apply-db` (no data touched; fingerprint unchanged).
已用 `make apply-db` 应用到真实数据库（数据未改动，指纹不变）。

---

## 1. The design problem: restore vs the date-order rule / 设计问题：恢复与日期顺序规则
**EN:**
- **The problem.** New events must not be dated before the portfolio's latest event (`trg_date_before_latest`). A deleted trade is usually old, so putting it back would break that rule.
- **The solution (your choice): an exact-replay exemption.**
  1. `CALL restore_trade(audit_id, NULL)` reads the audit row and checks:
     - it exists (`exec_audit_not_found`)
     - it is a DELETE (`exec_restore_not_delete`)
     - the trade isn't back already (`exec_trade_already_restored`)
     - it is that trade's newest audit row (`exec_restore_not_latest`)
  2. It inserts the trade with its **original id**:
     ```sql
     INSERT INTO trade (trade_id, portfolio_id, ticker, trade_type, shares, price, trade_date)
     OVERRIDING SYSTEM VALUE          -- allowed to write into a GENERATED ALWAYS identity column
     VALUES (v_audit.trade_id, ...);
     ```
  3. In `fn_event_date_order` (BEFORE INSERT), only for the trade table:
     ```sql
     SELECT a.operation = 'DELETE'
            AND (a.portfolio_id, a.ticker, a.trade_type, a.shares, a.price, a.trade_date)
              = (NEW.portfolio_id, NEW.ticker, NEW.trade_type, NEW.shares, NEW.price, NEW.trade_date)
     INTO v_is_restore
     FROM trade_audit a WHERE a.trade_id = NEW.trade_id
     ORDER BY a.audit_id DESC LIMIT 1;     -- the trade's LATEST audit row
     ...
     IF v_date < v_latest AND NOT v_is_restore THEN RAISE ... trg_date_before_latest
     ```
     `(a, b) = (c, d)` is a **row-value comparison**: all columns must be equal. Only the "before the latest event" check is skipped. The start-date check, `trg_trade_validate` (price range, no INDEX), the FK and the AFTER history replay all still run.
- **Why it can't be abused.** A normal insert gets a new id from the identity, and no audit row has that id. Inserting the old id with *different* values doesn't match either. Both are SQL tests.
- **Why the original id.** The replay orders same-day trades by id. With a new, bigger id the restored trade would move to the end of its day, which can change whether the history is valid. Example: a SELL that originally came after the BUY could end up before it.
- **Worked example (SQL test):**
  1. Start with 1,000 cash. BUY 2 @ 100 on 04-01, BUY 3 @ 100 on 04-02.
  2. Delete the 04-01 trade, then deposit 50 on 04-03 (now the latest event).
  3. `restore_trade` brings back the 04-01 trade with the same id. Cash = 500 (before the delete) + 50 = 550.
  4. Restoring it again → "Trade N is already back in the portfolio."

**中文：**
- **问题：** 新事件不能早于组合最近一次事件（`trg_date_before_latest`）。被删除的交易通常比较早，放回去就会违反这条规则。
- **方案（你选的）：精确重放豁免。**
  1. `restore_trade` 读取审计行并检查：它存在、它是 DELETE、交易还没有被恢复、它是这笔交易最新的审计行。
  2. 用**原来的 id** 插回交易（`OVERRIDING SYSTEM VALUE` 允许往 GENERATED ALWAYS 自增列写值）。
  3. 日期顺序触发器只有在新行与该交易**最新**的审计行完全相同、而且那一行是 DELETE 时，才跳过"早于最近事件"这一项检查。`(a, b) = (c, d)` 是**行值比较**：所有列都相等才成立。开始日期、价格范围、不能交易指数、外键、历史重放都照常检查。
- **为什么不会被滥用：** 普通插入会从自增列得到新的 id，没有任何审计行有这个 id；用旧 id 但值不同也匹配不上。两种情况都有 SQL 测试。
- **为什么保留原 id：** 重放时同一天的交易按 id 排序。换成更大的新 id，恢复的交易会排到当天最后，可能改变历史是否有效（例如原来排在买入之后的卖出，会跑到买入前面）。
- **算例：** 见上方英文步骤，恢复后现金 = 删除前的 500 + 存款 50 = 550；再恢复一次 → "Trade N is already back in the portfolio."

## 2. The menu functions / 菜单功能
**EN:**
- **List:** `da.list_trades(conn, pid, ticker=None)` uses `ORDER BY trade_date, trade_id`, the order the replay uses for trades (a test compares it with `fn_portfolio_history`). The optional filter is in SQL: `%(ticker)s::text IS NULL OR ticker = upper(btrim(...))`. The `::text` cast tells PostgreSQL the parameter's type, which it can't guess from a NULL alone.
- **Edit:**
  - Shows the trade and that day's low/high.
  - Asks for new shares and price; Enter = keep (`COALESCE(%s, shares)` in SQL).
  - The database may refuse, e.g. lowering a BUY so a later SELL oversells: "Not enough shares. DEMO shares would be -3 on 2025-03-04 …". When it refuses, the whole statement is rolled back, **including the audit row**.
- **Delete:** shows the trade, then asks you to type its ID (`confirm_typed(str(trade_id), ...)`). `str()` turns the number 168 into the text "168", because the input is text.
- **Audit log:** newest first, with a status for DELETE rows: "restorable" (the trade is gone and this is its newest audit row) or "restored" (the trade is back). The status uses the same rules as the procedure.
- **Restore:** lists only the DELETE rows (`only_deletes=True`, filtered in SQL), asks for an audit ID, and calls the procedure.
- Every data-access function also takes **portfolio_id** and filters by it, so a trade or audit row of another portfolio can't be touched from this menu (`NotFoundError`).

**中文：**
- **列表：** 按 `trade_date, trade_id` 排序，与重放时交易的顺序相同（测试与 `fn_portfolio_history` 对比）。可选的代码过滤写在 SQL 里；`::text` 告诉 PostgreSQL 参数的类型（只有一个 NULL 时它推断不出来）。
- **修改：**
  - 显示交易和当天的最低价、最高价。
  - 输入新股数和价格，回车 = 保留（SQL 里用 `COALESCE`）。
  - 数据库可能拒绝，例如把买入改少，导致后面的卖出卖超。拒绝时整条语句回滚，**包括审计行**。
- **删除：** 显示交易，要求输入它的 ID（`str()` 把数字 168 变成文字 "168"，因为输入的是文字）。
- **审计日志：** 最新的在前。DELETE 行有状态："restorable"（可恢复）或 "restored"（已恢复），判断规则与存储过程相同。
- **恢复：** 只列出 DELETE 行（`only_deletes=True`，在 SQL 里过滤），输入审计 ID，调用存储过程。
- 每个数据访问函数都同时接收 **portfolio_id** 并按它过滤，所以在这个菜单里碰不到其他组合的交易或审计行。

## 3. New Python features / 新的 Python 知识点
**EN:**
- **`re.sub` with a function:** `MONEY_IN_TEXT.sub(lambda match: f"{Decimal(match.group()):,.2f}", text)`. For every match, `sub` calls the function and puts its return value in place of the matched text. `match.group()` is the matched text, e.g. `"-20366046.40"`. The pattern `-?\d+\.\d{2}\b`:
  - `-?` = an optional minus
  - `\d+` = digits
  - `\.` = a literal point
  - `\d{2}` = exactly 2 decimals
  - `\b` = the number ends there

  Dates (`2025-03-04`) and integers (`1000`) don't match.
  Result: `"Cash would be -20366046.40"` → `"Cash would be -20,366,046.40"`.
- **Keyword argument at the call:** `safe_call(da.audit_log, conn, pid, only_deletes=True)`. `safe_call` passes `**kwargs` on unchanged, so named options work through it.
- **`str(number)`** turns a number into text for comparing with typed input.

**中文：**
- **`re.sub` 配合函数：** 每找到一个匹配，就调用这个函数，用它的返回值替换匹配到的文字。`match.group()` 是匹配到的文字。模式 `-?\d+\.\d{2}\b`：可选负号、若干数字、小数点、恰好两位小数、数字到此结束。日期和整数都不会被匹配到。
- **调用时用关键字参数：** `only_deletes=True` 通过 `safe_call` 的 `**kwargs` 原样传下去。
- **`str(数字)`** 把数字变成文字，以便和输入的文字比较。

## 4. Tests / 测试
**EN:**
- **19 new SQL tests** (`test_schema.sql`, "restore" section): a narrow exemption (a new trade on an old date and the old id with different values are both still rejected), all four `exec_` errors, restore after a later deposit (original id/values, cash = before + deposit, no new audit row), restore twice, restore after edit + second delete (only the newest DELETE row), and restore when the cash was spent (`trg_cash_never_negative`, nothing inserted).
  - Note: a CALL argument can't contain a subquery, so the tests build the text with `format('CALL restore_trade(%s, NULL)', <id>)`.
- **11 new pytest tests** (`tests/test_app_trade_history.py`): history order = replay order, edit → UPDATE audit row with the OLD values, edit outside the price range, an edit that breaks history is refused and changes nothing, delete → DELETE row, restore as it was with cash equal to before, restore twice, restore after the cash was spent, another portfolio's audit row, thousands separators.
- **Totals:** 338 SQL + 97 pytest. I also ran a full scripted UI session on the test DB (list, refused edit, edit, delete, audit log, restore, restore again), then read-only browsing on the real DB.

**中文：**
- **19 个新 SQL 测试**：豁免范围很窄（旧日期的新交易、旧 id 但值不同，都仍然被拒绝）；四种 `exec_` 错误；在后来有存款之后恢复（原 id 和原值，现金 = 删除前 + 存款，不新增审计行）；重复恢复；修改后再删除，只能从最新的 DELETE 行恢复；现金已被花掉时恢复被拒绝。
  - 注意：CALL 的参数里不能有子查询，所以测试用 `format(...)` 拼出语句。
- **11 个新 pytest 测试**：见上方英文列表。
- **合计：** SQL 338 个 + pytest 97 个。另外在测试库上手动跑了一遍完整的界面流程，并在真实库上用只读模式浏览过。
