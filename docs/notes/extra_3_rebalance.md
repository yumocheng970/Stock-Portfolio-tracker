# Extra 3: rebalance to target % / 按目标比例再平衡

Menu: Portfolio home → **9 Rebalance** (Rename is now 10, Delete 11).
菜单：组合主页 → **9 Rebalance**（改名变成 10，删除变成 11）。

Flow / 流程:
1. Date (Enter = the usual default) / 日期（回车 = 通常的默认日期）
2. Targets on one line / 一行输入目标：`AAPL 30, MSFT 20, KO 10` (`KO=10`, `KO: 10%` also work / 也可以)
3. Preview table / 预览表
4. Confirm / 确认
5. ALL trades in ONE transaction, SELLs first / 所有交易在一个事务里完成，先卖后买

Decisions (approved) / 已确认的决定:
- (a) targets per ticker / 按股票设定目标
- (b) held tickers you leave out are **kept**; type `KO 0` to sell all / 没写到的持仓**保持不变**，写 `KO 0` 才会全部卖出
- (c) no minimum-trade threshold, because skipping a small SELL could break the cash guarantee / 不设最小交易门槛，因为跳过一笔小额卖出可能破坏"现金不为负"的保证

In read-only mode the preview works (it only reads), and the trades are refused at the confirm step.
只读模式下可以预览（只读取数据），在确认那一步拒绝交易。

Files / 文件：`app/rebalance.py` (pure / 纯函数), `tests/test_rebalance.py` (21), `tests/test_app_rebalance.py` (8); `app/data_access.py` (`latest_closes`, `execute_rebalance`), `app/menus/portfolio_menu.py`.

---

## 1. Worked example by hand / 手算示例
**EN:** Cash 2,000. Holdings: 10 AAA @ 150, 20 BBB @ 40, 30 KEEP @ 10. Targets: `AAA 25, BBB 10, CCC 40` (CCC @ 33 is not held yet; KEEP is not in the targets, so it is kept).
**中文：** 现金 2,000。持仓：10 AAA @ 150，20 BBB @ 40，30 KEEP @ 10。目标：`AAA 25, BBB 10, CCC 40`（CCC @ 33 目前没有持有；KEEP 不在目标里，所以保持不变）。

**Step 1: total value / 总市值**
V = 2,000 + 10×150 + 20×40 + 30×10 = 2,000 + 1,500 + 800 + 300 = **4,600**

**Step 2: is it possible? / 能不能做到？**
- Kept / 保持不变：KEEP 300 / 4,600 = 6.52 %
- Targets / 目标：25 + 10 + 40 = 75 %
- 75 + 6.52 = 81.52 % ≤ 100 % ✓, so the cash target = 100 − 81.52 = **18.48 %** / 现金目标 = 18.48 %

**Step 3: target shares and whole-share trades (SELL rounds UP, BUY rounds DOWN) / 目标股数与整股交易（卖出向上取整，买入向下取整）**

| Ticker | Target value | ÷ price = target shares | Now | Trade | After | Value after | % after | Drift |
|---|---|---|---|---|---|---|---|---|
| AAA | 25 % × 4,600 = 1,150 | 1,150 / 150 = 7.667 | 10 | SELL ⌈2.333⌉ = **3** | 7 | 1,050 | 22.83 % | −2.17 |
| BBB | 10 % × 4,600 = 460 | 460 / 40 = 11.5 | 20 | SELL ⌈8.5⌉ = **9** | 11 | 440 | 9.57 % | −0.43 |
| CCC | 40 % × 4,600 = 1,840 | 1,840 / 33 = 55.758 | 0 | BUY ⌊55.758⌋ = **55** | 55 | 1,815 | 39.46 % | −0.54 |
| KEEP | (kept / 保持) | | 30 | – | 30 | 300 | 6.52 % | |

**Step 4: cash after / 交易后现金**
2,000 + 3×150 + 9×40 − 55×33 = 2,000 + 450 + 360 − 1,815 = **995** (21.63 %; target 18.48 %)
Check / 验算：1,050 + 440 + 1,815 + 300 + 995 = 4,600 = V ✓
Trades in order / 交易顺序：SELL 3 AAA, SELL 9 BBB, BUY 55 CCC. (The app computed exactly these numbers / 程序算出的结果完全相同。)

