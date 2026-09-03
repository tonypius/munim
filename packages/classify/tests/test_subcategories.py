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
