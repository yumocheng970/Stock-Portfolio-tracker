"""The app's current state, passed to every menu function."""
from dataclasses import dataclass

import psycopg


@dataclass
class Session:
    """Who is using the app and through which connection.

    investor_id / investor_name are None until an investor is chosen
    ("logged in"; there is no password).
    """
    conn: psycopg.Connection
    investor_id: int | None = None
    investor_name: str | None = None

    def choose_investor(self, investor_id, name):
        self.investor_id = investor_id
        self.investor_name = name

    def forget_investor(self):
        self.investor_id = None
        self.investor_name = None
