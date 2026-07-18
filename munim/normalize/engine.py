"""Stage 2: normalize raw bank strings using pluggable region packs.

A region pack is a YAML file of ordered regex rules:
  extract: patterns whose first capture group becomes the merchant candidate
  strip:   patterns removed from the string (rail noise, terminal IDs)
  payee:   patterns identifying a P2P payee handle (routed to payee memory)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PACKS_DIR = Path(__file__).parent / "packs"


@dataclass
class NormResult:
    merchant: str = ""
    payee_handle: str = ""
    rail: str = ""


@dataclass
class Normalizer:
    region: str = "in"
    _extract: list = field(default_factory=list)
    _strip: list = field(default_factory=list)
    _payee: list = field(default_factory=list)

    def __post_init__(self):
        pack_file = PACKS_DIR / f"{self.region}.yaml"
        if not pack_file.exists():
            pack_file = PACKS_DIR / "generic.yaml"
        pack = yaml.safe_load(pack_file.read_text())
        flags = re.IGNORECASE
        self._extract = [(re.compile(r["pattern"], flags), r.get("rail", ""))
                         for r in pack.get("extract", [])]
        self._strip = [re.compile(r["pattern"], flags) for r in pack.get("strip", [])]
        self._payee = [re.compile(r["pattern"], flags) for r in pack.get("payee", [])]

    def normalize(self, description: str) -> NormResult:
        text = description.strip()

        # 1. P2P payee detection first — a person is not a merchant
        for rx in self._payee:
            m = rx.search(text)
            if m:
                return NormResult(payee_handle=m.group(1).upper().strip(), rail="p2p")

        # 2. Rail-specific extraction (first capture group = merchant candidate)
        rail = ""
        for rx, rail_name in self._extract:
            m = rx.search(text)
            if m:
                text = m.group(1)
                rail = rail_name
                break

        # 3. Strip residual noise
        for rx in self._strip:
            text = rx.sub(" ", text)

        merchant = re.sub(r"[^A-Za-z0-9&' ]+", " ", text)
        merchant = re.sub(r"\s{2,}", " ", merchant).upper().strip()
        return NormResult(merchant=merchant, rail=rail)
