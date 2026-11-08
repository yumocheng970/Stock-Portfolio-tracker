# Fixes from the native-Windows test / 原生 Windows 测试后的修正

Your test / 你的测试：Windows 11, Miniforge Prompt, **PostgreSQL 18.6** (found in `C:\Program Files\PostgreSQL\18`; `postgres.exe --version` = 18.6), `cheng_project.zip`. It worked: environment, restore (1,155 trades), app, all reports and charts. The dump (made with PostgreSQL 16) restores into 18.
它能正常工作：环境、恢复（1,155 笔交易）、程序、所有报表和图表都没问题。用 PostgreSQL 16 生成的 dump 也能恢复到 18。

| # | Finding / 发现 | Fix / 修正 |
|---|---|---|
| 1 | "Extract All" doubles the folder (`cheng_project\cheng_project`) / 解压后文件夹多了一层 | README Quick start step 2 and section 2: "open the inner folder (the one with README.md / setup.bat)" |
| 2 | Port conflict with PostgreSQL in WSL on 5432 / 与 WSL 中的 PostgreSQL 端口冲突 | README section 1 (Windows) + section 8 row: stop one server, or use port 5433 for the Windows one |
| 3 | Too many manual steps (password on every psql command, `.env` by hand) / 手动步骤太多 | **Setup wizard**: `setup.bat` / `setup.sh` → `python -m setup`; restore alone: `python -m db.restore` |
| 4 | A date without a price went on to the price prompt / 没有价格的日期还会继续问价格 | Re-asked at once, with the **reason** and the **nearest trading days** (Buy / Sell, Rebalance) |
| 5 | "Open the chart" worked only in WSL / 只有 WSL 能打开图表 | Windows `os.startfile`, macOS `open`, WSL `explorer.exe` |
| 6 | README start / README 开头 | "Quick start" at the top; tested platforms updated (`setup.bat` not yet tested on Windows) |

---

## 1. The setup wizard / 安装向导
**EN:**
```
setup.bat / ./setup.sh          create conda env "spt" if missing -> conda run --no-capture-output -n spt python -m setup
  .env exists?                  show it (password only as "set"), "Overwrite it? (y/N)"; N = keep and use it
  host / port / user / password defaults per platform; password hidden (getpass)
  test the connection           to the maintenance database "postgres"; on failure: the reason, ask again
  "Connected to PostgreSQL 18.6 on localhost:5432 as postgres."
  server_version_num < 160000?  stop: "too old, 16 or newer" + https://www.postgresql.org/download/
  database name                 [portfolio_tracker] -> write .env (password never printed)
  database exists?              no -> CREATE DATABASE; empty -> restore; the app's tables -> "already restored";
                                other tables -> refuse ("choose another name")
  restore                       db/restore.py (one transaction), then the row counts (1,155 trades)
  "Start the app now? (y/N)"
```

**Per-platform defaults:**

| Platform | host | port | user | password |
|---|---|---|---|---|
| Windows | localhost | 5432 | postgres | asked |
| Linux / WSL | /var/run/postgresql | – | your login | none |
| macOS | /tmp | – | your login | none |

**New pieces of Python and shell:**
- **`getpass.getpass(prompt)`** reads a line without showing it on screen. In a real terminal nothing is echoed. Only without a terminal (e.g. input piped in, as in my automated run) Python warns "Can not control echo" and reads normally.
- **`.env` quoting:** values are written in **single quotes**, which python-dotenv takes literally: no `${VAR}` expansion, and `#` is not a comment. Only `\` and `'` get a backslash in front. A test round-trips the password `p'a ss#$X\y` exactly.
- **`psycopg.sql.Identifier(name)`:** `CREATE DATABASE` can't take a `%s` parameter, so the name is quoted safely as an identifier instead of being pasted into the SQL text.
- **`connect_timeout=5`:** a wrong host fails within 5 seconds instead of hanging.
- **`SHOW server_version_num`** gives a number (`180006` = 18.6). Comparing numbers is safer than comparing text ("9.6" > "16" as text).
- **`conda run --no-capture-output`:** without that flag, conda captures the program's output, and the wizard's questions would be invisible.
- **`call conda …` in `setup.bat`:** `conda` is itself a `.bat` file; without `call`, Windows runs it and **never comes back** to the rest of `setup.bat`.
- **`cd "$(dirname "$0")"` / `cd /d "%~dp0"`:** the scripts work from wherever they are started.

**A bug found by the tests:** the dump runs `SELECT pg_catalog.set_config('search_path', '', false)`. The `false` means "for the whole session", so after a restore, unqualified queries on the **same** connection couldn't find `investor`. `restore_dump` now runs `RESET search_path` afterwards. (`make verify-dump` never noticed, because it opens new connections.)

