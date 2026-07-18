"""Stage 3b: recurrence detection.

Same merchant + similar amount + near-regular interval => recurring
(subscription, rent, EMI, salary). High precision, huge user value.
Tags only — the category still comes from memory/dictionary/user.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from ..schema import Transaction

AMOUNT_TOLERANCE = 0.05      # +-5%
PERIODS_DAYS = (7, 14, 30, 31, 365)
PERIOD_JITTER = 4            # days of slack around the expected period
MIN_OCCURRENCES = 3


def detect_recurrence(txns: list[Transaction]) -> None:
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txns:
        key = t.merchant_norm or t.payee_handle
        if key:
            groups[(key, t.direction)].append(t)

    for group in groups.values():
        if len(group) < MIN_OCCURRENCES:
            continue
        group.sort(key=lambda t: t.date)
        med_amount = median(t.amount for t in group)
        similar = [t for t in group
                   if abs(t.amount - med_amount) <= AMOUNT_TOLERANCE * med_amount]
        if len(similar) < MIN_OCCURRENCES:
            continue
        gaps = [(similar[i + 1].date - similar[i].date).days
                for i in range(len(similar) - 1)]
        med_gap = median(gaps)
        if any(abs(med_gap - p) <= PERIOD_JITTER for p in PERIODS_DAYS):
            for t in similar:
                t.is_recurring = True
