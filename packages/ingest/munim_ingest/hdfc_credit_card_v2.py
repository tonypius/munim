"""HDFC credit-card statement layout introduced around Sep 2025, after a
card-number upgrade on the same underlying account — a physically
different template from the one hdfc_credit_card.py handles.

Unlike the older layout, pdfplumber never finds a ruled transaction table
here at all: every transaction line arrives as its own single-column row
via the generic text-line fallback in pdf_extract.py, shaped
"DD/MM/YYYY| HH:MM DESCRIPTION [REWARDS] [+] C AMOUNT l". Deliberately
kept out of pdf_extract.py's generic (bank-agnostic) extraction, same
rationale as hdfc_credit_card.py: this module is allowed to know HDFC's
specific layout and amount convention; pdf_extract.py's functions must
not. filter_transaction_rows() already isolates these lines correctly on
its own (dominant row shape + a date found anywhere in the first cell) —
no changes were needed there.

Verified against four real statements (Sep 2025, Nov 2025, Jan 2026, Jun
2026): every statement's computed debit/credit sum from this module's
parsing matched that statement's own "PURCHASES/DEBIT" and
"PAYMENTS/CREDITS RECEIVED" header totals exactly.

Direction convention: unlike the older format's explicit Cr/Dr suffix,
this layout has no textual direction word anywhere. The only reliable
signal found is structural — a bare "+" (no digits attached) sitting
immediately before the trailing "C <amount> l" marks a credit. That's a
different field from the reward-points annotation ("+N" earned, or "-N"
reversed) that independently appears right after the description on many
rows. A bill payment ("AUTOPAY THANK YOU...", or a differently-worded
manual/BillDesk payment on a month it wasn't autopaid) shows a bare "+"
with no attached number. A refund/reversal shows BOTH a negative
reward-points reversal for the points earned on the original purchase AND
that same bare "+" marker. Confirmed against two independent real
refunds, in different months and for different merchants, each an exact
amount-and-points match to an earlier purchase. Everything else — the
large majority of rows — has neither marker and defaults to debit.
"""
from __future__ import annotations

import re

# DOTALL: a transaction's reference number occasionally wraps mid-row
# during extraction, landing the date/time/amount in the middle of the
# cell with description text both before and after — `.` must cross those
# embedded newlines for the date/time/amount triple to still match.
_TXN_RE = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{4})\s*\|\s*(?P<time>\d{2}:\d{2}(?::\d{2})?)\s*"
    r"(?P<body>.*?)"
    r"C\s*(?P<amount>[\d,]+\.\d{2})\s*l\b",
    re.DOTALL,
)

# Trailing reward-points annotation(s) to strip from the description for
# readability — "+ 20", "- 12", or a bare "+"/"-" with no number, possibly
# two in a row (a refund carries both a "- N" reversal and the bare "+"
# direction marker, back to back).
_TRAILING_ANNOTATIONS_RE = re.compile(r"(?:[+-]\s*\d*\s*)+$")

HEADER_ROW = ["Date", "Transaction Description", "Amount (in Rs.)"]


def parse_transaction_line(text: str) -> tuple[str, str, str] | None:
    """Parses one raw extracted cell (possibly with embedded newlines)
    into (date, description, signed amount string). Returns None if no
    transaction-shaped substring is found — callers should skip such rows
    rather than guess at a value for them.
    """
    if not text:
        return None
    match = _TXN_RE.search(text)
    if not match:
        return None

    body = match.group("body")
    body_stripped = body.strip()
    is_credit = bool(body_stripped) and body_stripped.endswith("+") and (
        len(body_stripped) == 1 or body_stripped[-2].isspace())

    description = _TRAILING_ANNOTATIONS_RE.sub("", body).strip()
    description = re.sub(r"\s+", " ", description)

    amount = float(match.group("amount").replace(",", ""))
    signed = amount if is_credit else -amount
    return match.group("date"), description, f"{signed:.2f}"


def normalize_hdfc_v2_rows(rows: list[list[str | None]]) -> list[list[str]]:
    """Reshapes filter_transaction_rows()'s single-column output for this
    layout into munim's expected (Date, Description, signed Amount) rows.

    Rows that don't match the transaction-line pattern are dropped rather
    than passed through unchanged: unlike the older format's
    column-preserving normalizer, this one changes row width (1 column
    in, 3 out), so an unparsed row can't be left as-is without breaking
    CSV column-count uniformity for every other row.
    """
    result = []
    for row in rows:
        if not row or not row[0]:
            continue
        parsed = parse_transaction_line(row[0])
        if parsed is None:
            continue
        result.append(list(parsed))
    return result
