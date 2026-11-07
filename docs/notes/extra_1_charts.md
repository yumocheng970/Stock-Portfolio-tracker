# Extra 1: PNG charts / PNG 图表

Where / 在哪里:
- Portfolio home → 5 Reports → **Monthly return vs S&P 500** or **Sector allocation** → after the table: `Save as PNG chart (+ CSV data)? (y/N)`
- Main → 2 Market data → **Top movers** → the same question.
- 组合主页 → 5 Reports → 月度收益 / 行业配置，以及 主菜单 → 2 Market data → 涨跌幅榜：表格之后都会问是否保存 PNG 图表。

Files go into `charts/` (git-ignored) / 文件保存在 `charts/`（git 忽略）:
```
charts/portfolio-3_returns-vs-sp500_2026-11-07.png   + .csv   (the period's last day / 区间最后一天)
charts/portfolio-3_sector-allocation_2026-11-06.png  + .csv   (as-of date / 截至日期)
charts/top-movers_2026-10-07_to_2026-11-06.png       + .csv   (start_to_end / 开始到结束)
```
In WSL the app then asks `Open the chart in Windows? (y/N)`. Charts only read data, so they also work in `make run-readonly`.
在 WSL 里还会问是否用 Windows 打开。图表只读取数据，所以只读模式下也能用。

New files / 新文件：`app/charts.py`, `tests/test_app_charts.py` (13 tests).
Also / 另外：price history shows volume as `4,828,050,000` / 价格历史中的成交量带千位分隔符。

---

## New Python features only (matplotlib basics) / 只讲新的 Python 知识点（matplotlib 基础）

### 1. The backend, set before pyplot / 后端：在 pyplot 之前设置
**EN:**
```python
import matplotlib
matplotlib.use("Agg")                # "Agg" = draw into image files only
import matplotlib.pyplot as plt
```
- A **backend** decides where matplotlib draws: a window (interactive backends such as Qt or Tk), or only an image in memory (**Agg**).
- With Agg, `plt.show()` does nothing and no window can ever open. That is right for a terminal app, for tests, and for WSL without a display.
- It must be chosen **before** `pyplot` is imported, which is why those two imports are separated (the `# noqa` comment tells style checkers this order is on purpose).

**中文：**
- **后端**决定 matplotlib 画到哪里：窗口（Qt、Tk 等交互式后端），或者只画进内存里的图片（**Agg**）。
- 用 Agg 时 `plt.show()` 什么也不做，永远不会弹出窗口。这正适合终端程序、测试，以及没有显示器的 WSL。
- 必须在导入 `pyplot` **之前**选择，所以这两个 import 分开写（`# noqa` 告诉代码风格检查工具：这个顺序是故意的）。

### 2. Figure and Axes / 画布与坐标轴
**EN:**
```python
fig, ax = plt.subplots(figsize=(9, 5))       # a Figure (the image, 9 x 5 inches) with one Axes (the plot area)
ax.plot(x, y, label="Portfolio 3")           # a line
ax.barh(labels, values)                      # horizontal bars
ax.set_title("..."); ax.set_xlabel("..."); ax.legend(); ax.grid(alpha=0.3)
fig.savefig(path, dpi=120, bbox_inches="tight")   # write the PNG
plt.close(fig)                               # free it; otherwise figures pile up in memory
```
- `fig` is the whole image; `ax` is the area with the axes, where the data is drawn.
- We call methods on `ax` (the "object-oriented" style) instead of the global `plt.plot(...)`, so each function clearly owns its own figure.
- `dpi` = dots per inch: 9 inches × 120 dpi ≈ 1080 pixels wide.
- `bbox_inches="tight"` trims the empty margins.

**中文：**
- `fig` 是整张图；`ax` 是带坐标轴、真正画数据的区域。
- 我们调用 `ax` 的方法（"面向对象"的写法），而不是全局的 `plt.plot(...)`，这样每个函数明确地拥有自己的那张图。
- `dpi` 是每英寸点数：9 英寸 × 120 ≈ 1080 像素宽。
- `bbox_inches="tight"` 去掉多余的空白边。

