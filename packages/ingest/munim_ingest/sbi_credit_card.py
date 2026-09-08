"""SBI Elite credit card 'Transaction History' export — a from-Gmail or
self-service download, not a monthly billing statement PDF. Its own
"Date Description Type Amount" column header renders as a small ruled
table via pdfplumber — but ONLY that header, never the transaction rows
themselves, which sit in each page's plain, unruled text instead. This
makes pdf_extract.py's generic extract_rows() actively wrong for this
bank: finding any ruled table anywhere in the document (the header) makes
it return ONLY that table and skip every real transaction on every page.
This module bypasses extract_rows()/filter_transaction_rows() entirely
and works from pdfplumber's per-page extract_words() instead, using each
word's real (x0, top) position rather than the linear text-stream order
extract_text() would give.

That distinction is not cosmetic — it's the actual bug that motivated
this design. A first attempt used a plain regex against extract_text()'s
linear output, tuned against pypdf's text ordering. It silently dropped
or corrupted roughly 20% of transactions when run against pdfplumber's
own text order instead, because pdfplumber reorders a WRAPPED row's
tokens: a long merchant name/URL splits into an initial fragment BEFORE
its own date/type/amount line, and a trailing fragment (often just the
"IN" country-code suffix) AFTER it — e.g. a real row physically renders
across three lines as "SKYROCKET BEVERAGES PR HYDERABAD" / "30/03/2024
Debit 62.00" / "IN", with the description's first half sitting ABOVE the
date it belongs to. A linear top-to-bottom scan (or a regex across the
concatenated text) has no way to know that first fragment belongs to the
NEXT date rather than the row already in progress. Clustering by actual
vertical position instead sidesteps the problem entirely: every word
whose `top` falls closer to one date than any other belongs to that
date's row, regardless of which line of the extracted text it happened
to land on.

Column x-positions are read from each transaction's own words (a `Debit`/
`Credit` word, or an amount-shaped one past a firm right-hand cutoff),
not hardcoded — the exact pixel positions were observed to shift by 10-40
points across different real exports (different periods produce slightly
different PDF layouts), so a fixed-column-boundary design would silently
break on some real statements. Only two absolute cutoffs are hardcoded,
both wide safety margins rather than tight boundaries: a date word is
only trusted if `x0` is comfortably in the left margin, and an amount
word is only trusted if `x0` is comfortably in the right margin — this
guards against a coincidental date- or amount-shaped substring inside a
merchant description or reference number being mistaken for the real
column.

Verified against three real statement exports spanning Dec 2022–Jun
2025: this module's output, deduplicated across the ~7-month overlap
between two of the three exports, matched — transaction-for-transaction,
byte-for-byte on every date/description/amount — a fully independent
extraction of the same three PDFs done by hand during development (which
had itself already been cross-checked: 718 unique transactions with zero
gaps in monthly coverage across the whole span, and one period's numbers
independently reconciled against a separate real statement's own opening
balance, matching it to the paisa). The only difference between the two
was this module's deliberate exclusion of 10 "Monthly Installments" rows
(EMI-schedule line items, always amount 0.00 — informational, not real
money movement).
"""
from __future__ import annotations

import re

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")

HEADER_ROW = ["Date", "Description", "Amount (in Rs.)"]

# A date word never legitimately appears anywhere but the leftmost
# column; this bound is generous enough to tolerate the cross-file
# column-position variation observed in real statements while still
# excluding a coincidental date-shaped substring far to the right, inside
# a merchant description.
_DATE_COLUMN_MAX_X0 = 100.0

# An amount word is always in the rightmost column; excludes a
# coincidental amount-shaped substring (e.g. part of a reference number)
# appearing inside a leftward merchant description.
_AMOUNT_COLUMN_MIN_X0 = 400.0

# Half of one normal row's vertical span, in PDF points — used only to
# bound the very first and last transaction's cluster on a page, where
# there's no neighboring date on that side to take a true midpoint
# against. A wrapped row's stray fragment sits within a few points of its
# own date; this margin is comfortably larger than that while staying
# well short of a full row's ~27pt height, so it can't reach into a
# genuinely different transaction.
_ROW_HALF_HEIGHT = 15.0


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
        # (top, x0) order reconstructs correct reading order within this
        # row's cluster regardless of which physical line each word came
        # from — the whole reason this module clusters by position
        # instead of trusting extract_text()'s linear stream order.
        cluster.sort(key=lambda w: (round(w["top"]), w["x0"]))
        desc_words: list[str] = []
        type_word: str | None = None
        amount_word: str | None = None
        for w in cluster:
            if w is d:
                continue
            text = w["text"]
            if text in ("Debit", "Credit"):
                type_word = text
            elif text in ("Monthly", "Installments"):
                type_word = "__skip__"  # EMI-schedule row, not a real transaction
            elif _AMOUNT_RE.match(text) and w["x0"] > _AMOUNT_COLUMN_MIN_X0:
                amount_word = text
            else:
                desc_words.append(text)
        if type_word not in ("Debit", "Credit") or amount_word is None:
            continue
        amount = float(amount_word.replace(",", ""))
        signed = amount if type_word == "Credit" else -amount
        result.append((d["text"], " ".join(desc_words), f"{signed:.2f}"))
    return result


def parse_transactions(pages) -> list[tuple[str, str, str]]:
    """Parses an SBI 'Transaction History' export's pages (pdfplumber
    Page objects, or anything exposing the same `.extract_words()`
    interface) into (date, description, signed amount) tuples — negative
    for Debit, positive for Credit, munim's expected single-signed-
    amount-column convention. 'Monthly Installments' rows are recognized
    (to correctly bound the transactions on either side of them) but
    never emitted."""
    result = []
    for page in pages:
        words = page.extract_words()
        if words:
            result.extend(_parse_page(words))
    return result
