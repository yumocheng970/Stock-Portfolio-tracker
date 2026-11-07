# Task 2 deliverable: the database dump / 数据库导出文件

File: `db/dump/cheng_final_project.sql`, **2.6 MB** (2,634,970 bytes), far below Canvas upload limits. Restore time: **1.8 s with psql, 0.5 s without psql** (Python/psycopg).
文件：`db/dump/cheng_final_project.sql`，**2.6 MB**，远小于 Canvas 的上传限制。恢复时间：**psql 1.8 秒，不用 psql（Python/psycopg）0.5 秒**。

> **Version 2 (portable):** the first version used COPY and kept the `\restrict` lines, so only a recent psql could load it. Because the grader may use DBeaver/pgAdmin or an older psql, the dump now uses INSERTs and has no psql meta-commands. See section 1b.
> **第 2 版（可移植）：** 第一版用 COPY 并保留了 `\restrict` 行，只有较新的 psql 能加载。评分者可能用 DBeaver/pgAdmin 或较旧的 psql，所以现在改用 INSERT，并且没有任何 psql 元命令。见 1b 节。

```bash
make dump          # write the file from portfolio_tracker
make verify-dump   # restore it twice into a temporary DB (psql, then without psql), compare, check, drop
```
Run both right before submission (the data may have changed since).
提交前再运行这两条命令（数据可能已经变了）。

---

## 1. The `pg_dump` command / `pg_dump` 命令
```make
pg_dump --no-owner --no-privileges --format=plain -d portfolio_tracker -f db/dump/cheng_final_project.sql
```
**EN:**
- `--format=plain` writes a normal SQL text file that `psql -f` can run. Other formats (custom/tar) need `pg_restore`.
- `--no-owner` leaves out the `ALTER TABLE … OWNER TO ethan;` lines. On the grader's computer there is no role `ethan`, so those lines would fail. Without them, every object belongs to whoever runs the restore.
- `--no-privileges` leaves out `GRANT`/`REVOKE`, which also name roles of this machine.
- Result: `grep -cE "OWNER TO|GRANT |REVOKE "` finds **0** lines. The only "ethan" left in the file is **data**: `trade_audit.changed_by` records who made the 6 audited changes, which is correct history.
- No `--create` and no `--clean`: the file doesn't create or drop a database. You restore into an empty database you created yourself, with any name you like.

**中文：**
- `--format=plain` 输出普通的 SQL 文本文件，可以直接用 `psql -f` 执行；其他格式（custom/tar）需要 `pg_restore`。
- `--no-owner` 去掉 `ALTER TABLE … OWNER TO ethan;`。评分的电脑上没有 `ethan` 这个角色，这些语句会出错。去掉之后，所有对象都属于执行恢复的那个用户。
- `--no-privileges` 去掉同样会写出本机角色名的 `GRANT`/`REVOKE`。
- 结果：文件里 OWNER/GRANT/REVOKE 共 **0** 行。文件中唯一剩下的 "ethan" 是**数据**：`trade_audit.changed_by` 记录了是谁做的那 6 次被审计的修改，这是正确的历史记录。
- 不用 `--create` 和 `--clean`：文件不会创建或删除数据库。恢复到你自己建好的空数据库里，名字随意。

## 1b. Portability: INSERTs and no meta-commands / 可移植性：INSERT，没有元命令
```make
pg_dump --no-owner --no-privileges --column-inserts --rows-per-insert=1000 -d portfolio_tracker -f $(DUMP_FILE)
sed -i -E '/^\\(un)?restrict /d' $(DUMP_FILE)        # delete the \restrict / \unrestrict lines
! grep -n '^\\' $(DUMP_FILE) || exit 1             # fail if any line still starts with "\"
```
**EN:**
- **psql-only features in the old file:** (1) `COPY t FROM stdin;` followed by raw data lines and `\.`. Only psql knows how to send those lines. (2) `\restrict <key>` / `\unrestrict <key>`, psql commands added by pg_dump 16.10+ that older psql and every GUI reject.
- **`--column-inserts`** writes the data as `INSERT INTO public.stock (ticker, company_name, …) VALUES (…);`. This is ordinary SQL that every client can run. Naming the columns makes each INSERT independent of the table's column order.
- **`--rows-per-insert=1000`** puts up to 1000 rows in one INSERT: `VALUES (…), (…), …;`. That gives 50 INSERTs instead of 39,508. A GUI sends every statement separately, so 39,508 statements would be slow. One-row INSERTs would also make the file 6.2 MB instead of 2.6 MB.

  | option | size | INSERT statements |
  |---|---|---|
  | COPY (old) | 2.0 MB | 0 (11 COPY blocks) |
  | `--inserts` | 4.1 MB | 39,508 |
  | `--column-inserts` | 6.2 MB | 39,508 |
  | **`--column-inserts --rows-per-insert=1000`** | **2.6 MB** | **50** |
