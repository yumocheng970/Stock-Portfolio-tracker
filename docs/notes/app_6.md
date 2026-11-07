# App 6: market data and admin / 行情数据与管理

Menus / 菜单:
- Main → **2 Market data**: 1 Top movers, 2 List stocks (sector filter / 按行业过滤), 3 Price history (Enter = the last 30 price days / 回车 = 最近 30 个交易日).
- Main → **3 Admin**: 1 Add a stock (downloads its prices / 下载价格), 2 Edit, 3 Rename a ticker, 4 Delete, 5 Refresh all prices, 6 List sectors, 7 List exchanges.

Files / 文件:
- new / 新增：`app/market_data.py`, `app/menus/admin_menu.py`, `db/programmability/08_stock_protection.sql`, `tests/test_app_admin.py` (16), `tests/test_app_market.py` (3)
- changed / 修改：`etl/load_prices.py` (`refresh_tickers` extracted / 提取出来), `app/data_access.py`, `app/errors.py`, `app/menus/market_menu.py`, `app/menus/main_menu.py`, `tests/conftest.py` (network guard / 禁止联网), `db/apply.sql`, `db/tests/test_schema.sql` (+5 SQL)

Decisions (yours) / 你的决定：^GSPC can't be deleted or renamed (DB trigger); the app never writes `data/tickers.csv`; a new sector or exchange is created inside the add-stock transaction.
^GSPC 不能删除或改代码（数据库触发器）；程序从不写 `data/tickers.csv`；新的行业或交易所在添加股票的同一个事务里创建。

The add-stock flow (all or nothing) / 添加股票的流程（要么全成，要么全不成）:
```
download (network, no transaction) --fail/empty--> DownloadError: "... Nothing was saved."
      | ok
clean rows (loader rules)
      |
ONE transaction: new sector/exchange? + stock + all prices --refused--> rollback (nothing saved)
```

---

## New Python features only (mostly mocking) / 只讲新的 Python 知识点（主要是 mock）

### 1. Why tests must never use the network / 为什么测试绝不能联网
**EN:**
- A test that downloads from Yahoo is slow, fails when the Wi-Fi is down or Yahoo changes, gives different data every day, and would hammer a real service on every `make test`.
- So every download is replaced with a **fake** that returns prepared data. Replacing a real part with a fake during a test is called **mocking**.

**中文：**
- 从 Yahoo 下载数据的测试很慢，断网或 Yahoo 改版时会失败，每天的数据都不一样，而且每次 `make test` 都在频繁访问真实的服务。
- 所以每次下载都换成一个**假的**函数，返回事先准备好的数据。测试时用假的部件替换真的部件，就叫 **mock（模拟）**。

### 2. `unittest.mock.patch`: replace something for a while / 临时替换
**EN:**
```python
from unittest import mock

with mock.patch("app.market_data.download_prices", return_value=fake_rows) as download:
    rows, skipped = fetch_history("NEW1", end=D5)      # calls the FAKE, not Yahoo
download.assert_called_once_with("NEW1", FIRST_DATE, D5)
```
- Inside the `with` block, the name `download_prices` in the module `app.market_data` points to a **Mock** object. When the block ends, the real function is put back automatically, even if the test fails.
- **Patch where the name is *looked up*.** `fetch_history` calls `download_prices(...)` from its own module, so we patch `"app.market_data.download_prices"`.
- That is also why `app/market_data.py` has a tiny wrapper `download_prices` that calls `load_prices.download_prices` **at call time**. A default argument such as `def f(download=download_prices)` is fixed when `def` runs, and a later patch wouldn't reach it.

**中文：**
- 在 `with` 块里，`app.market_data` 模块中的名字 `download_prices` 指向一个 **Mock** 对象；块结束时真函数会自动换回来，即使测试失败也一样。
- **在名字被*查找*的地方打补丁。** `fetch_history` 在自己的模块里调用 `download_prices(...)`，所以 patch 的是 `"app.market_data.download_prices"`。
- 这也是 `app/market_data.py` 里有一个小包装函数的原因：它在**调用时**才去找 `load_prices.download_prices`。默认参数（如 `def f(download=download_prices)`）在执行 `def` 时就固定了，之后的 patch 改不到它。

