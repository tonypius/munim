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
    transactions are simply absent from both lists.

    A debit's match is "auto" only if it has exactly one candidate credit
    AND that credit is not also a candidate for any other debit -- a
    credit claimed by two different debits is exactly the case the system
    cannot tell apart, so both pairings go to "ambiguous" instead.
    """
    linked = set(store.transfer_link_map().keys())
    dismissed = store.dismissed_ids()

    def eligible(t):
        return t.is_transfer and t.id not in linked and t.id not in dismissed

    txns = [t for t in store.all_transactions() if eligible(t)]
    debits = [t for t in txns if t.direction == Direction.DEBIT]
    credits = [t for t in txns if t.direction == Direction.CREDIT]

    def candidates_for(d):
        return [c.id for c in credits
                if c.account != d.account
                and abs(c.amount - d.amount) < 0.01
                and abs((c.date - d.date).days) <= MIRROR_WINDOW_DAYS]

    debit_matches = {d.id: candidates_for(d) for d in debits}

    credit_claim_count: dict[str, int] = {}
    for matches in debit_matches.values():
        for cid in matches:
            credit_claim_count[cid] = credit_claim_count.get(cid, 0) + 1

    auto = []
    ambiguous = []
    for d in debits:
        matches = debit_matches[d.id]
        if len(matches) == 1 and credit_claim_count[matches[0]] == 1:
            auto.append((d.id, matches[0]))
        elif matches:
            ambiguous.append((d.id, matches))

    return {"auto": auto, "ambiguous": ambiguous}


def apply_auto_links(store) -> int:
    """Find and record every exact, unambiguous transfer pair. Returns
    the number of pairs linked."""
    candidates = find_transfer_candidates(store)
    for debit_id, credit_id in candidates["auto"]:
        store.link_transfer(debit_id, credit_id, confidence="auto")
    return len(candidates["auto"])
