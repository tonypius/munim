import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _txn(id_, amount=100.0, direction=Direction.DEBIT):
    return Transaction(id=id_, date="2026-06-01", amount=amount,
                       direction=direction, description_raw="X",
                       account="cc", category="Shopping")


def test_delete_transaction_removes_the_row(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_txn("t1")])
    assert store.get_transaction("t1") is not None

    store.delete_transaction("t1")

    assert store.get_transaction("t1") is None


def test_delete_transaction_removes_tags_and_transfer_links(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("t1", direction=Direction.DEBIT),
        _txn("t2", direction=Direction.CREDIT),
    ])
    store.set_tags("t1", ["business"])
    store.link_transfer("t1", "t2")

    store.delete_transaction("t1")

    assert store.tags_for("t1") == []
    assert store.linked_counterpart("t2") is None


def test_delete_transaction_on_unknown_id_is_a_noop(tmp_path):
    store = Store(home=tmp_path)
    store.delete_transaction("does-not-exist")  # must not raise
