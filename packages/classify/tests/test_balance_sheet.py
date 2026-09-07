"""Tests for opening balances and the balance-sheet computation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def test_set_opening_balance_writes_config(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["accounts", "set-opening-balance",
                                 "tony-hdfc-savings", "125000.00", "2021-01-01"])
    assert result.exit_code == 0, result.output
    store = Store(home=tmp_path)
    balances = store.get_config("account_opening_balances", {})
    assert balances["tony-hdfc-savings"] == {"balance": 125000.00, "as_of": "2021-01-01"}


def test_set_opening_balance_rejects_invalid_date(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["accounts", "set-opening-balance",
                                 "tony-hdfc-savings", "125000.00", "not-a-date"])
    assert result.exit_code != 0
    store = Store(home=tmp_path)
    assert store.get_config("account_opening_balances", {}) == {}


def test_set_opening_balance_overwrites_existing(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"tony-hdfc-savings": {"balance": 1.0, "as_of": "2020-01-01"}})
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["accounts", "set-opening-balance",
                                 "tony-hdfc-savings", "125000.00", "2021-01-01"])
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    balances = reloaded.get_config("account_opening_balances", {})
    assert balances["tony-hdfc-savings"] == {"balance": 125000.00, "as_of": "2021-01-01"}