### 3. The three charts / 三种图
**EN:**
- **Portfolio vs S&P 500:** two `ax.plot` lines. Both start at **100**: level = `100 × (1 + cumulative % / 100)`, so +18.24 % → 118.24 and −1.00 % → 99.00 (`charts.index_level`).
  - x = the first period's start date, then each month's end date. matplotlib understands `date` objects, and `fig.autofmt_xdate()` slants the date labels.
  - The title shows the final cumulative % of both.
- **Sector allocation:** `ax.barh` (horizontal bars, better than a pie when there are 9 slices).
  - Cash is drawn grey.
  - `ax.bar_label(bars, labels=[...])` writes "19.00 %" at the end of each bar.
  - `ax.invert_yaxis()` puts the first row at the top.
- **Top movers:** green bars for gains, red for losses: `color=["tab:green" if v > 0 else "tab:red" for v in values]`.
  - `ax.axvline(0)` draws the zero line.
  - `ax.set_xlim(...)` leaves 30 % extra room on both sides so the labels don't overlap the ticker names.

**中文：**
- **组合对比标普 500：** 两条 `ax.plot` 折线，都从 **100** 开始：水平 = `100 × (1 + 累计% / 100)`。x 轴是第一个区间的开始日期，再加上每个月的月末日期。matplotlib 认识 `date` 对象，`autofmt_xdate()` 让日期标签倾斜。标题显示两者最终的累计收益。
- **行业配置：** `ax.barh` 横向柱状图（9 个分类时比饼图清楚）。现金画成灰色；`bar_label` 在每根柱子末端写上百分比；`invert_yaxis()` 让第一行显示在最上面。
- **涨跌幅榜：** 上涨绿色、下跌红色；`axvline(0)` 画出零线；`set_xlim` 两边各留 30% 的空间，标签就不会盖住股票代码。

### 4. matplotlib wants numbers, not Decimal / matplotlib 要普通数字
**EN:** `values = [float(r["pct"] or 0) for r in rows]`. Plotting needs plain floats, and tiny float errors don't matter in a picture. The numbers printed **on** the chart still come from `format_pct` (exact Decimal, half-up). `x or 0` turns a `None` into 0.
**中文：** 画图需要普通的 float，图上的微小误差无所谓；但图上**写出来**的数字仍然用 `format_pct`（精确的 Decimal，四舍五入）。`x or 0` 把 `None` 变成 0。

### 5. Writing CSV / 写 CSV: `csv.DictWriter`
**EN:**
```python
with open(path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()          # first line: the column names
    writer.writerows(rows)        # one line per dict; None -> empty field
```
- `newline=""` is required by the csv module, otherwise Windows shows blank lines between rows.
- The CSV gets the SQL function's rows **unchanged**. A sorted copy is used only for drawing the bars, and a test checks the CSV equals `SELECT * FROM fn_…`.

**中文：**
- `newline=""` 是 csv 模块要求的写法，否则 Windows 里行与行之间会出现空行。
- CSV 里是 SQL 函数返回的**原样**数据；排序后的副本只用来画柱子，测试会核对 CSV 与 `SELECT * FROM fn_…` 完全一致。

### 6. `pathlib.Path` / 路径对象
**EN:**
- `Path(__file__).resolve().parent.parent / "charts"` means: this file → its folder (`app/`) → the repo root → `charts`. The `/` operator joins path parts.
- `folder.mkdir(parents=True, exist_ok=True)` creates the folder if needed and doesn't complain if it exists.
- `path.read_bytes()[:8]` reads the first 8 bytes, which is how a test checks the **PNG signature** `b"\x89PNG\r\n\x1a\n"`.

**中文：**
- `Path(__file__).resolve().parent.parent / "charts"`：本文件 → 所在文件夹（`app/`）→ 仓库根目录 → `charts`。`/` 运算符用来拼接路径。
- `mkdir(parents=True, exist_ok=True)`：需要时创建文件夹，已存在也不报错。
- `read_bytes()[:8]` 读出前 8 个字节，测试用它检查 **PNG 文件头**。

