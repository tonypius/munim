# Balance Sheet (Opening Balances + Net Worth) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user record a manually-entered opening balance per
account and compute a current balance sheet / net worth figure from it,
per `docs/superpowers/specs/2026-09-04-transfer-linking-design.md`'s
"Reporting: transfer-link coverage and balance sheet" section. Fully
independent of the transfer-linking plan — this computes each account's
balance from its own debit/credit history directly, with no dependency
on whether any transfers are linked.

**Architecture:** One new config key (`account_opening_balances`,
following the existing `account_types` flat-dict convention — no new
table), a small new module (`balance_sheet.py`) computing one account's
current balance from its opening balance plus every transaction since,
and two new CLI commands.

**Tech Stack:** Python 3.11+, SQLite, Typer, pytest. No new dependencies.

## Global Constraints

- Cost-basis only. This plan computes balances from transaction amounts,
  never from live market prices — there is no price-feed integration in
  munim, and building one is out of scope.
- An account with no opening balance set must be visibly excluded from
  the balance sheet, never silently treated as zero — the output must
  always state how many of the known accounts actually have a starting
  point.
- The sign convention differs by account type and must not be
  conflated: **Assets** — credit increases the balance, debit decreases
  it (the intuitive bank-statement direction). **Liabilities** — inverted,
  since the statement's "balance" represents what's owed: a debit
  (a purchase/charge) increases it, a credit (a payment) decreases it.
- "Opening balance as of DATE" means the balance immediately *before*
  that date's own transactions — so transactions dated exactly on the
  `as_of` date are included in the delta sum (`t.date >= as_of`), not
  excluded.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first).

---

### Task 1: `munim accounts set-opening-balance`

**Files:**
- Modify: `packages/classify/munim/cli.py` (`acct_app` gains a new command)
- Test: `packages/classify/tests/test_balance_sheet.py` (new file)

**Interfaces:**
- Produces: `munim accounts set-opening-balance <account> <amount>
  <as-of-date>` — validates the date, writes
  `config["account_opening_balances"][account] = {"balance": amount,
  "as_of": as_of}`.

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_balance_sheet.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: FAIL — `No such command 'set-opening-balance'`.

- [ ] **Step 3: Add the command**

In `packages/classify/munim/cli.py`, add right after `accounts_type`
(inside the existing `acct_app` group):

```python

@acct_app.command("set-opening-balance")
def accounts_set_opening_balance(
    account: str,
    amount: float,
    as_of: str = typer.Argument(..., help="Date the balance was true, YYYY-MM-DD"),
):
    """Record a starting balance for an account, copied from your oldest
    available statement. Needed for `munim balance-sheet` to compute a
    current balance for this account — without it, the account is
    excluded from the balance sheet entirely."""
    from datetime import date as _date
    try:
        _date.fromisoformat(as_of)
    except ValueError:
        console.print(f"[red]{as_of} is not a valid date (use YYYY-MM-DD).[/red]")
        raise typer.Exit(1)
    store = _store()
    balances = store.get_config("account_opening_balances", {}) or {}
    balances[account] = {"balance": amount, "as_of": as_of}
    store.set_config("account_opening_balances", balances)
    console.print(f"[green]{account}: opening balance {amount:,.2f} "
                  f"as of {as_of}.[/green]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_balance_sheet.py
git commit -m "Add munim accounts set-opening-balance"
```

---

### Task 2: Balance computation

**Files:**
- Create: `packages/classify/munim/balance_sheet.py`
- Test: `packages/classify/tests/test_balance_sheet.py`

**Interfaces:**
- Consumes: `config["account_opening_balances"]` (Task 1),
  `config["account_types"]`, `Store.all_transactions()`.
- Produces: `compute_account_balance(store, account: str) -> float |
  None` — `None` when no opening balance is set for that account.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_balance_sheet.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'munim.balance_sheet'`.

- [ ] **Step 3: Write the module**

Create `packages/classify/munim/balance_sheet.py`:

```python
"""Balance-sheet computation: an account's current balance, derived from
a manually-entered opening balance plus every transaction since. Cost-
basis, not market-value -- see the design spec's non-goals for why live
pricing is out of scope for this project.
"""
from __future__ import annotations

