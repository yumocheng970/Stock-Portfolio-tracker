"""A reusable numbered menu.

    run_menu("Main menu", [("Choose investor", investor_menu),
                           ("Market data",     coming_soon)], session)

prints
    === Main menu ===
      1) Choose investor
      2) Market data
      0) Back
and calls the chosen function with `session`, until the user picks 0.
"""
from app.error_log import report_unexpected
from app.inputs import ask_int, pause


def run_menu(title, items, session, back_label="Back"):
    """Show `items` (a list of (label, function) pairs) until the user picks 0.

    `title` may be a function of the session instead of a text, so it can
    change while the menu is open (e.g. after renaming the chosen investor).
    A function may return the text "back" to close this menu as well.

    This is the ONE place every menu action passes through, so an unexpected
    error (a bug, not a database refusal: those are handled by safe_call) is
    caught here: logged with an id (app/error_log.py), and the menu is shown again.
    """
    while True:
        heading = title(session) if callable(title) else title
        print(f"\n=== {heading} ===")
        # enumerate(items, start=1) gives (1, item0), (2, item1), ...
        for number, (label, _function) in enumerate(items, start=1):
            print(f"  {number}) {label}")
        print(f"  0) {back_label}")

        choice = ask_int("Choose", minimum=0, maximum=len(items))
        if choice == 0:
            return
        label, function = items[choice - 1]
        try:
            result = function(session)
        except (KeyboardInterrupt, EOFError):
            raise                    # Ctrl+C / Ctrl+D: the user wants to leave the app
        except Exception as error:   # anything else is a bug: log it, stay in the app
            report_unexpected(error, f"{heading} > {label}", getattr(session, "conn", None))
            continue                 # show this menu again
        if result == "back":
            return


def coming_soon(session):
    """Placeholder for menu items that are built in a later step."""
    print("\n  Coming in a later step (see docs/app_design.md, Roadmap).")
    pause()
