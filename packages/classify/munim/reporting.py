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

    `exclude_transfers=True` (the default) reproduces the
    transfer-exclusion half of _dashboard()'s existing spend filter
    (`not t.is_transfer`) -- pass `exclude_transfers=False` for a caller
    that genuinely wants transfers included (e.g. a raw account-activity
    view). This does NOT by itself reproduce _dashboard()'s full spend
    calculation: `direction` defaults to "" (both debit and credit
    summed together), so a caller wanting the full spend-only behavior
    (`t.direction == "debit" and not t.is_transfer`) must also pass
    `direction="debit"` explicitly. Raises ValueError for an
    unrecognized `group_by`.
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


def balance_series(
    store: Store,
    accounts: list[str] | None = None,
    *,
    group_by: str = "month",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Returns [{"label": "YYYY-MM", "value": float}, ...] -- the combined
    balance across every account in `accounts` at each month's end.

    `accounts=None` means "every account with a known opening balance"
    (used for the Dashboard's net-worth-over-time panel). An account
    named in `accounts` but with no opening balance set is silently
    excluded -- like compute_account_balance(), there is no defined
    starting point to walk forward from for it.

    Each tracked account's own running balance uses the same convention
    compute_account_balance() does (Assets: credit grows it, debit
    shrinks it; Liabilities: inverted, since the balance there represents
    what's owed). When several accounts are combined into one series, a
    Liabilities account's contribution is NEGATED before summing --
    owing money reduces net worth, it doesn't add to it.

    The reported range starts at the LATEST opening-balance `as_of`
    month across every tracked account, never earlier -- this guarantees
    every reported month has a complete combined number with no account
    silently missing from it, rather than showing an undercounted total
    for a period before every account had a known starting point.
    `date_from`/`date_to` narrow the range further; they never widen it
    past that floor or past the latest known transaction date.
    """
    if group_by != "month":
        raise ValueError(f"balance_series only supports group_by='month', got {group_by!r}")

    account_types = store.get_config("account_types", {}) or {}
    opening_balances = store.get_config("account_opening_balances", {}) or {}

    if accounts is None:
        accounts = list(opening_balances.keys())

    tracked = [a for a in accounts if a in opening_balances]
    if not tracked:
        return []

    all_txns = store.all_transactions()
    account_txns = {
        a: sorted(
            (t for t in all_txns if t.account == a
             and t.date >= Date.fromisoformat(opening_balances[a]["as_of"])),
            key=lambda t: t.date)
        for a in tracked
    }

    start = max(Date.fromisoformat(opening_balances[a]["as_of"]) for a in tracked)
    if date_from:
        start = max(start, Date.fromisoformat(date_from))

    txn_dates = [t.date for txns in account_txns.values() for t in txns]
    end = max([start, *txn_dates])
    if date_to:
        end = min(end, Date.fromisoformat(date_to))
    if end < start:
        return []

    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1

    combined = {mo: 0.0 for mo in months}
    for a in tracked:
        running = opening_balances[a]["balance"]
        is_liability = account_types.get(a, "Assets") == "Liabilities"
        txns_sorted = account_txns[a]
        idx = 0
        for mo in months:
            mo_y, mo_m = int(mo[:4]), int(mo[5:7])
            while (idx < len(txns_sorted)
                   and (txns_sorted[idx].date.year, txns_sorted[idx].date.month) <= (mo_y, mo_m)):
                t = txns_sorted[idx]
                if is_liability:
                    running += t.amount if t.direction == Direction.DEBIT else -t.amount
                else:
                    running += t.amount if t.direction == Direction.CREDIT else -t.amount
                idx += 1
            combined[mo] += -running if is_liability else running

    return [{"label": mo, "value": combined[mo]} for mo in months]
