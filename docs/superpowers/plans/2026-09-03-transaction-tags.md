# Transaction Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a transaction carry any number of manually-assigned tags
(Business, Personal, a specific family member) from a curated list,
purely for ownership/purpose tracking — orthogonal to `category`, never
auto-applied.

**Architecture:** A new many-to-many `tags` table keyed by transaction
id, with a curated tag list in `config["tags"]` managed like
`categories` already is. No pipeline, memory, or schema.py changes at
all — tags are deliberately outside the classification engine. The web
UI reuses the exact checkbox-selection + bulk-action-bar pattern the
Review page already has, rather than inventing a new interaction model.

**Tech Stack:** Python 3.11+, SQLite, Typer, pytest, the existing
stdlib `http.server` + vanilla JS web UI. No new dependencies.

## Global Constraints

- Tags never get applied automatically by any mechanism — no memory
  rules, no dictionary, no pipeline involvement. Every assignment is a
  deliberate human action (either one transaction at a time, or an
  explicit one-time bulk apply that is never saved as a recurring rule).
- The tag list is curated (`config["tags"]`), not freeform per-transaction text.
- A transaction may carry any number of tags (0 or more).
- Tag names are capped at `MAX_TAGS = 30` total (not per-transaction).
- `Transaction` (the pydantic schema) is never modified — tags live only
  in the new `tags` table, looked up separately, same way `corrections`
  already works.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first).

---

### Task 1: `tags` table, migration, and core Store methods

**Files:**
- Modify: `packages/classify/munim/store.py` (SCHEMA string, `_migrate`, new methods)
- Test: `packages/classify/tests/test_tags.py` (new file)