**中文：**
- 流程见上图。
- **`getpass.getpass`** 读入一行但不在屏幕上显示。在真正的终端里不会回显；只有在没有终端时（例如像我的自动测试那样用管道输入），Python 才会警告 "Can not control echo" 并正常读取。
- **`.env` 的引号：** 值用**单引号**写入，python-dotenv 会按字面读取：不展开 `${VAR}`，`#` 也不当作注释。只有 `\` 和 `'` 需要在前面加反斜杠。有测试验证密码 `p'a ss#$X\y` 能原样读回。
- **`sql.Identifier`：** `CREATE DATABASE` 不能用 `%s` 参数，所以把数据库名作为标识符安全地加上引号，而不是直接拼进 SQL。
- **`connect_timeout=5`：** 主机写错时 5 秒内失败，不会一直卡住。
- **`server_version_num`** 是数字（`180006` = 18.6）。比较数字比比较文字可靠（按文字比较 "9.6" > "16"）。
- **`--no-capture-output`：** 没有这个参数，conda 会截获输出，向导的问题就看不见了。
- **`.bat` 中的 `call conda`：** conda 本身是 `.bat`，不加 `call` 的话，Windows 运行完它就**不会回到** setup.bat 剩下的部分。
- **测试发现的 bug：** dump 里的 `set_config('search_path', '', false)` 对**整个会话**生效，恢复之后同一个连接上的查询找不到表。现在 `restore_dump` 会在最后执行 `RESET search_path`。

## 2. Dates without a price / 没有价格的日期
**EN:**
- `common.ask_trading_date` checks the date with `da.trading_day_info` (one query).
- If there is no price, it prints the reason and the nearest trading days, and asks again with **Enter = the nearest earlier trading day**.
- The reasons are checked in this order (`app/trading_days.py`):

  | Case | Message |
  |---|---|
  | weekend | "2025-03-08 is a Saturday: the market is closed on weekends." |
  | after the last price | "2025-03-12 is after TD1's latest loaded price (2025-03-11)." |
  | before the first price | "2025-02-28 is before TD1's first price (2025-03-03)." |
  | market holiday | "2025-03-05 is a market holiday: no prices that day, ^GSPC has none either." |
  | this stock only | "TD1 has no price on 2025-03-06, although the market was open (^GSPC has one)." |

  Plus: "Nearest trading days for TD1: before 2025-03-04, after 2025-03-07."
- **Buy / Sell** check the chosen ticker. **Rebalance** checks the market (^GSPC); a missing price for one target ticker is still caught by the DB (all or nothing).
- **Not checked:** cash dates, start dates, as-of dates and ranges, because they don't need a trading day.
- If there is nothing to suggest (no ^GSPC data, or a ticker without any prices), it doesn't ask in a loop: the database decides and explains. (The first version looped forever on the rebalance tests, which have no ^GSPC.)

**中文：**
- `ask_trading_date` 用一条查询检查日期。没有价格时，打印原因和最近的交易日，然后再问一次，**回车 = 最近的前一个交易日**。
- 原因按上表的顺序判断。
- 买入/卖出按所选股票检查；再平衡按市场（^GSPC）检查。
- 没有可建议的日期时（没有 ^GSPC 数据，或股票完全没有价格），不会无限循环地问，由数据库判断并说明原因。（第一版在没有 ^GSPC 的再平衡测试里出现过死循环。）

## 3. Opening a chart / 打开图表
**EN:**
- `charts.can_open_charts()` is true on WSL, Windows and macOS.
- `charts.open_chart(path)` dispatches: WSL → `open_in_windows` (wslpath + explorer.exe), Windows → `os.startfile` (like a double-click; it exists only on Windows), macOS → `subprocess.run(["open", path])`.
- Plain Linux isn't offered.

**中文：**
- WSL、Windows、macOS 上可以打开图表。
- WSL 用 explorer.exe，Windows 用 `os.startfile`（相当于双击；只在 Windows 上存在），macOS 用 `open` 命令。
- 普通 Linux 不提供这个选项。

## 4. Tests and checks / 测试与检查
**EN:**
- **21 new pytest tests:**
  - wizard: full run into a scratch DB with a tricky password (never printed, exact `.env` round trip); re-ask after a failed connection; refuses a DB with other tables; keeps an existing `.env` byte for byte; server 15.4 → stop before anything; `.env` quoting; platform defaults
  - `db.restore`: a new scratch DB → 1,155 trades / 15 investors / 26 stocks; the CLI; refuses a DB with tables
  - trading days: 5 reasons with the nearest days; no reason on a trading day; text; the ^GSPC market check; Buy re-asks the date before the price prompt and then buys on Friday
  - chart opener per platform (mocked)
- **Scratch databases** `pt_scratch_<random>` are dropped by a guarded fixture; none were left.
- **`setup.sh`, run end to end in WSL** from a scratch copy of the folder (without `.env`, so your `.env` was never touched) into `pt_setup_check`:
  - found the `spt` env
  - "Connected to PostgreSQL 16.15 on /var/run/postgresql:5432 as ethan."
  - wrote `.env`, created the database, restored in 0.5 s (1,155 trades), exit 0
  - the app started with that `.env`
  - cleaned up afterwards
- `make verify-dump`: ALL OK (the restore code moved to `db/restore.py`).
- Totals: 343 SQL + 250 pytest. The real DB fingerprint was unchanged throughout.

**中文：**
- **21 个新 pytest 测试**，覆盖上方英文列表中的情况。
- 临时数据库由带检查的 fixture 删除，没有残留。
- 在 WSL 里从文件夹的临时副本（不含 `.env`，所以你的 `.env` 不会被碰到）完整运行了 `setup.sh`：建库、恢复（1,155 笔交易）、退出码 0；程序能用写好的 `.env` 启动；之后已清理。
- `make verify-dump` 全部通过。
- 合计：SQL 343 个 + pytest 250 个。真实数据库的指纹始终不变。

**Not tested / 未测试：** `setup.bat` on Windows (it needs your Windows run); macOS.
`setup.bat` 需要你在 Windows 上运行才能测试；macOS 没有测试。
