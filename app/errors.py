"""Turn database errors into friendly messages.

Every rule in the database has a NAME: a constraint (chk_, fk_, uq_, pk_ / _pkey),
the unique index uq_investor_email_lower, or the name a trigger / procedure raises
with USING CONSTRAINT = 'trg_...' / 'exec_...'. psycopg gives it to us as
    error.diag.constraint_name
MESSAGES maps every such name to a sentence for the user. A test
(tests/test_app_errors.py) reads all names from the database catalog, so a
new constraint without a message here makes the tests fail.

safe_call() is what the menus use: it runs a data-access function and, if
the database refuses, prints the friendly message instead of a traceback.
"""
import re
from decimal import Decimal

import psycopg

from app.data_access import ImportRowError, NotFoundError
from app.market_data import DownloadError

MESSAGES = {
    # --- sector / exchange -------------------------------------------------
    "sector_pkey":                 "That sector id already exists.",
    "uq_sector_name":              "A sector with that name already exists.",
    "chk_sector_name_not_blank":   "The sector name can't be blank.",
    "exchange_pkey":               "That exchange id already exists.",
    "uq_exchange_name":            "An exchange with that name already exists.",
    "chk_exchange_name_not_blank": "The exchange name can't be blank.",

    # --- investor ----------------------------------------------------------
    "investor_pkey":               "That investor id already exists.",
    "chk_investor_name_not_blank": "The name can't be blank.",
    "chk_investor_email_format":   "That doesn't look like an email address (expected name@domain.com, no spaces).",
    "uq_investor_email_lower":     "That email is already used by another investor (emails are case-insensitive).",

    # --- stock / daily_price -----------------------------------------------
    "stock_pkey":                   "A stock with that ticker already exists.",
    "chk_stock_ticker_format":      "Tickers are 1-9 characters: capital letters, digits, '.' or '-' (an index may start with '^').",
    "chk_stock_company_not_blank":  "The company name can't be blank.",
    "chk_stock_security_type":      "The security type must be STOCK or INDEX.",
    "chk_stock_index_unclassified": "An INDEX can't have a sector or an exchange.",
    "fk_stock_sector":              "That sector doesn't exist, or it is still used by a stock.",
    "fk_stock_exchange":            "That exchange doesn't exist, or it is still used by a stock.",
    "pk_daily_price":               "There is already a price for that ticker on that date.",
    "chk_daily_price_positive":     "Prices must be greater than 0.",
    "chk_daily_price_range":        "The price row is inconsistent: open and close must lie between low and high.",
    "chk_daily_price_volume":       "Volume can't be negative.",
    "fk_daily_price_stock":         "That ticker isn't in the stock list.",

    # --- portfolio ---------------------------------------------------------
    "portfolio_pkey":               "That portfolio id already exists.",
    "chk_portfolio_name_not_blank": "The portfolio name can't be blank.",
    "chk_portfolio_starting_cash":  "Starting cash must be more than 0 and at most 10,000,000.",
    "uq_portfolio_investor_name":   "You already have a portfolio with that name.",
    "fk_portfolio_investor":        "That investor doesn't exist (any more).",

    # --- cash_transaction --------------------------------------------------
    "cash_transaction_pkey":      "That cash transaction id already exists.",
    "chk_cash_txn_type":          "The type must be DEPOSIT or WITHDRAWAL.",
    "chk_cash_amount_positive":   "The amount must be greater than 0.",
    "chk_cash_deposit_cap":       "A single deposit can be at most 10,000,000.",
    "fk_cash_portfolio":          "That portfolio doesn't exist (any more).",

    # --- trade -------------------------------------------------------------
    "trade_pkey":             "That trade id already exists.",
    "chk_trade_type":         "The trade type must be BUY or SELL.",
    "chk_trade_shares":       "Shares must be a whole number greater than 0.",
    "chk_trade_price":        "The price must be greater than 0.",
    "fk_trade_portfolio":     "That portfolio doesn't exist (any more).",
    "fk_trade_daily_price":   "There is no price for that ticker on that date (choose a trading day), "
                              "or the stock still has trades and can't be deleted.",

    # --- trade_audit -------------------------------------------------------
    "trade_audit_pkey":           "That audit id already exists.",
    "chk_trade_audit_operation":  "The audit operation must be UPDATE or DELETE.",

    # --- watchlist / watchlist_item ----------------------------------------
    "watchlist_pkey":               "That watchlist id already exists.",
    "chk_watchlist_name_not_blank": "The watchlist name can't be blank.",
    "uq_watchlist_investor_name":   "You already have a watchlist with that name.",
    "fk_watchlist_investor":        "That investor doesn't exist (any more).",
    "pk_watchlist_item":            "That stock is already on this watchlist.",
    "chk_watchlist_target_positive": "The target price must be greater than 0 (or left empty).",
    "fk_watchlist_item_watchlist":  "That watchlist doesn't exist (any more).",
    "fk_watchlist_item_stock":      "That ticker isn't in the stock list.",

    # --- raised by triggers (db/programmability/) --------------------------
    "trg_trade_price_in_range":  "The price must be within that day's low-high range.",
    "trg_trade_not_index":       "An index (like ^GSPC) can be watched but not traded.",
    "trg_trade_immutable_cols":  "Only the shares and the price of a trade can be changed.",
    "trg_trade_no_truncate":     "Trades can't be removed in bulk (TRUNCATE); delete them one by one.",
    "trg_cash_txn_immutable":    "Cash transactions can't be changed or deleted. "
                                 "To fix a mistake, record an opposite transaction.",
    "trg_cash_txn_no_truncate":  "Cash transactions can't be removed in bulk (TRUNCATE).",
    "trg_stock_benchmark_protected": "^GSPC can't be deleted or renamed (its company name can be edited).",
    "trg_cash_txn_future_date":  "A cash transaction can't be dated in the future.",
    "trg_date_before_start":     "The date is before the portfolio's start date.",
    "trg_date_before_latest":    "The date is before this portfolio's latest trade or cash transaction "
                                 "(events must be entered in date order).",
    "trg_cash_never_negative":   "Not enough cash.",
    "trg_shares_never_negative": "Not enough shares.",

    # --- raised by the procedures execute_trade / record_cash_transaction --
    "exec_missing_input":  "Some required input is missing.",
    "exec_no_price_data":  "There is no price for that ticker on that date (choose a trading day).",

    # --- raised by restore_trade ---------------------------------------------
    "exec_audit_not_found":        "There is no such audit row.",
    "exec_restore_not_delete":     "Only a DELETE row of the audit log can be restored.",
    "exec_trade_already_restored": "That trade is already back in the portfolio.",
    "exec_restore_not_latest":     "That trade was changed again later; restore it from its newest DELETE row.",
}

