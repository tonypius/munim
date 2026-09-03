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
