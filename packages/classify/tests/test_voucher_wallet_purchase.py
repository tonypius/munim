import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction, Status
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
    # Every other write path in this codebase treats is_transfer and
    # category=="Transfers" as inseparable (see the "reports/dashboard
    # check is_transfer, not the category string" convention in
    # pipeline.py/store.py/cli.py) -- without this, flow_query/dashboard
    # credit totals get inflated by the voucher's face value, and an
    # ambiguous multi-candidate purchase could never show up in the
    # Transfers tab's pending list (which filters on is_transfer).
    assert txn.is_transfer is True
    # Real money moved and the category is 100% deterministic -- no
    # ambiguity for a human to review, so this should land CONFIRMED
    # like house-sgs rows do, not PROVISIONAL.
    assert txn.status == Status.CONFIRMED


def test_import_purchase_registers_account_as_assets(tmp_path):
    store = Store(home=tmp_path)
    import_purchase(store, PURCHASE_RECORD)

    types = store.get_config("account_types", {})
    assert types["voucher-swiggy"] == "Assets"


def test_import_purchase_registers_a_zero_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    import_purchase(store, PURCHASE_RECORD)

    balances = store.get_config("account_opening_balances", {})
    assert balances["voucher-swiggy"] == {"balance": 0.0, "as_of": "2026-09-14"}


def test_import_purchase_does_not_overwrite_existing_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                      {"voucher-swiggy": {"balance": 500.0, "as_of": "2026-01-01"}})

    import_purchase(store, PURCHASE_RECORD)

    balances = store.get_config("account_opening_balances", {})
    assert balances["voucher-swiggy"] == {"balance": 500.0, "as_of": "2026-01-01"}


def test_import_purchase_moves_zero_balance_anchor_earlier_for_an_earlier_record(tmp_path):
    # A later fetch/import round can discover a real transaction dated
    # BEFORE whatever record happened to be imported first (e.g. a
    # parser bug fixed after the fact surfaces older mail) -- if the
    # opening-balance anchor stays fixed at the first-ever date, every
    # earlier real transaction silently falls outside
    # compute_account_balance's window and the reported balance is
    # wrong by exactly that much. Only ever moves EARLIER, and only
    # when the tracked balance is still the auto-created 0.0 sentinel
    # (a real non-zero manually-set balance, per the test above, must
    # never be touched).
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                      {"voucher-swiggy": {"balance": 0.0, "as_of": "2026-09-14"}})
    earlier_record = {**PURCHASE_RECORD, "code": "EARLIER-CODE",
                      "purchased_at": date(2025, 4, 1)}

    import_purchase(store, earlier_record)

    balances = store.get_config("account_opening_balances", {})
    assert balances["voucher-swiggy"] == {"balance": 0.0, "as_of": "2025-04-01"}


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
