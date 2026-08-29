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

from pathlib import Path

import pdfplumber


class PdfPasswordError(Exception):
    """Raised when a PDF can't be opened with the given password — either
    the password is wrong, or the file isn't a PDF pdfplumber can decrypt
    (e.g. AES-256 encryption, or a corrupt/non-PDF file)."""


def open_pdf(path: Path, password: str) -> pdfplumber.PDF:
    try:
        return pdfplumber.open(path, password=password)
    except Exception as e:
        raise PdfPasswordError(
            f"Could not open {path.name} — check the password, or this "
            f"may not be a PDF pdfplumber can decrypt: {e}") from e


def extract_rows(pdf: pdfplumber.PDF) -> list[list[str]]:
    """Rows from every page, concatenated in order. Prefers ruled tables
    (pdfplumber's extract_tables()) if ANY page has one; if no page in the
    whole document has a table, falls back to one row per non-empty line
    of extract_text(). No column-splitting is attempted in the fallback —
    each line becomes a single-element row; munim's CSV-import wizard
    handles turning arbitrary columns into a mapped schema from there.
    """
    all_tables: list[list[str]] = []
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
