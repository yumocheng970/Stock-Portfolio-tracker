"""app/inputs.py and app/menu.py with simulated keyboard input (no database)."""
from app.inputs import ask_int, ask_text, confirm_typed
from app.menu import run_menu


def fake_input(monkeypatch, answers):
    """Replace input() so it returns the given answers one by one."""
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_ask_int_reasks_until_valid(monkeypatch, capsys):
    fake_input(monkeypatch, ["abc", "99", "0", "3"])
    assert ask_int("Choose", minimum=1, maximum=5) == 3
    out = capsys.readouterr().out
    assert "whole number" in out and "<= 5" in out and ">= 1" in out


def test_ask_int_optional_empty_means_cancel(monkeypatch):
    fake_input(monkeypatch, [""])
    assert ask_int("ID", required=False) is None


def test_ask_text_strips_and_checks_length(monkeypatch, capsys):
    fake_input(monkeypatch, ["   ", "x" * 11, "  Alice  "])
    assert ask_text("Name", max_len=10) == "Alice"
    assert "Too long" in capsys.readouterr().out


def test_ask_text_optional_empty_means_keep(monkeypatch):
    fake_input(monkeypatch, [""])
    assert ask_text("Name", max_len=10, required=False) is None


def test_confirm_typed_needs_exact_text(monkeypatch):
    fake_input(monkeypatch, ["y"])
    assert confirm_typed("alice@example.com", "the email") is False
    fake_input(monkeypatch, ["alice@example.com"])
    assert confirm_typed("alice@example.com", "the email") is True


def test_run_menu_calls_chosen_item_and_exits_on_zero(monkeypatch):
    calls = []
    fake_input(monkeypatch, ["7", "2", "0"])        # 7 is invalid -> asked again
    run_menu("Test", [("One", lambda s: calls.append("one")),
                      ("Two", lambda s: calls.append("two"))], session=None)
    assert calls == ["two"]


def test_run_menu_closes_when_item_returns_back(monkeypatch):
    fake_input(monkeypatch, ["1"])                   # no "0" needed
    run_menu("Test", [("Leave", lambda s: "back")], session=None)
