"""HDFC credit-card-specific transaction normalization.

Deliberately scoped to HDFC's credit card statement layout, not folded
into pdf_extract.py's generic (bank-agnostic) extraction/filtering — this
module is allowed to know HDFC's specific column layout and amount
convention; pdf_extract.py's functions must not.

Observed convention (confirmed against a real HDFC Regalia statement,
2026-08-29): every amount is a positive magnitude with no minus sign — a
trailing "Cr" (or, defensively, "Dr") suffix marks the direction instead.
"Cr" = credit (refund, payment received); no suffix, or an explicit "Dr",
= debit (a purchase). munim's CSV importer instead expects a single
signed amount column: negative for a debit, positive for a credit, no
letter suffix. This bridges the two conventions for HDFC's 5-column
layout (Date, Description, Feature Reward Points, Amount,
trailing-empty) produced by filter_transaction_rows on an HDFC PDF.
"""
from __future__ import annotations

import re

AMOUNT_COL = 3
_SUFFIX_RE = re.compile(r"(cr|dr)\s*$", re.IGNORECASE)

# The real column header row extracted from an HDFC statement's own table
# ("Date | Transaction Description | Feature Reward Points | Amount (in
# Rs.) | <empty>") — used to label munim import's column-mapping wizard
# with the real names instead of a generic "Column 1/2/3..." placeholder,
# when the extracted row width matches this known 5-column shape.
HEADER_ROW = ["Date", "Transaction Description", "Feature Reward Points",
              "Amount (in Rs.)", ""]


def normalize_hdfc_credit_card_amounts(
    rows: list[list[str | None]],
) -> list[list[str | None]]:
    """Rewrites each row's amount column (index 3) from HDFC's
    positive-magnitude-plus-suffix convention into munim's signed-number
    convention. Rows that don't match the expected shape or whose amount
    field isn't parseable are left unchanged rather than guessed at —
    munim import's own parser will surface a clear error on those when it
    tries to import them, which is more informative than a silent
    transformation here with no visibility into what happened.
    """
    result = []
    for row in rows:
        if len(row) <= AMOUNT_COL:
            result.append(row)
            continue
        cell = row[AMOUNT_COL]
        if not cell:
            result.append(row)
            continue

        match = _SUFFIX_RE.search(cell)
        suffix = match.group(1).lower() if match else None
        numeric_part = cell[: match.start()] if match else cell

        try:
            value = float(numeric_part.replace(",", "").strip())
        except ValueError:
            result.append(row)
            continue

        signed = value if suffix == "cr" else -value
        new_row = list(row)
        new_row[AMOUNT_COL] = f"{signed:.2f}"
        result.append(new_row)
    return result
