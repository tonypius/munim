"""Downstream export formats. Munim classifies; these hand the results to
the tools that do budgeting, trends, and trajectories.

Deliberately simple, deliberately lossless-enough: every row carries
provenance (stage/status) where the format allows, so downstream tools can
distinguish ground truth from suggestions.
"""
from __future__ import annotations

import csv
import io
import json

from .schema import Transaction, Direction


def to_jsonl(txns: list[Transaction]) -> str:
    lines = []
    for t in txns:
        d = t.model_dump()
        d["date"] = t.date.isoformat()
        lines.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def to_ledger(txns: list[Transaction], tree: dict | None = None,
              account_types: dict | None = None) -> str:
    """Plain-text accounting format (ledger/hledger; beancount-convertible).

    Leaves resolve through the category tree (docs: categories are flat in
    the engine; the tree is a display mapping). Accounts post under Assets
    or Liabilities per `munim accounts type`. Transfers use the Transfers
    leaf's mapped path (default Equity:Transfers) as the counter-leg because
    Munim doesn't track the counterparty account.
    """
    from .tree import resolve, default_tree
    tree = tree or default_tree([])
    account_types = account_types or {}

    def acct_path(t: Transaction) -> str:
        return f"{account_types.get(t.account, 'Assets')}:{t.account}"

    out = []
    for t in sorted(txns, key=lambda x: x.date):
        payee = t.merchant_norm or t.payee_handle or t.description_raw[:48]
        path = resolve(tree, t.category).replace(" ", "-")
        date = t.date.strftime("%Y/%m/%d")
        note = f"    ; stage: {t.stage.value}, status: {t.status.value}"
        amt = f"{t.amount:.2f} {t.currency}"
        if t.is_transfer:
            counter = resolve(tree, "Transfers").replace(" ", "-")
            legs = [f"    {counter}    {amt}",
                    f"    {acct_path(t)}"]
            if t.direction == Direction.CREDIT:
                legs = [f"    {acct_path(t)}    {amt}",
                        f"    {counter}"]
        elif t.direction == Direction.DEBIT:
            legs = [f"    {path}    {amt}",
                    f"    {acct_path(t)}"]
        else:
            legs = [f"    {acct_path(t)}    {amt}",
                    f"    {path}"]
        out.append("\n".join([f"{date} {payee}", note, *legs]))
    return "\n\n".join(out) + "\n"


def to_firefly_csv(txns: list[Transaction]) -> str:
    """CSV shaped for the Firefly III Data Importer.

    Transfers are exported as withdrawals/deposits with category
    'Transfers' (Firefly's transfer type needs both asset accounts, which
    Munim doesn't track); Firefly's rules can reconcile them.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "type", "amount", "currency_code", "description",
                "category_name", "source_name", "destination_name",
                "notes", "tags"])
    for t in sorted(txns, key=lambda x: x.date):
        counter = t.merchant_norm or t.payee_handle or "(unknown)"
        tags = ",".join(filter(None, [
            "recurring" if t.is_recurring else "",
            "munim-provisional" if t.status.value != "confirmed" else "",
        ]))
        if t.direction == Direction.DEBIT:
            row_type, source, dest = "withdrawal", t.account, counter
        else:
            row_type, source, dest = "deposit", counter, t.account
        w.writerow([t.date.isoformat(), row_type, f"{t.amount:.2f}",
                    t.currency, t.description_raw,
                    t.category or "", source, dest,
                    f"classified_by={t.stage.value}", tags])
    return buf.getvalue()
