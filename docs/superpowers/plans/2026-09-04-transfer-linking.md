# Transfer-Pair Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explicitly link the two legs of a transfer between the user's
own accounts (e.g. a bank debit paying a credit-card bill, and that
bill's corresponding credit on the card statement) instead of both
independently washing through a generic `Equity:Transfers` clearing
bucket, per
`docs/superpowers/specs/2026-09-04-transfer-linking-design.md`.

**Architecture:** Two new tables (`transfer_links`, `transfer_dismissals`)
alongside a new matching module that finds candidate pairs among
currently-unlinked `is_transfer=True` transactions. Exact single-candidate
matches auto-link; multi-candidate matches queue for a `munim review`-style
confirmation step. No changes to `Transaction` or any existing table.

**Tech Stack:** Python 3.11+, SQLite, Typer, pytest. No new dependencies.

## Global Constraints

- No changes to `Transaction`, `transactions`, or `memory` — whether a
  transaction is linked is answered by querying `transfer_links`, never
  by a stored flag on the transaction itself.
- Only `is_transfer=True` transactions are ever candidates for linking —
  this plan never touches or reasons about non-transfer transactions.
- A transaction that is dismissed or already linked must never appear as
  a match candidate for another transaction.
- Matching is symmetric: it must find candidates regardless of which side
  (debit or credit) was imported first or more recently — the pass always
  runs over the full currently-unlinked pool, not just newly-imported rows.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first).

---

### Task 1: Schema and core Store methods

**Files:**
- Modify: `packages/classify/munim/store.py` (SCHEMA string, new methods)
- Test: `packages/classify/tests/test_transfer_links.py` (new file)