- **`sed -i -E '/^\\(un)?restrict /d'`** deletes, in place (`-i`), every line that starts with `\restrict ` or `\unrestrict ` (`(un)?` = optional "un"). In the Makefile the backslash is doubled (`\\`), because a regex needs `\\` to match one literal `\`.
- **The grep guard:** `grep -n '^\\'` prints the lines that start with a backslash and exits 0 if it finds any. `!` inverts that, so `make dump` fails if one is left.
- **Cost:** `\restrict` is a 2025 security fix (a malicious object name containing a newline could inject a psql command). Every name and value here is ours, so removing it is safe for this file.

Tiny example from the new file:
```sql
INSERT INTO public.sector (sector_id, sector_name) OVERRIDING SYSTEM VALUE VALUES
	(1, 'Communication Services'),
	(2, 'Consumer Discretionary'),
	...;
```
`OVERRIDING SYSTEM VALUE` lets the INSERT write the old ids into a `GENERATED ALWAYS` identity column (normally forbidden), so the ids stay the same.

**中文：**
- **旧文件里只有 psql 能用的部分：** (1) `COPY t FROM stdin;` 后面跟原始数据行和 `\.`，只有 psql 知道怎么发送这些行；(2) `\restrict` / `\unrestrict`，pg_dump 16.10+ 加的 psql 命令，旧版 psql 和所有图形界面工具都不认识。
- **`--column-inserts`** 把数据写成 `INSERT INTO public.stock (ticker, company_name, …) VALUES (…);`，是所有客户端都能执行的普通 SQL；写出列名后，INSERT 不依赖表的列顺序。
- **`--rows-per-insert=1000`** 每个 INSERT 最多放 1000 行：`VALUES (…), (…), …;`，一共 50 条而不是 39,508 条。图形界面工具每条语句单独发送，39,508 条会很慢；一行一条还会让文件变成 6.2 MB 而不是 2.6 MB（见上表）。
- **`sed -i -E '/^\\(un)?restrict /d'`**：直接在文件里（`-i`）删除以 `\restrict ` 或 `\unrestrict ` 开头的行（`(un)?` 表示可有可无的 "un"）。Makefile 里反斜杠写两次，因为正则需要 `\\` 才能匹配一个真正的 `\`。
- **grep 检查：** `grep -n '^\\'` 打印以反斜杠开头的行，找到就返回 0；`!` 取反，所以只要还剩一行，`make dump` 就失败。
- **代价：** `\restrict` 是 2025 年的安全修复（恶意对象名中带换行时，可能注入 psql 命令）。这里所有名字和数据都是我们自己的，所以对这个文件来说去掉它是安全的。
- 上面的例子里，`OVERRIDING SYSTEM VALUE` 允许 INSERT 往 `GENERATED ALWAYS` 自增列写入原来的 id（平时不允许），所以 id 保持不变。

## 2. What is in the file, in which order / 文件内容与顺序
**EN:** pg_dump orders the file so that it can be loaded in one pass:
1. **Pre-data:** functions and procedures (with `check_function_bodies = false`, so a function may mention a view created later), tables, views.
2. **Data:** multi-row `INSERT INTO table (cols) VALUES …;` for all 11 tables (38,064 price rows, …). After that, `setval(...)` sets each identity sequence to its last value, so the next new trade gets id 1159, not 1.
3. **Post-data:** primary keys, unique, foreign keys, indexes, and the **9 triggers**.

Because triggers and FKs come **after** the data, the INSERTs don't fire `trg_trade_history_check` and friends. That is correct, because the data already obeyed every rule when it was first inserted. It is also faster.

Tiny example from the file:
```sql
INSERT INTO public.trade_audit (audit_id, operation, changed_at, changed_by, trade_id, ...) OVERRIDING SYSTEM VALUE VALUES
	(1, 'UPDATE', '2026-11-02 17:42:39.684052-05', 'ethan', 416, 11, 'COST', 'BUY', 17, 902.60, '2026-09-09'),
	...;
