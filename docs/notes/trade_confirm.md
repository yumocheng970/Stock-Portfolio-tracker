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

---

## Follow-up: not enough cash, and where the allowed date comes from / 后续：现金不足提示与最早日期的来源

### 1. Not enough cash (Buy) / 现金不足
If "Cash after" would be negative, the Buy preview shows
`Not enough cash: the database will refuse this trade (you have 9,000.00).` **instead of** the
concentration warning (a share above 100 % would be confusing), and the question becomes
`Confirm anyway? (y/N)`. Hint only: after "y", `trg_cash_never_negative` refuses the trade.
`trade_preview.not_enough_cash(cash, shares, price)` returns the line or `None` (cash exactly 0 is enough).

中文：若买入后现金为负，就显示 "Not enough cash…（你有 X）"，代替集中度警告（否则会出现超过 100 % 的比例，令人困惑），问题改为 "Confirm anyway? (y/N)"。这只是提示，最终仍由数据库拒绝。

### 2. "New events must be dated on or after D (…)" / 最早允许日期的来源
`da.trade_context` now also returns the latest event (`event_kind`, `event_type`, `event_date`,
`event_ticker`, `event_shares`, `event_price`, `event_amount`). It uses the same order as the
history replay: date, then cash before trades on the same day, then id. So when a deposit and a
trade share the latest date, the **trade** is named. `trade_preview.allowed_date_source(context)`
turns it into text:
```
  New events must be dated on or after 2026-10-21 (the latest event: SELL 37 NVDA @ 221.97 on 2026-10-21).
  New events must be dated on or after 2025-03-04 (the latest event: DEPOSIT 5,000.00 on 2025-03-04).
  New events must be dated on or after 2025-03-03 (the portfolio's start date).
```
The line is printed by `show_context`, the only place that shows it: Buy, Sell, Deposit and Withdraw.
"Start date" is shown when there are no events, or when the start date is later than the latest event.

中文：`trade_context` 现在多返回"最新事件"，顺序与触发器重放历史的顺序相同（日期 → 同日先现金后交易 → id）。同一天既有存款又有交易时，显示的是交易。没有任何事件时显示"组合的开始日期"。

SQL notes / SQL 说明:
- `LEFT JOIN LATERAL (… UNION ALL … ORDER BY … LIMIT 1) e ON true`: for each portfolio, take the one latest event. `LEFT` keeps portfolios that have no events yet (all `e.*` columns become NULL).
- `GREATEST` ignores NULLs, so `GREATEST(start_date, NULL)` = `start_date`.

**Tests added** (`tests/test_trade_confirm.py`):
- Not enough cash: the line appears, there is no concentration warning, the prompt is "Confirm anyway?", and the DB still refuses.
- Exactly enough cash: the plain "Confirm?".
- The allowed-date source: start date (no events), the latest trade (including a same-day deposit, which is replayed earlier), and the latest deposit.

Existing tests changed:
- My own `test_the_database_still_decides_after_yes` from the previous step became `test_not_enough_cash_replaces_the_warning_and_the_database_still_decides`, with the same scenario and more assertions.
- No other test changed.

Checked read-only on the real DB: portfolio 3 → "SELL 37 NVDA @ 221.97 on 2026-10-21".

---

## Follow-up 2: Deposit / Withdraw confirm / 存取款确认
After the amount and the date, the app shows a preview and asks to confirm (Enter = No → "Cancelled, nothing saved."):
```
  DEPOSIT 5,000.00 on 2026-11-06. Cash after: 105,000.00.
  Cash transactions can't be edited or deleted later.
  Confirm? (y/N):
```
- **The functions:** `trade_preview.cash_preview_text(txn_type, amount, day, cash)` builds the preview line: a DEPOSIT adds the amount, a WITHDRAWAL subtracts it. The final sentence is the constant `CASH_FINAL_NOTE`.
- **Why confirm here:** for cash this step matters even more than for trades. `trg_cash_txn_immutable` blocks UPDATE and DELETE, so a wrong amount can only be fixed with an opposite transaction.
- **Hint only:** a withdrawal above the cash shows "Cash after: -0.01." and can be confirmed, and `trg_cash_never_negative` refuses it.
- **The short note before the amount prompt is kept** ("Note: cash transactions can't be edited or deleted later; a mistake is fixed with an opposite transaction.").

中文：
- 输入金额和日期后，先显示预览与"现金交易之后不能修改或删除"，再问 "Confirm? (y/N)"，默认 No。
- 因为现金交易不可修改、不可删除（触发器 `trg_cash_txn_immutable`），确认这一步比交易更重要。
- 取款超过现金时，预览会显示负数，但仍由数据库拒绝。

**Tests added** (`tests/test_trade_confirm.py`, 8 tests):
- the preview text
- y saves, for Deposit and for Withdraw
- n and Enter save nothing, for both
- a withdrawal above the cash is refused by the DB after "y"

**Existing tests changed:** none. No existing test deposited or withdrew through the menu; every one of them calls `da.record_cash_transaction` directly (checked with grep).