**Interfaces:**
- Produces:
  - `Store.link_transfer(txn_id_a: str, txn_id_b: str, confidence: str = "auto") -> None`
  - `Store.is_linked(txn_id: str) -> bool`
  - `Store.linked_counterpart(txn_id: str) -> Optional[str]`
  - `Store.transfer_link_map() -> dict[str, str]` — every linked txn_id
    mapped to its counterpart, both directions present as keys.
  - `Store.dismiss_transfer(txn_id: str) -> None`
  - `Store.is_dismissed(txn_id: str) -> bool`
  - `Store.all_transfer_links() -> list[dict]` — each dict has
    `txn_id_a`, `txn_id_b`, `confidence`, `created_at`.
  - `Store.dismissed_ids() -> set[str]`

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_transfer_links.py`:

```python
"""Tests for transfer-pair linking: the transfer_links and
transfer_dismissals tables, and Store's core methods over them."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store


def test_fresh_store_has_transfer_tables(tmp_path):
    store = Store(home=tmp_path)
    tables = {r[0] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "transfer_links" in tables
    assert "transfer_dismissals" in tables


def test_link_transfer_then_is_linked(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    assert store.is_linked("txn-a")
    assert store.is_linked("txn-b")
    assert not store.is_linked("txn-c")


def test_linked_counterpart_works_both_directions(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    assert store.linked_counterpart("txn-a") == "txn-b"
    assert store.linked_counterpart("txn-b") == "txn-a"
    assert store.linked_counterpart("txn-c") is None


def test_link_transfer_is_idempotent(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    store.link_transfer("txn-a", "txn-b")  # re-linking the same pair
    rows = store.all_transfer_links()
    assert len(rows) == 1


def test_transfer_link_map_covers_both_directions(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b", confidence="auto")
    store.link_transfer("txn-c", "txn-d", confidence="confirmed")
    m = store.transfer_link_map()
    assert m == {"txn-a": "txn-b", "txn-b": "txn-a",
                "txn-c": "txn-d", "txn-d": "txn-c"}


def test_all_transfer_links_records_confidence(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b", confidence="confirmed")
    rows = store.all_transfer_links()
    assert len(rows) == 1
    assert rows[0]["confidence"] == "confirmed"
    assert {rows[0]["txn_id_a"], rows[0]["txn_id_b"]} == {"txn-a", "txn-b"}


def test_dismiss_transfer_then_is_dismissed(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    assert store.is_dismissed("txn-x")
    assert not store.is_dismissed("txn-y")


def test_dismissed_ids_returns_a_set(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    store.dismiss_transfer("txn-y")
    assert store.dismissed_ids() == {"txn-x", "txn-y"}


def test_dismiss_transfer_is_idempotent(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    store.dismiss_transfer("txn-x")
    assert len(store.dismissed_ids()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `no such table: transfer_links`, `AttributeError` on the
not-yet-defined methods.

- [ ] **Step 3: Add the tables to SCHEMA**

In `packages/classify/munim/store.py`, add to the `SCHEMA` string, right
after the `tags` table (which currently ends the string):

```python
CREATE TABLE IF NOT EXISTS transfer_links (
    id TEXT PRIMARY KEY,
    txn_id_a TEXT NOT NULL,
    txn_id_b TEXT NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transfer_dismissals (
    txn_id TEXT PRIMARY KEY,
    dismissed_at TEXT DEFAULT (datetime('now'))
);
```

(These are brand-new tables, not column additions to an existing one, so
`CREATE TABLE IF NOT EXISTS` in the `executescript(SCHEMA)` call already
handles both fresh and pre-existing databases — no `_migrate()` change
needed, same as when the `tags` table was added.)

- [ ] **Step 4: Add the methods**

In `packages/classify/munim/store.py`, add a new section after the tags
methods (after `apply_tag_to_pattern`, at the end of the file):

```python

    # ---- transfer links ---------------------------------------------
    def link_transfer(self, txn_id_a: str, txn_id_b: str,
                      confidence: str = "auto") -> None:
        """Record that txn_id_a and txn_id_b are the two legs of one
        real-world transfer. Idempotent: linking the same pair twice is
        a no-op, not a duplicate row."""
        link_id = hashlib.sha1(
            f"{txn_id_a}|{txn_id_b}".encode()).hexdigest()[:16]
        self.db.execute(
            "INSERT OR IGNORE INTO transfer_links"
            "(id, txn_id_a, txn_id_b, confidence) VALUES (?,?,?,?)",
            (link_id, txn_id_a, txn_id_b, confidence))
        self.db.commit()

    def is_linked(self, txn_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM transfer_links WHERE txn_id_a=? OR txn_id_b=?",
            (txn_id, txn_id)).fetchone()
        return row is not None

    def linked_counterpart(self, txn_id: str) -> str | None:
        row = self.db.execute(
            "SELECT txn_id_a, txn_id_b FROM transfer_links "
            "WHERE txn_id_a=? OR txn_id_b=?", (txn_id, txn_id)).fetchone()
        if not row:
            return None
        return row["txn_id_b"] if row["txn_id_a"] == txn_id else row["txn_id_a"]

    def transfer_link_map(self) -> dict[str, str]:
        """Every linked txn_id -> its counterpart, both directions
        present as keys, for O(1) lookup either way."""
        out: dict[str, str] = {}
        for row in self.db.execute(
                "SELECT txn_id_a, txn_id_b FROM transfer_links").fetchall():
            out[row["txn_id_a"]] = row["txn_id_b"]
            out[row["txn_id_b"]] = row["txn_id_a"]
        return out

    def all_transfer_links(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT txn_id_a, txn_id_b, confidence, created_at "
            "FROM transfer_links ORDER BY created_at").fetchall()]

    def dismiss_transfer(self, txn_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO transfer_dismissals(txn_id) VALUES (?)",
            (txn_id,))
        self.db.commit()

    def is_dismissed(self, txn_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM transfer_dismissals WHERE txn_id=?",
            (txn_id,)).fetchone()
        return row is not None

    def dismissed_ids(self) -> set[str]:
        return {r["txn_id"] for r in self.db.execute(
            "SELECT txn_id FROM transfer_dismissals").fetchall()}
```

Add `import hashlib` to the top of `store.py` if it isn't already
imported — check first; `Transaction.compute_id()` in `schema.py` already
uses `hashlib`, but `store.py` is a different module and may not have it.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_transfer_links.py
git commit -m "Add transfer_links/transfer_dismissals tables and core Store methods"
```

---

### Task 2: Candidate-matching function

**Files:**
- Create: `packages/classify/munim/structural/transfer_matching.py`
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `Store.dismissed_ids()`, `Store.transfer_link_map()` (Task 1),
  `Store.all_transactions()`, `MIRROR_WINDOW_DAYS` from
  `munim.structural.transfers` (the existing same-batch mirror-matching
  window — reused here for cross-import matching instead of a new
  constant).
- Produces: `find_transfer_candidates(store) -> dict` returning:
  ```python
  {
      "auto": [(debit_id, credit_id), ...],       # exactly one candidate
      "ambiguous": [(debit_id, [credit_id, ...]), ...],  # 2+ candidates
  }
  ```
  Transactions with zero candidates are simply absent from both lists —
  no separate "unmatched" key, since the caller (Task 3/6) can derive
  "still unmatched" as "is_transfer, not linked, not dismissed, not in
  either list above."

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
from datetime import timedelta
from munim.schema import Transaction, Direction


def _transfer(id_, date, amount, direction, account):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"TRANSFER {id_}", account=account,
                       is_transfer=True, category="Transfers")


def test_find_transfer_candidates_exact_single_match_is_auto(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == [("d1", "c1")]
    assert result["ambiguous"] == []


def test_find_transfer_candidates_multiple_matches_is_ambiguous(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-03", 5000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert len(result["ambiguous"]) == 1
    assert result["ambiguous"][0][0] == "d1"
    assert set(result["ambiguous"][0][1]) == {"c1", "c2"}


def test_find_transfer_candidates_same_account_never_matches(tmp_path):
    """A debit and credit in the SAME account can't be a transfer between
    two of the user's accounts by definition."""
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "bank")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_outside_window_does_not_match(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-20", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_excludes_already_linked(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_excludes_dismissed(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.dismiss_transfer("d1")
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_ignores_non_transfers(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = Transaction(id="d1", date="2026-06-01", amount=5000,
                        direction=Direction.DEBIT, description_raw="GROCERY",
                        account="bank", is_transfer=False, category="Groceries")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named
'munim.structural.transfer_matching'`.

- [ ] **Step 3: Write the module**

Create `packages/classify/munim/structural/transfer_matching.py`:

```python
"""Cross-import transfer-pair matching: finds candidate links among
currently-unlinked is_transfer transactions in the store, spanning ALL
past imports -- not just one Pipeline.run() batch, which is what
structural/transfers.py's own mirror-matching is limited to. Reuses that
module's MIRROR_WINDOW_DAYS for the date-window heuristic, applied
across the whole database instead of one batch.
"""
from __future__ import annotations

from ..schema import Direction
from .transfers import MIRROR_WINDOW_DAYS


def find_transfer_candidates(store) -> dict:
    """Read-only: compute which unlinked, undismissed is_transfer
    transactions could pair up. Returns {"auto": [(debit_id, credit_id)],
    "ambiguous": [(debit_id, [credit_id, ...])]} -- zero-candidate
    transactions are simply absent from both lists."""
    linked = set(store.transfer_link_map().keys())
    dismissed = store.dismissed_ids()

    def eligible(t):
        return t.is_transfer and t.id not in linked and t.id not in dismissed

    txns = [t for t in store.all_transactions() if eligible(t)]
    debits = [t for t in txns if t.direction == Direction.DEBIT]
    credits = [t for t in txns if t.direction == Direction.CREDIT]

    auto = []
    ambiguous = []
    for d in debits:
        matches = [c.id for c in credits
                  if c.account != d.account
                  and abs(c.amount - d.amount) < 0.01
                  and abs((c.date - d.date).days) <= MIRROR_WINDOW_DAYS]
        if len(matches) == 1:
            auto.append((d.id, matches[0]))
        elif len(matches) > 1:
            ambiguous.append((d.id, matches))

    return {"auto": auto, "ambiguous": ambiguous}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/structural/transfer_matching.py packages/classify/tests/test_transfer_links.py
git commit -m "Add cross-import transfer candidate matching"
```

---

### Task 3: Auto-linking application, wired into import, plus `munim transfers link`

**Files:**
- Modify: `packages/classify/munim/cli.py` (new `transfers_app`, wire into `import_csv`)
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `find_transfer_candidates` (Task 2), `Store.link_transfer` (Task 1).
- Produces:
  - A module-level helper `apply_auto_links(store) -> int` in
    `transfer_matching.py`, returning the count of pairs auto-linked.
  - `munim import` now calls `apply_auto_links` after importing, prints
    a one-line summary if any pairs were auto-linked.
  - `munim transfers link` — CLI command re-running the same auto-link
    pass on demand, without a fresh import.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
def test_apply_auto_links_links_exact_matches_only(tmp_path):
    from munim.structural.transfer_matching import apply_auto_links
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    ambiguous_debit = _transfer("d2", "2026-06-01", 7000, Direction.DEBIT, "bank")
    ambiguous_credit1 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "card")
    ambiguous_credit2 = _transfer("c3", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit, ambiguous_debit,
                               ambiguous_credit1, ambiguous_credit2])
    n = apply_auto_links(store)
    assert n == 1
    assert store.linked_counterpart("d1") == "c1"
    assert not store.is_linked("d2")


def test_import_csv_auto_links_transfers(tmp_path, monkeypatch):
    """End-to-end: importing a CSV that structurally detects a transfer
    which exactly matches an existing unlinked transfer must auto-link
    them, without a separate `transfers link` call. Pre-seeds a saved
    CSV profile (matching _load_or_build_profile's "name in profiles"
    branch) so the import runs straight through without the interactive
    column-mapping wizard."""
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("csv_profiles", {
        "test": {"date_col": "Date", "description_col": "Narration",
                 "amount_col": "Amount", "debit_col": "", "credit_col": "",
                 "currency": "INR", "date_format": ""},
    })
    existing = _transfer("c1", "2026-06-02", 45230, Direction.CREDIT, "tony-hdfc-regalia-cc")
    store.upsert_transactions([existing])

    csv_path = tmp_path / "bank.csv"
    csv_path.write_text(
        "Date,Narration,Amount\n"
        "01/06/2026,CREDIT CARD PAYMENT BILLDESK HDFC CARD,-45230.00\n",
        encoding="utf-8")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["import", str(csv_path), "--profile", "test",
                                 "--account", "tony-hdfc-savings"])
    assert result.exit_code == 0, result.output

    reloaded = Store(home=tmp_path)
    new_debit_id = [t.id for t in reloaded.all_transactions() if t.id != "c1"][0]
    assert reloaded.linked_counterpart(new_debit_id) == "c1"


def test_transfers_link_command_reports_count(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "link"])
    assert result.exit_code == 0, result.output
    assert "1" in result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.linked_counterpart("d1") == "c1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_auto_links'`,
then `No such command 'transfers'`.

- [ ] **Step 3: Add `apply_auto_links`**

Append to `packages/classify/munim/structural/transfer_matching.py`:

```python

def apply_auto_links(store) -> int:
    """Find and record every exact, unambiguous transfer pair. Returns
    the number of pairs linked."""
    candidates = find_transfer_candidates(store)
    for debit_id, credit_id in candidates["auto"]:
        store.link_transfer(debit_id, credit_id, confidence="auto")
    return len(candidates["auto"])
```

- [ ] **Step 4: Wire into `import_csv` and add the `transfers` command group**

In `packages/classify/munim/cli.py`, change `import_csv`'s body right
after `inserted, skipped = store.upsert_transactions(txns)`:

```python
    inserted, skipped = store.upsert_transactions(txns)
    from .structural.transfer_matching import apply_auto_links
    n_linked = apply_auto_links(store)
```

and add, right after the existing stage-table print at the end of the
function:

```python
    if n_linked:
        console.print(f"[dim]{n_linked} transfer pair(s) auto-linked.[/dim]")
```

Then add, near the end of the file (after the `accounts` command group,
following the same pattern as `acct_app`/`tag_app`):

```python
# ---------------------------------------------------------------- transfers
transfers_app = typer.Typer(help="Link transfer pairs across accounts.",
                            no_args_is_help=True)
app.add_typer(transfers_app, name="transfers")


@transfers_app.command("link")
def transfers_link():
    """Re-run auto-linking over every currently-unlinked transfer pair,
    without a fresh import."""
    from .structural.transfer_matching import apply_auto_links
    store = _store()
    n = apply_auto_links(store)
    console.print(f"[green]{n} transfer pair(s) linked.[/green]")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (19 passed)

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/munim/structural/transfer_matching.py packages/classify/tests/test_transfer_links.py
git commit -m "Auto-link transfer pairs on import, add munim transfers link"
```

---

### Task 4: Review queue for ambiguous pairs

**Files:**
- Modify: `packages/classify/munim/cli.py` (`transfers_app` gains `review`)
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `find_transfer_candidates` (Task 2), `Store.link_transfer` (Task 1).
- Produces: `munim transfers review` — for each ambiguous debit, list its
  candidate credits, prompt for a choice (or skip), link the chosen pair
  with `confidence="confirmed"`.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
def test_transfers_review_links_the_chosen_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 7000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 7000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    # "2" selects the second listed candidate
    result = runner.invoke(app, ["transfers", "review"], input="2\n")
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.is_linked("d1")
    rows = reloaded.all_transfer_links()
    assert rows[0]["confidence"] == "confirmed"


def test_transfers_review_skip_leaves_unlinked(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 7000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 7000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "review"], input="s\n")
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert not reloaded.is_linked("d1")


def test_transfers_review_empty_queue_message(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "review"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "nothing" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `No such command 'review'` under the `transfers` group
(Typer reports this as a usage error, not a missing-attribute error,
since `transfers_app` already exists from Task 3).

- [ ] **Step 3: Add the command**

In `packages/classify/munim/cli.py`, add right after `transfers_link`:

```python

@transfers_app.command("review")
def transfers_review():
    """Resolve ambiguous transfer pairs one at a time -- a debit with
    multiple candidate credits, pick the right one."""
    from .structural.transfer_matching import find_transfer_candidates
    store = _store()
    ambiguous = find_transfer_candidates(store)["ambiguous"]
    if not ambiguous:
        console.print("[green]Nothing ambiguous — the transfer queue is "
                      "empty.[/green]")
        return

    txn_by_id = {t.id: t for t in store.all_transactions()}
    console.print(f"[bold]{len(ambiguous)} ambiguous transfer(s).[/bold] "
                  "number=pick a match · s=skip · q=quit\n")
    for debit_id, candidate_ids in ambiguous:
        d = txn_by_id[debit_id]
        label = d.merchant_norm or d.payee_handle or d.description_raw[:40]
        console.print(f"[bold]{label}[/bold]  {d.currency} {d.amount:,.2f}  "
                      f"{d.date}  ({d.account})")
        for i, cid in enumerate(candidate_ids, 1):
            c = txn_by_id[cid]
            console.print(f"  [{i}] {c.account}  {c.date}  "
                          f"{c.currency} {c.amount:,.2f}")
        choice = typer.prompt("      →", default="", show_default=False).strip().lower()
        if choice == "q":
            break
        if choice == "s" or not choice:
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(candidate_ids):
            chosen = candidate_ids[int(choice) - 1]
            store.link_transfer(debit_id, chosen, confidence="confirmed")
            console.print("        [green]Linked.[/green]\n")
        else:
            console.print("        [red]Skipped (unrecognized input).[/red]\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (22 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_transfer_links.py
git commit -m "Add munim transfers review for ambiguous transfer pairs"
```

---

### Task 5: Dismiss command

**Files:**
- Modify: `packages/classify/munim/cli.py` (`transfers_app` gains `dismiss`)
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `Store.dismiss_transfer`, `Store.is_linked` (Task 1).
- Produces: `munim transfers dismiss <txn-id>` — marks a transaction as
  intentionally, permanently unlinked.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
def test_transfers_dismiss_marks_dismissed(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "d1"])
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.is_dismissed("d1")


def test_transfers_dismiss_rejects_already_linked_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "d1"])
    assert result.exit_code != 0
    reloaded = Store(home=tmp_path)
    assert not reloaded.is_dismissed("d1")


