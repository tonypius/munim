# Category Subcategories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a transaction optionally carry a second, finer-grained
category level under a specific head — `Groceries` → `Groceries:Alcohol`
— without touching the existing flat `category` field, the 20-category
cap, or anything that currently keys off `category` alone.

**Architecture:** A new `subcategory` column rides alongside `category`
on `transactions`, plus the same column on `memory` so a taught rule can
carry one. The pipeline attaches a subcategory only when a **memory**
rule (never the community dictionary, never purpose-tail matching)
carries one. A new `apply_subcategory()` store method lets a subcategory
backfill onto already-**confirmed** history too — unlike category
propagation, refining a subcategory never re-opens the category
decision, so touching confirmed rows is safe. CLI and web UI both let
you teach/view/filter by subcategory as a deliberate, separate action
from the normal review flow.

**Tech Stack:** Python 3.11+, SQLite, pydantic, Typer, pytest — no new
dependencies. Web UI is the existing stdlib `http.server` + vanilla JS
single page.

## Global Constraints

- No changes to the `category` column's meaning, the 20-category
  `MAX_LEAVES` cap, transfer detection, `INCOME_MARKERS`, the community
  dictionary, purpose-tail matching, or the fallback classifier.
- Subcategory is always optional — never required to confirm/review a
  transaction.
- Subcategory assignment via memory rules, never inline in `munim
  review` or the review page's confirm flow.
- Subcategories are capped per parent category (`MAX_SUBCATEGORIES_PER_PARENT
  = 10` in `tree.py`), independent of the top-level 20-category cap.
- `apply_subcategory()` is allowed to update confirmed transactions'
  `subcategory` column — it must never touch `category`, `status`,
  `stage`, or `confidence`.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first).

---

### Task 1: Add `subcategory` to the `Transaction` schema

**Files:**
- Modify: `packages/classify/munim/schema.py:48` (insert after `category: str = ""`)
- Test: `packages/classify/tests/test_subcategories.py` (new file)

**Interfaces:**
- Produces: `Transaction.subcategory: str` (default `""`), available to every later task.

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_subcategories.py`:

```python
"""Category subcategories: a second, optional level under a category
head (Groceries -> Groceries:Alcohol), taught via memory rules and
applied independently of the existing flat category field."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.schema import Transaction, Direction


def test_transaction_subcategory_defaults_to_empty_string():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP")
    assert t.subcategory == ""


def test_transaction_subcategory_can_be_set():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP",
                     category="Groceries", subcategory="Alcohol")
    assert t.subcategory == "Alcohol"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `subcategory` is not a recognized field on `Transaction`
(pydantic raises a validation error on the second test; the first test
actually already passes trivially since accessing a nonexistent
attribute would raise `AttributeError` — confirm both fail, one each way).

- [ ] **Step 3: Add the field**

In `packages/classify/munim/schema.py`, change:

```python
    category: str = ""
    confidence: float = 0.0
```

to:

```python
    category: str = ""
    subcategory: str = ""
    confidence: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/schema.py packages/classify/tests/test_subcategories.py
git commit -m "Add subcategory field to Transaction schema"
```

---

### Task 2: Migrate the SQLite schema (new column on two tables)

**Files:**
- Modify: `packages/classify/munim/store.py:20-59` (SCHEMA string)
- Modify: `packages/classify/munim/store.py:62-72` (`Store.__init__`)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `transactions.subcategory` and `memory.subcategory` columns
  exist on every `Store`, whether freshly created or opened from an
  older database that predates this column. `Store._migrate()` is the
  method later tasks can extend if another column is ever added.

SQLite has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, so a fresh
`CREATE TABLE` and an existing database opened for the first time after
this change need two different code paths that end up at the same
result. Both must put `subcategory` as the **last** column on
`transactions` — `ALTER TABLE ADD COLUMN` always appends at the end, and
`upsert_transactions` uses positional `INSERT ... VALUES (?,?,...)`, so
the physical column order must be identical for a fresh table and a
migrated one.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
import sqlite3
from munim.store import Store


def _column_names(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_store_has_subcategory_columns(tmp_path):
    store = Store(home=tmp_path)
    assert "subcategory" in _column_names(store.db, "transactions")
    assert "subcategory" in _column_names(store.db, "memory")


def test_migrate_adds_subcategory_to_pre_existing_database(tmp_path):
    """Simulate a database created before this column existed: build the
    old schema by hand, then open it with Store and confirm the column
    gets added without losing existing rows."""
    (tmp_path).mkdir(exist_ok=True)
    db_path = tmp_path / "munim.db"
    old_schema = """
    CREATE TABLE transactions (
        id TEXT PRIMARY KEY, date TEXT NOT NULL, amount REAL NOT NULL,
        currency TEXT NOT NULL, direction TEXT NOT NULL,
        description_raw TEXT NOT NULL, account TEXT NOT NULL, balance REAL,
        merchant_norm TEXT DEFAULT '', payee_handle TEXT DEFAULT '',
        category TEXT DEFAULT '', confidence REAL DEFAULT 0,
        stage TEXT DEFAULT 'none', status TEXT DEFAULT 'unresolved',
        is_transfer INTEGER DEFAULT 0, is_recurring INTEGER DEFAULT 0
    );
    CREATE TABLE memory (
        pattern TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (pattern, kind)
    );
    CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO transactions VALUES "
        "('id1','2026-06-01',100,'INR','debit','desc','acct',NULL,"
        "'','','',0,'none','unresolved',0,0)")
    conn.commit()
    conn.close()

    store = Store(home=tmp_path)
    assert "subcategory" in _column_names(store.db, "transactions")
    assert "subcategory" in _column_names(store.db, "memory")
    row = store.db.execute("SELECT * FROM transactions WHERE id='id1'").fetchone()
    assert row["subcategory"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: subcategory`

- [ ] **Step 3: Update SCHEMA and add the migration**

In `packages/classify/munim/store.py`, change the `transactions` table
definition (end of the column list) from:

```python
    is_transfer INTEGER DEFAULT 0,
    is_recurring INTEGER DEFAULT 0
);
```

to:

```python
    is_transfer INTEGER DEFAULT 0,
    is_recurring INTEGER DEFAULT 0,
    subcategory TEXT DEFAULT ''
);
```

And the `memory` table definition from:

```python
CREATE TABLE IF NOT EXISTS memory (
    pattern TEXT NOT NULL,          -- normalized merchant string or payee handle
    kind TEXT NOT NULL,             -- 'merchant' | 'payee'
    category TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (pattern, kind)
);
```

to:

```python
CREATE TABLE IF NOT EXISTS memory (
    pattern TEXT NOT NULL,          -- normalized merchant string or payee handle
    kind TEXT NOT NULL,             -- 'merchant' | 'payee'
    category TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    subcategory TEXT DEFAULT '',
    PRIMARY KEY (pattern, kind)
);
```

Then change `Store.__init__` from:

```python
        self.db = sqlite3.connect(self.home / "munim.db",
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
```

to:

```python
        self.db = sqlite3.connect(self.home / "munim.db",
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
```

And add a new method right after `__init__`:

```python
    def _migrate(self) -> None:
        """One-time column additions for databases created before a given
        column existed. SQLite has no ADD COLUMN IF NOT EXISTS, so each
        addition needs its own existence check. New columns always land
        at the physical end of the table, same as a fresh CREATE TABLE
        with the column listed last — keeps positional INSERTs valid
        either way."""
        def has_column(table: str, col: str) -> bool:
            return any(r["name"] == col for r in
                       self.db.execute(f"PRAGMA table_info({table})").fetchall())

        if not has_column("transactions", "subcategory"):
            self.db.execute(
                "ALTER TABLE transactions ADD COLUMN subcategory TEXT DEFAULT ''")
        if not has_column("memory", "subcategory"):
            self.db.execute(
                "ALTER TABLE memory ADD COLUMN subcategory TEXT DEFAULT ''")
        self.db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full existing suite to check nothing regressed**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing (36+ before this plan, growing as this plan adds more)

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_subcategories.py
git commit -m "Migrate transactions/memory tables to carry a subcategory column"
```

---

### Task 3: Thread `subcategory` through Store's transaction read/write paths

**Files:**
- Modify: `packages/classify/munim/store.py:88-134` (`upsert_transactions`, `update_transaction`, `_row_to_txn`)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `Transaction.subcategory` (Task 1), migrated schema (Task 2).
- Produces: a `Transaction` round-tripped through the store keeps its
  `subcategory`.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_upsert_and_reload_preserves_subcategory(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP",
                     category="Groceries", subcategory="Alcohol")
    store.upsert_transactions([t])
    reloaded = store.get_transaction(t.id)
    assert reloaded.subcategory == "Alcohol"


def test_update_transaction_writes_subcategory(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP", category="Groceries")
    store.upsert_transactions([t])
    t.subcategory = "Alcohol"
    store.update_transaction(t)
    reloaded = store.get_transaction(t.id)
    assert reloaded.subcategory == "Alcohol"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `sqlite3.ProgrammingError` (16 values for 17 columns) on
the first test, and `subcategory` staying `""` on the second (the
UPDATE never sets it).

- [ ] **Step 3: Update the three methods**

In `packages/classify/munim/store.py`, change `upsert_transactions`'s
INSERT from:

```python
                self.db.execute(
                    "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.id, t.date.isoformat(), t.amount, t.currency,
                        t.direction.value, t.description_raw, t.account, t.balance,
                        t.merchant_norm, t.payee_handle, t.category, t.confidence,
                        t.stage.value, t.status.value,
                        int(t.is_transfer), int(t.is_recurring),
                    ),
                )
```

to (one more placeholder, `t.subcategory` appended last to match the
column order from Task 2):

```python
                self.db.execute(
                    "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.id, t.date.isoformat(), t.amount, t.currency,
                        t.direction.value, t.description_raw, t.account, t.balance,
                        t.merchant_norm, t.payee_handle, t.category, t.confidence,
                        t.stage.value, t.status.value,
                        int(t.is_transfer), int(t.is_recurring), t.subcategory,
                    ),
                )
