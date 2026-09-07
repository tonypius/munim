"""Balance-sheet computation: an account's current balance, derived from
a manually-entered opening balance plus every transaction since. Cost-
basis, not market-value -- see the design spec's non-goals for why live
pricing is out of scope for this project.
"""
from __future__ import annotations

from datetime import date as Date

from .schema import Direction


def compute_account_balance(store, account: str, transactions=None) -> float | None:
    """Returns the account's current balance, or None if no opening
    balance has been set for it (see `munim accounts
    set-opening-balance`). Assets: credit increases the balance, debit
    decreases it. Liabilities: inverted -- the statement's "balance" is
    what's owed, so a debit (purchase) increases it and a credit
    (payment) decreases it. A transaction dated exactly on the opening
    balance's as_of date is included in the delta, not excluded.

    `transactions`, if given, is used instead of a fresh
    `store.all_transactions()` scan -- callers that already have the
    account's transactions (or the full list) on hand should pass them to
    avoid a redundant full-table scan per account."""
    balances = store.get_config("account_opening_balances", {}) or {}
    entry = balances.get(account)
    if entry is None:
        return None
    opening = entry["balance"]
    as_of = Date.fromisoformat(entry["as_of"])

    account_types = store.get_config("account_types", {}) or {}
    is_liability = account_types.get(account, "Assets") == "Liabilities"

    debit_total = credit_total = 0.0
    txns = transactions if transactions is not None else store.all_transactions()
    for t in txns:
        if t.account != account or t.date < as_of:
            continue
        if t.direction == Direction.DEBIT:
            debit_total += t.amount
        else:
            credit_total += t.amount

    if is_liability:
        return opening + debit_total - credit_total
    return opening + credit_total - debit_total