...
CREATE TRIGGER trg_trade_audit AFTER DELETE OR UPDATE ON public.trade FOR EACH ROW EXECUTE FUNCTION public.fn_trade_audit();
```

**中文：** pg_dump 会安排好顺序，使文件可以一次加载完：
1. **数据之前：** 函数和存储过程（设置了 `check_function_bodies = false`，所以函数可以引用之后才创建的视图）、表、视图。
2. **数据：** 11 张表各用多行 `INSERT INTO 表 (列) VALUES …;`（价格 38,064 行，……）。之后用 `setval(...)` 把每个自增序列设为最后的值，所以下一笔新交易的 id 是 1159，而不是 1。
3. **数据之后：** 主键、唯一约束、外键、索引和 **9 个触发器**。

因为触发器和外键在数据**之后**才创建，INSERT 时不会触发 `trg_trade_history_check` 等触发器。这是正确的：这些数据第一次插入时就已经满足所有规则。这样也更快。

## 3. How the restore is verified / 如何验证恢复 (`make verify-dump`)
The steps live in `db/tests/verify_dump.sh` (`set -euo pipefail`: any failing command stops it).
步骤写在 `db/tests/verify_dump.sh` 里（`set -euo pipefail`：任何命令失败都会停止）。

**EN:** Step 0 checks that no line starts with `\`. Then the **whole check runs twice**:
- **A. with psql:** `psql -v ON_ERROR_STOP=1 --single-transaction -f cheng_final_project.sql`
- **B. without psql:** `python -m db.tests.restore_without_psql <db> <file>` reads the file and sends it through psycopg as **one plain string** in one transaction. Only the PostgreSQL server parses it, as when a GUI sends SQL, so any psql-only line would be a syntax error. It refuses to run on a database that already has tables. Proof that this test catches problems: the old COPY dump fails it with `syntax error at "\restrict"`.

For each method:
1. `createdb portfolio_tracker_restore_check`, a **new empty** database.
2. Restore (A or B), and print the time.
3. **Inventory diff.** `db/tests/dump_compare.sql` (read-only) runs on the real DB **and** the restored DB, and `diff` must print nothing. It prints 37 `name|value` lines:
   - row counts of all 11 tables
   - the names of every table, view, index, function (15), procedure (2), trigger (9, all enabled `O`) and constraint (47)
   - every identity sequence's last value
   - an md5 of all rows of sector/exchange/stock/daily_price, and of the output of `v_cash_balance`, `v_holdings` and the 5 analysis functions. If the views or functions behaved differently after the restore, the md5 would differ.
4. **Behaviour checks.** `db/tests/check_restore.sql` runs inside a transaction that is rolled back:

   | # | check | expected |
   |---|---|---|
   | 1 | `CALL execute_trade` BUY more than the cash | `trg_cash_never_negative` |
   | 2 | SELL more than held | `trg_shares_never_negative` |
   | 3 | trade ^GSPC | `trg_trade_not_index` |
   | 4 | `UPDATE cash_transaction` | `trg_cash_txn_immutable` |
   | 5 | `TRUNCATE trade` | `trg_trade_no_truncate` |
   | 6 | `CALL record_cash_transaction` withdraw more than the cash | `trg_cash_never_negative` |
   | 7 | valid BUY of 1 share | succeeds, new id > all restored ids, cash drops by the close |
   | 8 | UPDATE that trade | a `trade_audit` row is written |
   | 9 | views and analysis functions | return rows |
5. **Fingerprint.** `check_sample_data.sql` on both databases; the two values must be equal (`ea1746ea9890df106c8c9c8df1e38c28`).
6. `dropdb portfolio_tracker_restore_check`. This runs in a shell `trap … EXIT`, so the temp database is dropped **even when a check fails**. The target never touches any other database name.

**中文：** 这个 make 目标依次执行以下步骤，遇到第一个问题就停止：
第 0 步检查没有以 `\` 开头的行。然后**整套检查跑两遍**：A. 用 psql；B. 不用 psql：`restore_without_psql.py` 把整个文件作为**一个普通字符串**通过 psycopg 发给服务器（在一个事务里），只有服务器解析，和图形界面工具一样，所以任何 psql 专用的行都会报语法错误。旧的 COPY 版 dump 在这个测试里报 `\restrict` 语法错误，说明这个测试确实能发现问题。每一遍：
1. `createdb portfolio_tracker_restore_check`：一个**新的空**数据库。
2. 恢复（A 或 B），并打印用时。
3. **清单比对：** `dump_compare.sql`（只读）分别在真实库**和**恢复出来的库上运行，`diff` 必须没有任何输出。它输出 37 行：11 张表的行数；所有表、视图、索引、函数（15 个）、存储过程（2 个）、触发器（9 个，全部启用）和约束（47 个）的名字；自增序列的值；参考表、视图和 5 个分析函数输出结果的 md5。如果恢复后视图或函数的行为不同，md5 就会不一样。
4. **行为检查：** `check_restore.sql`（事务最后回滚），见上表。透支、卖超、交易指数、修改现金交易、TRUNCATE、超额取款都被拒绝，并报出对应的 `trg_` 名字。正常的交易成功，拿到新的 id，并且被审计。
5. **指纹：** 两个数据库的生成数据指纹必须相同。
6. 删除临时数据库。删除写在 shell 的 `trap … EXIT` 里，所以**即使检查失败**也会删除。这个目标不会碰任何其他数据库。

Last run (2026-11-07), for BOTH psql and non-psql restores: inventory identical (37 lines), 9/9 behaviour checks PASS, fingerprint equal, temporary DB dropped. Restore time: psql 1.84 s, Python 0.52 s.
最近一次运行（2026-11-07），psql 和非 psql 两种恢复：清单完全相同（37 行），9/9 行为检查通过，指纹一致，临时数据库已删除。恢复时间：psql 1.84 秒，Python 0.52 秒。

## 4. Restore commands (for the README / final report) / 恢复命令（写进 README 和最终报告）
**psql:**
```bash
createdb portfolio_tracker
psql -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql
```
With a password login (Windows, user `postgres`), add `-h localhost -U postgres` to both commands.
使用密码登录时（Windows，用户 `postgres`），两条命令都加上 `-h localhost -U postgres`。

**DBeaver:** create an empty database, open the file (File > Open File), select that database in the editor, then **SQL Editor > Execute SQL Script** (`Alt+X`). It runs 145 statements.
**DBeaver：** 新建空数据库，打开文件（File > Open File），在编辑器里选中该数据库，然后 **SQL Editor > Execute SQL Script**（`Alt+X`），共执行 145 条语句。
Full steps are in `README.md`. / 完整步骤见 `README.md`。

## 5. Limitations / 限制
- **DBeaver itself was not tested here** (it is a Windows GUI). The psycopg restore tests the same property: plain SQL that only the server parses. It is still worth one manual test in DBeaver on Windows before submission.
  **这里没能直接测试 DBeaver**（它是 Windows 图形界面程序）。psycopg 恢复测试验证的是同一件事：只由服务器解析的普通 SQL。提交前最好在 Windows 的 DBeaver 里手动试一次。
- **A GUI runs the statements one by one** (auto-commit), so if one fails, the database is left half restored. Drop it and restore into a new empty one. psql with `--single-transaction` is all or nothing.
  **图形界面工具逐条执行语句**（自动提交）。如果中途出错，数据库会只恢复了一半，需要删掉，再恢复到一个新的空数据库。psql 加 `--single-transaction` 则是要么全部成功、要么全部不生效。
- The `\restrict` protection is removed (see 1b). The file also changes on every `make dump` only if the data changed (the random key is gone).
  去掉了 `\restrict` 保护（见 1b）。现在没有随机密钥了，所以只有数据变化时，`make dump` 生成的文件才会变。
- The target server should be PostgreSQL 16 or newer (made with 16.15). Older servers aren't tested.
  目标服务器应为 PostgreSQL 16 或更新版本（用 16.15 生成），更旧的版本没有测试。
