"""Turns parsed voucher-purchase/redemption records (from
munim_ingest.voucher_parse) into real Transaction rows on auto-created
voucher-<brand> virtual Assets accounts -- the same double-entry
pattern already used for house-sgs. See
docs/superpowers/specs/2026-09-16-voucher-redemption-tracking-design.md.
"""
from __future__ import annotations

from datetime import date

from .pipeline import Pipeline
from .schema import Direction, Stage, Status, Transaction
from .store import Store

# How many days apart a voucher purchase's card debit can be from the
# GYFTR purchase-confirmation email's own date and still be considered
# the same real-world event -- covers card-network posting lag.
LINK_WINDOW_DAYS = 5

# Synthetic id prefixes this module generates -- see import_purchase and
# import_spend below. recheck() uses these (not "any transaction on a
# voucher-<brand> account") to decide what it's safe to delete-and-
# replay, so a hand-entered transaction on a voucher account (e.g. a
# manual top-up not routed through GYFTR email, following the same
# double-entry pattern documented for house-sgs) survives untouched.
PURCHASE_ID_PREFIX = "voucher-purchase-"
REDEMPTION_ID_PREFIX = "voucher-redemption-"


def _ensure_voucher_account(store: Store, brand: str, opening_date: date) -> str:
    """Registers voucher-<brand> as an Assets account (if not already
    registered) and gives it a 0.0 opening balance as of opening_date
    (if it doesn't already have one) -- mirrors how house-sgs is
    registered, so the account shows a real balance in the Accounts tab
    / balance-sheet / net-worth total instead of being excluded for
    having no starting point. Never overwrites an opening balance that's
    already set: a later purchase/spend for the same brand shouldn't
    reset the running total. Returns the account name."""
    account = f"voucher-{brand}"

    account_types = store.get_config("account_types", {}) or {}
    if account not in account_types:
        account_types[account] = "Assets"
        store.set_config("account_types", account_types)

    opening_balances = store.get_config("account_opening_balances", {}) or {}
    if account not in opening_balances:
        opening_balances[account] = {"balance": 0.0, "as_of": opening_date.isoformat()}
        store.set_config("account_opening_balances", opening_balances)

    return account


def import_purchase(store: Store, record: dict) -> str:
    """record: {"kind": "purchase", "brand": str, "value": float,
    "code": str, "purchased_at": date}. Creates (or, on rerun,
    idempotently finds) a credit transaction on voucher-<brand> for the
    voucher's face value, links it to the one unambiguous matching real
    card debit if exactly one exists, and returns the transaction id."""
    brand = record["brand"]
    account = _ensure_voucher_account(store, brand, record["purchased_at"])

    txn = Transaction(
        id=f"{PURCHASE_ID_PREFIX}{record['code']}",
        date=record["purchased_at"],
        amount=record["value"],
        direction=Direction.CREDIT,
        description_raw=f"GYFTR voucher purchase - {brand}",
        account=account,
        category="Transfers",
        is_transfer=True,
        stage=Stage.STRUCTURAL,
        confidence=1.0,
        status=Status.CONFIRMED,
    )
    store.upsert_transactions([txn])

    linked = set(store.transfer_link_map().keys())
    candidates = [
        t for t in store.all_transactions()
        if t.direction == Direction.DEBIT
        and not t.account.startswith("voucher-")
        and t.id not in linked
        and abs(t.amount - record["value"]) < 0.01
        and abs((t.date - record["purchased_at"]).days) <= LINK_WINDOW_DAYS
    ]
    if len(candidates) == 1:
        store.link_transfer(candidates[0].id, txn.id, confidence="auto")

    return txn.id


# Payment-rail strings confirmed to mean "a real bank transaction already
# covers this" -- matched case-insensitively against a spend record's
# paid_via. Anything else (a voucher/wallet-branded value, or None) falls
# through to the bank cross-check below, which is the authoritative
# signal either way (per the user: "there will be an HDFC transaction if
# paid by card, else it'll be using GYFTR coupons").
KNOWN_REAL_PAYMENT_RAILS = {"credit/debit card", "credit card", "debit card",
                            "upi", "netbanking"}

# category is deterministic for these two sources -- Swiggy/Instamart
# order emails don't carry enough merchant detail for the normal
# classification pipeline to do better than guess. Amazon Pay's merchant
# varies too widely for a fixed category, so it goes through Pipeline
# instead (see import_spend).
FIXED_CATEGORY_BY_SOURCE = {"swiggy_order": "Dining", "instamart_order": "Groceries"}

