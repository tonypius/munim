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
