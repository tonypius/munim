import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.voucher_wallet import import_spend, recheck


def _real_debit(id_, amount, d):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="INSTAMART", account="cc",
                       category="Groceries")


INSTAMART_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "instamart_order",
    "amount": 395.0, "merchant": "Instamart", "order_id": "248336149154232",
    "order_date": "2026-09-14", "paid_via": None,
}


def test_recheck_removes_redemption_once_real_bank_txn_appears(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("voucher_records", [INSTAMART_RECORD])
    from datetime import date
    import_spend(store, {**INSTAMART_RECORD, "order_date": date(2026, 9, 14)})
    assert len(store.all_transactions()) == 1  # the redemption

    # the corresponding bank statement is imported later, revealing this
    # was actually card-paid all along
    store.upsert_transactions([_real_debit("card1", 395.0, "2026-09-14")])

    result = recheck(store)

    remaining = [t for t in store.all_transactions() if t.account.startswith("voucher-")]
    assert remaining == []
    assert result["removed_existing"] >= 1


def test_recheck_recreates_redemption_still_correctly_missing(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("voucher_records", [INSTAMART_RECORD])
    from datetime import date
    original_id = import_spend(store, {**INSTAMART_RECORD, "order_date": date(2026, 9, 14)})

    result = recheck(store)

    remaining_ids = {t.id for t in store.all_transactions() if t.account.startswith("voucher-")}
    assert remaining_ids == {original_id}
    assert result["created"] == 1