**EN:** Every targeted ticker ends a little **below** its target (negative drift), and the cash ends a little **above** its target. That is the price of whole shares, and it is exactly what keeps cash from going negative. AAA's drift is the largest (−2.17 points) because one AAA share (150) is 3.3 % of this small portfolio.
**中文：** 每只目标股票最后都略**低于**目标（漂移为负），现金略**高于**目标。这是整股交易的代价，也正是它保证现金不会变成负数。AAA 的漂移最大（−2.17 个百分点），因为在这个小组合里一股 AAA（150）就占 3.3 %。

## 2. Why cash can never go negative (the proof in plain words) / 为什么现金永远不会为负（用白话证明）
**EN:**
1. Rounding a SELL **up** sells at least enough, and rounding a BUY **down** buys at most enough. So every targeted ticker ends **at or below** its target value (25 % of V, …).
2. Every trade uses the same price the portfolio was valued at, so a trade only moves value between cash and shares. The total stays V.
3. So cash after = V − (targeted values after) − (kept values) ≥ V − (targets × V) − kept = V × (100 % − targets − kept %).
4. That is ≥ 0 exactly when targets + kept ≤ 100 %, which the calculation checks first ("Targets (…) + positions you keep (…) exceed 100 %").
5. A test runs the calculation on **1,000 random portfolios** (seeded, so they are the same every time) and checks both facts every time: cash after ≥ 0, and every value after ≤ its target.

- **Why SELLs go first:** all trades are on the same day, and the database replays same-day trades by trade_id. Inserting SELLs first gives them smaller ids, so the sale cash already exists when each BUY is checked. A test shows the BUY-first order is refused (`BUY 100 BBB: Not enough cash …`).

**中文：**
1. 卖出**向上**取整，就至少卖够；买入**向下**取整，就最多买够。所以每只目标股票最后都**不超过**它的目标市值。
2. 每笔交易都用估值时的同一个价格，交易只是让价值在现金和股票之间移动，总市值仍然是 V。
3. 所以交易后现金 = V − 目标股票交易后的市值 − 保持不变的市值 ≥ V × (100 % − 目标合计 − 保持部分的 %)。
4. 只要"目标 + 保持部分 ≤ 100 %"（计算前会先检查），结果就 ≥ 0。
5. 有一个测试用 **1,000 个随机组合**（固定种子，每次都一样）检查这两点：交易后现金 ≥ 0，每只股票交易后的市值 ≤ 它的目标。

- **为什么先卖后买：** 所有交易都在同一天，数据库按 trade_id 重放同一天的交易。先插入卖出，它们的 id 就更小，检查每笔买入时卖出得到的现金已经在了。有测试证明先买后卖会被拒绝。

## 3. All or nothing / 要么全成，要么全不成
**EN:** `da.execute_rebalance` runs all trades in ONE `with conn.transaction():`. If the database refuses any trade, for example a ticker valued at an earlier close but with **no price on the chosen day**, or an index such as ^GSPC, it raises `RebalanceTradeError("BUY 250 LATE", error)` inside the block. Every trade before it (here the SELL) is rolled back, and the message reads: `BUY 250 LATE: No price for LATE on 2025-03-04 (not a trading day, or unknown ticker).`
**中文：** 所有交易在一个事务里执行。只要数据库拒绝其中任何一笔，例如某只股票按更早的收盘价估值、但选定那天**没有价格**，或者是 ^GSPC 这样的指数，就在事务块里抛出 `RebalanceTradeError`，之前的交易（这里是那笔卖出）全部回滚，并显示上面那条消息。

---

## 4. New Python features / 新的 Python 知识点
### `math.floor` / `math.ceil` on Decimal / 对 Decimal 取整
**EN:** `math.floor(Decimal("55.758"))` → `55` and `math.ceil(Decimal("2.333"))` → `3`. The result is an exact Python `int` (no float in between), which is what a whole number of shares needs. `-math.ceil(x)` writes a SELL as a negative trade.
**中文：** 结果是精确的 Python `int`（中间不经过 float），正好用于整数股数。`-math.ceil(x)` 把卖出表示成负数。

### Signed integers for trades / 用正负号表示买卖
**EN:** In `Line.trade`, `+76` = BUY 76 and `−80` = SELL 80. One number gives both direction and size; `trade_text()` turns it into "BUY 76" / "SELL 80" for display. `shares_after = shares + trade` works for both.
**中文：** `+76` 表示买入 76，`−80` 表示卖出 80。一个数字同时表示方向和数量；`shares_after = shares + trade` 对买卖都成立。

