import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.voucher_wallet import import_purchase


def _card_debit(id_, amount, d):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="GYFTR SWIGGY VOUCHER", account="cc",
                       category="Transfers")


PURCHASE_RECORD = {
    "kind": "purchase", "brand": "swiggy", "value": 2000.0,
    "code": "VGHDR7VACB6SD15E", "purchased_at": date(2026, 9, 14),
}


def test_import_purchase_creates_credit_on_voucher_account(tmp_path):
    store = Store(home=tmp_path)
    txn_id = import_purchase(store, PURCHASE_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.direction == Direction.CREDIT
    assert txn.amount == 2000.0
    assert txn.category == "Transfers"
    assert txn.date.isoformat() == "2026-09-14"


def test_import_purchase_registers_account_as_assets(tmp_path):
    store = Store(home=tmp_path)
    import_purchase(store, PURCHASE_RECORD)

    types = store.get_config("account_types", {})
    assert types["voucher-swiggy"] == "Assets"


def test_import_purchase_links_to_unique_matching_card_debit(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_card_debit("card1", 2000.0, "2026-09-14")])

    txn_id = import_purchase(store, PURCHASE_RECORD)

    assert store.linked_counterpart("card1") == txn_id


def test_import_purchase_does_not_link_when_multiple_candidates(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _card_debit("card1", 2000.0, "2026-09-13"),
        _card_debit("card2", 2000.0, "2026-09-15"),
    ])

    txn_id = import_purchase(store, PURCHASE_RECORD)

    assert store.linked_counterpart("card1") is None
    assert store.linked_counterpart("card2") is None
    assert store.linked_counterpart(txn_id) is None


def test_import_purchase_is_idempotent_on_rerun(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_card_debit("card1", 2000.0, "2026-09-14")])

    first_id = import_purchase(store, PURCHASE_RECORD)
    second_id = import_purchase(store, PURCHASE_RECORD)

    assert first_id == second_id
    assert len(store.all_transactions()) == 2  # card1 + the one voucher credit
    assert store.linked_counterpart("card1") == first_id
