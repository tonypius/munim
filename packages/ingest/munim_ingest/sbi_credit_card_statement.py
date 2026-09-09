"""SBI Card's monthly e-statement PDF — the attachment on "Your SBI CARD
ELITE Monthly Statement" / "Your AURUM Card Monthly Statement" emails.
A different document from the netbanking "Transaction History" export
sbi_credit_card.py handles, with a genuinely different (and simpler)
layout: every real transaction sits entirely on its own line of plain
text, "DD Mon YY Description Amount C" or "...Amount D" — no word-position
clustering needed here, unlike that other module.

pdfplumber does find one ruled table per statement covering this section,
but its cells are column-major and NOT safe to zip by line index: a
"TRANSACTIONS FOR <name>" section-divider between the "payments/credits"
and "purchases" halves of the table lands inside the description cell's
newline-joined text with no corresponding line in either the date or
amount cell, silently shifting every later row by one once naively
zipped. Reading extract_text() and matching one transaction per physical
line sidesteps that entirely — confirmed across 15 real statements
(Jun 2025-Aug 2026, 2-33 transactions each) that no transaction line ever
wraps across two physical lines in this format.

One real exception found in those 15 statements: an annual-fee charge's
GST sometimes bills as its own separate Debit line directly below the fee
line, but that GST line carries no date of its own. A line with an
amount+C/D ending but no leading date, appearing immediately after
another transaction line, inherits that transaction's date rather than
being silently dropped — confirmed against the one real statement this
occurred in, whose "Fee, Taxes & Interest" summary total only reconciled
once this line was included.

Verified against those same 15 real statements: this module's per-
statement transaction count and the sum of its signed amounts matched
each statement's own printed "ACCOUNT SUMMARY" totals exactly.

The statement's own "DD Mon YY" dates are normalized to "DD/MM/YYYY"
here (rather than left as-is) so this module's CSV output matches
sbi_credit_card.py's date shape exactly — both bank flags can then share
one munim `csv_profiles` entry instead of needing two.
"""
from __future__ import annotations

import re
from datetime import datetime

_LINE_RE = re.compile(
    r"^(?:(?P<date>\d{2} [A-Za-z]{3} \d{2}) )?(?P<desc>.+) (?P<amount>[\d,]+\.\d{2}) (?P<type>[CD])$"
)

HEADER_ROW = ["Date", "Description", "Amount (in Rs.)"]


def _parse_line(line: str, inherited_date: str | None) -> tuple[str, str, str] | None:
    match = _LINE_RE.match(line)
    if not match:
        return None
    raw_date = match["date"] or inherited_date
    if raw_date is None:
        return None
    date = datetime.strptime(raw_date, "%d %b %y").strftime("%d/%m/%Y")
    amount = float(match["amount"].replace(",", ""))
    signed = amount if match["type"] == "C" else -amount
    return (date, match["desc"].strip(), f"{signed:.2f}")


def parse_transactions(pages) -> list[tuple[str, str, str]]:
    """Parses an SBI Card monthly e-statement's pages (pdfplumber Page
    objects, or anything exposing the same `.extract_text()` interface)
    into (date, description, signed amount) tuples — negative for a Debit
    line, positive for a Credit line, munim's expected single-signed-
    amount-column convention. A dateless amount+C/D line directly after a
    matched transaction line inherits that transaction's own date (see
    module docstring); any other line is ignored."""
    result = []
    for page in pages:
        text = page.extract_text()
        if not text:
            continue
        last_date: str | None = None
        for line in text.split("\n"):
            own_date = re.match(r"^\d{2} [A-Za-z]{3} \d{2}", line)
            parsed = _parse_line(line, last_date)
            if parsed:
                result.append(parsed)
                last_date = own_date[0] if own_date else last_date
            else:
                last_date = None
    return result
