"""South Indian Bank's emailed yearly "Statement of Account" PDF — a
different source and format from the netbanking "Transaction History"
CSV export sib_account.py handles. pdfplumber finds no ruled table here
at all (a borderless, position-only layout): a row's own Withdrawals/
Deposits/Balance figures sit on their own physical line, BETWEEN the two
fragments of a wrapped Particulars narration — e.g. a real row renders
as "01-04-25 NACH_DR/.../CAMS" / "500.00 20,389.49Cr" / "LTD/ACH_DR",
three separate lines for one transaction. Shorter narrations that don't
wrap put everything on a single line instead — row height varies row to
row. This module reads each page's extract_words() and clusters by each
word's vertical distance to the nearest date, the same technique
sbi_credit_card.py uses for a structurally similar problem: a
text-stream/line-scan has no way to know a fragment belongs to a
not-yet-seen (or already-passed) row, but clustering by position doesn't
care which physical line a word landed on.

Column x-positions are read from each word's own (x0, top), not
hardcoded to an exact pixel — only four cutoffs are hardcoded, each a
wide safety margin against the 55-90pt gaps observed between real
column bands (date/particulars/withdrawals/deposits/balance), not a
tight boundary: a coincidental amount-shaped or date-shaped substring
inside a narration is what these guard against, not real column
variation.

A large vertical gap (real statements: ~45pt) separates the last real
transaction on a page from its "Page Total : ..." summary row — well
past the half-row margin used to bound a page's first/last transaction,
so that row is never mistaken for a transaction of its own nor swept
into the last real one.

Verified against a real statement (password-verified 2026-09-09,
36 pages, covering 01-04-2025 to 31-03-2026): this module's running
balance (opening balance + cumulative signed amount) matches the PDF's
own Balance column for every row on every sampled page, and the
statement's own opening balance exactly equals the closing balance
already on file from the netbanking CSV export covering the prior
period (sib_account.py) — no gap, no overlap.

This statement's own "DD-MM-YY" dates are normalized to "DD-Mon-YYYY"
here (rather than left as-is) so this module's CSV output matches
sib_account.py's date shape exactly — both bank flags can then share
one munim `csv_profiles` entry instead of needing two.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")
_BALANCE_RE = re.compile(r"^[\d,]+\.\d{2}(Cr|Dr)$")

HEADER_ROW = ["Date", "Particulars", "Amount"]

# A date word never legitimately appears anywhere but the leftmost
# column.
_DATE_COLUMN_MAX_X0 = 30.0

# Withdrawals: observed ~360-380. Deposits: observed ~450-465. Both
# cutoffs sit in the wide (55-90pt) gaps either side of those bands.
_WITHDRAWAL_MIN_X0 = 340.0
_WITHDRAWAL_MAX_X0 = 420.0
_DEPOSIT_MIN_X0 = 420.0
_DEPOSIT_MAX_X0 = 505.0
_BALANCE_MIN_X0 = 505.0

# Half of one normal (unwrapped) row's vertical span — used only to
# bound the very first and last transaction's cluster on a page, where
# there's no neighboring date on that side to take a true midpoint
# against. Comfortably smaller than the ~45pt gap before a page's
# trailing "Page Total" row, so that row is never swept in.
_ROW_HALF_HEIGHT = 12.0


def _parse_page(words: list[dict]) -> list[tuple[str, str, str]]:
    dates = sorted(
        (w for w in words if _DATE_RE.match(w["text"]) and w["x0"] < _DATE_COLUMN_MAX_X0),
        key=lambda w: w["top"])
    if not dates:
        return []
    n = len(dates)
    result = []
    for i, d in enumerate(dates):
        lo = (dates[i - 1]["top"] + d["top"]) / 2 if i > 0 else d["top"] - _ROW_HALF_HEIGHT
        hi = (d["top"] + dates[i + 1]["top"]) / 2 if i < n - 1 else d["top"] + _ROW_HALF_HEIGHT
        cluster = [w for w in words if lo <= w["top"] < hi]
        cluster.sort(key=lambda w: (round(w["top"]), w["x0"]))
        desc_words: list[str] = []
        withdrawal: str | None = None
        deposit: str | None = None
        for w in cluster:
            if w is d:
                continue
            text = w["text"]
            if _AMOUNT_RE.match(text) and _WITHDRAWAL_MIN_X0 <= w["x0"] < _WITHDRAWAL_MAX_X0:
                withdrawal = text
            elif _AMOUNT_RE.match(text) and _DEPOSIT_MIN_X0 <= w["x0"] < _DEPOSIT_MAX_X0:
                deposit = text
            elif _BALANCE_RE.match(text) and w["x0"] >= _BALANCE_MIN_X0:
                continue  # running balance isn't part of munim's expected output
            else:
                desc_words.append(text)
        if withdrawal is None and deposit is None:
            continue
        w_amt = float(withdrawal.replace(",", "")) if withdrawal else 0.0
        d_amt = float(deposit.replace(",", "")) if deposit else 0.0
        signed = d_amt - w_amt
        date = datetime.strptime(d["text"], "%d-%m-%y").strftime("%d-%b-%Y")
        result.append((date, " ".join(desc_words), f"{signed:.2f}"))
    return result


def parse_transactions(pages) -> list[tuple[str, str, str]]:
    """Parses a SIB yearly statement PDF's pages (pdfplumber Page
    objects, or anything exposing the same `.extract_words()` interface)
    into (date, description, signed amount) tuples — negative for a
    Withdrawal row, positive for a Deposit row, munim's expected single-
    signed-amount-column convention.

    An exact (date, description, amount) repeat — across pages, since a
    same-day repeat can span a page boundary — gets its 2nd+ occurrence
    suffixed " (N)". This account runs several HDFC MF SIPs that debit
    the identical ₹500 via the same NACH batch on the same day with no
    per-instance reference in the narration (241 such repeat groups in
    one real 599-transaction statement); left alone, munim's
    content-hash dedup would silently collapse each pair into one,
    losing real money."""
    parsed = []
    for page in pages:
        words = page.extract_words()
        if words:
            parsed.extend(_parse_page(words))

    seen: Counter = Counter()
    result = []
    for date_str, desc, signed_str in parsed:
        key = (date_str, desc, signed_str)
        seen[key] += 1
        if seen[key] > 1:
            desc = f"{desc} ({seen[key]})"
        result.append((date_str, desc, signed_str))
    return result
