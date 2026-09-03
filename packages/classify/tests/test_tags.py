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
