"""Main menu: the first screen of the app."""
from app.menu import coming_soon, run_menu
from app.menus.investor_menu import investor_menu
from app.menus.market_menu import market_menu


def main_menu(session):
    run_menu("Main menu", [
        ("Choose / create investor", investor_menu),
        ("Market data",              market_menu),
        ("Admin",                    coming_soon),     # App 6
    ], session, back_label="Exit")
