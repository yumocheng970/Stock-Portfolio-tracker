# Submission check: fresh-machine README test + Task 4 package / 提交前检查

Date / 日期: 2026-11-07. Tested platform / 测试平台: Windows 11 + WSL 2, Ubuntu 24.04.1, PostgreSQL 16.15, conda 26.1, git 2.43.
Real database `portfolio_tracker`: only read; fingerprint `ea1746ea9890df106c8c9c8df1e38c28` before, between and after every run.
真实数据库 `portfolio_tracker`：只读；每次运行前、中、后指纹都是 `ea1746ea…`。

## 1. Dump regenerated / 重新生成 dump
**EN:**
- `make dump && make verify-dump`: ALL OK.
  - Restored with psql (0.59 s) and without psql (0.63 s).
  - The 37-line inventory is identical to the real DB.
  - 9/9 behaviour checks passed, and the fingerprint is equal.
- The dump now contains `restore_trade`, `trg_stock_benchmark_protected` and the current functions.
- The file is 2,648,331 bytes, with no line starting with `\`.
- Committed separately (`d198faa`).

**中文：**
- `make dump && make verify-dump` 全部通过：用 psql 和不用 psql 各恢复了一次，清单完全相同，9/9 行为检查通过，指纹一致。
- dump 中包含了 `restore_trade`、^GSPC 保护触发器和最新的函数。
- 单独提交（`d198faa`）。

## 2. Fresh-machine test, Run 1 (the OLD README) / 第一次全新环境测试（旧 README）
**Method:** a clone into a scratch folder, a new conda env `spt-fresh`, a new database `pt_fresh_check`, then only what the README said. Where it was silent, I improvised as a new user would and wrote it down.
**方法：** 克隆到临时文件夹，新建 conda 环境 `spt-fresh` 和数据库 `pt_fresh_check`，只按 README 操作；README 没写的地方像新用户一样自己摸索，并记录下来。

| # | Step / 步骤 | What happened / 结果 | Fix / 修正 |
|---|---|---|---|
| 1 | Start / 开始 | No overview, no tested platform, no prerequisites, no download pages / 没有介绍、测试平台、前置条件和下载页面 | New sections "Tested platform" and "1. Install the prerequisites (download pages)" for PostgreSQL, Miniforge, Python, Git, DBeaver, WSL |
| 2 | Get the code / 获取代码 | Not mentioned / 没有提到 | "2. Get the code" (git clone, or unzip the package) + "run every command from this folder" |
| 3 | `conda activate spt` | The README's first command; the environment doesn't exist on a new machine, and creating it is never mentioned / 环境不存在，README 也没说怎么创建 | "3. Create the Python environment" (conda, or pip + venv) |
| 4 | `environment.yml` | Created fine on Linux (41 s), but it was a **Linux build export** (`python=3.12.14=h5f976f7_3_cpython`, …), impossible on Windows / macOS, and it installed unused `cxx-compiler`, `pybind11`, `cmake`, `kaggle` / 是 Linux 专用的导出文件，在 Windows/macOS 上无法创建，还包含没用到的包 | **Portable** `environment.yml` and `requirements.txt`: only the 8 libraries the code imports, tested versions as minimums, Faker exact (40.40.0); a library / version table in the README |
| 5 | Database name / 数据库名 | The commands used `portfolio_tracker`, and nothing said the name must match `.env` / 没说名字要和 `.env` 一致 | "use the same name as DB_NAME in .env" |
| 6 | Restore / 恢复 | `psql … -f cheng_final_project.sql` → **No such file or directory** (the file is in `db/dump/`) / 找不到文件 | All paths are now `db/dump/cheng_final_project.sql` (Windows: `db\dump\…`) |
| 7 | Run the app / 运行 | **No `.env` step** → "Can't connect to PostgreSQL (No such file or directory)": conda's libpq looks for the socket in `/tmp` / 没有 `.env` 这一步，连不上 | "4. Configure the connection (.env)": `cp .env.example .env` + a table for Linux/WSL, Windows / password login (`postgres`), macOS; the variants also written into `.env.example` |
| 8 | Start PostgreSQL / 启动服务 | Only in the troubleshooting table / 只出现在故障排除表里 | In step 1: `sudo service postgresql start`, `createuser --createdb "$USER"` |
| 9 | Windows / macOS | Nothing, and `make` / `$VAR=` syntax don't work on Windows / 没有说明 | Platform notes in steps 1, 3, 4, 5, 6 (PowerShell `$env:DB_NAME=…`, commands without make); marked **untested** |
| 10 | DBeaver step | Said "15 functions, 2 procedures, about 140 statements": out of date / 数字过时 | Now 16 functions, 3 procedures, 10 triggers, 148 statements (counted in the restored DB) |
| 11 | Developers / 开发者 | `make test` etc. not explained / 没有说明 | "9. For developers": a table of make targets + building from source + commands without make |
| 12 | Packaging (found in step 4 of this check) | `unzip` isn't installed on a fresh Ubuntu, and the README asked for `zip`, which `git archive` doesn't need / 新装的 Ubuntu 没有 unzip | `make package` lists the zip with Python's `zipfile`; `zip` removed from the apt line |

With these workarounds, Run 1 still worked end to end (restore: 1,155 trades; the app: investor, portfolio, BUY 5 AAPL @ 342.37, monthly report). The README was the problem, not the code.
按这些方法绕过之后，第一次测试也能从头到尾跑通，问题出在 README，而不是代码。

## 3. Fresh-machine test, Run 2 (the NEW README, commit `1727274`) / 第二次测试（新 README）
**EN:** a new clone, following only the new README's Linux / WSL path:
1. Prerequisites present: psql 16.15, the service running, git, make.
2. `git clone` (from the local repository, because nothing is pushed to GitHub yet).
3. `conda env create -f environment.yml`, **27 s**, as `-n spt-fresh` so it doesn't collide with the working `spt`. It resolved Python 3.12.16, psycopg 3.3.8, Faker 40.40.0, and all imports work.
4. `cp .env.example .env`, with `DB_NAME=pt_fresh_check`.
5. `createdb pt_fresh_check` + the README's restore command → exit 0; the quick check shows 1,155 trades.
6. `python -m app`: create investor → create portfolio (10,000) → Buy 5 AAPL → Reports → Sector allocation (Technology 17.12 %, Cash 82.88 %) → exit 0.
7. `make test` inside the clone: **343 SQL + 229 pytest passed**.

**Result: PASS, using only the README.**

**Cleanup:** `dropdb pt_fresh_check` (name checked first), `conda env remove -n spt-fresh`, clone deleted; fingerprint unchanged.

**中文：** 新克隆一份，只按新 README 的 Linux/WSL 步骤操作：
1. 前置软件都在（psql 16.15、服务在运行、git、make）。
2. 克隆（从本地仓库，因为还没推送到 GitHub）。
3. 创建环境用了 27 秒（命名为 spt-fresh，避免和正在用的 spt 冲突），所有库都能导入。
4. 复制 `.env`，`DB_NAME=pt_fresh_check`。
5. 建库、恢复、检查：1,155 笔交易。
6. 运行程序：新建投资者和组合、买入 5 股 AAPL、查看行业配置报表、退出。
7. 在克隆里运行 `make test`：全部通过。

**结果：只看 README 就能完成，通过。** 清理：删除临时数据库、环境和克隆；指纹不变。

**Not tested / 没有测试：** native Windows and macOS (the instructions are written from the official installers' defaults). The pip + venv path was not run either; it lists the same libraries as `environment.yml`.
原生 Windows 和 macOS（按官方安装程序的默认设置写的说明），以及 pip + venv 的方式（库与 environment.yml 相同）。

## 4. The Task 4 package / 提交包: `make package` → `cheng_project.zip`
**EN:**
- Built with `git archive --prefix=cheng_project/ HEAD`, minus `analytics_cpp/` and `CLAUDE.md`.
- Only **committed** files can be in it, so `.env`, `logs/`, `charts/` and `__pycache__` (all git-ignored) can't get in, and `.git` is never part of an archive. The target warns if there are uncommitted changes.
- **CLAUDE.md is excluded** (your decision, changed after the first build: it holds working notes for the AI assistant, not part of building or running the project). It stays in the git repository.
- **Contents** (117 files, **about 1.05 MB** zipped; listed again after the change: no CLAUDE.md):

| Files | Path |
|---|---|
| 1 each | `README.md`, `Makefile`, `pytest.ini`, `environment.yml`, `requirements.txt`, `.env.example`, `.gitignore` |
| 23 | `app/` |
| 7 | `etl/` |
| 32 | `db/` (schema, views, programmability, analysis, tests, `dump/cheng_final_project.sql`) |
| 22 | `docs/` (including these notes) |
| 6 | `data/` (`tickers.csv`, `samples/`) |
| 20 | `tests/` |

- **Secret scan:** no `.env`, `logs/`, `charts/`, `__pycache__`, `.git`, `analytics_cpp` or `CLAUDE.md` entries. No line sets `DB_PASSWORD=` (or `password="…"`) to a value. The local `.env` has no password at all (peer login), so there is nothing to leak.
- The zip is git-ignored (`cheng_project.zip`). Rebuild it right before uploading: `make dump && make verify-dump`, commit, `make package`.

**中文：**
- 用 `git archive` 从 HEAD 生成，排除 `analytics_cpp/` 和 `CLAUDE.md`。
- 只会包含**已提交**的文件，所以 `.env`、`logs/`、`charts/`、`__pycache__`（都被 git 忽略）不可能进入压缩包，`.git` 也从来不在 archive 里。有未提交改动时会给出警告。
- **不包含 CLAUDE.md**（你后来改变了决定：它是给 AI 助手的工作说明，不属于项目的构建或运行）。它仍保留在 git 仓库中。
- 117 个文件，压缩后约 1.05 MB，内容见上表（已重新列出，确认没有 CLAUDE.md）。
- **敏感信息扫描：** 没有 `.env`、日志、图表、缓存、`.git`、`analytics_cpp`、`CLAUDE.md`；没有任何一行给 `DB_PASSWORD` 赋了值；本地 `.env` 本身就没有密码（peer 登录）。
- 压缩包被 git 忽略。上传前请重新生成：`make dump && make verify-dump`，提交，然后 `make package`。

## 5. Commits in this step / 本步提交
- `d198faa`: dump regenerated
- `1727274`: README rewrite, portable environment, `make package`
- the final commit: the packaging fixes found during the check (README apt line, zip listing without `unzip`), these notes, report material
