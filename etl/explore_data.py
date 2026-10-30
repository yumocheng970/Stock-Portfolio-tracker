"""Explore the Kaggle S&P 500 dataset to inform the schema design.

Run from the repo root:  python etl/explore_data.py
"""
import pandas as pd  # pandas: a library for working with tables in Python

RAW = "data/raw"

# --- Load ------------------------------------------------------------------
# read_csv returns a DataFrame: think of it as an in-memory SQL table.
companies = pd.read_csv(f"{RAW}/sp500_companies.csv")
stocks = pd.read_csv(f"{RAW}/sp500_stocks.csv", parse_dates=["Date"])


def section(title):
    """Print a header so the output is easy to read."""
    print(f"\n=== {title} ===")


# --- 1. Companies file -----------------------------------------------------
section("Companies: row count")
print(len(companies), "rows")

section("Missing values in key columns")
print(companies[["Exchange", "Symbol", "Sector", "Industry"]].isna().sum())

section("Distinct exchanges")
# SQL: SELECT exchange, COUNT(*) FROM companies GROUP BY exchange;
print(companies["Exchange"].value_counts())

section("Number of sectors and industries")
print("sectors:   ", companies["Sector"].nunique())
print("industries:", companies["Industry"].nunique())

section("Industries that appear under more than one sector")
# SQL: SELECT industry FROM companies
#      GROUP BY industry HAVING COUNT(DISTINCT sector) > 1;
per_industry = companies.groupby("Industry")["Sector"].nunique()
print(per_industry[per_industry > 1])
print("(empty = every industry belongs to exactly one sector)")

# --- 2. Prices file --------------------------------------------------------
section("Prices: date range")
print(stocks["Date"].min().date(), "to", stocks["Date"].max().date())

section("Rows with missing Close price")
missing = stocks["Close"].isna().sum()
print(f"{missing} of {len(stocks)} rows ({missing / len(stocks):.1%})")

section("Duplicate (Symbol, Date) pairs")
# If this is 0, (security, date) can be the primary key of daily_price.
print(stocks.duplicated(subset=["Symbol", "Date"]).sum())

# --- 3. Gaps in the middle of a ticker's history (2020+) --------------------
section("Tickers with missing prices AFTER their first valid date (2020+)")
recent = stocks[stocks["Date"] >= "2020-01-01"]
# First date each symbol has a real price.
first_valid = recent.dropna(subset=["Close"]).groupby("Symbol")["Date"].min()
recent = recent.join(first_valid.rename("first_valid"), on="Symbol")
gaps = recent[(recent["Date"] >= recent["first_valid"]) & recent["Close"].isna()]
print(gaps.groupby("Symbol").size().sort_values(ascending=False).head(10))
print("(empty = no mid-history gaps)")