**Interfaces:**
- Produces:
  - `Store.set_tags(txn_id: str, tags: list[str]) -> None` — replace-all.
  - `Store.tags_for(txn_id: str) -> list[str]`
  - `Store.all_tags() -> dict[str, list[str]]` — txn_id → tags, for
    bulk-populating a transaction list without N+1 queries.
  - `Store.tag_counts() -> dict[str, int]` — tag name → usage count.

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_tags.py`:

```python
"""Transaction tags: manually-assigned, multi-valued ownership/purpose
labels (Business, Personal, a family member's name) from a curated list.
Orthogonal to category — never auto-applied by any pipeline mechanism."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _column_names(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_store_has_tags_table(tmp_path):
    store = Store(home=tmp_path)
    tables = {r[0] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "tags" in tables


def test_set_tags_then_read_back(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business", "Spouse"])
    assert sorted(store.tags_for("txn1")) == ["Business", "Spouse"]


def test_set_tags_replaces_not_merges(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn1", ["Personal"])
    assert store.tags_for("txn1") == ["Personal"]


def test_set_tags_empty_list_clears(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn1", [])
    assert store.tags_for("txn1") == []


def test_all_tags_returns_only_transactions_with_tags(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn2", ["Spouse", "Business"])
    assert store.all_tags() == {"txn1": ["Business"], "txn2": ["Business", "Spouse"]}


def test_tag_counts(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn2", ["Business", "Spouse"])
    assert store.tag_counts() == {"Business": 2, "Spouse": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: FAIL — `no such table: tags`, `AttributeError` on the
not-yet-defined methods.

- [ ] **Step 3: Add the table to SCHEMA**

In `packages/classify/munim/store.py`, add a new `CREATE TABLE`
statement to the `SCHEMA` string, right after the `config` table (which
currently ends the string at line 58):

```python
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    txn_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (txn_id, tag)
);
"""
```

(This is a brand-new table, not a column addition to an existing one,
so `CREATE TABLE IF NOT EXISTS` in the `executescript(SCHEMA)` call
already handles both fresh and pre-existing databases — no `_migrate()`
change needed for this table.)

- [ ] **Step 4: Add the four methods**

In `packages/classify/munim/store.py`, add a new section right after
`stage_accuracy` (the last method, ending the file at line 218):

```python

    # ---- tags -----------------------------------------------------------
    def set_tags(self, txn_id: str, tags: list[str]) -> None:
        """Replace-all: a transaction's tag set becomes exactly `tags`.
        Manual assignment only — never called from the pipeline."""
        self.db.execute("DELETE FROM tags WHERE txn_id=?", (txn_id,))
        for tag in tags:
            self.db.execute(
                "INSERT OR IGNORE INTO tags(txn_id, tag) VALUES(?,?)",
                (txn_id, tag))
        self.db.commit()

    def tags_for(self, txn_id: str) -> list[str]:
        rows = self.db.execute(
            "SELECT tag FROM tags WHERE txn_id=? ORDER BY tag", (txn_id,)
        ).fetchall()
        return [r["tag"] for r in rows]

    def all_tags(self) -> dict[str, list[str]]:
        """txn_id -> sorted tags, for every transaction that has at least
        one. Bulk lookup to avoid N+1 queries when listing transactions."""
        rows = self.db.execute(
            "SELECT txn_id, tag FROM tags ORDER BY txn_id, tag").fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["txn_id"], []).append(r["tag"])
        return out

    def tag_counts(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag").fetchall()
        return {r["tag"]: r["n"] for r in rows}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_tags.py
git commit -m "Add tags table and core Store methods"
```

---

### Task 2: One-time bulk tag application by pattern

**Files:**
- Modify: `packages/classify/munim/store.py` (add one method in the tags section from Task 1)
- Test: `packages/classify/tests/test_tags.py`

**Interfaces:**
- Consumes: Task 1's `tags` table.
- Produces: `Store.apply_tag_to_pattern(pattern: str, tag: str, kind: str = "merchant") -> int`
  — adds `tag` to every transaction whose merchant/payee matches
  `pattern`, without removing any tags those transactions already have.
  This is the "I know this whole batch was business" one-time action —
  it does not write to the `memory` table and has no effect on future
  imports.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_tags.py`:

```python
def test_apply_tag_to_pattern_tags_every_matching_transaction(tmp_path):
    store = Store(home=tmp_path)
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="UBER RIDE 1")
    t1.merchant_norm = "UBER INDIA SYSTEMS"
    t2 = Transaction(date="2026-06-02", amount=250, direction=Direction.DEBIT,
                     description_raw="UBER RIDE 2")
    t2.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t1, t2])
    n = store.apply_tag_to_pattern("UBER INDIA SYSTEMS", "Business")
    assert n == 2
    assert store.tags_for(t1.id) == ["Business"]
    assert store.tags_for(t2.id) == ["Business"]


def test_apply_tag_to_pattern_adds_without_removing_existing_tags(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    t.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t])
    store.set_tags(t.id, ["Spouse"])
    store.apply_tag_to_pattern("UBER INDIA SYSTEMS", "Business")
    assert sorted(store.tags_for(t.id)) == ["Business", "Spouse"]


def test_apply_tag_to_pattern_matches_payee_handle_for_payee_kind(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=5000, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-513324498817")
    t.merchant_norm, t.payee_handle = "", "RAMESH KUMAR"
    store.upsert_transactions([t])
    n = store.apply_tag_to_pattern("RAMESH KUMAR", "Spouse", "payee")
    assert n == 1
    assert store.tags_for(t.id) == ["Spouse"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute
'apply_tag_to_pattern'`.

- [ ] **Step 3: Add the method**

In `packages/classify/munim/store.py`, add to the tags section (right
after `tag_counts`):

```python

    def apply_tag_to_pattern(self, pattern: str, tag: str,
                             kind: str = "merchant") -> int:
        """One-time bulk apply: add `tag` to every transaction currently
        matching pattern, confirmed or not. Does NOT write to the memory
        table — this never auto-applies to future imports, and never
        removes a transaction's other tags. The web/CLI escape hatch for
        'I know this whole batch was business' without violating the
        manual-only guarantee."""
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        ids = [r["id"] for r in self.db.execute(
            f"SELECT id FROM transactions WHERE {col}=?", (pattern,)).fetchall()]
        for txn_id in ids:
            self.db.execute(
                "INSERT OR IGNORE INTO tags(txn_id, tag) VALUES(?,?)",
                (txn_id, tag))
        self.db.commit()
        return len(ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_tags.py
git commit -m "Add one-time bulk tag application by merchant/payee pattern"
```

---

### Task 3: `munim tags add/list/remove` (curated list management)

**Files:**
- Modify: `packages/classify/munim/cli.py` (add near the end, after `relabel` — currently ending at line 780, before the `# eval` section at line 783)
- Test: `packages/classify/tests/test_tags.py`

**Interfaces:**
- Produces: `munim tags add <name> [--force]`, `munim tags list`,
  `munim tags remove <name>`. Reads/writes `config["tags"]: list[str]`.
  `MAX_TAGS = 30` module-level constant in `cli.py`.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_tags.py`:

```python
from typer.testing import CliRunner
from munim.cli import app

runner = CliRunner()


def test_tags_add_creates_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    result = runner.invoke(app, ["tags", "add", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.get_config("tags", []) == ["Business"]


def test_tags_add_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    result = runner.invoke(app, ["tags", "add", "Business"])
    assert result.exit_code != 0


def test_tags_add_enforces_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", [f"Tag{i}" for i in range(30)])
    result = runner.invoke(app, ["tags", "add", "OneTooMany"])
    assert result.exit_code != 0
    result_forced = runner.invoke(app, ["tags", "add", "OneTooMany", "--force"])
    assert result_forced.exit_code == 0, result_forced.output


def test_tags_list_shows_usage_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    store.set_tags("txn1", ["Business"])
    result = runner.invoke(app, ["tags", "list"])
    assert result.exit_code == 0
    assert "Business" in result.output


def test_tags_remove_deletes_from_taxonomy_and_all_transactions(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    store.set_tags("txn1", ["Business"])
    result = runner.invoke(app, ["tags", "remove", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.get_config("tags", []) == []
    assert fresh.tags_for("txn1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: FAIL — `No such command 'tags'`.

- [ ] **Step 3: Add the commands**

In `packages/classify/munim/cli.py`, add near the top with the other
module constants (right after `DEFAULT_CATEGORIES`, currently ending at
line 30):

```python
MAX_TAGS = 30   # a generous cap — tags don't fight the same top-level
                # "labeling consistency" pressure a mutually-exclusive
                # category list has, so this is about avoiding a
                # genuinely unmanageable list, not review-menu sanity.
```

Then, right after `relabel` (which currently ends at line 780, just
before the `# eval` section comment at line 783), add:

```python
# -------------------------------------------------------------------- tags
tag_app = typer.Typer(help="Manage the curated tag list.", no_args_is_help=True)
app.add_typer(tag_app, name="tags")


@tag_app.command("add")
def tags_add(name: str, force: bool = typer.Option(False, "--force")):
    """Add a tag to the curated list, e.g.: munim tags add Business"""
    store = _store()
    tags = store.get_config("tags", [])
    if name in tags:
        console.print(f"[yellow]{name} already exists.[/yellow]")
        raise typer.Exit(1)
    if len(tags) >= MAX_TAGS and not force:
        console.print(f"[red]You already have {len(tags)} tags — the "
                      f"limit is {MAX_TAGS}.[/red] --force if you accept "
                      "the tradeoff.")
        raise typer.Exit(1)
    tags.append(name)
    store.set_config("tags", tags)
    console.print(f"[green]Added tag: {name}.[/green]")


@tag_app.command("list")
def tags_list():
    """Show your curated tags and how much each has been used."""
    store = _store()
    tags = store.get_config("tags", [])
    counts = store.tag_counts()
    table = Table(title="Tags")
    table.add_column("Name")
    table.add_column("Transactions", justify="right")
    for name in tags:
        table.add_row(name, str(counts.get(name, 0)))
    console.print(table)


@tag_app.command("remove")
def tags_remove(name: str):
    """Remove a tag from the taxonomy and every transaction carrying it."""
    store = _store()
    tags = store.get_config("tags", [])
    if name not in tags:
        console.print(f"[red]{name} is not a tag (munim tags list).[/red]")
        raise typer.Exit(1)
    tags.remove(name)
    store.set_config("tags", tags)
    n = store.db.execute("DELETE FROM tags WHERE tag=?", (name,)).rowcount
    store.db.commit()
    console.print(f"[green]Removed tag {name}[/green] — "
                  f"cleared from {n} transactions.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_tags.py
git commit -m "Add munim tags add/list/remove commands"
```

---

### Task 4: `munim tag` — set tags on one transaction, or bulk-apply by pattern

**Files:**
- Modify: `packages/classify/munim/cli.py` (add right after the tags section from Task 3)
- Test: `packages/classify/tests/test_tags.py`

**Interfaces:**
- Consumes: `Store.set_tags`, `Store.apply_tag_to_pattern` (Tasks 1-2),
  `config["tags"]` (Task 3).
- Produces: `munim tag <txn-id> <tag> [<tag2> ...]` (replace-all) and
  `munim tag --pattern "<text>" <tag> [--payee]` (one-time bulk add).

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_tags.py`:

```python
def test_tag_command_sets_tags_on_one_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business", "Spouse"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["tag", t.id, "Business", "Spouse"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert sorted(fresh.tags_for(t.id)) == ["Business", "Spouse"]


def test_tag_command_rejects_tag_not_in_curated_list(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["tag", t.id, "NotARealTag"])
    assert result.exit_code != 0


def test_tag_command_with_pattern_bulk_applies(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="UBER 1")
    t1.merchant_norm = "UBER INDIA SYSTEMS"
    t2 = Transaction(date="2026-06-02", amount=250, direction=Direction.DEBIT,
                     description_raw="UBER 2")
    t2.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t1, t2])
    result = runner.invoke(app, ["tag", "--pattern", "UBER INDIA SYSTEMS", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.tags_for(t1.id) == ["Business"]
    assert fresh.tags_for(t2.id) == ["Business"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: FAIL — `No such command 'tag'`.

- [ ] **Step 3: Add the command**

Right after the `tags_remove` command from Task 3, add:

```python
@app.command("tag")
def tag_transaction(
    txn_id: str = typer.Argument(None, help="Transaction id (omit when using --pattern)"),
    tags: list[str] = typer.Argument(None, help="Tags to set (replaces existing)"),
    pattern: str = typer.Option(
        "", "--pattern",
        help="Bulk one-time apply to every transaction matching this merchant/payee text"),
    payee: bool = typer.Option(False, "--payee",
                               help="Pattern is a person, not a merchant (only with --pattern)"),
):
    """Set a transaction's tags, or bulk-apply one tag to every currently-
    matching transaction with --pattern. Manual only — never saved as a
    rule, never affects future imports."""
    store = _store()
    curated = store.get_config("tags", [])
    if pattern:
        if len(tags) != 1:
            console.print("[red]--pattern takes exactly one tag.[/red]")
            raise typer.Exit(1)
        tag = tags[0]
        if tag not in curated:
            console.print(f"[red]{tag} is not a tag (munim tags list).[/red]")
            raise typer.Exit(1)
        n = store.apply_tag_to_pattern(pattern.upper().strip(), tag,
                                       "payee" if payee else "merchant")
        console.print(f"[green]Tagged {n} matching transactions with "
                      f"{tag}.[/green]")
        return
    if not txn_id:
        console.print("[red]Need a transaction id, or --pattern.[/red]")
        raise typer.Exit(1)
    unknown = [t for t in tags if t not in curated]
    if unknown:
        console.print(f"[red]Not in your tag list (munim tags list): "
                      f"{', '.join(unknown)}[/red]")
        raise typer.Exit(1)
    store.set_tags(txn_id, tags)
    console.print(f"[green]{txn_id} → {', '.join(tags) or '(no tags)'}[/green]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_tags.py
git commit -m "Add munim tag command: set-tags and pattern-based bulk apply"
```

---

### Task 5: Web backend — `/api/tags`, `/api/tag`, `/api/tags/bulk`, and tags on `/api/transactions` rows

**Files:**
- Modify: `packages/classify/munim/web/server.py:47-71` (`do_GET`)
- Modify: `packages/classify/munim/web/server.py:74-79` (`do_POST` routing)
- Modify: `packages/classify/munim/web/server.py:169-196` (`_transactions`, `_row`)
- Test: `packages/classify/tests/test_tags.py`

**Interfaces:**
- Consumes: `Store.all_tags`, `Store.tag_counts`, `Store.set_tags` (Task
  1), `config["tags"]` (Task 3).
- Produces:
  - `GET /api/tags` → `{"tags": [...curated list...], "counts": {name: n}}`
  - `POST /api/tag` body `{id, tags: [...]}` → replace-all on one transaction.
  - `POST /api/tags/bulk` body `{ids: [...], tag, action: "add"|"remove"}`
    → bulk add/remove one tag across many transactions (the Transactions
    page's bulk-select action).
  - Every row from `GET /api/transactions` gains a `"tags": [...]` field.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_tags.py`:

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


def test_api_tags_returns_curated_list_and_counts(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business", "Spouse"])
    store.set_tags("txn1", ["Business"])
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/tags", timeout=3).read())
        assert d["tags"] == ["Business", "Spouse"]
        assert d["counts"] == {"Business": 1}
    finally:
        srv.shutdown()


def test_post_api_tag_sets_tags_on_one_transaction(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    srv, port = _server(store)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tag", method="POST",
            data=json.dumps({"id": t.id, "tags": ["Business"]}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert res["ok"] is True
        assert store.tags_for(t.id) == ["Business"]
    finally:
        srv.shutdown()


def test_post_api_tags_bulk_add_and_remove(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="A")
    t2 = Transaction(date="2026-06-02", amount=200, direction=Direction.DEBIT,
                     description_raw="B")
    store.upsert_transactions([t1, t2])
    srv, port = _server(store)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tags/bulk", method="POST",
            data=json.dumps({"ids": [t1.id, t2.id], "tag": "Business",
                             "action": "add"}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert res["ok"] is True and res["updated"] == 2
        assert store.tags_for(t1.id) == ["Business"]
        assert store.tags_for(t2.id) == ["Business"]

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tags/bulk", method="POST",
            data=json.dumps({"ids": [t1.id], "tag": "Business",
                             "action": "remove"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        assert store.tags_for(t1.id) == []
        assert store.tags_for(t2.id) == ["Business"]
    finally:
        srv.shutdown()


def test_api_transactions_rows_include_tags(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    store.set_tags(t.id, ["Business"])
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/transactions", timeout=3).read())
        assert d["rows"][0]["tags"] == ["Business"]
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: FAIL — `/api/tags` and `/api/tags/bulk` return 404, `/api/tag`
returns 404, and rows lack a `"tags"` key.

- [ ] **Step 3: Add GET routing and handler**

In `do_GET`, change:

```python
        elif route == "/api/rules":
            self._send(self._rules())
```

to (adding the new route right after it):

```python
        elif route == "/api/rules":
            self._send(self._rules())
        elif route == "/api/tags":
            self._send(self._tags())
```

Then add a new method, right after `_rules` (which currently ends at
line 275, right before `_accounts` at line 277):

```python
    def _tags(self):
        return {"tags": self.store.get_config("tags", []),
                "counts": self.store.tag_counts()}
```

- [ ] **Step 4: Add POST routing and handlers**

Change `do_POST`'s routing (already modified once in the subcategories
plan if that landed first — if so, add another branch the same way;
shown here as if starting from the original):

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
        if path == "/api/tag":
            self._handle_tag()
            return
        if path == "/api/tags/bulk":
            self._handle_tags_bulk()
            return
        if path != "/api/confirm":
            self._send({"error": "not found"}, status=404)
            return
```

(If the category-subcategories plan already changed this method to
branch on `/api/rule/subcategory`, add the two `if` blocks above
alongside that one — the order between them doesn't matter, each
returns early.)

Then add two new methods, right after `_confirm_one`:

```python
    def _handle_tag(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        txn_id = data.get("id")
        tags = data.get("tags") or []
        curated = self.store.get_config("tags", [])
        unknown = [t for t in tags if t not in curated]
        if not txn_id or unknown:
            self._send({"error": "need a valid id and known tags"}, status=400)
            return
        self.store.set_tags(txn_id, tags)
        self._send({"ok": True})

    def _handle_tags_bulk(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        ids = data.get("ids") or []
        tag = data.get("tag")
        action = data.get("action")
        curated = self.store.get_config("tags", [])
        if not ids or tag not in curated or action not in ("add", "remove"):
            self._send({"error": "need ids, a known tag, and add/remove"},
                       status=400)
            return
        updated = 0
        for txn_id in ids:
            current = set(self.store.tags_for(txn_id))
            if action == "add":
                current.add(tag)
            else:
                current.discard(tag)
            self.store.set_tags(txn_id, sorted(current))
            updated += 1
        self._send({"ok": True, "updated": updated})
```

- [ ] **Step 5: Add `tags` to `/api/transactions` rows**

Change `_row` from:

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

to (accepting tags as a parameter, defaulting to empty, so existing
call sites that don't pass it keep working, and `_transactions` — the
only caller that needs real data — is updated to pass it):

```python
    @staticmethod
    def _row(t, tags=()):
        return {
            "id": t.id, "date": t.date.isoformat(), "amount": t.amount,
            "currency": t.currency, "direction": t.direction.value,
            "merchant": t.merchant_norm or t.payee_handle,
            "is_person": bool(t.payee_handle),
            "category": t.category, "confidence": t.confidence,
            "stage": t.stage.value, "status": t.status.value,
            "account": t.account, "transfer": t.is_transfer,
            "recurring": t.is_recurring, "raw": t.description_raw,
            "tags": list(tags),
        }
```

Change `_transactions` from:

```python
    def _transactions(self, q):
        # Same filter surface as /api/queue (month, q, plus a category
        # filter — the sentinel "__none__" here means "no category
        # assigned yet", mirroring queue's "no suggestion" case) — the
        # ledger page needs the same search/filter a large review queue
        # needs, once thousands of already-classified rows pile up.
        month, needle = q.get("month", ""), q.get("q", "").upper()
        category = q.get("category", "")
        all_txns = self.store.all_transactions()
        rows = []
        for t in sorted(all_txns, key=lambda x: x.date, reverse=True):
            iso = t.date.isoformat()
            if month and not iso.startswith(month):
                continue
            if category == "__none__" and t.category:
                continue
            if category and category != "__none__" and t.category != category:
                continue
            hay = f"{t.merchant_norm} {t.payee_handle} {t.category} " \
                  f"{t.description_raw}".upper()
            if needle and needle not in hay:
                continue
            rows.append(self._row(t))
            if len(rows) >= 300:
                break
        months = sorted({t.date.isoformat()[:7] for t in all_txns}, reverse=True)
        categories = sorted({t.category for t in all_txns if t.category})
        return {"rows": rows, "months": months, "categories": categories}
```

to (one new line: look up all tags once, pass each transaction's tags
into `_row`):

```python
    def _transactions(self, q):
        # Same filter surface as /api/queue (month, q, plus a category
        # filter — the sentinel "__none__" here means "no category
        # assigned yet", mirroring queue's "no suggestion" case) — the
        # ledger page needs the same search/filter a large review queue
        # needs, once thousands of already-classified rows pile up.
        month, needle = q.get("month", ""), q.get("q", "").upper()
        category = q.get("category", "")
        all_txns = self.store.all_transactions()
        all_tags = self.store.all_tags()
        rows = []
        for t in sorted(all_txns, key=lambda x: x.date, reverse=True):
            iso = t.date.isoformat()
            if month and not iso.startswith(month):
                continue
            if category == "__none__" and t.category:
                continue
            if category and category != "__none__" and t.category != category:
                continue
            hay = f"{t.merchant_norm} {t.payee_handle} {t.category} " \
                  f"{t.description_raw}".upper()
            if needle and needle not in hay:
                continue
            rows.append(self._row(t, all_tags.get(t.id, [])))
            if len(rows) >= 300:
                break
        months = sorted({t.date.isoformat()[:7] for t in all_txns}, reverse=True)
        categories = sorted({t.category for t in all_txns if t.category})
        return {"rows": rows, "months": months, "categories": categories}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_tags.py -v`
Expected: PASS (21 passed)

- [ ] **Step 7: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — `_row`'s new `tags` parameter defaults to `()`,
so `test_web_confirm_as_transfers_sets_is_transfer` and any other
existing caller of `_row` without the new argument keep working.

- [ ] **Step 8: Commit**

```bash
git add packages/classify/munim/web/server.py packages/classify/tests/test_tags.py
git commit -m "Expose tags through the web API"
```

---

### Task 6: Web frontend — tag filter and bulk-tag bar on the Transactions page

**Files:**
- Modify: `packages/classify/munim/web/index.html`
  - Transactions page controls (currently lines 155-163) and
    `transactions()` (currently lines 319-339)
  - CSS: reuse `.tag`/`.controls`/`.confirm` — no new classes needed
    beyond one for the tag chip list

**Interfaces:**
- Consumes: `GET /api/tags`, `POST /api/tags/bulk`, `tags` field on
  `/api/transactions` rows (Task 5).
- Produces: no new automated test — manually verified in a browser, per
  this project's convention for UI-only changes.

This reuses the exact row-checkbox + bulk-action-bar interaction the
Review page already has (`#bulkBar`/`updateBulkBar()`/the delegated
`change` listener on the stable container) rather than inventing a new
pattern — a per-row inline tag picker would mean a lot more new UI code
for the same outcome, when bulk assignment is the realistic common case
anyway (tag every Uber charge from a trip at once, not one row at a
time).

- [ ] **Step 1: Add CSS for the tag chip list**

Right after the existing `.tag.broad` rule, add:

```css
.tagchips{display:flex;gap:4px;flex-wrap:wrap;margin-top:3px}
```

- [ ] **Step 2: Update the Transactions section markup**

Change:

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
    <select id="fTag"><option value="">All tags</option></select>
    <input id="fSearch" placeholder="Search merchant, category, raw text" size="34">
  </div>
  <div class="controls" id="txnBulkBar" hidden>
    <span id="txnBulkCount"></span>
    <select id="txnBulkTag"></select>
    <button id="txnBulkAdd" class="confirm">Add tag</button>
    <button id="txnBulkRemove">Remove tag</button>
  </div>
  <div id="txnBody"></div>
</section>
```

- [ ] **Step 3: Rewrite `transactions()` and add the bulk-tag wiring**

Change the whole `transactions` block (function plus its three
`addEventListener` lines, currently lines 319-342) to:

```javascript
/* transactions */
let TAGS=[];
async function loadTags(){
  const d=await api("/api/tags");TAGS=d.tags;
  $("#fTag").innerHTML=`<option value="">All tags</option>`+
    TAGS.map(t=>`<option value="${esc(t)}">${esc(t)} (${d.counts[t]||0})</option>`).join("");
  $("#txnBulkTag").innerHTML=TAGS.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join("");
}
async function transactions(){
  if(!TAGS.length)await loadTags();
  const month=$("#fMonth").value,q=$("#fSearch").value,category=$("#fCategory").value,
        tag=$("#fTag").value;
  const params=new URLSearchParams({month,q,category});
  const d=await api(`/api/transactions?${params}`);
  if($("#fMonth").options.length===1)
    d.months.forEach(m=>$("#fMonth").insertAdjacentHTML("beforeend",`<option>${m}</option>`));
  if($("#fCategory").options.length===2)
    d.categories.forEach(c=>$("#fCategory")
      .insertAdjacentHTML("beforeend",`<option value="${esc(c)}">${esc(c)}</option>`));
  const rows=tag?d.rows.filter(r=>r.tags.includes(tag)):d.rows;
  $("#txnBody").innerHTML=rows.length?`<table><thead><tr>
    <th><input type="checkbox" id="txnSelectAll" title="Select all"></th>
    <th>Date</th><th>Entry</th><th class="num">Amount</th><th>Head</th><th>Provenance</th><th>Account</th>
  </tr></thead><tbody>`+rows.map(r=>`<tr data-id="${r.id}">
    <td><input type="checkbox" class="txnRowSel" value="${r.id}"></td>
    <td class="num">${r.date}</td>
    <td><div class="merchant">${esc(r.merchant)||"—"}${r.transfer?' <span class="tag">transfer</span>':""}${r.recurring?' <span class="tag">recurring</span>':""}</div><div class="raw">${esc(r.raw)}</div>${r.tags.length?`<div class="tagchips">`+r.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join("")+`</div>`:""}</td>
    ${amountCell(r)}
    <td>${esc(r.category)||'<span class="tag">—</span>'}</td>
    <td>${statusTag(r)}</td>
    <td class="merchant">${esc(r.account)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">No entries match.</p>`;
  updateTxnBulkBar();
}
function updateTxnBulkBar(){
  const n=document.querySelectorAll("#txnBody .txnRowSel:checked").length;
  $("#txnBulkBar").hidden=n===0;
  $("#txnBulkCount").textContent=n===1?"1 selected":`${n} selected`;
}
$("#fMonth")?.addEventListener("change",transactions);
$("#fCategory")?.addEventListener("change",transactions);
$("#fTag")?.addEventListener("change",transactions);
let deb;$("#fSearch")?.addEventListener("input",()=>{clearTimeout(deb);deb=setTimeout(transactions,250)});
$("#txnBody").addEventListener("change",e=>{
  if(e.target.id==="txnSelectAll"){
    document.querySelectorAll("#txnBody .txnRowSel")
      .forEach(cb=>cb.checked=e.target.checked);
  }
  updateTxnBulkBar();
});
async function bulkTag(action){
  const ids=[...document.querySelectorAll("#txnBody .txnRowSel:checked")].map(cb=>cb.value);
  if(!ids.length)return;
  const tag=$("#txnBulkTag").value;
  try{
    await api("/api/tags/bulk",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ids,tag,action})});
    await loadTags();await transactions();
  }catch(err){
    alert("Tag update failed: "+err.message);
  }
}
$("#txnBulkAdd")?.addEventListener("click",()=>bulkTag("add"));
$("#txnBulkRemove")?.addEventListener("click",()=>bulkTag("remove"));
```

- [ ] **Step 4: Manually verify in the browser**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim munim web
```

In a terminal (with the server running):
```bash
munim tags add Business
munim tags add Spouse
```

In the browser:
1. Go to **Transactions**, reload the tab — confirm the "All tags"
   dropdown now lists Business and Spouse with counts.
2. Tick a couple of rows, confirm the bulk-tag bar appears with a count.
3. Pick "Business" in the bulk-tag select, click **Add tag** — confirm
   the rows now show a "Business" chip after the list re-renders.
4. Filter by tag = Business — confirm only tagged rows show.
5. Select those same rows again, click **Remove tag** — confirm the
   chips disappear and the tag filter now shows 0 for Business.
6. Stop the server with Ctrl-C (no hot-reload — restart after any
   further edit to `index.html`/`server.py`).

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/web/index.html
git commit -m "Add tag filter and bulk-tag UI to the Transactions page"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After both tasks land, update:
- `docs/data-contract.md`: add a short note that tags live in a separate
  `tags` table (txn_id, tag), not on `transactions` itself, since a
  reader of that doc's column table would otherwise wonder where they
  are.
- `README.md`: one sentence pointing at `munim tags --help` / `munim tag
  --help`, likely near wherever subcategories end up documented (see
  the sibling plan's doc touch-up section) so both new taxonomy layers
  are introduced together.

These are documentation-only, no tests — do them in one small commit
after Task 6's manual verification.