### 3. `return_value` vs `side_effect` / 返回值与副作用
**EN:**
- `mock.Mock(return_value=[...])`: every call returns that list.
- `mock.Mock(side_effect=ConnectionError("no route to host"))`: every call **raises** that exception. This is how we test "the download failed" without unplugging anything.
- `side_effect` can also be a function: it is called with the same arguments and its result is returned (used in `test_refresh_all_prices_covers_every_stock_and_reports_failures`, where only ^GSPC fails).
- In the tests:
  ```python
  @pytest.mark.parametrize("download_mock, expected", [
      (mock.Mock(side_effect=ConnectionError("no route to host")), "Download failed for NEW2"),
      (mock.Mock(return_value=[]),                                 "Yahoo returned no prices"),
      ...])
  ```

**中文：**
- `return_value=[...]`：每次调用都返回这个列表。
- `side_effect=ConnectionError(...)`：每次调用都**抛出**这个异常。不用拔网线，就能测试"下载失败"。
- `side_effect` 也可以是一个函数：用同样的参数调用它，并返回它的结果（例如只让 ^GSPC 下载失败的那个测试）。

### 4. Checking HOW the fake was called / 检查假函数是怎么被调用的
**EN:**
- `download.assert_called_once_with("OLD1", D4, D5)` fails unless the mock was called exactly once with exactly these arguments. It proves the refresh asks only for the days **after** the last stored price (D3 → start D4).
- `fake.assert_not_called()` checks that a ticker that is already up to date causes **no** download.
- `fake.reset_mock()` forgets the earlier calls before the next check.

**中文：**
- `assert_called_once_with(...)`：只有恰好被调用一次、并且参数完全一样才通过。它证明刷新只请求最后一个已存价格**之后**的日子（D3 → 从 D4 开始）。
- `assert_not_called()`：已经是最新的股票**不会**触发下载。
- `reset_mock()`：清空之前的调用记录，再做下一次检查。

### 5. Dependency injection: pass the function in / 依赖注入：把函数作为参数传进去
**EN:**
```python
def refresh_tickers(conn, symbols, yesterday, download=download_prices): ...
refresh_tickers(conn, ["OLD1"], D5, download=fake)       # test: no patch needed
```
- The function receives the thing it depends on (the downloader) as a parameter. The real program uses the default; a test passes a fake.
- This is simpler than patching, and the dependency is visible in the signature.

**中文：** 函数把它依赖的东西（下载函数）作为参数接收：正式程序用默认值，测试传入假的。这比打补丁更简单，依赖关系也直接写在函数签名里。

### 6. `monkeypatch` vs `mock.patch` / 两种替换方式
**EN:**
- Both replace something and put it back after the test.
- **`monkeypatch`** is a pytest fixture, used since App 1 for `input()`. It is good for setting a value.
- **`mock.patch`** also gives a **Mock object that records its calls**, so you can `assert_called_once_with`.
- The network guard in `tests/conftest.py` uses `monkeypatch` with **`autouse=True`**, which means it runs for **every** test without being requested:
  ```python
  @pytest.fixture(autouse=True)
  def no_network(monkeypatch):
      monkeypatch.setattr(yfinance, "Ticker", refuse)    # any real download -> RuntimeError
  ```
  So a test that forgets its mock fails at once with "network disabled in tests" (there is a test for that).
- `mock.patch.object(market_data, "yesterday", return_value=D4)` patches an attribute of an object you already imported. Here it fixes "yesterday" to a known date.

**中文：**
- 两者都会替换某个东西，并在测试结束后恢复。
- **`monkeypatch`** 是 pytest 的 fixture（从 App 1 起用来替换 `input()`），适合直接设置一个值。
- **`mock.patch`** 还会给出一个**记录调用的 Mock 对象**，可以用 `assert_called_once_with` 检查。
- `conftest.py` 里的联网保护用 `monkeypatch`，并设置了 **`autouse=True`**：不用写出来，**每个**测试都会自动使用它。忘记 mock 的测试会立刻失败并提示 "network disabled in tests"（有专门的测试检查这一点）。
- `mock.patch.object(market_data, "yesterday", return_value=D4)` 替换已导入对象的一个属性，这里把"昨天"固定成一个已知的日期。