from datetime import date as Date

from .schema import Direction


def compute_account_balance(store, account: str) -> float | None:
    """Returns the account's current balance, or None if no opening
    balance has been set for it (see `munim accounts
    set-opening-balance`). Assets: credit increases the balance, debit
    decreases it. Liabilities: inverted -- the statement's "balance" is
    what's owed, so a debit (purchase) increases it and a credit
    (payment) decreases it. A transaction dated exactly on the opening
    balance's as_of date is included in the delta, not excluded."""
    balances = store.get_config("account_opening_balances", {}) or {}
    entry = balances.get(account)
    if entry is None:
        return None
    opening = entry["balance"]
    as_of = Date.fromisoformat(entry["as_of"])

    account_types = store.get_config("account_types", {}) or {}
    is_liability = account_types.get(account, "Assets") == "Liabilities"

    debit_total = credit_total = 0.0
    for t in store.all_transactions():
        if t.account != account or t.date < as_of:
            continue
        if t.direction == Direction.DEBIT:
            debit_total += t.amount
        else:
            credit_total += t.amount

    if is_liability:
        return opening + debit_total - credit_total
    return opening + credit_total - debit_total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/balance_sheet.py packages/classify/tests/test_balance_sheet.py
git commit -m "Add compute_account_balance for the balance sheet"
```

---

### Task 3: `munim balance-sheet` command

**Files:**
- Modify: `packages/classify/munim/cli.py` (new top-level command)
- Test: `packages/classify/tests/test_balance_sheet.py`

**Interfaces:**
- Consumes: `compute_account_balance` (Task 2), `config["account_types"]`.
- Produces: `munim balance-sheet` — a table of every known account's
  balance (or "no opening balance" if unset), plus a net-worth total and
  an explicit "N/M accounts have a starting point" caveat.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_balance_sheet.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: FAIL — `No such command 'balance-sheet'`.

- [ ] **Step 3: Add the command**

In `packages/classify/munim/cli.py`, add near the end of the file
(after the `accounts` command group, following the same top-level-
command pattern as `export`):

```python

# ------------------------------------------------------------ balance sheet
@app.command("balance-sheet")
def balance_sheet():
    """Net worth: sum of Asset account balances minus Liability account
    balances, computed from each account's opening balance plus every
    transaction since. Cost-basis only -- an account with no opening
    balance set is excluded and called out, never silently treated as
    zero."""
    from .balance_sheet import compute_account_balance
    store = _store()
    accounts = [r["account"] for r in store.db.execute(
        "SELECT DISTINCT account FROM transactions").fetchall()]
    account_types = store.get_config("account_types", {}) or {}

    table = Table(title="Balance sheet")
    table.add_column("Account")
    table.add_column("Type")
    table.add_column("Balance", justify="right")
    total_assets = total_liabilities = 0.0
    counted = 0
    for account in sorted(accounts):
        acct_type = account_types.get(account, "Assets")
        balance = compute_account_balance(store, account)
        if balance is None:
            table.add_row(account, acct_type, "[dim]no opening balance[/dim]")
            continue
        counted += 1
        table.add_row(account, acct_type, f"{balance:,.2f}")
        if acct_type == "Liabilities":
            total_liabilities += balance
        else:
            total_assets += balance
    console.print(table)
    console.print(f"\n[bold]Net worth: {total_assets - total_liabilities:,.2f}"
                  f"[/bold]  [dim]({counted}/{len(accounts)} accounts have a "
                  "starting point)[/dim]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_balance_sheet.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_balance_sheet.py
git commit -m "Add munim balance-sheet command"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After both tasks land, update:
- `docs/data-contract.md`: add a short note under `config` that
  `account_opening_balances` is a new key, same style as the existing
  `account_types` entry.
- `README.md`: a short paragraph on the balance sheet / net worth
  command, near wherever transfer linking ends up documented, pointing
  at `munim balance-sheet --help` and `munim accounts
  set-opening-balance --help`.

These are documentation-only, no tests — do them in one small commit
after Task 3's full-suite pass is green.