```

Change `update_transaction` from:

```python
    def update_transaction(self, t: Transaction) -> None:
        self.db.execute(
            "UPDATE transactions SET merchant_norm=?, payee_handle=?, category=?, "
            "confidence=?, stage=?, status=?, is_transfer=?, is_recurring=? WHERE id=?",
            (
                t.merchant_norm, t.payee_handle, t.category, t.confidence,
                t.stage.value, t.status.value,
                int(t.is_transfer), int(t.is_recurring), t.id,
            ),
        )
        self.db.commit()
```

to:

```python
    def update_transaction(self, t: Transaction) -> None:
        self.db.execute(
            "UPDATE transactions SET merchant_norm=?, payee_handle=?, category=?, "
            "subcategory=?, confidence=?, stage=?, status=?, is_transfer=?, "
            "is_recurring=? WHERE id=?",
            (
                t.merchant_norm, t.payee_handle, t.category, t.subcategory,
                t.confidence, t.stage.value, t.status.value,
                int(t.is_transfer), int(t.is_recurring), t.id,
            ),
        )
        self.db.commit()
```

Change `_row_to_txn` from:

```python
    def _row_to_txn(self, r: sqlite3.Row) -> Transaction:
        return Transaction(
            id=r["id"], date=r["date"], amount=r["amount"], currency=r["currency"],
            direction=r["direction"], description_raw=r["description_raw"],
            account=r["account"], balance=r["balance"],
            merchant_norm=r["merchant_norm"], payee_handle=r["payee_handle"],
            category=r["category"], confidence=r["confidence"],
            stage=Stage(r["stage"]), status=Status(r["status"]),
            is_transfer=bool(r["is_transfer"]), is_recurring=bool(r["is_recurring"]),
        )