### 7. Running another program / 运行其他程序: `subprocess.run`
**EN:**
```python
windows_path = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, check=True).stdout.strip()
subprocess.run(["explorer.exe", windows_path], check=False)
```
- `wslpath -w` turns `/home/ethan/...` into `\\wsl.localhost\Ubuntu\home\ethan\...`. `explorer.exe` (Windows) then opens the file like a double-click.
- `capture_output=True, text=True` gives the program's output as a string in `.stdout`.
- `check=True` raises an error if the program fails. For explorer.exe it's `False`, because explorer.exe exits with code 1 even when it worked.
- Arguments are passed as a **list**, not as one string, so a path with spaces is safe.
- `is_wsl()` checks `platform.uname().release` (contains "microsoft" in WSL) or the `WSL_DISTRO_NAME` environment variable.

**中文：**
- `wslpath -w` 把 Linux 路径变成 Windows 能用的路径，然后 `explorer.exe` 像双击一样打开文件。
- `capture_output=True, text=True`：把程序的输出作为字符串放在 `.stdout` 里。
- `check=True`：程序失败时抛出错误。explorer.exe 用 `False`，因为它即使成功也返回 1。
- 参数用**列表**传，而不是拼成一个字符串，所以路径里有空格也没问题。
- `is_wsl()` 通过 `platform.uname().release`（WSL 里包含 "microsoft"）或环境变量 `WSL_DISTRO_NAME` 判断。

### 8. Passing a function by name / 按名字传函数: `getattr`
**EN:**
- `offer_chart("save_sector_chart", rows, pid, as_of)` imports `app.charts` only when the user answers "y", and then finds the function with `getattr(charts, "save_sector_chart")`, which is the same as `charts.save_sector_chart`.
- So the menus don't import matplotlib, and the app starts fast.

**中文：** `offer_chart` 只有在用户回答 "y" 时才导入 `app.charts`，再用 `getattr(charts, "函数名")` 找到函数（等同于 `charts.函数名`）。所以菜单不需要导入 matplotlib，程序启动更快。

### 9. Thousands separators for whole numbers / 整数的千位分隔符
**EN:** `f"{4828050000:,}"` → `"4,828,050,000"`. The `,` in the format spec adds the separators. `print_table(..., thousands=("volume",))` applies it only to the columns named there: IDs must stay `1159`, not `1,159`.
**中文：** 格式说明中的 `,` 会加上千位分隔符。`thousands=("volume",)` 只对指定的列生效，ID 必须保持 `1159`，而不是 `1,159`。

---

## Tests / 测试
**EN:**
- 13 new pytest tests (test DB rolled back; files only in pytest's `tmp_path`):
  - the backend is Agg
  - each chart writes a real PNG (signature + size) and a CSV equal to the SQL function's rows (3 tests)
  - index levels start at 100
  - an empty result → None and no file (3, parametrized)
  - menu: "y" saves into `CHART_DIR` and offers "open in Windows" when `is_wsl` (opening is recorded, not done)
  - menu: "n" saves nothing
  - charts work in a read-only transaction
  - volume separators
- An autouse fixture makes `subprocess.run` fail, so no test can start explorer.exe.
- Changed existing tests: 3 in `test_app_reports.py` got one more answer (`""` = no) for the new "Save as PNG chart?" question.
- Totals: 343 SQL + 160 pytest. Also: the three charts were made from the real DB in read-only mode, and I looked at them (the top-movers labels were overlapping, now fixed).

**中文：**
- 新增 13 个 pytest 测试（测试库回滚；文件只写到 pytest 的 `tmp_path`），覆盖上方英文列表中的情况。
- 一个自动使用的 fixture 让 `subprocess.run` 直接失败，所以任何测试都不可能启动 explorer.exe。
- 修改的已有测试：`test_app_reports.py` 里 3 个测试多了一个回答（`""` = 不保存），对应新增的 "Save as PNG chart?" 问题。
- 合计：SQL 343 个 + pytest 160 个。另外用真实数据在只读模式下生成了三张图，并查看过（涨跌幅榜的标签原来有重叠，已修正）。