### 7. A custom exception that carries a message / 带提示信息的自定义异常
**EN:**
```python
class DownloadError(Exception):
    """str(error) is a sentence for the user."""

raise DownloadError(f"Download failed for {ticker}: {error}. Nothing was saved.") from error
```
- `errors.safe_call` catches `DownloadError` like a database error and prints `str(error)`.
- `raise ... from error` keeps the original exception attached as the *cause*, which is useful when debugging. The user sees only the friendly sentence.

**中文：**
- `errors.safe_call` 像处理数据库错误一样捕获 `DownloadError`，并打印 `str(error)`。
- `raise ... from error` 把原来的异常作为*原因*保留下来，方便调试；用户只看到友好的那句话。

### 8. Tuples: `(ticker,) + tuple(row[1:])` / 元组拼接
**EN:**
- `row[1:]` is a **slice**: everything except the first item.
- `(ticker,)` is a one-item tuple, and `+` joins tuples.
- Together they build a copy of the price row with the normalized ticker in front.

**中文：**
- `row[1:]` 是**切片**：除第一个元素外的全部。
- `(ticker,)` 是只有一个元素的元组，`+` 把元组连起来。
- 合起来，就是把价格行复制一份，并把规范化后的代码放在最前面。

### 9. `str.isdigit()` and an import inside a function / `isdigit()` 与函数内导入
**EN:**
- `answer.isdigit()` is True for `"3"` and False for `"Real Estate"`. That is how the sector prompt tells a list number from a new name.
- `data_access.refresh_all_prices` imports `market_data` and `load_prices` **inside** the function, so importing `data_access` (which every module does) doesn't load yfinance and pandas until a refresh is actually requested.

**中文：**
- `answer.isdigit()`：`"3"` 为 True，`"Real Estate"` 为 False，行业输入就是这样区分"列表编号"和"新名字"的。
- `refresh_all_prices` 在**函数内部**才导入 `market_data` 和 `load_prices`，所以导入 `data_access`（每个模块都会导入）时不会加载 yfinance 和 pandas，直到真的要刷新时才加载。

---

## Tests / 测试
**EN:**
- **5 SQL tests:** delete / rename of ^GSPC blocked, its prices still there, its company name editable, other stocks can still be renamed and deleted.
- **19 pytest tests:**
  - add (cleaned prices, a new sector/exchange, the exact download call)
  - a failed / empty / unusable download saves nothing (parametrized, 3 mocks)
  - the menu add when the download fails (the new sector is not saved either)
  - the menu add success
  - a duplicate ticker
  - rename: cascade counts, one UPDATE audit row per trade with the OLD ticker, cash unchanged
  - rename refused (duplicate, bad format, too long, unknown)
  - delete traded (RESTRICT) / untraded (cascade)
  - the ^GSPC protection
  - an edit keeps unchanged fields
  - refresh insert-only (the exact start date; already up to date = no download)
  - an overlapping download adds no duplicates
  - refresh all with one failing ticker
  - the network guard works
  - market: list + sector filter, the 30-day window, price history defaults, end < start
- Also: a smoke test of the refactored `make load-prices` code (`main()` twice on the test DB with yfinance faked: 52 rows, then 0); a scripted UI session on the test DB; read-only browsing on the real DB (fingerprint unchanged). **No add or refresh on the real DB.**
- Totals: 343 SQL + 148 pytest.

**中文：**
- **5 个 SQL 测试**：删除或改名 ^GSPC 被阻止、价格还在、可以改公司名、其他股票仍可改名和删除。
- **19 个 pytest 测试**：覆盖上方英文列表中的各种情况。
- 另外：用伪造的 yfinance 在测试库上把重构后的 `main()` 运行两次（第一次 52 行，第二次 0 行）；在测试库上跑了脚本化的界面操作；在真实库上只读浏览（指纹不变）。**没有在真实库上添加股票或刷新价格。**
- 合计：SQL 343 个 + pytest 148 个。
