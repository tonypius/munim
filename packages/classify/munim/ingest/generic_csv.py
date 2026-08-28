"""Stage 1: ingest. Generic CSV adapter driven by a column-mapping profile.

Bank-specific profiles are just saved mappings — supporting a new bank is
a few lines of YAML, not code. The wizard in `munim import` builds one
interactively the first time and saves it for reuse.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..schema import Transaction, Direction

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%d %b %Y", "%d-%b-%Y", "%d/%m/%y")


@dataclass
class CsvProfile:
    date_col: str
    description_col: str
    amount_col: str = ""            # single signed-amount column, OR:
    debit_col: str = ""             # separate debit/credit columns
    credit_col: str = ""
    account: str = "default"
    currency: str = "INR"
    date_format: str = ""           # blank = auto-detect
    extras: dict = field(default_factory=dict)


def _parse_date(value: str, fmt: str = ""):
    value = value.strip()
    formats = (fmt,) if fmt else DATE_FORMATS
    for f in formats:
        try:
            return datetime.strptime(value, f).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {value!r} — set date_format in the profile")


def _parse_amount(value: str) -> float:
    cleaned = value.replace(",", "").replace("₹", "").replace("$", "").strip()
    return float(cleaned) if cleaned else 0.0


def load_csv(path: Path, profile: CsvProfile) -> list[Transaction]:
    txns: list[Transaction] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            desc = row.get(profile.description_col, "")
            if not desc:
                continue
            if profile.amount_col:
                amt = _parse_amount(row.get(profile.amount_col, "0"))
                if amt == 0:
                    continue
                direction = Direction.DEBIT if amt < 0 else Direction.CREDIT
                amount = abs(amt)
            else:
                debit = _parse_amount(row.get(profile.debit_col, "") or "0")
                credit = _parse_amount(row.get(profile.credit_col, "") or "0")
                if debit > 0:
                    direction, amount = Direction.DEBIT, debit
                elif credit > 0:
                    direction, amount = Direction.CREDIT, credit
                else:
                    continue
            txns.append(Transaction(
                date=_parse_date(row[profile.date_col], profile.date_format),
                amount=amount, currency=profile.currency, direction=direction,
                description_raw=desc, account=profile.account,
            ))
    return txns
