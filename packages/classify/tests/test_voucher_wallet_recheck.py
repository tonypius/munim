import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction, Status
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


def test_recheck_leaves_hand_entered_transaction_on_voucher_account_alone(tmp_path):
    # Only synthetic transactions (ids prefixed voucher-purchase-/
    # voucher-redemption-) are recheck's to delete-and-replay. A user can
    # hand-enter a manual transaction on a voucher-<brand> account too --
    # e.g. a manual top-up not routed through GYFTR email, following the
    # same double-entry pattern documented for house-sgs -- and that must
    # survive recheck untouched, since nothing enforces "only synthetic
    # transactions ever live on these accounts."
    store = Store(home=tmp_path)
    manual_txn = Transaction(
        id="manual-topup-1", date="2026-08-01", amount=1000.0,
        direction=Direction.CREDIT, description_raw="Manual top-up",
        account="voucher-swiggy", category="Transfers", is_transfer=True)
    store.upsert_transactions([manual_txn])

    result = recheck(store)

    assert store.get_transaction("manual-topup-1") is not None
    assert result["removed_existing"] == 0


def test_recheck_replayed_redemption_is_confirmed_again(tmp_path):
    # import_spend's fixed-category branch now creates CONFIRMED rows;
    # recheck deletes and replays via the same function, so a replayed
    # row must come back CONFIRMED too, not reset to PROVISIONAL.
    store = Store(home=tmp_path)
    store.set_config("voucher_records", [INSTAMART_RECORD])
    from datetime import date
    original_id = import_spend(store, {**INSTAMART_RECORD, "order_date": date(2026, 9, 14)})
    assert store.get_transaction(original_id).status == Status.CONFIRMED

    recheck(store)

    replayed = store.get_transaction(original_id)
    assert replayed is not None
    assert replayed.status == Status.CONFIRMED
