# Task 2 deliverable: the database dump / 数据库导出文件

File: `db/dump/cheng_final_project.sql`, **2.0 MB** (2,076,393 bytes; 0.68 MB if gzipped). That is far below Canvas upload limits, so it can be uploaded as is.
文件：`db/dump/cheng_final_project.sql`，**2.0 MB**（gzip 后 0.68 MB），远小于 Canvas 的上传限制，可以直接上传。

```bash
make dump          # write the file from portfolio_tracker
make verify-dump   # restore it into a temporary DB, compare, run checks, drop the temp DB
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

## 2. What is in the file, in which order / 文件内容与顺序
**EN:** pg_dump orders the file so that it can be loaded in one pass:
1. **Pre-data:** functions and procedures (with `check_function_bodies = false`, so a function may mention a view created later), tables, views.
2. **Data:** `COPY table FROM stdin;` followed by the rows, for all 11 tables (38,064 price rows, …). After that, `setval(...)` sets each identity sequence to its last value, so the next new trade gets id 1159, not 1.
3. **Post-data:** primary keys, unique, foreign keys, indexes, and the **9 triggers**.

Because triggers and FKs come **after** the data, COPY doesn't fire `trg_trade_history_check` and friends. That is correct, because the data already obeyed every rule when it was first inserted. It is also faster.

Tiny example from the file:
```sql
COPY public.trade_audit (audit_id, operation, changed_at, changed_by, trade_id, ...) FROM stdin;
1	UPDATE	2026-11-02 17:42:39.684052-05	ethan	416	11	COST	BUY	17	902.60	2026-09-09
\.
...
CREATE TRIGGER trg_trade_audit AFTER DELETE OR UPDATE ON public.trade FOR EACH ROW EXECUTE FUNCTION public.fn_trade_audit();
```

**中文：** pg_dump 会安排好顺序，使文件可以一次加载完：
1. **数据之前：** 函数和存储过程（设置了 `check_function_bodies = false`，所以函数可以引用之后才创建的视图）、表、视图。
2. **数据：** 11 张表各一段 `COPY 表 FROM stdin;` 加上数据行（价格 38,064 行，……）。之后用 `setval(...)` 把每个自增序列设为最后的值，所以下一笔新交易的 id 是 1159，而不是 1。
3. **数据之后：** 主键、唯一约束、外键、索引和 **9 个触发器**。

因为触发器和外键在数据**之后**才创建，COPY 时不会触发 `trg_trade_history_check` 等触发器。这是正确的：这些数据第一次插入时就已经满足所有规则。这样也更快。

## 3. How the restore is verified / 如何验证恢复 (`make verify-dump`)
**EN:** The target does all of the following and stops at the first problem:
1. `createdb portfolio_tracker_restore_check`, a **new empty** database.
2. `psql -v ON_ERROR_STOP=1 --single-transaction -f cheng_final_project.sql`: all or nothing.
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
1. `createdb portfolio_tracker_restore_check`：一个**新的空**数据库。
2. 用 `ON_ERROR_STOP` 和 `--single-transaction` 恢复：要么全部成功，要么全部不生效。
3. **清单比对：** `dump_compare.sql`（只读）分别在真实库**和**恢复出来的库上运行，`diff` 必须没有任何输出。它输出 37 行：11 张表的行数；所有表、视图、索引、函数（15 个）、存储过程（2 个）、触发器（9 个，全部启用）和约束（47 个）的名字；自增序列的值；参考表、视图和 5 个分析函数输出结果的 md5。如果恢复后视图或函数的行为不同，md5 就会不一样。
4. **行为检查：** `check_restore.sql`（事务最后回滚），见上表。透支、卖超、交易指数、修改现金交易、TRUNCATE、超额取款都被拒绝，并报出对应的 `trg_` 名字。正常的交易成功，拿到新的 id，并且被审计。
5. **指纹：** 两个数据库的生成数据指纹必须相同。
6. 删除临时数据库。删除写在 shell 的 `trap … EXIT` 里，所以**即使检查失败**也会删除。这个目标不会碰任何其他数据库。

Last run (2026-11-07): inventory identical (37 lines), 9/9 behaviour checks PASS, fingerprint equal, temporary DB dropped.
最近一次运行（2026-11-07）：清单完全相同（37 行），9/9 行为检查通过，指纹一致，临时数据库已删除。

## 4. Restore commands (for the README / final report) / 恢复命令（写进 README 和最终报告）
```bash
createdb portfolio_tracker
psql -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql
```
With a password login (Windows, user `postgres`), add `-h localhost -U postgres` to both commands. Also in `README.md`.
使用密码登录时（Windows，用户 `postgres`），两条命令都加上 `-h localhost -U postgres`。`README.md` 里也有。

## 5. Limitations / 限制
- **A recent psql is needed.** pg_dump 16.15 writes a `\restrict <random key>` line at the top and `\unrestrict` at the bottom. This is a 2025 security fix that stops a malicious dump from running shell commands. psql older than 16.10 (or 13.22/14.19/15.14/17.6) doesn't know these commands. The workaround is to upgrade psql or delete those two lines. The random key also changes on every `make dump`, so the file shows a git diff even when the data is the same.
  **需要较新的 psql。** pg_dump 16.15 会在开头写 `\restrict <随机密钥>`，结尾写 `\unrestrict`（2025 年的安全修复，防止恶意 dump 文件执行 shell 命令）。低于 16.10 的 psql 不认识这两个命令。解决办法是升级 psql，或删掉这两行。每次 `make dump` 密钥都会变，所以即使数据没变，git 也会显示文件有改动。
- **psql only, not a GUI query window.** The data is loaded with `COPY … FROM stdin`, which only psql understands. `--inserts` would allow pasting into a GUI, but the file would be bigger and much slower to load. The requirement is psql, so COPY was kept.
  **只能用 psql，不能在图形界面的查询窗口里执行。** 数据用 `COPY … FROM stdin` 加载，只有 psql 能识别。`--inserts` 可以在图形界面里粘贴执行，但文件更大、加载更慢。要求是用 psql，所以保留 COPY。
- The target database should be PostgreSQL 16 (the version used here). Newer versions should also work. Older versions aren't tested.
  目标数据库应为 PostgreSQL 16（这里用的版本）。更新的版本应该也可以，更旧的版本没有测试过。
