"""Writes extracted PDF rows to a CSV file for munim import to consume."""
from __future__ import annotations

import csv
from pathlib import Path


def write_csv(rows: list[list[str | None]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
