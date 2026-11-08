# Ticker help at the prompts / 股票代码提示

**EN:** Every ticker prompt now says `(? = list, Enter = cancel)`:
- **Prompts covered:** Buy, Sell, watchlist add, price history, rebalance targets, and admin edit / rename / delete.
- **`?`** lists the tickers that prompt accepts, grouped by sector, two per line (the real list is 30 lines):

  | Prompt | `?` shows |
  |---|---|
  | Buy, Rebalance | all STOCKs (no indexes) |
  | Sell | only the tickers held in this portfolio, with share counts |
  | Watchlist add, price history, admin | stocks **and** indexes (^GSPC under "Indexes") |

- **A company name instead of a ticker** (`apple`, `NVIDIA`, `banking two`: any case, part of the name):
  - one match → "'nvidia' is not a ticker. Did you mean NVDA (NVIDIA Corporation)? (y/N)"
  - several → they are listed, then "Type one of these tickers"
  - no match → "… is not in the stock list"

  In Sell mode only held tickers are searched. In the rebalance targets each unknown name is resolved the same way (`apple 50` → `AAPL 50` after you confirm).
- **Hints only:** the database still decides. Sell of a ticker you don't hold is asked again at once ("You don't hold TK2 in this portfolio. Type ? for what you hold.").

**中文：** 每个股票代码输入处都显示 `(? = list, Enter = cancel)`：
- **覆盖的输入处：** 买入、卖出、添加关注、价格历史、再平衡目标、管理（编辑/改名/删除）。
- **`?`** 按行业分组列出该处接受的代码，每行两个。买入和再平衡只列股票；卖出只列本组合持有的代码和股数；关注、价格历史和管理还包括指数（^GSPC 在 "Indexes" 下）。
- **输入公司名而不是代码**（不区分大小写，可以只写一部分）：
  - 只有一个匹配 → 建议它并请你确认
  - 多个匹配 → 列出来，请你输入其中一个代码
  - 没有匹配 → "不在股票列表中"

  卖出时只在持有的股票里找。再平衡目标中的未知名字也同样处理。
- **只是提示**，仍由数据库决定。

**New Python / 新知识点:**
- **`itertools.groupby(rows, key=…)`** groups consecutive rows with the same key (here the sector). The rows must already be sorted by that key, which the SQL `ORDER BY sector_name` does.
  `groupby` 把相邻、键相同的行分成一组（这里按行业）；行必须先按这个键排好序，SQL 的 `ORDER BY sector_name` 已经做了。
- **`f"{name:<{NAME_WIDTH}}"`** is a nested format spec: pad `name` on the right to a width that is itself a variable.
  嵌套的格式说明：把 `name` 右侧补齐到某个宽度，而这个宽度本身是一个变量。
- **LIKE escaping:** `%` and `_` typed by the user are escaped (`\%`, `\_`), so they match literally, not as wildcards. A test checks `%` matches nothing.
  用户输入的 `%` 和 `_` 会被转义，按字面匹配，不当作通配符；有测试检查 `%` 匹配不到任何内容。
- **One SQL "from" part** (`_TICKER_HELP_FROM`) shared by the list and the search, so both use the same three kinds.
  列表和搜索共用同一段 SQL 的 FROM 部分，所以两者对三种情况的判断完全一致。

**Tests / 测试:** 13 new: the catalog per kind; the format (sectors, two per line, cut names, shares); `?` for Buy (no ^GSPC), watchlist (with ^GSPC) and Sell (only held, then re-ask for an unheld ticker); the Sell menu; one match confirmed / declined; several matches listed; held-only search; wildcards literal; rebalance `?` + `apple 50`; admin by company name.
- **Existing test changed / 修改的已有测试:** `test_app_rebalance.py::test_menu_rebalance_missing_price_message`. An unknown target ticker (`ZZZ 10`) is now caught at the targets prompt ("ZZZ is not in the stock list (type ? for the list).") instead of failing later with "No price for ZZZ …". Same inputs; only the expected message changed.
- Totals: 343 SQL + 270 pytest. Checked read-only on the real DB: the full list is 30 lines; `nvidia` → NVDA.
