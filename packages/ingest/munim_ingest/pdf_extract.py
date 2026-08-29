"""Stage: decrypt and open a password-protected bank statement PDF.

pdfplumber (via pdfminer.six) decrypts standard RC4/AES-128 PDF encryption
natively through its `password=` argument — no separate decryption library
is needed for that case. AES-256-encrypted PDFs are a known gap: if a real
statement uses it, pdfplumber will raise here just like a wrong password
would, and that's indistinguishable from this module's point of view. If
that turns out to matter for a real bank, it needs a follow-up, not a
guess made now.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


class PdfPasswordError(Exception):
    """Raised when a PDF can't be opened with the given password — either
    the password is wrong, or the file isn't a PDF pdfplumber can decrypt
    (e.g. AES-256 encryption, or a corrupt/non-PDF file)."""


def open_pdf(path: Path, password: str) -> pdfplumber.PDF:
    try:
        return pdfplumber.open(path, password=password)
    except Exception as e:
        # For the most common real failure (a wrong password), pdfplumber's
        # underlying exception often has an empty str() — fall back to a
        # generic reason instead of leaving a dangling, empty ": " suffix.
        reason = str(e) or "incorrect password"
        raise PdfPasswordError(
            f"Could not open {path.name} — check the password, or this "
            f"may not be a PDF pdfplumber can decrypt: {reason}") from e


def extract_rows(pdf: pdfplumber.PDF) -> list[list[str | None]]:
    """Rows from every page, concatenated in order. Prefers ruled tables
    (pdfplumber's extract_tables()) if ANY page has one; if no page in the
    whole document has a table, falls back to one row per non-empty line
    of extract_text(). No column-splitting is attempted in the fallback —
    each line becomes a single-element row; munim's CSV-import wizard
    handles turning arbitrary columns into a mapped schema from there.
    Cells can be None: pdfplumber's extract_tables() emits None for
    empty/unruled cells in a partially-ruled table (csv.writer renders
    those as an empty field).
    """
    all_tables: list[list[str | None]] = []
    for page in pdf.pages:
        for table in page.extract_tables():
            all_tables.extend(table)
    if all_tables:
        return all_tables

    all_lines: list[list[str]] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            if line.strip():
                all_lines.append([line])
    return all_lines


def filter_transaction_rows(
    rows: list[list[str | None]],
) -> list[list[str | None]]:
    """From extract_rows()'s raw output — which mixes real transaction rows
    with page-header titles, per-page summary boxes, and blank spacer rows
    all detected as "tables" by pdfplumber alongside the genuine ledger —
    keep only the rows that plausibly represent a transaction.

    This is a generic cleanup step, not per-bank column parsing: it never
    interprets amount or description content, only decides which raw rows
    to keep. Two conditions, both required:
      1. The row's length matches the DOMINANT (most common) length across
         all rows — real transaction tables vastly outnumber the noise
         rows in any real statement, so the majority shape is a reliable
         signal for "this is the transaction table," and it also excludes
         same-shaped-by-coincidence summary rows a date check alone
         wouldn't catch (e.g. a 3-column "Payment Due Date" row that also
         starts with a date, but isn't a transaction).
      2. The first cell contains something that looks like a date
         (DD/MM/YYYY) ANYWHERE in the cell, not just as a strict prefix —
         a real extraction artifact observed against an actual statement
         prepended stray text before the date in one row; anchoring the
         match at position 0 would have silently dropped that transaction.

    Without this, extract_rows()'s raw output — mixed row lengths — breaks
    munim import's column-mapping wizard, which applies one fixed column
    index across every row.
    """
    if not rows:
        return []
    lengths = Counter(len(r) for r in rows)
    dominant_length = lengths.most_common(1)[0][0]
    return [
        r for r in rows
        if len(r) == dominant_length and r[0] and _DATE_RE.search(r[0])
    ]
