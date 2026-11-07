"""Investor menu: list, create, choose ("login", no password), and the chosen
investor's home and profile (view, edit name/email, delete)."""
from app import data_access as da
from app.display import print_table
from app.errors import safe_call
from app.inputs import ask_int, ask_text, confirm_typed, pause
from app.menu import run_menu
from app.menus.portfolio_menu import portfolios_menu
from app.menus.watchlist_menu import watchlists_menu

NAME_MAX = 100       # investor.name  VARCHAR(100)
EMAIL_MAX = 254      # investor.email VARCHAR(254)

INVESTOR_COLUMNS = [
    ("investor_id", "ID"), ("name", "Name"), ("email", "Email"),
    ("portfolios", "Portfolios"), ("watchlists", "Watchlists"), ("created_date", "Created"),
]


def investor_menu(session):
    run_menu("Investors", [
        ("List investors",  list_investors),
        ("Create investor", create_investor),
        ("Choose investor", choose_investor),
    ], session)


# ---------------------------------------------------------------------
# Investors menu items
# ---------------------------------------------------------------------
def list_investors(session):
    ok, rows = safe_call(da.list_investors, session.conn)
    if ok:
        print_table(rows, INVESTOR_COLUMNS)
    pause()


def create_investor(session):
    print("\nNew investor")
    name = ask_text("Name", NAME_MAX)
    email = ask_text("Email", EMAIL_MAX)
    ok, investor_id = safe_call(da.create_investor, session.conn, name, email)
    if ok:
        print(f"\n  Created investor {investor_id}: {name}")
        session.choose_investor(investor_id, name)
        investor_home(session)          # created = chosen, go straight to their home
    else:
        pause()


def choose_investor(session):
    ok, rows = safe_call(da.list_investors, session.conn)
    if not ok:
        pause()
        return
    if not rows:
        print("\n  No investors yet: create one first.")
        pause()
        return
    print_table(rows, INVESTOR_COLUMNS)
    investor_id = ask_int("Investor ID (Enter = cancel)", minimum=1, required=False)
    if investor_id is None:
        return
    ok, investor = safe_call(da.get_investor, session.conn, investor_id)
    if not ok:
        pause()
        return
    if investor is None:
        print(f"\n  There is no investor with ID {investor_id}.")
        pause()
        return
    session.choose_investor(investor["investor_id"], investor["name"])
    investor_home(session)


# ---------------------------------------------------------------------
# The chosen investor's home and profile
# ---------------------------------------------------------------------
def investor_home(session):
    run_menu(lambda s: f"Investor home: {s.investor_name}", [
        ("Portfolios", portfolios_menu),
        ("Watchlists", watchlists_menu),
        ("Profile",    profile_menu),
    ], session)
    session.forget_investor()           # leaving the home = "log out"


def profile_menu(session):
    run_menu(lambda s: f"Profile: {s.investor_name}", [
        ("View profile",    view_profile),
        ("Edit name",       edit_name),
        ("Edit email",      edit_email),
        ("Delete investor", delete_investor),
    ], session)
    # After a delete there is no investor any more: close the home menu too
    if session.investor_id is None:
        return "back"


def view_profile(session):
    ok, investor = safe_call(da.get_investor, session.conn, session.investor_id)
    if ok and investor is not None:
        print_table([investor], [("investor_id", "ID"), ("name", "Name"),
                                 ("email", "Email"), ("created_date", "Created")])
    pause()


def edit_name(session):
    name = ask_text("New name (Enter = keep)", NAME_MAX, required=False)
    if name is None:
        return
    ok, _ = safe_call(da.update_investor, session.conn, session.investor_id, name=name)
    if ok:
        session.choose_investor(session.investor_id, name)
        print("  Name changed.")
    pause()


def edit_email(session):
    email = ask_text("New email (Enter = keep)", EMAIL_MAX, required=False)
    if email is None:
        return
    ok, _ = safe_call(da.update_investor, session.conn, session.investor_id, email=email)
    if ok:
        print("  Email changed.")
    pause()


def delete_investor(session):
    ok, investor = safe_call(da.get_investor, session.conn, session.investor_id)
    if not ok or investor is None:
        pause()
        return
    ok, summary = safe_call(da.investor_delete_summary, session.conn, session.investor_id)
    if not ok:
        pause()
        return
    print(f"\n  Delete {investor['name']} <{investor['email']}>?")
    print(f"  This also deletes {summary['portfolios']} portfolio(s) "
          f"({summary['trades']} trades, {summary['cash_transactions']} cash transactions) "
          f"and {summary['watchlists']} watchlist(s).")
    print("  Deleted trades stay visible in the trade audit log.")
    if not confirm_typed(investor["email"], "the investor's email"):
        pause()
        return
    ok, _ = safe_call(da.delete_investor, session.conn, session.investor_id)
    if ok:
        print(f"  Deleted investor {investor['name']}.")
        session.forget_investor()
        pause()
        return "back"                   # the profile menu has nothing left to show
    pause()