def test_transfers_dismiss_rejects_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "nonexistent"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `No such command 'dismiss'`.

- [ ] **Step 3: Add the command**

In `packages/classify/munim/cli.py`, add right after `transfers_review`:

```python

@transfers_app.command("dismiss")
def transfers_dismiss(txn_id: str):
    """Mark a transfer as intentionally unlinked -- it will never have a
    counterpart in munim (e.g. money sent to an untracked account)."""
    store = _store()
    t = store.get_transaction(txn_id)
    if t is None:
        console.print(f"[red]No transaction with id {txn_id}.[/red]")
        raise typer.Exit(1)
    if store.is_linked(txn_id):
        console.print(f"[red]{txn_id} is already linked — nothing to "
                      "dismiss.[/red]")
        raise typer.Exit(1)
    store.dismiss_transfer(txn_id)
    console.print(f"[green]{txn_id} dismissed.[/green]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (25 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_transfer_links.py
git commit -m "Add munim transfers dismiss for permanently one-sided transfers"
```

---

### Task 6: Status/reporting command

**Files:**
- Modify: `packages/classify/munim/cli.py` (`transfers_app` gains `status`)
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `Store.all_transfer_links`, `Store.dismissed_ids`,
  `Store.all_transactions` (Task 1).
- Produces: `munim transfers status` — counts of linked (split
  auto/confirmed), unmatched-pending, and dismissed transfers, with
  unmatched-pending broken down by account.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
