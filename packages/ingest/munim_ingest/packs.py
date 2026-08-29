"""Bank search packs: which sender domains and attachment types identify a
bank's statement emails. Mirrors packages/classify's region-pack pattern
(packages/classify/munim/normalize/packs/).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PACKS_DIR = Path(__file__).parent / "packs"


@dataclass
class BankPack:
    bank: str
    from_domains: list[str] = field(default_factory=list)
    attachment_extensions: list[str] = field(default_factory=list)
    # Sender-domain search alone can match years of non-statement mail
    # (alerts, OTPs, offers) from a bank's domain — subject_keywords narrows
    # the IMAP search to statement emails specifically. Empty by default so
    # existing packs without this key keep today's from-domain-only search.
    subject_keywords: list[str] = field(default_factory=list)


class PackNotFoundError(Exception):
    pass


def load_pack(bank: str) -> BankPack:
    pack_file = PACKS_DIR / f"{bank}.yaml"
    if not pack_file.exists():
        available = ", ".join(list_packs())
        raise PackNotFoundError(f"No pack for {bank!r}. Available: {available}")
    data = yaml.safe_load(pack_file.read_text())
    return BankPack(
        bank=data["bank"],
        from_domains=data.get("from_domains", []),
        attachment_extensions=data.get("attachment_extensions", [".csv", ".pdf"]),
        subject_keywords=data.get("subject_keywords", []),
    )


def list_packs() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.yaml"))
