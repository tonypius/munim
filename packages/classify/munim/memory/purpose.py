"""Last-resort stage: match the raw narration's purpose tail (see
Normalizer's `purpose` field) against a keyword dictionary. This is for
UPI payments to individuals who have no merchant or payee identity of
their own — a street vendor, a driver — where the counterparty name
carries zero category signal but the narration itself says "food" or
"taxi". Deliberately last-resort: only consulted after merchant/payee
memory and the community dictionary have already missed, so a specific
taught rule always wins over a coincidental purpose word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz, process

PURPOSE_DICT_PATH = Path(__file__).parent.parent / "data" / "dictionary" / "purpose.yaml"
FUZZY_THRESHOLD = 90


@dataclass
class PurposeMatch:
    category: str
    matched_pattern: str
    score: float  # 100 = exact


class PurposeMatcher:
    def __init__(self, threshold: int = FUZZY_THRESHOLD):
        self.threshold = threshold
        self.dictionary = self._load()

    @staticmethod
    def _load() -> dict[str, str]:
        out: dict[str, str] = {}
        if PURPOSE_DICT_PATH.exists():
            data = yaml.safe_load(PURPOSE_DICT_PATH.read_text()) or {}
            for category, patterns in data.items():
                for p in patterns or []:
                    out[str(p).upper()] = category
        return out

    def match(self, purpose_text: str) -> Optional[PurposeMatch]:
        # Whitespace is stripped, not just collapsed: raw narrations often
        # carry a single stray space inserted mid-word from PDF/line-wrap
        # reconstruction ("fo od", "ta xi"), and dictionary keys are
        # stored space-free for exactly this reason.
        key = re.sub(r"\s+", "", purpose_text or "").upper()
        if not key or not self.dictionary:
            return None
        if key in self.dictionary:
            return PurposeMatch(self.dictionary[key], key, 100.0)
        # Some raw narrations over-capture (an earlier short digit run
        # matches first, gluing leftover VPA/IFSC text onto the front of
        # the real purpose word) — recognize those by the trailing word.
        suffix_hits = [k for k in self.dictionary if key.endswith(k)]
        if suffix_hits:
            best = max(suffix_hits, key=len)
            return PurposeMatch(self.dictionary[best], best, 99.0)
        result = process.extractOne(
            key, self.dictionary.keys(), scorer=fuzz.token_set_ratio,
            score_cutoff=self.threshold,
        )
        if result:
            pattern, score, _ = result
            return PurposeMatch(self.dictionary[pattern], pattern, float(score))
        return None
