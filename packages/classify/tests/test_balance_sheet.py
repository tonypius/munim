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


def test_compute_balance_returns_none_without_opening_balance(tmp_path):
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    assert compute_account_balance(store, "tony-hdfc-savings") is None


def test_compute_balance_for_asset_account(tmp_path):
    """Assets: credit increases the balance, debit decreases it."""
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
        Transaction(date="2026-06-10", amount=200, direction=Direction.DEBIT,
                    description_raw="GROCERIES", account="bank"),
    ])
    # 1000 + 500 (credit) - 200 (debit) = 1300
    assert compute_account_balance(store, "bank") == 1300.0


def test_compute_balance_for_liability_account_is_inverted(tmp_path):
    """Liabilities: the statement's balance is what's owed -- a debit
    (purchase) increases it, a credit (payment) decreases it."""
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_types", {"cc": "Liabilities"})
    store.set_config("account_opening_balances",
                     {"cc": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.DEBIT,
                    description_raw="PURCHASE", account="cc"),
        Transaction(date="2026-06-10", amount=200, direction=Direction.CREDIT,
                    description_raw="PAYMENT", account="cc"),
    ])
    # 1000 + 500 (debit/purchase) - 200 (credit/payment) = 1300
    assert compute_account_balance(store, "cc") == 1300.0


def test_compute_balance_excludes_transactions_before_as_of(tmp_path):
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-05-15", amount=9999, direction=Direction.CREDIT,
                    description_raw="BEFORE OPENING", account="bank"),
    ])
    assert compute_account_balance(store, "bank") == 1000.0


def test_compute_balance_includes_transaction_dated_exactly_as_of(tmp_path):
    """"Opening balance as of DATE" means the balance immediately BEFORE
    that date's own activity -- a transaction dated exactly as_of is
    part of the delta, not excluded."""
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-01", amount=100, direction=Direction.CREDIT,
                    description_raw="SAME DAY", account="bank"),
    ])
    assert compute_account_balance(store, "bank") == 1100.0


def test_compute_balance_ignores_other_accounts(tmp_path):
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=99999, direction=Direction.CREDIT,
                    description_raw="OTHER ACCOUNT", account="some-other-account"),
    ])
    assert compute_account_balance(store, "bank") == 1000.0


def test_balance_sheet_command_shows_net_worth_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("account_types", {"cc": "Liabilities"})
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "cc": {"balance": 200.0, "as_of": "2026-06-01"},
    })
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
        Transaction(date="2026-06-05", amount=50, direction=Direction.DEBIT,
                    description_raw="PURCHASE", account="cc"),
        Transaction(date="2026-06-05", amount=10, direction=Direction.DEBIT,
                    description_raw="NO OPENING BALANCE", account="untracked"),
    ])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["balance-sheet"])
    assert result.exit_code == 0, result.output
    out = result.output
    # bank: 1000 + 500 = 1500 (asset). cc: 200 + 50 = 250 (liability).
    # net worth = 1500 - 250 = 1250
    assert "1,250.00" in out or "1250.00" in out
    assert "2/3" in out  # 2 of 3 known accounts have a starting point
    assert "untracked" in out


def test_balance_sheet_includes_account_with_opening_balance_but_no_transactions(
        tmp_path, monkeypatch):
    """An account can have its opening balance set before its first import
    (e.g. setting up all accounts up front) -- it must still appear in the
    balance sheet and count toward net worth, not vanish because it has
    zero rows in `transactions`."""
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances", {
        "fixed-deposit": {"balance": 50000.0, "as_of": "2026-06-01"},
    })
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["balance-sheet"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "fixed-deposit" in out
    assert "50,000.00" in out or "50000.00" in out
    assert "1/1" in out


def test_balance_sheet_includes_account_known_only_via_account_types(
        tmp_path, monkeypatch):
    """An account the user has told munim about via `accounts type` (e.g.
    right after opening a new credit card, before either an opening
    balance or a single transaction exists for it) must still surface as
    a 'no opening balance' row -- not vanish, which would let the
    coverage caveat overstate completeness."""
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("account_types", {"hdfc-cc": "Liabilities"})
    store.set_config("account_opening_balances", {
        "hdfc-savings": {"balance": 1000.0, "as_of": "2026-06-01"},
    })
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["balance-sheet"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "hdfc-cc" in out
    assert "1/2" in out
