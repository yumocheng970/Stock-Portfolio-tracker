"""The app's current state, passed to every menu function."""
from dataclasses import dataclass

import psycopg


@dataclass
class Session:
    """Who is using the app and through which connection.

    investor_id / investor_name are None until an investor is chosen
    ("logged in"; there is no password). portfolio_id / portfolio_name are
    None until one of that investor's portfolios is chosen.
    """
    conn: psycopg.Connection
    investor_id: int | None = None
    investor_name: str | None = None
    portfolio_id: int | None = None
    portfolio_name: str | None = None

    def choose_investor(self, investor_id, name):
        self.investor_id = investor_id
        self.investor_name = name

    def forget_investor(self):
        self.investor_id = None
        self.investor_name = None
        self.forget_portfolio()          # a portfolio belongs to the investor

    def choose_portfolio(self, portfolio_id, name):
        self.portfolio_id = portfolio_id
        self.portfolio_name = name

    def forget_portfolio(self):
        self.portfolio_id = None
        self.portfolio_name = None
