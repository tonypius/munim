import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction, Status
from munim.voucher_wallet import import_spend


def _real_debit(id_, amount, d, account="cc"):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="ZOMATO", account=account,
                       category="Dining")


AMAZONPAY_RECORD = {
    "kind": "spend", "brand": "amazonpay", "source": "amazonpay",
    "amount": 132.0, "merchant": "Zomato", "order_id": "171-9035274-8173116",
    "order_date": date(2026, 9, 1), "paid_via": None,
}

SWIGGY_CARD_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "swiggy_order",
    "amount": 391.0, "merchant": "Cafe Iftar", "order_id": "246907327135063",
    "order_date": date(2024, 8, 28), "paid_via": "Credit/Debit card",
}

INSTAMART_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "instamart_order",
    "amount": 395.0, "merchant": "Instamart", "order_id": "248336149154232",
    "order_date": date(2026, 9, 14), "paid_via": None,
}


def test_import_spend_skips_when_paid_via_names_a_real_rail(tmp_path):
    store = Store(home=tmp_path)
    txn_id = import_spend(store, SWIGGY_CARD_RECORD)
    assert txn_id is None
    assert store.all_transactions() == []


def test_import_spend_skips_when_matching_bank_txn_exists(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_real_debit("card1", 395.0, "2026-09-14")])

    txn_id = import_spend(store, INSTAMART_RECORD)

    assert txn_id is None
    # only the pre-existing real transaction, nothing created
    assert len(store.all_transactions()) == 1


def test_import_spend_creates_redemption_when_no_bank_match(tmp_path):
    store = Store(home=tmp_path)

    txn_id = import_spend(store, INSTAMART_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.direction == Direction.DEBIT
    assert txn.amount == 395.0
    assert txn.category == "Groceries"
    # Deterministic category, real money moved -- CONFIRMED like
    # house-sgs rows, not PROVISIONAL (adjudicated decision; the Amazon
    # Pay/Pipeline branch below is explicitly NOT part of this).
    assert txn.status == Status.CONFIRMED


def test_import_spend_registers_account_type_and_opening_balance(tmp_path):
    # import_purchase already did this; import_spend didn't at all, so a
    # brand created only via import_spend (amazonpay, since GYFTR_BRAND_MAP
    # currently only maps to "swiggy") never got an opening balance and
    # showed a blank balance in the Accounts tab / was excluded from net
    # worth.
    store = Store(home=tmp_path)

    import_spend(store, INSTAMART_RECORD)

    types = store.get_config("account_types", {})
    assert types["voucher-swiggy"] == "Assets"
    balances = store.get_config("account_opening_balances", {})
    assert balances["voucher-swiggy"] == {"balance": 0.0, "as_of": "2026-09-14"}


def test_import_spend_does_not_overwrite_existing_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                      {"voucher-swiggy": {"balance": 250.0, "as_of": "2026-01-01"}})

    import_spend(store, INSTAMART_RECORD)

    balances = store.get_config("account_opening_balances", {})
    assert balances["voucher-swiggy"] == {"balance": 250.0, "as_of": "2026-01-01"}


def test_import_spend_swiggy_order_category_is_dining(tmp_path):
    store = Store(home=tmp_path)
    record = {**SWIGGY_CARD_RECORD, "paid_via": "Swiggy Money"}

    txn_id = import_spend(store, record)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.category == "Dining"
    assert txn.status == Status.CONFIRMED


def test_import_spend_reuses_passed_pipeline_instead_of_constructing_one(tmp_path, monkeypatch):
    # Pipeline.__init__ is expensive (loads the fallback ML model from
    # disk, rebuilds the merchant-memory matcher) -- a caller looping
    # over many records (munim vouchers import/recheck) should build one
    # Pipeline once and pass it in, not pay that cost per call.
    import munim.voucher_wallet as voucher_wallet

    def _must_not_construct(*args, **kwargs):
        raise AssertionError(
            "import_spend must not construct its own Pipeline when one is passed in")

    monkeypatch.setattr(voucher_wallet, "Pipeline", _must_not_construct)

    calls = []

    class FakePipeline:
        def run(self, txns):
            calls.append(txns)
            for t in txns:
                t.category = "Dining"

    store = Store(home=tmp_path)
    txn_id = import_spend(store, AMAZONPAY_RECORD, pipeline=FakePipeline())

    assert len(calls) == 1
    txn = store.get_transaction(txn_id)
    assert txn.category == "Dining"


def test_import_spend_amazonpay_uses_pipeline_classification(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("categories", ["Dining", "Groceries"])
    store.remember("ZOMATO", "Dining", kind="merchant")

    txn_id = import_spend(store, AMAZONPAY_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-amazonpay"
    assert txn.category == "Dining"


def test_import_spend_is_idempotent_on_rerun(tmp_path):
    store = Store(home=tmp_path)
    first_id = import_spend(store, INSTAMART_RECORD)
    second_id = import_spend(store, INSTAMART_RECORD)
    assert first_id == second_id
    assert len(store.all_transactions()) == 1
