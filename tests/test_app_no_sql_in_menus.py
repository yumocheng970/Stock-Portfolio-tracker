"""Layering check: menu modules contain no SQL and don't talk to psycopg.

Same idea as the shell check
    grep -nE '\\b(SELECT|INSERT|UPDATE|DELETE|CALL)\\b' app/menus/*.py
SQL keywords are matched in CAPITALS only, so menu labels such as
"Delete investor" are allowed.
"""
import re
from pathlib import Path

MENU_DIR = Path(__file__).resolve().parent.parent / "app" / "menus"
FORBIDDEN = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CALL)\b|\.execute\(|import psycopg")


def test_menu_modules_exist():
    assert len(list(MENU_DIR.glob("*.py"))) >= 3


def test_no_sql_in_menu_modules():
    problems = []
    for path in sorted(MENU_DIR.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                problems.append(f"{path.name}:{number}: {line.strip()}")
    assert problems == [], "SQL belongs in app/data_access.py:\n" + "\n".join(problems)