def test_transfers_status_reports_all_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    linked_a = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    linked_b = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    pending = _transfer("d2", "2026-06-05", 3000, Direction.DEBIT, "bank")
    dismissed = _transfer("d3", "2026-06-06", 2000, Direction.DEBIT, "wallet")
    store.upsert_transactions([linked_a, linked_b, pending, dismissed])
    store.link_transfer("d1", "c1", confidence="auto")
    store.dismiss_transfer("d3")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "status"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "bank" in out  # the pending one's account surfaced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `No such command 'status'`.

- [ ] **Step 3: Add the command**

In `packages/classify/munim/cli.py`, add right after `transfers_dismiss`:

```python

@transfers_app.command("status")
def transfers_status():
    """Coverage report: how many transfer pairs are linked, still
    pending a counterpart, or dismissed."""
    store = _store()
    txns = {t.id: t for t in store.all_transactions() if t.is_transfer}
    linked_ids = set(store.transfer_link_map().keys())
    dismissed_ids = store.dismissed_ids()
    links = store.all_transfer_links()
    n_auto = sum(1 for l in links if l["confidence"] == "auto")
    n_confirmed = sum(1 for l in links if l["confidence"] == "confirmed")
    pending = [t for tid, t in txns.items()
              if tid not in linked_ids and tid not in dismissed_ids]

    console.print(f"[bold]Transfer link coverage[/bold]")
    console.print(f"  Linked: {len(links)} pairs "
                  f"({n_auto} auto, {n_confirmed} confirmed)")
    console.print(f"  Dismissed: {len(dismissed_ids)}")
    console.print(f"  Still pending a counterpart: {len(pending)}")
    if pending:
        by_account: dict[str, int] = {}
        for t in pending:
            by_account[t.account] = by_account.get(t.account, 0) + 1
        table = Table(title="Pending, by account")
        table.add_column("Account")
        table.add_column("Count", justify="right")
        for account, n in sorted(by_account.items(), key=lambda x: -x[1]):
            table.add_row(account, str(n))
        console.print(table)
```

