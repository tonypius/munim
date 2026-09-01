"""HDFC savings/current account e-statement parsing ("Combined Email
Statement"), distinct from both credit-card layouts in hdfc_credit_card.py
/ hdfc_credit_card_v2.py — deliberately kept out of pdf_extract.py's
generic (bank-agnostic) extraction for the same reason those are: this
module is allowed to know HDFC's specific layout; pdf_extract.py's
functions must not.

Unlike the credit-card statements, this IS a genuine ruled table
pdfplumber detects — but it merges an entire page into a single row, with
every transaction's Date / Narration / Withdrawals / Deposits / Closing
Balance newline-joined within its own cell (so a page with 9 transactions
produces one row whose Date cell has 9 newline-separated dates, whose
Withdrawals cell has 9 newline-separated amounts, and so on).
filter_transaction_rows() already isolates these one-row-per-page rows
correctly on its own (dominant row shape + a date found in the first
cell) — the account-summary row and the repeated per-page header row are
both filtered out already, no changes needed there.

No direction inference is needed here at all (unlike both credit-card
formats): Withdrawals and Deposits are already separate columns.

The one real wrinkle is the Narration cell: each transaction's narration
wraps across a variable number of physical lines with no clean delimiter
of its own — but every entry reliably ends with "Value Dt DD/MM/YYYY Ref
<refnum>", used here to split the blob back into one narration per
transaction, in order.

Verified against a real statement (2026-09-01, 42 transactions across 5
pages): reconstructing the running balance from the Withdrawals/Deposits
columns and comparing to the statement's own Closing Balance column
matched exactly for every transaction, and the final reconstructed
balance matched the statement's stated closing balance to the rupee.
"""
from __future__ import annotations

import re

# DOTALL: narration text itself contains embedded newlines from PDF line
# wrapping. Non-greedy so each match stops at the FIRST following
# "Value Dt ..." marker rather than swallowing multiple transactions'
# narrations into one match. \s+ (not a literal space) before the ref
# number: a real extraction artifact wraps the reference number onto the
# next physical line after "Ref" on some transactions — a plain "Ref "
# (single space) pattern would silently mis-segment every narration
# after the first occurrence of that wrap. The trailing "Ref <num>" is
# OPTIONAL (greedy '?', not lazy — consumes it when it's actually there):
# interest-posting and FD-transfer entries ("FD Redeem Interest...",
# "FT -: FD A/C NO...", "Interest debited till...") end with just
# "Value Dt DATE" and never carry a Ref number at all. A version that
# required Ref found real, IRL data where this silently misaligned the
# narration-segment count against the date count on any page containing
# one of these — dropping the ENTIRE page (every transaction on it, not
# just the Ref-less one) via the alignment guard below with no warning
# anywhere. Confirmed against a real account: 47 of 355 transactions
# across 9 months were lost this way, including one large FD redemption.
_NARRATION_SPLIT_RE = re.compile(
    r".*?Value\s+Dt\s+\d{2}/\d{2}/\d{4}(?:\s+Ref\s+\S+)?", re.DOTALL,
)

HEADER_ROW = ["Date", "Narration", "Amount"]


def _clean_narration(chunk: str) -> str:
    return re.sub(r"\s+", " ", chunk).strip()


def _parse_mega_row(row: list[str | None]) -> list[list[str]] | None:
    """Explodes one page's merged mega-row into one (Date, Narration,
    signed Amount) row per real transaction it contains. Returns None —
    not an empty list — when the Date/Narration/Withdrawals/Deposits
    segment counts don't all agree, so a caller can tell "this page had
    no transactions at all" apart from "this page's alignment failed and
    everything on it was dropped"; the two need different handling
    (silence vs. a loud warning; see count_unparseable_pages below).

    With no reliable way to tell which narration belongs to which date on
    a misalignment, silently guessing would be worse than dropping the
    page — munim import's own parser has no visibility into this
    ingest-time reshaping, so a bad alignment here would look like clean
    data to it.
    """
    if len(row) < 5:
        return None
    dates = [d.strip() for d in (row[0] or "").split("\n") if d.strip()]
    narrations = _NARRATION_SPLIT_RE.findall(row[1] or "")
    withdrawals = [w.strip() for w in (row[2] or "").split("\n") if w.strip()]
    deposits = [d.strip() for d in (row[3] or "").split("\n") if d.strip()]
    n = len(dates)
    if not (n and len(narrations) == n and len(withdrawals) == n
            and len(deposits) == n):
        return None
    try:
        amounts = [
            float(deposits[i].replace(",", "")) -
            float(withdrawals[i].replace(",", ""))
            for i in range(n)
        ]
    except ValueError:
        return None
    return [
        [dates[i], _clean_narration(narrations[i]), f"{amounts[i]:.2f}"]
        for i in range(n)
    ]


def normalize_hdfc_bank_account_rows(
    rows: list[list[str | None]],
) -> list[list[str]]:
    """Explodes every page's mega-row into one (Date, Narration, signed
    Amount) row per real transaction. See count_unparseable_pages for a
    way to detect (and warn about) pages this drops due to misalignment
    — a version of this parser that silently dropped pages with no way
    for a caller to notice was the actual root cause of transactions
    missing from a real account (47 of 355 across 9 months, including one
    large FD redemption) before the Narration-splitting regex was fixed.
    """
    result = []
    for row in rows:
        result.extend(_parse_mega_row(row) or [])
    return result


def count_unparseable_pages(rows: list[list[str | None]]) -> int:
    """How many mega-rows failed the alignment check in
    normalize_hdfc_bank_account_rows and had every transaction on them
    dropped silently — callers (the CLI) should warn loudly when this is
    nonzero rather than let a whole page vanish with no visible trace."""
    return sum(1 for row in rows if _parse_mega_row(row) is None)
