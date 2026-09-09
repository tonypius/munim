"""South Indian Bank's own netbanking "Transaction History" export
("OpTransactionHistory<date>.csv") — downloaded directly from the bank's
website, not emailed. Already a CSV, but not one munim import's generic
loader can read as-is: a preamble block (account holder name/address,
statement metadata, From/To Date) sits before the real column header,
and a "****End of A/c Statement****" footer sits after the last real
row — same shape as HDFC's own Excel export (see
hdfc_bank_account_excel.py), just delivered as CSV instead of a
spreadsheet, so the same read/normalize split and header-by-content-scan
technique applies here.

Real columns: SlNo, Transaction Date, Value Date, Particulars, two blank
columns, Cheque Number, Withdrawals, Deposits, Balance Amount. Amounts
use Indian lakh-style comma grouping ("7,05,506.47", not "705,506.47") —
a plain comma strip handles this fine either way.

Verified against four real statements spanning April 2021 - March 2025:
this module's own running balance (opening balance + cumulative signed
amount) matches the file's own printed Balance Amount column for every
row — the strongest cross-check available, since this export (unlike
SBI's) prints its own running balance.

A real, separate issue found in that same verification: munim's import
dedups by content hash (date + amount + direction + description +
account), and this bank's Particulars narration sometimes carries no
per-instance reference at all — two genuinely separate same-day NACH
bounce-charge events print byte-identical text, unlike a SIP debit's
narration, which carries a unique CAMS reference. Importing all four
statements as-is silently collapsed three such rows into their earlier
duplicate, undercounting real debits by ₹618 in the final ledger balance
(confirmed against the account's own true closing balance). The second
and later occurrence of an exact (date, description, amount) repeat is
now suffixed with a counter so each stays a distinct transaction.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

HEADER_ROW = ["Date", "Particulars", "Amount"]

_DATE_RE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")


def read_csv_rows(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _find_header_row(rows: list[list[str]]) -> int | None:
    """The real column header sits after a variable-length preamble
    (account holder/address/statement-metadata block) — found by
    content, not a fixed row index, since From/To Date make the preamble
    a different length in every file."""
    for i, row in enumerate(rows[:40]):
        text = " ".join(str(c) for c in row if c)
        if "Transaction Date" in text and "Particulars" in text:
            return i
    return None


def _parse_amount(value: str) -> float:
    return float(value.replace(",", "")) if value else 0.0


def _rows_to_transactions(rows: list[list[str]]) -> list[tuple[str, str, str]]:
    """Rows before/after the real transaction table (the preamble and
    the "****End of A/c Statement****" footer) are excluded by requiring
    column 1 (Transaction Date) to look like a DD-Mon-YYYY date — neither
    surrounding block has that shape.

    An exact (date, description, amount) repeat gets its 2nd+ occurrence
    suffixed " (N)" — see the module docstring: this bank's narration
    sometimes carries no per-instance reference, so two genuinely
    separate transactions can otherwise be indistinguishable from one
    row imported twice, and munim's content-hash dedup would silently
    drop the real second one."""
    header_idx = _find_header_row(rows)
    if header_idx is None:
        return []
    parsed = []
    for row in rows[header_idx + 1:]:
        if len(row) < 9:
            continue
        date_str = row[1].strip()
        if not _DATE_RE.match(date_str):
            continue
        particulars = row[3].strip()
        withdrawal = _parse_amount(row[7].strip())
        deposit = _parse_amount(row[8].strip())
        signed = deposit - withdrawal
        parsed.append([date_str, particulars, f"{signed:.2f}"])

    seen: Counter = Counter()
    result = []
    for date_str, particulars, signed_str in parsed:
        key = (date_str, particulars, signed_str)
        seen[key] += 1
        if seen[key] > 1:
            particulars = f"{particulars} ({seen[key]})"
        result.append((date_str, particulars, signed_str))
    return result


def parse_sib_account_csv(path: Path) -> list[tuple[str, str, str]]:
    """Reads and parses one SIB netbanking "Transaction History" CSV
    export in one step — the public entry point; read_csv_rows and
    _rows_to_transactions exist separately so the parsing logic can be
    unit-tested without a real file on disk."""
    return _rows_to_transactions(read_csv_rows(path))
