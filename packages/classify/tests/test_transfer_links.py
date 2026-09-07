"""Tests for transfer-pair linking: the transfer_links and
transfer_dismissals tables, and Store's core methods over them."""
import sys
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


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
