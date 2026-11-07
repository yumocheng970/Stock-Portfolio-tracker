"""Asking the user for input. Every helper re-asks until the answer is usable.

Only the SHAPE of the input is checked here (not empty, a whole number, not
too long). Business rules (valid email, enough cash, ...) are checked by the
database, and the menus show its answer via errors.safe_call().
"""
from datetime import date
from decimal import Decimal, InvalidOperation


def ask_text(prompt, max_len, required=True):
    """Ask for a line of text, stripped of spaces at both ends.

    required=False: an empty answer returns None (meaning "keep" / "skip").
    """
    while True:
        answer = input(f"{prompt}: ").strip()
        if answer == "":
            if not required:
                return None
            print("  Please type something.")
            continue
        if len(answer) > max_len:
            print(f"  Too long: at most {max_len} characters (you typed {len(answer)}).")
            continue
        return answer


def ask_int(prompt, minimum=None, maximum=None, required=True):
    """Ask for a whole number, optionally between minimum and maximum (inclusive).

    required=False: an empty answer returns None (meaning "cancel").
    """
    while True:
        answer = input(f"{prompt}: ").strip()
        if answer == "" and not required:
            return None
        try:
            number = int(answer)
        except ValueError:
            print("  Please type a whole number.")
            continue
        if minimum is not None and number < minimum:
            print(f"  Please type a number >= {minimum}.")
            continue
        if maximum is not None and number > maximum:
            print(f"  Please type a number <= {maximum}.")
            continue
        return number


def ask_decimal(prompt, required=True):
    """Ask for an amount of money or a price, returned as a Decimal (exact,
    unlike float). Accepts "1,000.50". At most 2 decimals, because the
    database stores money with 2 decimals and would silently round more.
    The sign and the limits are left to the database (CHECK constraints).

    required=False: an empty answer returns None (e.g. "use the close").
    """
    while True:
        answer = input(f"{prompt}: ").strip().replace(",", "")
        if answer == "" and not required:
            return None
        try:
            amount = Decimal(answer)
        except InvalidOperation:          # Decimal("abc") raises this
            print("  Please type a number, e.g. 1500 or 1500.25.")
            continue
        if not amount.is_finite():        # Decimal accepts "NaN" and "Infinity"
            print("  Please type a normal number.")
            continue
        if amount.as_tuple().exponent < -2:   # 1.234 has exponent -3
            print("  At most 2 decimals, please.")
            continue
        return amount


def ask_date(prompt, default=None):
    """Ask for a date as YYYY-MM-DD. Enter = `default` (shown in the prompt),
    if there is one. Whether the date is ALLOWED is decided by the database."""
    hint = f" [Enter = {default.isoformat()}]" if default else ""
    while True:
        answer = input(f"{prompt} (YYYY-MM-DD){hint}: ").strip()
        if answer == "" and default is not None:
            return default
        try:
            return date.fromisoformat(answer)
        except ValueError:                # bad format, or a day like 2025-02-30
            print("  Please type a real date like 2025-03-14.")


def confirm_typed(expected, what):
    """Typed confirmation for dangerous actions: the user must type `expected`
    exactly (e.g. the investor's email). Returns True only on an exact match."""
    print(f"  To confirm, type {what} exactly: {expected}")
    answer = input("  > ").strip()
    if answer == expected:
        return True
    print("  Not confirmed: nothing was changed.")
    return False


def pause():
    """Wait for Enter, so the user can read the output before the menu returns."""
    input("\n(press Enter to continue)")
