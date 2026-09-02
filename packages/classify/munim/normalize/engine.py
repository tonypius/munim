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

# The trailing purpose word on a UPI narration (e.g.
# '...-336468937787-fo od Value Dt 30/12/2023 Ref 336468937787' means
# "food") sits after the last long reference number, before Value Dt/Ref.
# It's real signal for otherwise-unidentifiable P2P payments, but it lives
# outside the merchant/payee capture group entirely — extracted here,
# independently, so it survives regardless of which extract rail fires
# (or none at all).
_PURPOSE_TAIL_RE = re.compile(r"-\d{6,}-(.*)$")
_VALUE_DT_RE = re.compile(r"\s*Value\s+Dt\s+\d{2}/\d{2}/\d{4}.*$", re.IGNORECASE)
_TRAILING_REF_RE = re.compile(r"\s*Ref\s+\d+$", re.IGNORECASE)


def _extract_purpose(description: str) -> str:
    m = _PURPOSE_TAIL_RE.search(description)
    if not m:
        return ""
    tail = _VALUE_DT_RE.sub("", m.group(1))
    tail = _TRAILING_REF_RE.sub("", tail)
    return tail.strip()


@dataclass
class NormResult:
    merchant: str = ""
    payee_handle: str = ""
    rail: str = ""
    purpose: str = ""


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
        purpose = _extract_purpose(text)

        # 1. P2P payee detection first — a person is not a merchant
        for rx in self._payee:
            m = rx.search(text)
            if m:
                return NormResult(payee_handle=m.group(1).upper().strip(),
                                   rail="p2p", purpose=purpose)

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
        return NormResult(merchant=merchant, rail=rail, purpose=purpose)