# Date-window for deciding a spend record already has a matching real
# bank transaction -- covers order-date vs. settlement-date lag.
BANK_MATCH_WINDOW_DAYS = 2


def _has_matching_bank_txn(store: Store, amount: float, when: date,
                           window_days: int = BANK_MATCH_WINDOW_DAYS) -> bool:
    return any(
        t.direction == Direction.DEBIT
        and not t.account.startswith("voucher-")
        and abs(t.amount - amount) < 0.01
        and abs((t.date - when).days) <= window_days
        for t in store.all_transactions()
    )


def import_spend(store: Store, record: dict, pipeline: Pipeline | None = None) -> str | None:
    """record: {"kind": "spend", "brand": str, "source": str,
    "amount": float, "merchant": str, "order_id": str, "order_date":
    date, "paid_via": str | None}. Returns the created transaction id,
    or None if this spend is already covered by a real bank transaction
    (skipped, nothing created).

    `pipeline`, if given, is reused for Amazon Pay's classification pass
    instead of constructing a fresh `Pipeline(store)` -- Pipeline.__init__
    is expensive (loads the fallback ML model from disk, rebuilds the
    merchant-memory matcher), so a caller looping over many records (e.g.
    `munim vouchers import`/`recheck`) should build one Pipeline once and
    pass it in. Omitted, a single-call caller gets today's behavior
    unchanged (a Pipeline is constructed locally, once)."""
    paid_via = (record.get("paid_via") or "").strip().lower()
    if paid_via in KNOWN_REAL_PAYMENT_RAILS:
        return None
    if _has_matching_bank_txn(store, record["amount"], record["order_date"]):
        return None

    account = _ensure_voucher_account(store, record["brand"], record["order_date"])
    txn = Transaction(
        id=f"{REDEMPTION_ID_PREFIX}{record['order_id']}",
        date=record["order_date"],
        amount=record["amount"],
        direction=Direction.DEBIT,
        # description_raw is the bare merchant name, not an annotated
        # string like "Zomato (via ... voucher)" -- for the Amazon Pay
        # case this text goes straight through Pipeline/Normalizer, which
        # expects real-narration-shaped input, and annotation text risks
        # polluting the extracted merchant_norm so an existing "ZOMATO"
        # memory rule no longer matches. The voucher-<brand> account
        # already conveys "this was a voucher redemption" on its own.
        description_raw=record["merchant"],
        account=account,
    )

    fixed_category = FIXED_CATEGORY_BY_SOURCE.get(record["source"])
    if fixed_category:
        txn.category = fixed_category
        txn.stage = Stage.STRUCTURAL
        txn.confidence = 1.0
        txn.status = Status.CONFIRMED
    else:
        (pipeline or Pipeline(store)).run([txn])

    store.upsert_transactions([txn])
    return txn.id


def recheck(store: Store) -> dict:
    """Deletes every existing SYNTHETIC transaction this module itself
    generated (id prefixed PURCHASE_ID_PREFIX or REDEMPTION_ID_PREFIX --
    NOT every transaction on a voucher-<brand> account, since a user can
    hand-enter a manual transaction there too, following the same
    double-entry pattern documented for house-sgs, and that must survive
    a recheck untouched), then replays the full voucher_records log
    (persisted by `munim vouchers import`) from scratch against the
    CURRENT set of real bank transactions. Safe to run any time --
    corrects any earlier "no matching bank transaction, must be
    voucher-funded" guess that was only true because that period's bank
    statement hadn't been imported yet when the guess was originally
    made.

    Returns {"checked": len(voucher_records), "removed_existing": N,
    "created": N} -- created counts new/recreated transactions across
    both purchases and non-skipped redemptions."""
    removed_existing = 0
    for t in store.all_transactions():
        if t.id.startswith(PURCHASE_ID_PREFIX) or t.id.startswith(REDEMPTION_ID_PREFIX):
            store.delete_transaction(t.id)
            removed_existing += 1

    records = store.get_config("voucher_records", []) or []
    pipeline = Pipeline(store)
    created = 0
    for record in records:
        if record["kind"] == "purchase":
            live_record = {**record, "purchased_at": date.fromisoformat(record["purchased_at"])}
            import_purchase(store, live_record)
            created += 1
        else:
            live_record = {**record, "order_date": date.fromisoformat(record["order_date"])}
            if import_spend(store, live_record, pipeline=pipeline) is not None:
                created += 1

    return {"checked": len(records), "removed_existing": removed_existing, "created": created}
