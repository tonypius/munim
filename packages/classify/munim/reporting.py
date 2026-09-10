"""Generic chart-data aggregation, shared by the Dashboard tab and
on-the-go conversational charts (see docs/superpowers/specs/
2026-09-10-chart-engine-design.md). Pure functions only -- no HTTP, no
direct SQL access -- testable against a plain list of Transaction
objects, the same way balance_sheet.py's compute_account_balance() is.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as Date

from .schema import Direction, Transaction
from .store import Store

_VALID_GROUP_BY = ("month", "category", "subcategory", "merchant", "account")


def flow_query(
    txns: list[Transaction],
    group_by: str,
    *,
    direction: str = "",
    exclude_transfers: bool = True,
    account: str = "",
    category: str = "",
    subcategory: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Sums `amount` across `txns` grouped by `group_by`, after applying
    every given filter. Returns [{"label": str, "value": float}, ...] --
    chronologically sorted for group_by="month", by descending value
    otherwise (so a "top N" caller gets that ordering for free without a
    separate sort step).

    `exclude_transfers=True` (the default) matches _dashboard()'s
    existing spend calculation exactly (`t.direction == "debit" and not
    t.is_transfer`) -- pass `exclude_transfers=False` for a caller that
    genuinely wants transfers included (e.g. a raw account-activity
    view). Raises ValueError for an unrecognized `group_by`.
    """
    if group_by not in _VALID_GROUP_BY:
        raise ValueError(f"Unknown group_by {group_by!r}; expected one of {_VALID_GROUP_BY}")

    d_from = Date.fromisoformat(date_from) if date_from else None
    d_to = Date.fromisoformat(date_to) if date_to else None

    totals: dict[str, float] = defaultdict(float)
    for t in txns:
        if exclude_transfers and t.is_transfer:
            continue
        if direction and t.direction.value != direction:
            continue
        if account and t.account != account:
            continue
        if category and t.category != category:
            continue
        if subcategory and t.subcategory != subcategory:
            continue
        if d_from and t.date < d_from:
            continue
        if d_to and t.date > d_to:
            continue

        if group_by == "month":
            label = t.date.isoformat()[:7]
        elif group_by == "category":
            label = t.category or "(uncategorized)"
        elif group_by == "subcategory":
            label = t.subcategory or "(none)"
        elif group_by == "merchant":
            label = t.merchant_norm or t.payee_handle or "(unknown)"
        else:  # "account"
            label = t.account
        totals[label] += t.amount

    rows = [{"label": k, "value": v} for k, v in totals.items()]
    if group_by == "month":
        rows.sort(key=lambda r: r["label"])
    else:
        rows.sort(key=lambda r: -r["value"])
    return rows
