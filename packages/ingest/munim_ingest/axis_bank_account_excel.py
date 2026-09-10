"""Axis Bank savings account statement — the .xls export from Axis's own
netbanking ("Download Statement"). Like hdfc_bank_account_excel.py this is
a clean tabular export, one row per real transaction, no line-wrapping —
but Axis's own column layout: SRL NO / Tran Date / CHQNO / PARTICULARS /
DR / CR / BAL / SOL, dates as DD-MM-YYYY, and DR/CR read by xlrd as
whitespace-padded strings (a present amount like '   150134.00', an empty
side as a single space ' ' — never a genuinely empty string or None, since
Axis's own export always writes a placeholder character into both amount
columns for every transaction row).

Reading and interpreting the sheet are kept separate (read_workbook_rows
does file I/O via xlrd; _rows_to_transactions is pure and unit-testable
with plain lists) — the same split hdfc_bank_account_excel.py uses.

Verified against two real statements spanning April 2025 - September 2026
(password-free .xls, downloaded 2026-09-10): 42 transactions total across
both files, non-overlapping periods, 0 same-day identical-narration
repeats (the recurring "IMPS/MRT/<ref>/919686526569//..." and "STIRRUP
COMMUNI/" rows all carry a unique transfer reference or a distinct amount
per month, so the duplicate-narration bug class documented in
sib_account_pdf.py does not reproduce here — still worth re-checking on
any new statement before trusting it, per CLAUDE.md).
"""
from __future__ import annotations

import re
from pathlib import Path

HEADER_ROW = ["Date", "Narration", "Amount"]

_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def read_workbook_rows(path: Path) -> list[list]:
    """Reads every cell of the first sheet as a list of rows, values
    as-is. Axis's netbanking export has only ever been observed as
    legacy binary .xls."""
    suffix = Path(path).suffix.lower()
    if suffix == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        sheet = wb.sheet_by_index(0)
        return [sheet.row_values(i) for i in range(sheet.nrows)]
    raise ValueError(f"Unsupported spreadsheet format: {suffix!r} (expected .xls)")


def _find_header_row(rows: list[list]) -> int | None:
    """The real column header ("Tran Date", "PARTICULARS", ...) sits
    after a variable-length preamble (account holder name/address/IFSC
    block) — found by content, not a fixed row index."""
    for i, row in enumerate(rows[:40]):
        text = " ".join(str(c) for c in row if c is not None)
        if "Tran Date" in text and "PARTICULARS" in text:
            return i
    return None


def _rows_to_transactions(rows: list[list]) -> list[list[str]]:
    """Turns the raw sheet rows into (Date, Particulars, signed Amount)
    rows, munim import's expected shape. Rows before/after the real
    transaction table (the preamble, and the footer's legend/disclosure
    text) are skipped by requiring column 1 (Tran Date) to look like a
    DD-MM-YYYY date — none of that surrounding text does."""
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return []
    result = []
    for row in rows[header_idx + 1:]:
        if not row or len(row) < 2:
            continue
        date_str = str(row[1]).strip()
        if not _DATE_RE.match(date_str):
            continue
        particulars = str(row[3]).strip() if len(row) > 3 else ""
        withdrawal = str(row[4]).strip() if len(row) > 4 else ""
        deposit = str(row[5]).strip() if len(row) > 5 else ""
        try:
            w = float(withdrawal) if withdrawal else 0.0
            d = float(deposit) if deposit else 0.0
        except ValueError:
            continue
        result.append([date_str, particulars, f"{d - w:.2f}"])
    return result


def parse_axis_bank_excel(path: Path) -> list[list[str]]:
    """Reads and parses one Axis bank-account .xls statement export in
    one step — the public entry point; read_workbook_rows and
    _rows_to_transactions exist separately so the parsing logic can be
    unit-tested without a real spreadsheet file on disk."""
    return _rows_to_transactions(read_workbook_rows(path))
