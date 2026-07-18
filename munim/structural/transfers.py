"""Stage 3a: transfer & self-payment detection.

The #1 source of garbage in personal finance: credit card bill payments,
moving money to savings, wallet top-ups. These are NOT spending and must
never be categorized as such (double counting).

Two signals, both high-precision:
  1. Keyword markers in the description (CC payment, own-account transfer).
  2. Mirror matching: a debit in account A matched by an equal credit in
     account B within a small date window.
"""
from __future__ import annotations

import re
from datetime import timedelta

from ..schema import Transaction, Direction, Stage, Status

TRANSFER_MARKERS = re.compile(
    r"\b(CREDIT\s*CARD\s*(?:PAYMENT|BILL)|CC\s*PAYMENT|BILLDESK.*CARD|"
    r"OWN\s*ACCOUNT|SELF\s*TRANSFER|AUTO\s*SWEEP|RD\s*INSTALLMENT|"
    r"FD\s*BOOKING|WALLET\s*(?:TOP\s*UP|LOAD)|ADD\s*MONEY)\b",
    re.IGNORECASE,
)
MIRROR_WINDOW_DAYS = 3


def detect_transfers(txns: list[Transaction]) -> None:
    """Mutates txns in place: sets is_transfer + category='Transfers'."""
    for t in txns:
        if TRANSFER_MARKERS.search(t.description_raw):
            _mark(t)

    # Mirror matching across the user's own accounts
    debits = [t for t in txns if t.direction == Direction.DEBIT and not t.is_transfer]
    credits = [t for t in txns if t.direction == Direction.CREDIT and not t.is_transfer]
    used: set[str] = set()
    for d in debits:
        for c in credits:
            if c.id in used or c.account == d.account:
                continue
            if abs(c.amount - d.amount) < 0.01 and \
               abs((c.date - d.date).days) <= MIRROR_WINDOW_DAYS:
                _mark(d)
                _mark(c)
                used.add(c.id)
                break


def _mark(t: Transaction) -> None:
    t.is_transfer = True
    t.category = "Transfers"
    t.stage = Stage.STRUCTURAL
    t.confidence = 0.98
    t.status = Status.PROVISIONAL
