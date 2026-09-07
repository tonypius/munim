"""Cross-import transfer-pair matching: finds candidate links among
currently-unlinked is_transfer transactions in the store, spanning ALL
past imports -- not just one Pipeline.run() batch, which is what
structural/transfers.py's own mirror-matching is limited to. Reuses that
module's MIRROR_WINDOW_DAYS for the date-window heuristic, applied
across the whole database instead of one batch.
"""
from __future__ import annotations

from ..schema import Direction
from .transfers import MIRROR_WINDOW_DAYS


def find_transfer_candidates(store) -> dict:
    """Read-only: compute which unlinked, undismissed is_transfer
    transactions could pair up. Returns {"auto": [(debit_id, credit_id)],
    "ambiguous": [(debit_id, [credit_id, ...])]} -- zero-candidate
    transactions are simply absent from both lists."""
    linked = set(store.transfer_link_map().keys())
    dismissed = store.dismissed_ids()

    def eligible(t):
        return t.is_transfer and t.id not in linked and t.id not in dismissed

    txns = [t for t in store.all_transactions() if eligible(t)]
    debits = [t for t in txns if t.direction == Direction.DEBIT]
    credits = [t for t in txns if t.direction == Direction.CREDIT]

    auto = []
    ambiguous = []
    for d in debits:
        matches = [c.id for c in credits
                  if c.account != d.account
                  and abs(c.amount - d.amount) < 0.01
                  and abs((c.date - d.date).days) <= MIRROR_WINDOW_DAYS]
        if len(matches) == 1:
            auto.append((d.id, matches[0]))
        elif len(matches) > 1:
            ambiguous.append((d.id, matches))

    return {"auto": auto, "ambiguous": ambiguous}
