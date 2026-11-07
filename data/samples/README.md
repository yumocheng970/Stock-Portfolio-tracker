# Sample CSV files for "Import from CSV" (Portfolio home → 8)

Both files use real trading days and real tickers, so they work on the real database
(`portfolio_tracker`, prices loaded through at least 2026-10-01).

## Setup (once, in the app)
1. Choose or create an investor.
2. Portfolios → **Create portfolio**: starting cash **10000**, start date **2026-09-01**.
3. In that portfolio: **8 Import from CSV**, then type the path, e.g.
   `data/samples/import_valid.csv` (relative to the repo root), or a Windows path such as
   `C:\Users\me\Desktop\import_valid.csv` (converted to `/mnt/c/...` in WSL).

## `import_valid.csv`: everything is imported
| Row | Date | Type | Details |
|---|---|---|---|
| 2 | 2026-09-01 | DEPOSIT | 5,000 |
| 3 | 2026-09-01 | BUY | 10 AAPL at the close |
| 4 | 2026-09-15 | BUY | 20 KO at the close (deliberately **out of order**) |
| 5 | 2026-09-02 | BUY | 5 MSFT at the close |
| 6 | 2026-09-30 | SELL | 4 AAPL at the close |
| 7 | 2026-09-30 | WITHDRAWAL | 1,000 (imported before row 6: cash before trades) |
| 8 | 2026-10-01 | BUY | 5 NVDA at 230.00 (that day's range: 228.16 to 232.29) |

The preview says the rows will be imported in history order. With real prices the cash
afterwards is 10,000 + 5,000 − 3,251.30 − 2,484.10 − 1,774.20 − 1,000 + 1,332.08 − 1,150.00
= **6,672.48**.

## `import_fails_row_6.csv`: nothing is imported
Rows 2 to 5 are valid. Row 6 buys 1,000 NVDA (about 212,000) with about 7,500 cash left, so the
database refuses it:
```
Row 6: Not enough cash. Cash would be -204,679.60 on 2026-09-15, after trade … (BUY 1000 NVDA @ 212.17).
Nothing was saved (the whole import was rolled back).
```
Rows 2 to 5 were already inside the transaction but are rolled back too: the portfolio is
unchanged (all or nothing).
