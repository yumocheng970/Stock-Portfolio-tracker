# Buy / Sell confirm step and concentration warning

From the proposal's trade flowchart. Python only: no database changes.

## What changed / 改了什么
- **New `app/trade_preview.py`** (pure Python: no database, no input)
  - `trade_amount(shares, price)`: shares × price, rounded half up to cents
  - `cash_after(cash, trade_type, amount)`: BUY subtracts the amount, SELL adds it
  - `preview_text(...)`: the preview line
  - `concentration_after_buy(cash, holdings, closes, ticker, shares, price)`: the ticker's % of the total value after the purchase, or `None` when it can't be computed
  - `concentration_warning(ticker, pct)`: the warning line, or `None` at or below 40 %
  - `CONCENTRATION_WARNING_PCT = Decimal("40")`: the one named constant
- **`app/menus/portfolio_menu.py`**
  - `trade()` calls `confirm_trade()` after the price prompt. No → "Cancelled, nothing saved." and back to the menu. Yes → `execute_trade()` exactly as before.
  - `buy_concentration_warning()` reads the holdings (`da.open_holdings`) and the closes (`da.latest_closes` on the trade day). Both already existed, so there is no new SQL.

中文：
- 新文件 `app/trade_preview.py`（纯 Python，不连数据库、不读输入），负责算预览文字和集中度百分比。
- `portfolio_menu.trade()` 在输入价格之后先显示预览并询问 "Confirm? (y/N)"，默认是 No。
- 只有买入（Buy）才会检查集中度：若买完后某只股票超过总值的 40 %，就显示警告。警告**从不阻止**交易，用户仍然自己决定确认或取消。
- 数据库照样决定一切：确认之后，现金不足等问题仍由触发器拒绝。

## The formula / 公式
Valued at the trade day's closes `c_i`, with the cash before the trade:
```
value_t = (held_t + n) × c_t
total   = cash − n × p + Σ held_i × c_i + n × c_t
share_t = value_t / total × 100
```
- If you pay exactly the close, the total doesn't change; only cash turns into shares.
- If you pay above the close, the total drops a little (you overpaid).
- A missing close or a total ≤ 0 → `None` → no warning.

中文：若成交价等于收盘价，总值不变，只是现金变成了股票；若高于收盘价，总值会略微减少。

**Tiny example / 小例子:** cash 9,000, 20 CC2 @ 50 (1,000), total 10,000. Buy 50 CC1 @ 100:
- CC1 = 50 × 100 = 5,000
- total = 9,000 − 5,000 + 1,000 + 5,000 = 10,000
- share = 5,000 / 10,000 = **50 %** > 40 %

The screen then shows:
```
  BUY 50 CC1 @ 100.00 on 2025-03-03 = 5,000.00. Cash after: 4,000.00.
  Warning: CC1 would be 50.00 % of this portfolio (limit for the warning: 40 %).
  Confirm? (y/N):
```

## Python notes / Python 语法说明
- `price if price is not None else close`: a *conditional expression*, Python's one-line if/else. Enter at the price prompt means "that day's close", so the preview uses the close.
- `sum((... for t, n in holdings.items()), Decimal("0"))`: a generator expression. The start value `Decimal("0")` keeps the result a Decimal even when there are no holdings (otherwise it would be the int 0).
- `f"{limit:g} %"`: the `g` format drops trailing zeros, so `Decimal("40")` prints as `40`.
- `ask_yes_no` already treats Enter as No, which gives the "default No" behaviour.

中文：`a if 条件 else b` 是 Python 的一行 if/else；`sum(..., Decimal("0"))` 的第二个参数是起始值，保证结果仍是 Decimal。

## Why the warning is not in the database / 为什么警告不放进数据库
A portfolio that is 100 % one stock is valid data, just risky. Database rules protect data integrity (cash ≥ 0, prices within the day's range). Advice belongs in the app. The confirm step is also only a hint: "Cash after: −11,000.00" can be confirmed, and `trg_cash_never_negative` refuses it.

中文：单一股票占 100 % 的组合在数据上是合法的，只是风险高。数据库规则保证数据正确，而风险建议属于应用层。

## Tests / 测试
**`tests/test_trade_confirm.py`** (new, 11 tests):
- the preview text and the formula (including paying above the close, and a missing close)
- the warning appears only above 40 % (exactly 40 % → none)
- Buy + y saves
- Buy + n saves nothing, and so does Buy + Enter
- the warning appears above 40 % and the trade is still saved after y
- no warning below 40 %
- Sell has the confirm but never a warning
- after y, the database still refuses a purchase without enough cash

**Existing tests changed:** only the answer lists, each with one `"y"` added after the price answer (for the new question). All three are in `tests/test_trading_days.py`:
- `test_buy_reasks_the_date_before_the_price`
- `test_a_date_before_the_start_is_reasked_at_once`
- `test_no_price_date_inside_the_range_suggests_only_allowed_days`

`test_ticker_help.py::test_sell_menu_uses_the_held_list` was not changed: it cancels at the ticker prompt, before the confirm.
