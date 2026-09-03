"""Category subcategories: a second, optional level under a category
head (Groceries -> Groceries:Alcohol), taught via memory rules and
applied independently of the existing flat category field."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.schema import Transaction, Direction
from munim.store import Store


def test_transaction_subcategory_defaults_to_empty_string():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP")
    assert t.subcategory == ""


def test_transaction_subcategory_can_be_set():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP",
                     category="Groceries", subcategory="Alcohol")
    assert t.subcategory == "Alcohol"


def _column_names(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_store_has_subcategory_columns(tmp_path):
    store = Store(home=tmp_path)
    assert "subcategory" in _column_names(store.db, "transactions")
    assert "subcategory" in _column_names(store.db, "memory")


def test_upsert_and_get_transaction_roundtrips_subcategory(tmp_path):
    """A non-default subcategory written through the app's normal insert
    path (upsert_transactions) must come back intact via get_transaction,
    which exercises _row_to_txn. This is the path real imports use, as
    opposed to just asserting the column exists."""
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP",
                     category="Groceries", subcategory="Alcohol")

    store.upsert_transactions([t])
    reloaded = store.get_transaction(t.id)

    assert reloaded is not None
    assert reloaded.subcategory == "Alcohol"


def test_update_transaction_writes_subcategory(tmp_path):
    """After calling update_transaction with a non-default subcategory,
    the value must be persisted to the database and readable via
    get_transaction."""
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP", category="Groceries")
    store.upsert_transactions([t])
    t.subcategory = "Alcohol"
    store.update_transaction(t)
    reloaded = store.get_transaction(t.id)
    assert reloaded is not None
    assert reloaded.subcategory == "Alcohol"


def test_migrate_adds_subcategory_to_pre_existing_database(tmp_path):
    """Simulate a database created before this column existed: build the
    old schema by hand, then open it with Store and confirm the column
    gets added without losing existing rows."""
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
                     description_raw="SHETTY BEER SHOP", merchant_norm="SHETTY BEER SHOP")
    store.upsert_transactions([t])
    n = store.propagate("SHETTY BEER SHOP", "Groceries", "merchant",
                        subcategory="Alcohol")
    assert n == 1
    reloaded = store.get_transaction(t.id)
    assert reloaded.category == "Groceries"
    assert reloaded.subcategory == "Alcohol"


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
                     status="confirmed", merchant_norm="SHETTY BEER SHOP")
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


def test_max_subcategories_per_parent_constant_exists():
    from munim.tree import MAX_SUBCATEGORIES_PER_PARENT
    assert MAX_SUBCATEGORIES_PER_PARENT == 10


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
