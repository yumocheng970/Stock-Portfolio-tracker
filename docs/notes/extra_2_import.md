# Extra 2: CSV trade import / CSV 交易导入

Menu: Portfolio home → **8 Import from CSV**. Samples for the video: `data/samples/` (read its README).
菜单：组合主页 → **8 Import from CSV**。录视频用的示例文件在 `data/samples/`（请先看那里的 README）。

```
date,type,ticker,shares,price,amount
2026-09-01,DEPOSIT,,,,5000
2026-09-01,BUY,AAPL,10,,            <- empty price = that day's close / 价格留空 = 当天收盘价
2026-10-01,BUY,NVDA,5,230.00,
```

The three steps / 三个步骤:
1. **Check the shape of every row** (`app/csv_import.py`, pure Python). If anything is wrong, ALL problems are listed and nothing is saved.
   **检查每一行的格式**（纯 Python）。有任何问题就列出全部问题，什么都不保存。
2. **Preview and confirm**: counts, date range, tickers, and whether rows were reordered.
   **预览并确认**：数量、日期范围、股票代码、是否重新排序。
3. **ONE transaction** (`da.import_events`): each row through `execute_trade()` / `record_cash_transaction()`. The first refusal → "Row N: <message + DETAIL>", and everything is rolled back.
   **一个事务**：每行都通过存储过程；第一次被拒绝 → "Row N: …"，全部回滚。

Decisions / 决定：
- rows are sorted into history order (date, cash before trades, file order) / 自动按历史顺序排序
- Windows paths work / 支持 Windows 路径
- at most 1,000 rows (measured: 1.70 s) / 最多 1,000 行（实测 1.70 秒）

---

## New Python features only (the csv module especially) / 只讲新的 Python 知识点（重点是 csv 模块）

### 1. Reading CSV with `csv.DictReader` / 用 DictReader 读 CSV
**EN:**
```python
with open(path, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f, restkey="_extra")
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    for record in reader:          # record = {"date": "2026-09-01", "type": "BUY", ...}
        row_number = reader.line_num
```
- **`DictReader`** reads the first line as the column names and gives every later line as a **dict** (column name → text). So the code says `record["date"]`, not `record[0]`, and the column order in the file doesn't matter.
- **The csv module handles quoting:** `"Coca-Cola, Inc."` stays one value even though it contains a comma. Splitting each line on commas by hand would get that wrong.
- **`reader.fieldnames`** is the header. Assigning a cleaned list (trimmed, lower case) means `" Date "` and `date` both work.
- **`reader.line_num`** is the line number in the file the reader just read (the header is line 1). That is the "Row N" in every message.
- **`restkey="_extra"`:** if a line has *more* values than there are columns, the extras are put in a list under `"_extra"`, which is how "more values than columns" is detected. A line with *fewer* values gets `None` for the missing columns, which is why the code uses `record.get(column) or ""`.
- **`newline=""`** is required by the csv module (it handles line endings itself). Fully empty lines are skipped automatically.
- **Values are always text.** `int("10")` and `parse_amount("230.00")` turn them into numbers; that's the "shape" check.

**中文：**
- **`DictReader`** 把第一行当作列名，之后每一行都给成一个**字典**（列名 → 文字）。代码写 `record["date"]` 而不是 `record[0]`，文件里列的顺序也就无所谓了。
- **csv 模块会处理引号**：`"Coca-Cola, Inc."` 虽然包含逗号，仍是一个值。自己按逗号切分会出错。
- **`reader.fieldnames`** 是表头；换成清理过的列表（去空格、转小写）后，`" Date "` 和 `date` 都能识别。
- **`reader.line_num`** 是刚读到的那一行在文件中的行号（表头是第 1 行），也就是每条消息里的 "Row N"。
- **`restkey="_extra"`**：某行的值比列*多*时，多出来的值放进 `"_extra"` 下的列表，以此发现 "more values than columns"。值比列*少*时，缺少的列是 `None`，所以代码写 `record.get(column) or ""`。
- **`newline=""`** 是 csv 模块要求的写法（换行由它自己处理）。完全空白的行会被自动跳过。
- **读到的值都是文字**，要用 `int(...)`、`parse_amount(...)` 转成数字，这就是"格式检查"。

### 2. `utf-8-sig` and the BOM / 字节顺序标记
**EN:**
- Excel often saves CSV files with an invisible **byte order mark** (BOM, the bytes `EF BB BF`) at the very start.
- Read as plain `utf-8`, the first column name would be `"\ufeffdate"` and the `date` column would seem to be missing.
- `encoding="utf-8-sig"` removes the BOM if present and works normally without one. There is a test with a BOM file.

**中文：**
- Excel 保存 CSV 时，常在文件最开头加一个看不见的**字节顺序标记**（BOM）。
- 用普通 `utf-8` 读取时，第一列名会变成 `"\ufeffdate"`，看起来就像缺少了 `date` 列。
- `utf-8-sig` 有 BOM 就去掉，没有也照常读取。有一个专门用 BOM 文件的测试。

