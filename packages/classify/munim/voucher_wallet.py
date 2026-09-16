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
