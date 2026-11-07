"""Main menu: the first screen of the app."""
from app.menu import coming_soon, run_menu
from app.menus.investor_menu import investor_menu


def main_menu(session):
    run_menu("Main menu", [
        ("Choose / create investor", investor_menu),
        ("Market data",              coming_soon),     # App 6
        ("Admin",                    coming_soon),     # App 6
    ], session, back_label="Exit")