### 3. `typing.NamedTuple`: a small record type / 小型记录类型
**EN:**
```python
class Event(NamedTuple):
    row: int
    date: object
    kind: str
    ...
    @property
    def is_cash(self):
        return self.kind in CASH_TYPES
```
- A **NamedTuple** is a tuple whose items also have names: `event.date` instead of `event[1]`.
- It is **immutable** (can't be changed after creation), which suits checked data.
- `@property` makes `event.is_cash` look like a field but compute its value.
- Compared with `@dataclass` (App 1's Session, which changes as the user moves around): use NamedTuple for fixed values and dataclass for state that changes.

**中文：**
- **NamedTuple** 是带名字的元组：写 `event.date` 而不是 `event[1]`。
- 它**不可修改**（创建后不能改），正适合检查过的数据。
- `@property` 让 `event.is_cash` 看起来像字段，实际上是计算出来的。
- 和 `@dataclass`（App 1 的 Session，会随用户操作而变化）相比：固定的值用 NamedTuple，会变化的状态用 dataclass。

### 4. Sorting with a tuple key / 用元组作为排序键
**EN:**
```python
sorted(events, key=lambda e: (e.date, 0 if e.is_cash else 1, e.row))
```
- `key=` tells `sorted` what to compare. A **tuple** key compares item by item: first the date; on the same date, cash (0) before trades (1); then the file row.
- Python's sort is **stable**: equal keys keep their original order. Here the row number in the key makes the order fully defined anyway.
- That is exactly the order the database replays a portfolio's history in.

**中文：**
- `key=` 告诉 `sorted` 按什么比较。**元组**作为键时逐项比较：先比日期；同一天现金（0）排在交易（1）前面；最后比文件行号。
- Python 的排序是**稳定的**：键相同的元素保持原来的顺序；这里键中有行号，所以顺序完全确定。
- 这正是数据库重放组合历史时用的顺序。

### 5. Collect ALL errors, don't stop at the first / 收集所有错误，不在第一个就停
**EN:**
- `check_row` returns `(event, problems)`, and `read_events` keeps going through the whole file, collecting `"Row N: …"` sentences into a list.
- The user fixes every mistake in one go instead of one per try.
- `errors.extend(generator)` adds every item of a generator to the list.

**中文：**
- `check_row` 返回 `(event, problems)`，`read_events` 一直读完整个文件，把 `"Row N: …"` 收集到列表里。
- 用户一次就能改完所有错误，不用一次只改一个。
- `errors.extend(生成器)` 把生成器的每一项都加进列表。

### 6. An exception that carries data / 携带数据的异常
**EN:**
```python
class ImportRowError(Exception):
    def __init__(self, row, error):
        super().__init__(f"row {row}: {error}")
        self.row = row
        self.error = error
```
- `__init__` runs when the exception is created. `super().__init__(...)` lets the normal Exception set its message, and the two attributes keep the **row number** and the **original database error**.
- `errors.friendly_message` then builds `f"Row {error.row}: {friendly_message(error.error)}"`: the usual friendly text plus DETAIL, with the row in front.
- Raising it **inside** `with conn.transaction():` is what rolls back all earlier rows.

**中文：**
- 创建异常时会运行 `__init__`。`super().__init__(...)` 让普通的 Exception 设置它的消息，另外两个属性保存**行号**和**原来的数据库错误**。
- `errors.friendly_message` 再拼成 `"Row 行号: 友好提示 + DETAIL"`。
- 在 `with conn.transaction():` **里面**抛出它，前面导入的所有行都会被回滚。

### 7. Paths: Windows → WSL, quotes, `~` / 路径处理
**EN:**
```python
WINDOWS_PATH = re.compile(r"([A-Za-z]):[\\/](.*)")
# "C:\Users\me\a.csv" -> Path("/mnt") / "c" / "Users/me/a.csv"
```
- `text.strip('"')` removes the quotes Windows adds with "Copy as path".
- `Path(text).expanduser()` turns `~` into your home folder.
- `path.exists()` and `path.is_file()` give the friendly "File not found" / "Not a file" messages.
- `r"..."` is a raw string, so `\\` in the pattern means one literal backslash.

**中文：**
- `strip('"')` 去掉 Windows "复制为路径" 时加上的引号。
- `expanduser()` 把 `~` 变成你的主目录。
- `exists()` 和 `is_file()` 用来给出 "File not found" / "Not a file" 这样的友好提示。
- `r"..."` 是原始字符串，模式里的 `\\` 表示一个真正的反斜杠。

### 8. A set for "each ticker once" / 用集合去重
**EN:** `sorted({e.ticker for e in events if e.ticker})`. The `{ … for … }` braces without `:` build a **set** (no duplicates), and `sorted` turns it into an ordered list for the preview.
**中文：** 不带 `:` 的 `{ … for … }` 生成**集合**（没有重复），再用 `sorted` 变成排好序的列表用于预览。

---

## Tests / 测试
**EN:**
- 28 new pytest tests (test DB rolled back, CSV files in `tmp_path`):
  - a valid file (cash and holdings = the views)
  - errors on rows 3 and 5 both listed, nothing saved
  - each shape rule (7, parametrized)
  - empty / header-only / missing column / unknown column
  - not found / a folder
  - the row limit
  - an Excel BOM + header spaces
  - an overdraw on row 4 → "Row 4: Not enough cash. Cash would be -90,500.00 …", nothing saved (rows 2 and 3 rolled back too)
  - the history order (same-day deposit first, row numbers kept)
  - Windows paths (4) and `~`
  - both sample files
  - the menu: confirmed / declined / bad file / read-only
- Measured: 1,000 rows import in 1.70 s.
- Totals: 343 SQL + 188 pytest. Also: a scripted UI run with both samples on the test DB, and the read-only refusal on the real DB (fingerprint unchanged).

**中文：**
- 新增 28 个 pytest 测试（测试库回滚，CSV 文件写在 `tmp_path`），覆盖上方英文列表中的情况。
- 实测：导入 1,000 行用 1.70 秒。
- 合计：SQL 343 个 + pytest 188 个。另外在测试库上用两个示例文件跑过界面流程，在真实库上确认只读模式会拒绝导入（指纹不变）。