### Parsing a line of text / 解析一行文字
**EN:**
```python
entries = [part.strip() for part in text.split(",") if part.strip()]   # "AAPL 30, KO 10" -> ["AAPL 30", "KO 10"]
ENTRY = re.compile(r"(\S+?)\s*[=:\s]\s*(\S+)")                          # ticker, then = or : or space, then number
```
- `\S+?` = one or more non-space characters, as few as possible (the `?`), so `KO=10` splits at `=`.
- `[=:\s]` = one of `=`, `:` or a space.
- `.rstrip("%")` removes a trailing `%`.
- Every problem is collected, as in the CSV import.

**中文：**
- `\S+?` 表示一个或多个非空白字符，尽量少地匹配（就是那个 `?`），所以 `KO=10` 会在 `=` 处分开。
- `[=:\s]` 表示 `=`、`:` 或空格中的一个。
- `.rstrip("%")` 去掉结尾的 `%`。
- 和 CSV 导入一样，所有问题都会收集起来一起显示。

### `NamedTuple._asdict()` and a NamedTuple inside a NamedTuple / 转成字典
**EN:** `Plan` holds a list of `Line` tuples. The menu displays them with `line._asdict()`, which gives a dict `{"ticker": …, "price": …}` (the leading underscore is part of the official name; it isn't "private"), and adds two display columns with `{**dict, …}`.
**中文：** `Plan` 里包含一个 `Line` 列表。菜单用 `line._asdict()` 把它变成字典再显示（开头的下划线是官方名字的一部分，不表示"私有"），再用 `{**字典, …}` 加两列显示用的文字。

### Randomized tests with a seed / 带种子的随机测试
**EN:**
```python
rng = random.Random(5200)          # its own random generator, seeded
prices = {t: D(rng.randint(100, 500000)) / 100 for t in tickers}
```
- A **seed** makes the "random" numbers the same on every run, so a failure can be repeated and debugged.
- `random.Random(seed)` is a separate generator, so it doesn't disturb any other code that uses `random`.
- 1,000 random cases check the rounding proof far more broadly than a few hand-picked examples.

**中文：**
- **种子**让"随机"数每次运行都一样，一旦失败就能重现、调试。
- `random.Random(seed)` 是独立的生成器，不会影响其他使用 `random` 的代码。
- 1,000 个随机组合比几个手选的例子更全面地检验了取整的证明。

### Set union / 集合并集
**EN:** `set(holdings) | set(targets)` gives every ticker that is held **or** targeted, each once. Those are the tickers whose prices are needed.
**中文：** `set(holdings) | set(targets)` 得到"持有**或**设了目标"的所有股票代码，每个只出现一次，也就是需要查价格的那些股票。

---

## Tests / 测试
**EN:**
- **21 pure tests:** the two examples from the spec, uneven prices (cash left 15.52), a SELL rounded up, **1,000 random portfolios**, kept ticker, targets + kept > 100 %, a target of 0, missing price, empty portfolio, no trades needed, and parsing (formats + 9 shape errors, all listed).
- **8 DB tests:** sell-then-buy executes and matches the views; buy-first is refused (why the order matters); all or nothing when a later trade has no price that day; an index target refused by the DB; `latest_closes`; the menu (confirmed / declined / read-only / missing price).
- Totals: 343 SQL + 217 pytest. Also: a read-only preview on the real DB (portfolio 3: SELL 80 CVX, SELL 29 HD, SELL 10 NVDA, BUY 76 AAPL), refused at the confirm step; fingerprint unchanged.

**中文：**
- **21 个纯函数测试**：规格里的两个例子、除不尽的价格（剩余现金 15.52）、卖出向上取整、**1,000 个随机组合**、保持不变的持仓、目标 + 保持部分 > 100 %、目标为 0、缺少价格、空组合、无需交易，以及解析（各种格式 + 9 种格式错误，全部列出）。
- **8 个数据库测试**：先卖后买成功，并与视图一致；先买后卖被拒绝（说明顺序的重要性）；后面某笔交易当天没有价格时全部回滚；指数目标被数据库拒绝；`latest_closes`；菜单（确认 / 取消 / 只读 / 缺少价格）。
- 合计：SQL 343 个 + pytest 217 个。另外在真实库上用只读模式预览过（组合 3），在确认那一步被拒绝；指纹不变。