`transfer_link_map()` returns each linked id as its own key with its
counterpart as the value (Task 1's `test_transfer_link_map_covers_both_directions`),
so `set(store.transfer_link_map().keys())` is exactly the set of every
transaction id that participates in at least one link — correct for
excluding them from "pending."

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (26 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_transfer_links.py
git commit -m "Add munim transfers status coverage report"
```

---

### Task 7: Ledger export uses real counterparty accounts for linked transfers

**Files:**
- Modify: `packages/classify/munim/export_formats.py` (`to_ledger`)
- Modify: `packages/classify/munim/cli.py` (the `export` command's `to_ledger` call site)
- Test: `packages/classify/tests/test_transfer_links.py`

**Interfaces:**
- Consumes: `Store.transfer_link_map` (Task 1).
- Produces: `to_ledger(txns, tree=None, account_types=None, links=None)` —
  new optional `links: dict[str, str] | None` parameter (txn_id ->
  counterpart txn_id). When a transfer's id is a key in `links`, its
  counter-leg posts against the counterpart transaction's real account
  path instead of the generic `Equity:Transfers` bucket. Existing
  callers that don't pass `links` are unaffected (defaults to `{}`,
  identical output to today).

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_transfer_links.py`:

```python
def test_ledger_export_uses_real_account_for_linked_transfer(tmp_path):
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "tony-hdfc-regalia-cc")
    tree = default_tree(["Transfers"])
    account_types = {"tony-hdfc-savings": "Assets", "tony-hdfc-regalia-cc": "Liabilities"}
    links = {"d1": "c1", "c1": "d1"}
    out = to_ledger([debit, credit], tree=tree, account_types=account_types, links=links)
    assert "Equity:Transfers" not in out
    assert "Liabilities:tony-hdfc-regalia-cc" in out
    assert "Assets:tony-hdfc-savings" in out


def test_ledger_export_falls_back_to_equity_transfers_when_unlinked(tmp_path):
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    tree = default_tree(["Transfers"])
    out = to_ledger([debit], tree=tree, account_types={"tony-hdfc-savings": "Assets"})
    assert "Equity:Transfers" in out


def test_ledger_export_links_parameter_is_optional(tmp_path):
    """Existing callers that never pass `links` must see identical
    output to before this change -- links defaults to {}."""
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    tree = default_tree(["Transfers"])
    out = to_ledger([debit], tree=tree, account_types={"tony-hdfc-savings": "Assets"})
    assert "Equity:Transfers" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: FAIL — `TypeError: to_ledger() got an unexpected keyword
argument 'links'`.

- [ ] **Step 3: Update `to_ledger`**

In `packages/classify/munim/export_formats.py`, change the function
signature and body. Current:

```python
def to_ledger(txns: list[Transaction], tree: dict | None = None,
              account_types: dict | None = None) -> str:
    """Plain-text accounting format (ledger/hledger; beancount-convertible).

    Leaves resolve through the category tree (docs: categories are flat in
    the engine; the tree is a display mapping). Accounts post under Assets
    or Liabilities per `munim accounts type`. Transfers use the Transfers
    leaf's mapped path (default Equity:Transfers) as the counter-leg because
    Munim doesn't track the counterparty account.
    """
    from .tree import resolve, default_tree
    tree = tree or default_tree([])
    account_types = account_types or {}

    def acct_path(t: Transaction) -> str:
        return f"{account_types.get(t.account, 'Assets')}:{t.account}"

    out = []
    for t in sorted(txns, key=lambda x: x.date):
        payee = t.merchant_norm or t.payee_handle or t.description_raw[:48]
        path = resolve(tree, t.category)
        if t.subcategory:
            path += f":{t.subcategory}"
        path = path.replace(" ", "-")
        date = t.date.strftime("%Y/%m/%d")
        note = f"    ; stage: {t.stage.value}, status: {t.status.value}"
        amt = f"{t.amount:.2f} {t.currency}"
        if t.is_transfer:
            counter = resolve(tree, "Transfers").replace(" ", "-")
            legs = [f"    {counter}    {amt}",
                    f"    {acct_path(t)}"]
            if t.direction == Direction.CREDIT:
                legs = [f"    {acct_path(t)}    {amt}",
                        f"    {counter}"]
        elif t.direction == Direction.DEBIT:
            legs = [f"    {path}    {amt}",
                    f"    {acct_path(t)}"]
        else:
            legs = [f"    {acct_path(t)}    {amt}",
                    f"    {path}"]
        out.append("\n".join([f"{date} {payee}", note, *legs]))
    return "\n\n".join(out) + "\n"
```

Change to:

```python
def to_ledger(txns: list[Transaction], tree: dict | None = None,
              account_types: dict | None = None,
              links: dict | None = None) -> str:
    """Plain-text accounting format (ledger/hledger; beancount-convertible).

    Leaves resolve through the category tree (docs: categories are flat in
    the engine; the tree is a display mapping). Accounts post under Assets
    or Liabilities per `munim accounts type`. A linked transfer (see
    `Store.transfer_link_map`) posts its counter-leg against the real
    counterparty account; an unlinked one falls back to the Transfers
    leaf's mapped path (default Equity:Transfers) as a generic clearing
    bucket, exactly as before this parameter existed.
    """
    from .tree import resolve, default_tree
    tree = tree or default_tree([])
    account_types = account_types or {}
    links = links or {}
    by_id = {t.id: t for t in txns}

    def acct_path(t: Transaction) -> str:
        return f"{account_types.get(t.account, 'Assets')}:{t.account}"

    out = []
    for t in sorted(txns, key=lambda x: x.date):
        payee = t.merchant_norm or t.payee_handle or t.description_raw[:48]
        path = resolve(tree, t.category)
        if t.subcategory:
            path += f":{t.subcategory}"
        path = path.replace(" ", "-")
        date = t.date.strftime("%Y/%m/%d")
        note = f"    ; stage: {t.stage.value}, status: {t.status.value}"
        amt = f"{t.amount:.2f} {t.currency}"
        if t.is_transfer:
            counterpart_id = links.get(t.id)
            counterpart = by_id.get(counterpart_id) if counterpart_id else None
            counter = (acct_path(counterpart) if counterpart
                      else resolve(tree, "Transfers").replace(" ", "-"))
            legs = [f"    {counter}    {amt}",
                    f"    {acct_path(t)}"]
            if t.direction == Direction.CREDIT:
                legs = [f"    {acct_path(t)}    {amt}",
                        f"    {counter}"]
        elif t.direction == Direction.DEBIT:
            legs = [f"    {path}    {amt}",
                    f"    {acct_path(t)}"]
        else:
            legs = [f"    {acct_path(t)}    {amt}",
                    f"    {path}"]
        out.append("\n".join([f"{date} {payee}", note, *legs]))
    return "\n\n".join(out) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_transfer_links.py -v`
Expected: PASS (29 passed)

- [ ] **Step 5: Wire `links` through the `export` CLI command**

In `packages/classify/munim/cli.py`, find the `export` command's
`ledger` branch (currently calls `ef.to_ledger(txns, tree=get_tree(store),
account_types=store.get_config("account_types", {}) or {})`). Change it to
also pass `links=store.transfer_link_map()`:

```python
    elif fmt == "ledger":
        from .tree import get_tree
        out = out or Path("munim-export.ledger")
        out.write_text(ef.to_ledger(
            txns, tree=get_tree(store),
            account_types=store.get_config("account_types", {}) or {},
            links=store.transfer_link_map(),
        ), encoding="utf-8")
```

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — the `links` parameter defaults to `{}`, so every
existing caller and test of `to_ledger` that doesn't pass it keeps
working identically.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/export_formats.py packages/classify/munim/cli.py packages/classify/tests/test_transfer_links.py
git commit -m "Ledger export posts linked transfers against real counterparty accounts"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After all 7 tasks land, update:
- `docs/data-contract.md`: add a short note that `transfer_links` and
  `transfer_dismissals` are new tables (not columns on `transactions`),
  same style as the existing `tags`/`corrections` entries.
- `docs/pipeline.md`: one sentence noting that `munim import` now also
  runs a cross-import transfer-matching pass after classification.
- `README.md`: a short paragraph on transfer linking, near wherever
  subcategories/tags are documented, pointing at `munim transfers --help`.

These are documentation-only, no tests — do them in one small commit
after Task 7's full-suite pass is green.