```

to:

```python
    def _row_to_txn(self, r: sqlite3.Row) -> Transaction:
        return Transaction(
            id=r["id"], date=r["date"], amount=r["amount"], currency=r["currency"],
            direction=r["direction"], description_raw=r["description_raw"],
            account=r["account"], balance=r["balance"],
            merchant_norm=r["merchant_norm"], payee_handle=r["payee_handle"],
            category=r["category"], subcategory=r["subcategory"],
            confidence=r["confidence"],
            stage=Stage(r["stage"]), status=Status(r["status"]),
            is_transfer=bool(r["is_transfer"]), is_recurring=bool(r["is_recurring"]),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — this touches shared code paths every existing
test exercises, so this is the step most likely to catch a mistake.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_subcategories.py
git commit -m "Thread subcategory through Store's transaction read/write paths"
```

---

### Task 4: Extend `remember()` and `propagate()` to carry a subcategory

**Files:**
- Modify: `packages/classify/munim/store.py:158-191`
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: migrated `memory.subcategory` column (Task 2).
- Produces: `Store.remember(pattern, category, kind="merchant", subcategory="")`,
  `Store.propagate(pattern, category, kind="merchant", exclude_id="", subcategory="") -> int`.
  Both keep working exactly as before when `subcategory` is omitted.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_remember_stores_subcategory(tmp_path):
    store = Store(home=tmp_path)
    store.remember("SHETTY BEER SHOP", "Groceries", subcategory="Alcohol")
    row = store.db.execute(
        "SELECT category, subcategory FROM memory WHERE pattern=?",
        ("SHETTY BEER SHOP",)).fetchone()
    assert row["category"] == "Groceries"
    assert row["subcategory"] == "Alcohol"


def test_remember_without_subcategory_leaves_it_blank(tmp_path):
    store = Store(home=tmp_path)
    store.remember("SWIGGY", "Dining")
    row = store.db.execute(
        "SELECT subcategory FROM memory WHERE pattern=?", ("SWIGGY",)).fetchone()
    assert row["subcategory"] == ""


def test_propagate_carries_subcategory_to_unconfirmed_rows(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP")
    store.upsert_transactions([t])
    n = store.propagate("SHETTY BEER SHOP", "Groceries", "merchant",
                        subcategory="Alcohol")
    assert n == 1
    reloaded = store.get_transaction(t.id)
    assert reloaded.category == "Groceries"
    assert reloaded.subcategory == "Alcohol"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `remember()`/`propagate()` raise `TypeError: unexpected
keyword argument 'subcategory'`.

- [ ] **Step 3: Update both methods**

Change `remember` from:

```python
    def remember(self, pattern: str, category: str, kind: str = "merchant") -> None:
        if not pattern:
            return
        self.db.execute(
            "INSERT INTO memory(pattern,kind,category) VALUES(?,?,?) "
            "ON CONFLICT(pattern,kind) DO UPDATE SET category=excluded.category",
            (pattern.upper().strip(), kind, category),
        )
        self.db.commit()
```

to:

```python
    def remember(self, pattern: str, category: str, kind: str = "merchant",
                 subcategory: str = "") -> None:
        if not pattern:
            return
        self.db.execute(
            "INSERT INTO memory(pattern,kind,category,subcategory) VALUES(?,?,?,?) "
            "ON CONFLICT(pattern,kind) DO UPDATE SET category=excluded.category, "
            "subcategory=excluded.subcategory",
            (pattern.upper().strip(), kind, category, subcategory),
        )
        self.db.commit()
```

Change `propagate` from:

```python
    def propagate(self, pattern: str, category: str, kind: str = "merchant",
                  exclude_id: str = "") -> int:
        """Apply a just-confirmed rule to every other unconfirmed transaction
        with the identical merchant/payee string. This is what makes bulk
        backfill sane: confirm SWIGGY once, all 40 occurrences resolve.
        Exact string matches only — fuzzy variants stay in the queue for
        `munim reclassify` so the user still sees anything ambiguous.
        """
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        # is_transfer must track the category, not just the structural
        # auto-detector's own pass: a transaction the auto-detector
        # couldn't pair (e.g. a credit-card bill payment where only the
        # card's own statement is imported) still needs is_transfer=True
        # once the user confirms "Transfers" here — reports/dashboard
        # check is_transfer, not the category string.
        is_transfer = 1 if category == "Transfers" else 0
        cur = self.db.execute(
            f"UPDATE transactions SET category=?, status='confirmed', "
            f"stage='memory_exact', confidence=1.0, is_transfer=? "
            f"WHERE {col}=? AND status != 'confirmed' AND id != ?",
            (category, is_transfer, pattern, exclude_id),
        )
        self.db.commit()
        return cur.rowcount
```

to:

```python
    def propagate(self, pattern: str, category: str, kind: str = "merchant",
                  exclude_id: str = "", subcategory: str = "") -> int:
        """Apply a just-confirmed rule to every other unconfirmed transaction
        with the identical merchant/payee string. This is what makes bulk
        backfill sane: confirm SWIGGY once, all 40 occurrences resolve.
        Exact string matches only — fuzzy variants stay in the queue for
        `munim reclassify` so the user still sees anything ambiguous.
        """
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        # is_transfer must track the category, not just the structural
        # auto-detector's own pass: a transaction the auto-detector
        # couldn't pair (e.g. a credit-card bill payment where only the
        # card's own statement is imported) still needs is_transfer=True
        # once the user confirms "Transfers" here — reports/dashboard
        # check is_transfer, not the category string.
        is_transfer = 1 if category == "Transfers" else 0
        cur = self.db.execute(
            f"UPDATE transactions SET category=?, subcategory=?, status='confirmed', "
            f"stage='memory_exact', confidence=1.0, is_transfer=? "
            f"WHERE {col}=? AND status != 'confirmed' AND id != ?",
            (category, subcategory, is_transfer, pattern, exclude_id),
        )
        self.db.commit()
        return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — every existing caller of `remember`/`propagate`
omits `subcategory`, which defaults to `""` and preserves old behavior
exactly.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_subcategories.py
git commit -m "Let remember()/propagate() carry an optional subcategory"
```

---

### Task 5: Add `memory_subcategories()` and `apply_subcategory()`

**Files:**
- Modify: `packages/classify/munim/store.py` (add two new methods near `memory_rules`, around line 193-197)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: migrated schema (Task 2).
- Produces:
  - `Store.memory_subcategories(kind: str = "merchant") -> dict[str, str]`
    — pattern → subcategory, only for patterns that have one set. Used
    by the pipeline (Task 7).
  - `Store.apply_subcategory(pattern: str, subcategory: str, kind: str = "merchant") -> int`
    — backfills `subcategory` onto every matching transaction
    (confirmed or not), touching no other column. Returns the count
    updated. Used by the CLI (Task 8) and the web endpoint (Task 10).

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_memory_subcategories_returns_only_patterns_with_one_set(tmp_path):
    store = Store(home=tmp_path)
    store.remember("SHETTY BEER SHOP", "Groceries", subcategory="Alcohol")
    store.remember("SWIGGY", "Dining")  # no subcategory
    assert store.memory_subcategories("merchant") == {"SHETTY BEER SHOP": "Alcohol"}


def test_apply_subcategory_updates_confirmed_rows_without_touching_category(tmp_path):
    """The whole point: refining subcategory must reach already-reviewed
    history, which propagate() deliberately excludes for category
    changes. apply_subcategory() is a different, narrower operation."""
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP", category="Groceries",
                     status="confirmed")
    store.upsert_transactions([t])
    n = store.apply_subcategory("SHETTY BEER SHOP", "Alcohol", "merchant")
    assert n == 1
    reloaded = store.get_transaction(t.id)
    assert reloaded.subcategory == "Alcohol"
    assert reloaded.category == "Groceries"       # untouched
    assert reloaded.status.value == "confirmed"   # untouched


def test_apply_subcategory_matches_on_payee_handle_for_payee_kind(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                     description_raw="RAMESH KUMAR", category="Family & Friends")
    t.merchant_norm, t.payee_handle = "", "RAMESH KUMAR"
    store.upsert_transactions([t])
    n = store.apply_subcategory("RAMESH KUMAR", "Loan Repayment", "payee")
    assert n == 1
    assert store.get_transaction(t.id).subcategory == "Loan Repayment"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute
'memory_subcategories'` (and same for `apply_subcategory`).

- [ ] **Step 3: Add both methods**

In `packages/classify/munim/store.py`, right after `memory_rules`
(after the closing of the method that currently ends at line 197),
add:

```python
    def memory_subcategories(self, kind: str = "merchant") -> dict[str, str]:
        """pattern -> subcategory, for patterns that have one set. The
        pipeline uses this to attach a subcategory when a memory rule
        resolves a transaction — never for dictionary or purpose-tail
        matches, which never carry one."""
        rows = self.db.execute(
            "SELECT pattern, subcategory FROM memory "
            "WHERE kind=? AND subcategory != ''", (kind,)
        ).fetchall()
        return {r["pattern"]: r["subcategory"] for r in rows}

    def apply_subcategory(self, pattern: str, subcategory: str,
                          kind: str = "merchant") -> int:
        """Backfill a subcategory onto every transaction matching pattern,
        confirmed or not. Unlike propagate(), this never touches
        category, status, stage, or confidence — subcategorizing is a
        refinement on top of an already-settled category decision, not a
        re-opening of it, so already-confirmed history is fair game."""
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        cur = self.db.execute(
            f"UPDATE transactions SET subcategory=? WHERE {col}=?",
            (subcategory, pattern),
        )
        self.db.commit()
        return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_subcategories.py
git commit -m "Add memory_subcategories() and apply_subcategory() to Store"
```

---

### Task 6: Add the per-parent subcategory cap to `tree.py`

**Files:**
- Modify: `packages/classify/munim/tree.py:20` (near `MAX_LEAVES`)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Produces: `tree.MAX_SUBCATEGORIES_PER_PARENT: int` constant, used by
  the CLI in Task 8.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_max_subcategories_per_parent_constant_exists():
    from munim.tree import MAX_SUBCATEGORIES_PER_PARENT
    assert MAX_SUBCATEGORIES_PER_PARENT == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_SUBCATEGORIES_PER_PARENT'`

- [ ] **Step 3: Add the constant**

In `packages/classify/munim/tree.py`, change:

```python
MAX_LEAVES = 20   # labeling consistency collapses beyond this; hard limit
```

to:

```python
MAX_LEAVES = 20   # labeling consistency collapses beyond this; hard limit

# Subcategories only ever show up once you've already committed to a
# parent head, so they get their own smaller, per-parent budget instead
# of competing for the scarce top-level MAX_LEAVES slots.
MAX_SUBCATEGORIES_PER_PARENT = 10
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/tree.py packages/classify/tests/test_subcategories.py
git commit -m "Add MAX_SUBCATEGORIES_PER_PARENT cap to tree.py"
```

---

### Task 7: Wire subcategory lookup into the pipeline

**Files:**
- Modify: `packages/classify/munim/pipeline.py:49-140` (`Pipeline.__init__`, `run`, `_assign`)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `Store.memory_subcategories()` (Task 5).
- Produces: `Pipeline._assign(t, category, stage, conf, subcategory="")`
  — every existing call site keeps working unchanged; three call sites
  (payee-handle exact match, merchant memory/dictionary match, and the
  looks-like-person payee match) now pass a real subcategory when one
  exists. `_try_purpose` and the fallback classifier never set one.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
from munim.store import Store
from munim.pipeline import Pipeline
from munim.schema import Stage


def test_pipeline_attaches_subcategory_from_memory_exact_match(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.remember("SHETTY BEER SHOP", "Groceries", subcategory="Alcohol")
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP")
    Pipeline(store).run([t])
    assert t.category == "Groceries"
    assert t.subcategory == "Alcohol"
    assert t.stage == Stage.MEMORY_EXACT


def test_pipeline_attaches_subcategory_for_payee_kind_match(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.remember("RAMESH KUMAR", "Family & Friends", kind="payee",
                   subcategory="Loan Repayment")
    t = Transaction(date="2026-06-01", amount=5000, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-513324498817")
    Pipeline(store).run([t])
    assert t.category == "Family & Friends"
    assert t.subcategory == "Loan Repayment"


def test_pipeline_leaves_subcategory_blank_without_a_memory_rule(tmp_path):
    """Dictionary and fallback matches never carry a subcategory —
    scoped to memory rules only, since community knowledge and ML
    guesses aren't precise enough for this level of detail."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-01", amount=340, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY8102@okaxis-513324498812")
    Pipeline(store).run([t])
    assert t.category == "Dining"   # community dictionary hit
    assert t.subcategory == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `t.subcategory` stays `""` on the first two tests (the
pipeline never sets it yet); the third test already passes.

- [ ] **Step 3: Update `Pipeline`**

In `packages/classify/munim/pipeline.py`, change `__init__` from:

```python
        self.payee_rules = store.memory_rules("payee")
        self.purpose_matcher = PurposeMatcher(
            threshold=store.get_config("fuzzy_threshold", 90))
```

to:

```python
        self.payee_rules = store.memory_rules("payee")
        self.subcat_rules = store.memory_subcategories("merchant")
        self.payee_subcat_rules = store.memory_subcategories("payee")
        self.purpose_matcher = PurposeMatcher(
            threshold=store.get_config("fuzzy_threshold", 90))
```

Change the P2P branch in `run` from:

```python
            # P2P: only payee memory can resolve a payment to a person
            if t.payee_handle:
                if t.payee_handle in self.payee_rules:
                    self._assign(t, self.payee_rules[t.payee_handle],
                                 Stage.MEMORY_EXACT, 1.0)
                    stats.bump(Stage.MEMORY_EXACT)
```

to:

```python
            # P2P: only payee memory can resolve a payment to a person
            if t.payee_handle:
                if t.payee_handle in self.payee_rules:
                    self._assign(t, self.payee_rules[t.payee_handle],
                                 Stage.MEMORY_EXACT, 1.0,
                                 subcategory=self.payee_subcat_rules.get(
                                     t.payee_handle, ""))
                    stats.bump(Stage.MEMORY_EXACT)
```

Change the merchant memory/dictionary branch from:

```python
            # Stage 4: memory then dictionary
            match = self.matcher.match(t.merchant_norm)
            if match:
                stage = (Stage.MEMORY_EXACT if match.score == 100 and
                         match.source == "memory"
                         else Stage.MEMORY_FUZZY if match.source == "memory"
                         else Stage.DICTIONARY)
                self._assign(t, match.category, stage, match.score / 100)
                stats.bump(stage)
                continue
```

to:

```python
            # Stage 4: memory then dictionary
            match = self.matcher.match(t.merchant_norm)
            if match:
                stage = (Stage.MEMORY_EXACT if match.score == 100 and
                         match.source == "memory"
                         else Stage.MEMORY_FUZZY if match.source == "memory"
                         else Stage.DICTIONARY)
                subcat = (self.subcat_rules.get(match.matched_pattern, "")
                         if match.source == "memory" else "")
                self._assign(t, match.category, stage, match.score / 100,
                             subcategory=subcat)
                stats.bump(stage)
                continue
```

Change the looks-like-person branch from:

```python
            if self._looks_like_person(t.merchant_norm):
                if t.merchant_norm in self.payee_rules:
                    self._assign(t, self.payee_rules[t.merchant_norm],
                                 Stage.MEMORY_EXACT, 1.0)
                    stats.bump(Stage.MEMORY_EXACT)
```

to:

```python
            if self._looks_like_person(t.merchant_norm):
                if t.merchant_norm in self.payee_rules:
                    self._assign(t, self.payee_rules[t.merchant_norm],
                                 Stage.MEMORY_EXACT, 1.0,
                                 subcategory=self.payee_subcat_rules.get(
                                     t.merchant_norm, ""))
                    stats.bump(Stage.MEMORY_EXACT)
```

Finally, change `_assign` from:

```python
    def _assign(self, t: Transaction, category: str, stage: Stage,
                conf: float) -> None:
        t.category = self.aliases.get(category, category)
        t.stage = stage
        t.confidence = round(conf, 3)
        # A user-memory exact hit is as good as confirmed — the user taught it.
        t.status = (Status.CONFIRMED if stage == Stage.MEMORY_EXACT
                    else Status.PROVISIONAL)
```

to:

```python
    def _assign(self, t: Transaction, category: str, stage: Stage,
                conf: float, subcategory: str = "") -> None:
        t.category = self.aliases.get(category, category)
        t.subcategory = subcategory
        t.stage = stage
        t.confidence = round(conf, 3)
        # A user-memory exact hit is as good as confirmed — the user taught it.
        t.status = (Status.CONFIRMED if stage == Stage.MEMORY_EXACT
                    else Status.PROVISIONAL)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (16 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — every existing `_assign` call site omits
`subcategory`, defaulting to `""`.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/pipeline.py packages/classify/tests/test_subcategories.py
git commit -m "Attach memory-rule subcategories during pipeline classification"
```

---

### Task 8: `munim learn --subcategory` and `munim reclassify` reset

**Files:**
- Modify: `packages/classify/munim/cli.py:443-465` (`learn`)
- Modify: `packages/classify/munim/cli.py:218-242` (`reclassify`)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `Store.remember`/`propagate`/`apply_subcategory` (Tasks 4-5),
  `store.get_config("subcategories", {})` (a config key first written in
  Task 9, but read defensively here with `or {}` so this task doesn't
  depend on Task 9 landing first).
- Produces: `munim learn <pattern> <category> --subcategory <sub>` CLI
  behavior; `munim reclassify` resets `subcategory` alongside `category`
  on unconfirmed rows.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
from typer.testing import CliRunner
from munim.cli import app

runner = CliRunner()


def test_learn_with_subcategory_flag(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    result = runner.invoke(app, ["learn", "SHETTY BEER SHOP", "Groceries",
                                 "--subcategory", "Alcohol"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    row = fresh.db.execute(
        "SELECT subcategory FROM memory WHERE pattern=?",
        ("SHETTY BEER SHOP",)).fetchone()
    assert row["subcategory"] == "Alcohol"


def test_learn_rejects_subcategory_not_defined_under_category(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    result = runner.invoke(app, ["learn", "SOME SHOP", "Groceries",
                                 "--subcategory", "NotARealSubcat"])
    assert result.exit_code != 0


def test_learn_subcategory_backfills_confirmed_transactions(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    status="confirmed")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["learn", "SHETTY BEER SHOP", "Groceries",
                                 "--subcategory", "Alcohol"])
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.subcategory == "Alcohol"
    assert reloaded.status.value == "confirmed"


def test_reclassify_resets_subcategory_on_unconfirmed_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Groceries"])
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    subcategory="StaleGuess")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["reclassify"])
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.subcategory == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `learn` doesn't accept `--subcategory` yet (Typer
usage error), and the reclassify test fails because `subcategory` stays
`"StaleGuess"`.

- [ ] **Step 3: Update `learn`**

Change:

```python
@app.command()
def learn(pattern: str, category: str,
          payee: bool = typer.Option(False, "--payee",
                                     help="Pattern is a person, not a merchant"),
          propagate: bool = typer.Option(True,
                                         help="Apply to stored unconfirmed txns")):
    """Write one confirmed rule to memory — the feedback channel for host
    apps. When a user confirms a category in YOUR review UI, call this so
    the engine learns. Pure memory write; no transaction required to exist.
    """
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if category not in cats:
        console.print(f"[red]{category} is not in the taxonomy "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    kind = "payee" if payee else "merchant"
    pattern = pattern.upper().strip()
    store.remember(pattern, category, kind=kind)
    n = store.propagate(pattern, category, kind) if propagate else 0
    console.print(f"[green]Learned: {pattern} → {category}[/green]"
                  + (f" ({n} stored transactions updated)" if n else ""))
```

to:

```python
@app.command()
def learn(pattern: str, category: str,
          payee: bool = typer.Option(False, "--payee",
                                     help="Pattern is a person, not a merchant"),
          subcategory: str = typer.Option(
              "", "--subcategory",
              help="Optional finer-grained head under category, e.g. Alcohol under Groceries"),
          propagate: bool = typer.Option(True,
                                         help="Apply to stored unconfirmed txns")):
    """Write one confirmed rule to memory — the feedback channel for host
    apps. When a user confirms a category in YOUR review UI, call this so
    the engine learns. Pure memory write; no transaction required to exist.
    """
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if category not in cats:
        console.print(f"[red]{category} is not in the taxonomy "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    if subcategory:
        subcats = store.get_config("subcategories", {}) or {}
        if subcategory not in subcats.get(category, []):
            console.print(
                f"[red]{subcategory} is not a subcategory of {category} "
                f"(munim categories subcategories list {category}).[/red]")
            raise typer.Exit(1)
    kind = "payee" if payee else "merchant"
    pattern = pattern.upper().strip()
    store.remember(pattern, category, kind=kind, subcategory=subcategory)
    n = store.propagate(pattern, category, kind, subcategory=subcategory) \
        if propagate else 0
    console.print(f"[green]Learned: {pattern} → {category}"
                  + (f" / {subcategory}" if subcategory else "") + "[/green]"
                  + (f" ({n} stored transactions updated)" if n else ""))
    if subcategory:
        n_sub = store.apply_subcategory(pattern, subcategory, kind)
        console.print(f"[dim]Subcategory applied to {n_sub} matching "
                      "transactions (including already-confirmed ones).[/dim]")
```

- [ ] **Step 4: Update `reclassify`**

Change:

```python
    # reset provisional state so stale suggestions don't stick
    for t in txns:
        if not t.is_transfer:
            t.category, t.confidence, t.stage = "", 0.0, Stage.NONE
            t.status = Status.UNRESOLVED
```

to:

```python
    # reset provisional state so stale suggestions don't stick
    for t in txns:
        if not t.is_transfer:
            t.category, t.confidence, t.stage = "", 0.0, Stage.NONE
            t.subcategory = ""
            t.status = Status.UNRESOLVED
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (20 passed)

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_subcategories.py
git commit -m "Add munim learn --subcategory and reset it on reclassify"
```

---

### Task 9: `munim categories subcategories add/list`

**Files:**
- Modify: `packages/classify/munim/cli.py` (add after `categories_map`, currently ending at line 619, before the `# accounts` section comment at line 622)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `tree.MAX_SUBCATEGORIES_PER_PARENT` (Task 6).
- Produces: `munim categories subcategories add <parent> <name> [--force]`,
  `munim categories subcategories list [parent]`. Writes/reads
  `config["subcategories"]: dict[str, list[str]]`.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_subcategories_add_creates_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    result = runner.invoke(app, ["categories", "subcategories", "add",
                                 "Groceries", "Alcohol"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.get_config("subcategories", {}) == {"Groceries": ["Alcohol"]}


def test_subcategories_add_rejects_unknown_parent(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    result = runner.invoke(app, ["categories", "subcategories", "add",
                                 "NotACategory", "Alcohol"])
    assert result.exit_code != 0


def test_subcategories_add_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    result = runner.invoke(app, ["categories", "subcategories", "add",
                                 "Groceries", "Alcohol"])
    assert result.exit_code != 0


def test_subcategories_add_enforces_per_parent_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": [f"Sub{i}" for i in range(10)]})
    result = runner.invoke(app, ["categories", "subcategories", "add",
                                 "Groceries", "OneTooMany"])
    assert result.exit_code != 0
    result_forced = runner.invoke(app, ["categories", "subcategories", "add",
                                        "Groceries", "OneTooMany", "--force"])
    assert result_forced.exit_code == 0, result_forced.output


def test_subcategories_list_shows_usage_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    subcategory="Alcohol")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["categories", "subcategories", "list"])
    assert result.exit_code == 0
    assert "Alcohol" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `No such command 'subcategories'`.

- [ ] **Step 3: Add the commands**

In `packages/classify/munim/cli.py`, right after `categories_map`
(ends at line 619, right before the `# accounts` section comment),
insert:

```python
subcat_app = typer.Typer(help="Manage subcategories under a category head.",
                         no_args_is_help=True)
cat_app.add_typer(subcat_app, name="subcategories")


@subcat_app.command("add")
def subcategories_add(parent: str, name: str,
                      force: bool = typer.Option(False, "--force")):
    """Add a subcategory under an existing category, e.g.:
    munim categories subcategories add Groceries Alcohol"""
    from .tree import MAX_SUBCATEGORIES_PER_PARENT
    store = _store()
    cats = store.get_config("categories", DEFAULT_CATEGORIES)
    if parent not in cats:
        console.print(f"[red]{parent} is not a category "
                      f"(munim categories list).[/red]")
        raise typer.Exit(1)
    subcats = store.get_config("subcategories", {}) or {}
    existing = subcats.get(parent, [])
    if name in existing:
        console.print(f"[yellow]{parent}:{name} already exists.[/yellow]")
        raise typer.Exit(1)
    if len(existing) >= MAX_SUBCATEGORIES_PER_PARENT and not force:
        console.print(
            f"[red]{parent} already has {len(existing)} subcategories — "
            f"the limit is {MAX_SUBCATEGORIES_PER_PARENT} per head.[/red] "
            "--force if you accept the tradeoff.")
        raise typer.Exit(1)
    subcats[parent] = existing + [name]
    store.set_config("subcategories", subcats)
    console.print(f"[green]Added {parent}:{name}.[/green] Teach it with: "
                  f"munim learn <pattern> {parent} --subcategory {name}")


@subcat_app.command("list")
def subcategories_list(
    parent: str = typer.Argument(None, help="Show one head's subcategories only"),
):
    """Show subcategories and how much each has been used."""
    store = _store()
    subcats = store.get_config("subcategories", {}) or {}
    usage = {(r["category"], r["subcategory"]): r["n"] for r in store.db.execute(
        "SELECT category, subcategory, COUNT(*) AS n FROM transactions "
        "WHERE subcategory != '' GROUP BY category, subcategory")}
    items = subcats.items() if not parent else [(parent, subcats.get(parent, []))]
    if not any(names for _, names in items):
        console.print("[dim]No subcategories yet — "
                      "munim categories subcategories add <head> <name>[/dim]")
        return
    table = Table(title="Subcategories")
    table.add_column("Head")
    table.add_column("Subcategory")
    table.add_column("Transactions", justify="right")
    for head, names in items:
        for name in names:
            table.add_row(head, name, str(usage.get((head, name), 0)))
    console.print(table)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (25 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_subcategories.py
git commit -m "Add munim categories subcategories add/list commands"
```

---

### Task 10: Web backend — categories/rules payloads and a subcategory endpoint

**Files:**
- Modify: `packages/classify/munim/web/server.py:59-71` (`do_GET` routing)
- Modify: `packages/classify/munim/web/server.py:231-275` (`_categories`, `_rules`)
- Modify: `packages/classify/munim/web/server.py:74-118` (`do_POST` routing)
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `store.get_config("subcategories", {})` (Task 9),
  `Store.remember`/`apply_subcategory` (Tasks 4-5).
- Produces: `GET /api/categories` response gains a `"subcategories"` key
  (same shape as the config: `{parent: [names]}`). `GET /api/rules`
  response's `learned` rows gain a `"subcategory"` field. New
  `POST /api/rule/subcategory` (body `{pattern, kind, subcategory}`)
  sets a rule's subcategory (keeping its existing category) and
  backfills every matching transaction.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
import json
import threading
import urllib.request
from http.server import HTTPServer
from munim.web.server import Handler


def _server(store):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_api_categories_includes_subcategories_config(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/categories", timeout=3).read())
        assert d["subcategories"] == {"Groceries": ["Alcohol"]}
    finally:
        srv.shutdown()


def test_api_rules_includes_subcategory_field(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.remember("SHETTY BEER SHOP", "Groceries", subcategory="Alcohol")
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/rules", timeout=3).read())
        row = next(r for r in d["learned"] if r["pattern"] == "SHETTY BEER SHOP")
        assert row["subcategory"] == "Alcohol"
    finally:
        srv.shutdown()


def test_post_rule_subcategory_updates_rule_and_backfills(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("categories", ["Groceries"])
    store.set_config("subcategories", {"Groceries": ["Alcohol"]})
    store.remember("SHETTY BEER SHOP", "Groceries")
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    status="confirmed")
    store.upsert_transactions([t])
    srv, port = _server(store)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rule/subcategory", method="POST",
            data=json.dumps({"pattern": "SHETTY BEER SHOP", "kind": "merchant",
                             "subcategory": "Alcohol"}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert res["ok"] is True
        assert res["updated"] == 1
        reloaded = store.get_transaction(t.id)
        assert reloaded.subcategory == "Alcohol"
        assert reloaded.category == "Groceries"
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — `subcategories` key missing from `/api/categories`,
`subcategory` missing from `/api/rules` rows, and `/api/rule/subcategory`
returns 404.

- [ ] **Step 3: Update `_categories`**

Change:

```python
    def _categories(self):
        cats = self.store.get_config("categories", [])
        usage: dict[str, dict] = defaultdict(lambda: {"n": 0, "total": 0.0})
        for t in self.store.all_transactions():
            if t.category and t.direction.value == "debit" and not t.is_transfer:
                usage[t.category]["n"] += 1
                usage[t.category]["total"] += t.amount
        from ..tree import get_tree, resolve
        tree = get_tree(self.store)
        return {"categories": cats,
                "paths": {c: resolve(tree, c) for c in cats},
                "usage": {c: usage.get(c, {"n": 0, "total": 0.0})
                          for c in set(cats) | set(usage)}}
```

to:

```python
    def _categories(self):
        cats = self.store.get_config("categories", [])
        usage: dict[str, dict] = defaultdict(lambda: {"n": 0, "total": 0.0})
        for t in self.store.all_transactions():
            if t.category and t.direction.value == "debit" and not t.is_transfer:
                usage[t.category]["n"] += 1
                usage[t.category]["total"] += t.amount
        from ..tree import get_tree, resolve
        tree = get_tree(self.store)
        return {"categories": cats,
                "paths": {c: resolve(tree, c) for c in cats},
                "usage": {c: usage.get(c, {"n": 0, "total": 0.0})
                          for c in set(cats) | set(usage)},
                "subcategories": self.store.get_config("subcategories", {}) or {}}
```

Change `_rules` — the `SELECT` and the `learned` list comprehension —
from:

```python
    def _rules(self):
        learned = self.store.db.execute(
            "SELECT pattern, kind, category, created_at FROM memory "
            "ORDER BY created_at DESC").fetchall()
```

to:

```python
    def _rules(self):
        learned = self.store.db.execute(
            "SELECT pattern, kind, category, subcategory, created_at FROM memory "
            "ORDER BY created_at DESC").fetchall()
```

(The rest of `_rules` already does `{**dict(r), "broad": ...}`, so
`subcategory` flows through automatically once it's in the `SELECT` —
no further change needed there.)

- [ ] **Step 4: Add the routing and handler**

In `do_GET`, no change needed (this is a POST endpoint). In `do_POST`,
change:

```python
    def do_POST(self):
        if urlparse(self.path).path != "/api/confirm":
            self._send({"error": "not found"}, status=404)
            return
```

to:

```python
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/rule/subcategory":
            self._handle_rule_subcategory()
            return
        if path != "/api/confirm":
            self._send({"error": "not found"}, status=404)
            return
```

Then add a new method, right after `_confirm_one` (which currently ends
at line 151, right before `# ---- data assembly` at line 153):

```python
    def _handle_rule_subcategory(self):
        """Set a rule's subcategory (keeping its existing category) and
        backfill every currently-matching transaction, confirmed or not
        — the deliberate 'refine my history' action from the Rules page,
        never triggered automatically from review/confirm."""
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        pattern = (data.get("pattern") or "").upper().strip()
        kind = data.get("kind") or "merchant"
        subcategory = data.get("subcategory") or ""
        row = self.store.db.execute(
            "SELECT category FROM memory WHERE pattern=? AND kind=?",
            (pattern, kind)).fetchone()
        if row is None:
            self._send({"error": "unknown rule"}, status=404)
            return
        self.store.remember(pattern, row["category"], kind=kind,
                            subcategory=subcategory)
        n = self.store.apply_subcategory(pattern, subcategory, kind)
        self._send({"ok": True, "updated": n})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (28 passed)

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/web/server.py packages/classify/tests/test_subcategories.py
git commit -m "Expose subcategories through the web API"
```

---

### Task 11: Web frontend — rules page and transactions page

**Files:**
- Modify: `packages/classify/munim/web/index.html`
  - Rules page: `rules()` function (currently lines 370-385) and
    `patternCell` (lines 365-369)
  - Transactions page: `transactions()` function (currently lines
    319-339) and its filter controls (currently lines 155-163)
  - CSS: add a `.subcat` style near the existing `.tag` rules
    (currently lines 55-59)

**Interfaces:**
- Consumes: `/api/categories`'s new `subcategories` field,
  `/api/rules`'s new `subcategory` field on learned rows,
  `POST /api/rule/subcategory` (Task 10).
- Produces: no new automated test — this is manually verified in a
  browser, per this project's convention for UI-only changes.

- [ ] **Step 1: Add CSS for the subcategory label**

In `packages/classify/munim/web/index.html`, right after the existing
`.tag.broad` rule:

```css
.tag.broad{color:var(--ledger-red);border-color:var(--ledger-red);cursor:help}
```

add:

```css
.subcat{color:var(--ink-soft);font-size:12.5px}
.subcat select{font-size:12.5px;padding:2px 5px}
```

- [ ] **Step 2: Add the subcategory column to the Rules page**

Change `rules()` from:

```javascript
async function rules(){
  const d=await api("/api/rules");
  const learned=d.learned.length?`<table><thead><tr>
    <th>Pattern</th><th>Kind</th><th>Head</th><th>Learned</th>
  </tr></thead><tbody>`+d.learned.map(r=>`<tr>
    ${patternCell(r)}
    <td>${r.kind==="payee"?'<span class="tag person">person</span>':'<span class="tag">merchant</span>'}</td>
    <td>${esc(r.category)}</td><td class="num">${esc(r.created_at).slice(0,10)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">Nothing learned yet — confirm entries in Review.</p>`;
  $("#rulesBody").innerHTML=`<h2 style="font-size:16px">Learned (${d.learned.length})</h2>${learned}
  <h2 style="font-size:16px;margin-top:26px">Community dictionary (${d.dictionary.length})</h2>
  <table><thead><tr><th>Pattern</th><th>Head</th></tr></thead><tbody>`+
  d.dictionary.map(r=>`<tr>${patternCell(r)}<td>${esc(r.category)}</td></tr>`).join("")+
  `</tbody></table>`;
}
```

to (adding a Subcategory column that shows a picker only when the
row's category has subcategories defined, per SUBCATS which
`categories()` now populates in Task 3 of this step):

```javascript
let SUBCATS={};
function subcatCell(r){
  const opts=(SUBCATS[r.category]||[]);
  if(!opts.length)return `<td class="subcat">—</td>`;
  const current=r.subcategory||"";
  return `<td class="subcat"><select data-pattern="${esc(r.pattern)}" data-kind="${esc(r.kind)}">`
    +`<option value=""${current===""?" selected":""}>—</option>`
    +opts.map(o=>`<option value="${esc(o)}"${o===current?" selected":""}>${esc(o)}</option>`).join("")
    +`</select></td>`;
}
async function rules(){
  const d=await api("/api/rules");
  const learned=d.learned.length?`<table><thead><tr>
    <th>Pattern</th><th>Kind</th><th>Head</th><th>Subcategory</th><th>Learned</th>
  </tr></thead><tbody>`+d.learned.map(r=>`<tr>
    ${patternCell(r)}
    <td>${r.kind==="payee"?'<span class="tag person">person</span>':'<span class="tag">merchant</span>'}</td>
    <td>${esc(r.category)}</td>
    ${subcatCell(r)}
    <td class="num">${esc(r.created_at).slice(0,10)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">Nothing learned yet — confirm entries in Review.</p>`;
  $("#rulesBody").innerHTML=`<h2 style="font-size:16px">Learned (${d.learned.length})</h2>${learned}
  <h2 style="font-size:16px;margin-top:26px">Community dictionary (${d.dictionary.length})</h2>
  <table><thead><tr><th>Pattern</th><th>Head</th></tr></thead><tbody>`+
  d.dictionary.map(r=>`<tr>${patternCell(r)}<td>${esc(r.category)}</td></tr>`).join("")+
  `</tbody></table>`;
}
$("#rulesBody").addEventListener("change",async e=>{
  const sel=e.target.closest("select[data-pattern]");if(!sel)return;
  sel.disabled=true;
  try{
    await api("/api/rule/subcategory",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({pattern:sel.dataset.pattern,kind:sel.dataset.kind,
                           subcategory:sel.value})});
  }catch(err){
    alert("Couldn't update subcategory: "+err.message);
  }finally{
    sel.disabled=false;
  }
});
```

- [ ] **Step 3: Populate `SUBCATS` when categories load**

Change `categories()` from:

```javascript
async function categories(){
  const d=await api("/api/categories");CATS=d.categories;
```

to:

```javascript
async function categories(){
  const d=await api("/api/categories");CATS=d.categories;SUBCATS=d.subcategories||{};
```

- [ ] **Step 4: Add a subcategory filter to the Transactions page**

Change the transactions section's controls from:

```html
<section id="transactions">
  <h2>The ledger</h2>
  <div class="controls">
    <select id="fMonth"><option value="">All months</option></select>
    <select id="fCategory"><option value="">All heads</option><option value="__none__">No head</option></select>
    <input id="fSearch" placeholder="Search merchant, category, raw text" size="34">
  </div>
  <div id="txnBody"></div>
</section>
```

to:

```html
<section id="transactions">
  <h2>The ledger</h2>
  <div class="controls">
    <select id="fMonth"><option value="">All months</option></select>
    <select id="fCategory"><option value="">All heads</option><option value="__none__">No head</option></select>
    <select id="fSubcategory" hidden><option value="">All subcategories</option></select>
    <input id="fSearch" placeholder="Search merchant, category, raw text" size="34">
  </div>
  <div id="txnBody"></div>
</section>
```

Change the `transactions()` function from:

```javascript
async function transactions(){
  const month=$("#fMonth").value,q=$("#fSearch").value,category=$("#fCategory").value;
  const params=new URLSearchParams({month,q,category});
  const d=await api(`/api/transactions?${params}`);
  if($("#fMonth").options.length===1)
    d.months.forEach(m=>$("#fMonth").insertAdjacentHTML("beforeend",`<option>${m}</option>`));
  if($("#fCategory").options.length===2)
    d.categories.forEach(c=>$("#fCategory")
      .insertAdjacentHTML("beforeend",`<option value="${esc(c)}">${esc(c)}</option>`));
  $("#txnBody").innerHTML=d.rows.length?`<table><thead><tr>
    <th>Date</th><th>Entry</th><th class="num">Amount</th><th>Head</th><th>Provenance</th><th>Account</th>
  </tr></thead><tbody>`+d.rows.map(r=>`<tr>
    <td class="num">${r.date}</td>
    <td><div class="merchant">${esc(r.merchant)||"—"}${r.transfer?' <span class="tag">transfer</span>':""}${r.recurring?' <span class="tag">recurring</span>':""}</div><div class="raw">${esc(r.raw)}</div></td>
    ${amountCell(r)}
    <td>${esc(r.category)||'<span class="tag">—</span>'}</td>
    <td>${statusTag(r)}</td>
    <td class="merchant">${esc(r.account)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">No entries match.</p>`;
}
$("#fMonth")?.addEventListener("change",transactions);
$("#fCategory")?.addEventListener("change",transactions);
let deb;$("#fSearch")?.addEventListener("input",()=>{clearTimeout(deb);deb=setTimeout(transactions,250)});
```

to (subcategory filtering happens client-side against the already-
fetched rows, mirroring how the category dropdown's option list is
built once and reused — no new query param or server round-trip
needed since `/api/transactions` already returns each row's full
data):

```javascript
function refreshSubcategoryFilter(){
  const cat=$("#fCategory").value;
  const opts=(SUBCATS[cat]||[]);
  const sel=$("#fSubcategory");
  sel.hidden=opts.length===0;
  sel.innerHTML=`<option value="">All subcategories</option>`
    +opts.map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join("");
}
async function transactions(){
  const month=$("#fMonth").value,q=$("#fSearch").value,category=$("#fCategory").value,
        subcategory=$("#fSubcategory").value;
  refreshSubcategoryFilter();
  const params=new URLSearchParams({month,q,category});
  const d=await api(`/api/transactions?${params}`);
  if($("#fMonth").options.length===1)
    d.months.forEach(m=>$("#fMonth").insertAdjacentHTML("beforeend",`<option>${m}</option>`));
  if($("#fCategory").options.length===2)
    d.categories.forEach(c=>$("#fCategory")
      .insertAdjacentHTML("beforeend",`<option value="${esc(c)}">${esc(c)}</option>`));
  const rows=subcategory?d.rows.filter(r=>r.subcategory===subcategory):d.rows;
  $("#txnBody").innerHTML=rows.length?`<table><thead><tr>
    <th>Date</th><th>Entry</th><th class="num">Amount</th><th>Head</th><th>Provenance</th><th>Account</th>
  </tr></thead><tbody>`+rows.map(r=>`<tr>
    <td class="num">${r.date}</td>
    <td><div class="merchant">${esc(r.merchant)||"—"}${r.transfer?' <span class="tag">transfer</span>':""}${r.recurring?' <span class="tag">recurring</span>':""}</div><div class="raw">${esc(r.raw)}</div></td>
    ${amountCell(r)}
    <td>${esc(r.category)||'<span class="tag">—</span>'}${r.subcategory?` <span class="subcat">· ${esc(r.subcategory)}</span>`:""}</td>
    <td>${statusTag(r)}</td>
    <td class="merchant">${esc(r.account)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">No entries match.</p>`;
}
$("#fMonth")?.addEventListener("change",transactions);
$("#fCategory")?.addEventListener("change",transactions);
$("#fSubcategory")?.addEventListener("change",transactions);
let deb;$("#fSearch")?.addEventListener("input",()=>{clearTimeout(deb);deb=setTimeout(transactions,250)});
```

Note this step depends on the server's `_row()` (in `server.py`)
already including `subcategory` in each row — add that now too. Change
`_row` from:

```python
    @staticmethod
    def _row(t):
        return {
            "id": t.id, "date": t.date.isoformat(), "amount": t.amount,
            "currency": t.currency, "direction": t.direction.value,
            "merchant": t.merchant_norm or t.payee_handle,
            "is_person": bool(t.payee_handle),
            "category": t.category, "confidence": t.confidence,
            "stage": t.stage.value, "status": t.status.value,
            "account": t.account, "transfer": t.is_transfer,
            "recurring": t.is_recurring, "raw": t.description_raw,
        }
```

to:

```python
    @staticmethod
    def _row(t):
        return {
            "id": t.id, "date": t.date.isoformat(), "amount": t.amount,
            "currency": t.currency, "direction": t.direction.value,
            "merchant": t.merchant_norm or t.payee_handle,
            "is_person": bool(t.payee_handle),
            "category": t.category, "subcategory": t.subcategory,
            "confidence": t.confidence,
            "stage": t.stage.value, "status": t.status.value,
            "account": t.account, "transfer": t.is_transfer,
            "recurring": t.is_recurring, "raw": t.description_raw,
        }
```

- [ ] **Step 5: Add a backend test for `_row` carrying subcategory**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_api_transactions_row_includes_subcategory(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    subcategory="Alcohol")
    store.upsert_transactions([t])
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/transactions", timeout=3).read())
        assert d["rows"][0]["subcategory"] == "Alcohol"
    finally:
        srv.shutdown()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (29 passed)

- [ ] **Step 7: Manually verify in the browser**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim munim web
```

In the browser:
1. Go to the **Categories** tab, confirm it still loads (no console errors).
2. In a terminal, run `munim categories subcategories add Groceries Alcohol`.
3. Reload the web page, go to **Rules**, confirm a Groceries-category
   rule now shows a subcategory dropdown with "Alcohol" as an option;
   pick it and confirm no error (check the Network tab for a 200 from
   `/api/rule/subcategory`).
4. Go to **Transactions**, filter by Head = Groceries; confirm a
   Subcategory dropdown appears, and selecting "Alcohol" narrows the
   list correctly.
5. Stop the server with Ctrl-C (the dev server does not hot-reload —
   restart it after any further `index.html`/`server.py` edit).

- [ ] **Step 8: Commit**

```bash
git add packages/classify/munim/web/index.html packages/classify/munim/web/server.py packages/classify/tests/test_subcategories.py
git commit -m "Add subcategory UI to the Rules and Transactions pages"
```

---

### Task 12: Fold subcategory into the ledger export path

**Files:**
- Modify: `packages/classify/munim/export_formats.py:44-46`
- Test: `packages/classify/tests/test_subcategories.py`

**Interfaces:**
- Consumes: `Transaction.subcategory` (Task 1), `tree.resolve` (unchanged).
- Produces: `to_ledger()` output includes `:subcategory` in the account
  path when set, e.g. `Expenses:Groceries:Alcohol`.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategories.py`:

```python
def test_ledger_export_includes_subcategory_in_path():
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SHETTY BEER SHOP", category="Groceries",
                    subcategory="Alcohol", account="hdfc")
    out = to_ledger([t], tree=default_tree(["Groceries"]))
    assert "Expenses:Groceries:Alcohol" in out


def test_ledger_export_omits_colon_when_no_subcategory():
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    t = Transaction(date="2026-06-01", amount=300, direction=Direction.DEBIT,
                    description_raw="SWIGGY", category="Dining", account="hdfc")
    out = to_ledger([t], tree=default_tree(["Dining"]))
    assert "Expenses:Dining" in out
    assert "Expenses:Dining:" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: FAIL — the first test fails, `Expenses:Groceries:Alcohol` not
in output (only `Expenses:Groceries` is there).

- [ ] **Step 3: Update `to_ledger`**

Change:

```python
        payee = t.merchant_norm or t.payee_handle or t.description_raw[:48]
        path = resolve(tree, t.category).replace(" ", "-")
```

to:

```python
        payee = t.merchant_norm or t.payee_handle or t.description_raw[:48]
        path = resolve(tree, t.category)
        if t.subcategory:
            path += f":{t.subcategory}"
        path = path.replace(" ", "-")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategories.py -v`
Expected: PASS (31 passed)

- [ ] **Step 5: Run the full existing suite one final time**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing. This is the last task in this plan — a clean
full-suite pass here means the feature is complete end to end.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/export_formats.py packages/classify/tests/test_subcategories.py
git commit -m "Include subcategory in the ledger export path"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After all 12 tasks land, update:
- `docs/data-contract.md`: add a `subcategory` row to the `transactions`
  column table (same style as the existing `merchant_norm`/`category`
  rows).
- `docs/pipeline.md`: note in the Stage 4 (Memory) row that a matched
  memory rule may also carry a subcategory.
- `README.md`: one sentence in the "Region packs & community dictionary"
  section or a new short paragraph noting subcategories exist, pointing
  at `munim categories subcategories --help`.

These are documentation-only, no tests — do them in one small commit
after Task 12's full-suite pass is green.
