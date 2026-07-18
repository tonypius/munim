"""Stage 4: memory — exact then fuzzy match against user-confirmed rules
and the community dictionary. Deliberately character-level (RapidFuzz),
NOT embeddings: bank-string noise is orthographic, not semantic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz, process

DICTIONARY_DIR = Path(__file__).parent.parent / "data" / "dictionary"
FUZZY_THRESHOLD = 90  # calibrated by Loop 3 over time; conservative default


@dataclass
class Match:
    category: str
    matched_pattern: str
    score: float          # 100 = exact
    source: str           # 'memory' | 'dictionary'


class MemoryMatcher:
    def __init__(self, user_rules: dict[str, str], region: str = "in",
                 threshold: int = FUZZY_THRESHOLD):
        self.user_rules = {k.upper(): v for k, v in user_rules.items()}
        self.threshold = threshold
        self.dictionary = self._load_dictionary(region)

    @staticmethod
    def _load_dictionary(region: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in ("common", region):
            f = DICTIONARY_DIR / f"{name}.yaml"
            if f.exists():
                data = yaml.safe_load(f.read_text()) or {}
                for category, patterns in data.items():
                    for p in patterns or []:
                        out[str(p).upper()] = category
        return out

    def _lookup(self, merchant: str, rules: dict[str, str], source: str) -> Optional[Match]:
        if not merchant or not rules:
            return None
        # exact
        if merchant in rules:
            return Match(rules[merchant], merchant, 100.0, source)
        # substring containment: 'SWIGGY8102' contains dictionary key 'SWIGGY'.
        # Longest key wins so 'AMAZON FRESH' beats 'AMAZON'.
        contained = [k for k in rules if k in merchant]
        if contained:
            best = max(contained, key=len)
            if len(best) >= 4:  # avoid 2-3 char false positives
                return Match(rules[best], best, 99.0, source)
        # fuzzy: catches truncation and spacing damage (SWIG GY, MCDONALD S)
        result = process.extractOne(
            merchant, rules.keys(), scorer=fuzz.token_set_ratio,
            score_cutoff=self.threshold,
        )
        if result:
            pattern, score, _ = result
            return Match(rules[pattern], pattern, float(score), source)
        return None

    def match(self, merchant: str) -> Optional[Match]:
        """User memory always outranks the community dictionary."""
        merchant = merchant.upper().strip()
        return (self._lookup(merchant, self.user_rules, "memory")
                or self._lookup(merchant, self.dictionary, "dictionary"))
