"""Asking the user for input. Every helper re-asks until the answer is usable.

Only the SHAPE of the input is checked here (not empty, a whole number, not
too long). Business rules (valid email, enough cash, ...) are checked by the
database, and the menus show its answer via errors.safe_call().
"""


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