# For these names the database's DETAIL already says everything the message
# says, only more precisely ("No price for ZZZZ on 2026-10-30 (not a trading
# day, or unknown ticker)."), so the DETAIL is shown alone, as one clear line.
# The MESSAGES text is the fallback when there is no DETAIL.
DETAIL_REPLACES_MESSAGE = {"exec_no_price_data", "exec_missing_input", "exec_audit_not_found",
                           "exec_trade_already_restored", "exec_restore_not_latest"}

# Errors without a constraint name, by SQLSTATE (the 5-character error code)
SQLSTATE_MESSAGES = {
    "23502": "{column} is required.",                                    # not_null_violation
    "22001": "A value is too long.",                                     # string_data_right_truncation
    "22003": "A number is too large.",                                   # numeric_value_out_of_range
    "22P02": "A value has the wrong format.",                            # invalid_text_representation
    "22007": "A date has the wrong format.",                             # invalid_datetime_format
    "22008": "That date doesn't exist.",                                 # datetime_field_overflow
    "40001": "Someone else changed the same data at the same time. Please try again.",  # serialization_failure
    "40P01": "Someone else changed the same data at the same time. Please try again.",  # deadlock_detected
    "25006": "The database is in read-only mode: nothing was changed.",  # read_only_sql_transaction
}


# A money amount in a DETAIL text: optional minus, digits, a point, exactly 2 decimals
# ("-20366046.40", "107.00"). Dates (2025-03-04), ids and share counts don't match.
MONEY_IN_TEXT = re.compile(r"-?\d+\.\d{2}\b")


def format_money_in_text(text):
    """'Cash would be -20366046.40 on ...' -> 'Cash would be -20,366,046.40 on ...',
    the same 1,234.56 style as the app's tables."""
    # Decimal, not float: exact for any size of amount
    return MONEY_IN_TEXT.sub(lambda match: f"{Decimal(match.group()):,.2f}", text)


def friendly_message(error):
    """The sentence to show the user for any exception from a database action."""
    if isinstance(error, (NotFoundError, DownloadError)):
        return str(error)
    if isinstance(error, ImportRowError):         # "Row 6: Not enough cash. Cash would be ..."
        return f"Row {error.row}: {friendly_message(error.error)}"
    if isinstance(error, psycopg.OperationalError):
        return "Lost the connection to the database. Please restart the app."

    diag = error.diag
    name = diag.constraint_name
    detail = format_money_in_text(diag.message_detail) if diag.message_detail else None
    if name in DETAIL_REPLACES_MESSAGE and detail:
        return detail
    if name in MESSAGES:
        message = MESSAGES[name]
        # Trigger errors carry useful numbers in DETAIL, e.g.
        # "Cash would be -120.00 on 2025-03-04, after trade 17 (BUY 10 AAPL @ 230.00)."
        if name.startswith(("trg_", "exec_")) and detail:
            message += " " + detail
        return message
    if diag.sqlstate in SQLSTATE_MESSAGES:
        column = (diag.column_name or "A value").replace("_", " ")
        return SQLSTATE_MESSAGES[diag.sqlstate].format(column=column.capitalize())
    # Not mapped (should not happen; the catalog test checks every name)
    return f"The database refused this: {diag.message_primary}"


def safe_call(func, *args, **kwargs):
    """Run func(*args, **kwargs). Return (True, result) on success.

    If the database refuses, the transaction inside func has already been
    rolled back: print the friendly message and return (False, None).
    """
    try:
        return True, func(*args, **kwargs)
    except (psycopg.Error, NotFoundError, DownloadError, ImportRowError) as error:
        print(f"\n  !! {friendly_message(error)}")
        return False, None
