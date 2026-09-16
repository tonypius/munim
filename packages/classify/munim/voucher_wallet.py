"""Turns parsed voucher-purchase/redemption records (from
munim_ingest.voucher_parse) into real Transaction rows on auto-created
voucher-<brand> virtual Assets accounts -- the same double-entry
pattern already used for house-sgs. See
docs/superpowers/specs/2026-09-16-voucher-redemption-tracking-design.md.
"""
from __future__ import annotations

from datetime import date

from .schema import Direction, Stage, Status, Transaction
from .store import Store

# How many days apart a voucher purchase's card debit can be from the
# GYFTR purchase-confirmation email's own date and still be considered
# the same real-world event -- covers card-network posting lag.
LINK_WINDOW_DAYS = 5


def import_purchase(store: Store, record: dict) -> str:
    """record: {"kind": "purchase", "brand": str, "value": float,
    "code": str, "purchased_at": date}. Creates (or, on rerun,
    idempotently finds) a credit transaction on voucher-<brand> for the
    voucher's face value, links it to the one unambiguous matching real
    card debit if exactly one exists, and returns the transaction id."""
    brand = record["brand"]
    account = f"voucher-{brand}"

    account_types = store.get_config("account_types", {}) or {}
    if account not in account_types:
        account_types[account] = "Assets"
        store.set_config("account_types", account_types)

    txn = Transaction(
        id=f"voucher-purchase-{record['code']}",
        date=record["purchased_at"],
        amount=record["value"],
        direction=Direction.CREDIT,
        description_raw=f"GYFTR voucher purchase - {brand}",
        account=account,
        category="Transfers",
        stage=Stage.STRUCTURAL,
        confidence=1.0,
        status=Status.PROVISIONAL,
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


def import_spend(store: Store, record: dict) -> str | None:
    """record: {"kind": "spend", "brand": str, "source": str,
    "amount": float, "merchant": str, "order_id": str, "order_date":
    date, "paid_via": str | None}. Returns the created transaction id,
    or None if this spend is already covered by a real bank transaction
    (skipped, nothing created)."""
    paid_via = (record.get("paid_via") or "").strip().lower()
    if paid_via in KNOWN_REAL_PAYMENT_RAILS:
        return None
    if _has_matching_bank_txn(store, record["amount"], record["order_date"]):
        return None

    account = f"voucher-{record['brand']}"
    txn = Transaction(
        id=f"voucher-redemption-{record['order_id']}",
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
        txn.status = Status.PROVISIONAL
    else:
        from .pipeline import Pipeline
        Pipeline(store).run([txn])

    store.upsert_transactions([txn])
    return txn.id


def recheck(store: Store) -> dict:
    """Deletes every existing synthetic transaction on voucher-<brand>
    accounts, then replays the full voucher_records log (persisted by
    `munim vouchers import`) from scratch against the CURRENT set of
    real bank transactions. Safe to run any time -- corrects any earlier
    "no matching bank transaction, must be voucher-funded" guess that
    was only true because that period's bank statement hadn't been
    imported yet when the guess was originally made.

    Returns {"checked": len(voucher_records), "removed_existing": N,
    "created": N} -- created counts new/recreated transactions across
    both purchases and non-skipped redemptions."""
    removed_existing = 0
    for t in store.all_transactions():
        if t.account.startswith("voucher-"):
            store.delete_transaction(t.id)
            removed_existing += 1

    records = store.get_config("voucher_records", []) or []
    created = 0
    for record in records:
        if record["kind"] == "purchase":
            live_record = {**record, "purchased_at": date.fromisoformat(record["purchased_at"])}
            import_purchase(store, live_record)
            created += 1
        else:
            live_record = {**record, "order_date": date.fromisoformat(record["order_date"])}
            if import_spend(store, live_record) is not None:
                created += 1

    return {"checked": len(records), "removed_existing": removed_existing, "created": created}
