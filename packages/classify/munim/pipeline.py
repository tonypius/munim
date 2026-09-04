"""The orchestrator. Runs every transaction through the stages in order,
attaching provenance (stage + confidence) to every decision.

Design invariants (see docs/philosophy.md):
  1. Machine outputs are PROVISIONAL. Only the user's confirmation in
     `munim review` promotes anything to CONFIRMED / into memory.
  2. User memory outranks the community dictionary outranks the model.
  3. Every classification is explainable: stage + matched pattern + score.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Transaction, Direction, Stage, Status
from .store import Store
from .normalize import Normalizer
from .memory import MemoryMatcher, PurposeMatcher
from .structural import detect_transfers, detect_recurrence
from .fallback import TfidfClassifier, SKLEARN_AVAILABLE

# Provisional predictions below this go to the queue with no suggestion at all.
FALLBACK_MIN_CONFIDENCE = 0.40

# Person-name heuristic: 2-4 alpha-only words, no business vocabulary.
# Applied ONLY after every merchant source misses — a dictionary hit always
# wins, so 'UBER INDIA SYSTEMS' never gets misrouted to payee memory.
NAME_LIKE = re.compile(r"^[A-Z]{2,15}(?: [A-Z]{2,15}){1,3}$")
BUSINESS_WORDS = {
    "SYSTEMS", "SERVICES", "STORES", "TRADERS", "ENTERPRISES", "AGENCIES",
    "SOLUTIONS", "RETAIL", "FOODS", "SWEETS", "SNACKS", "BAKERY", "HOTEL",
    "RESTAURANT", "CAFE", "MART", "SUPERMARKET", "PHARMACY", "HOSPITAL",
    "CLINIC", "MOTORS", "FUELS", "PETROL", "TRAVELS", "TOURS", "AND",
    "SHOP", "SHOPPE", "CENTRE", "CENTER", "AGENCY", "WORKS", "TRADING",
    "KIRANA", "GENERAL", "PROVISION", "DAIRY", "JUICE", "TIFFIN",
}
INCOME_MARKERS = re.compile(r"\b(SALARY|SAL CREDIT|PAYROLL|STIPEND)\b", re.I)


@dataclass
class PipelineStats:
    total: int = 0
    by_stage: dict = field(default_factory=dict)

    def bump(self, stage: Stage) -> None:
        self.by_stage[stage.value] = self.by_stage.get(stage.value, 0) + 1


class Pipeline:
    def __init__(self, store: Store):
        self.store = store
        region = store.get_config("region", "in")
        self.normalizer = Normalizer(region=region)
        self.matcher = MemoryMatcher(
            user_rules=store.memory_rules("merchant"),
            region=region,
            threshold=store.get_config("fuzzy_threshold", 90),
        )
        self.payee_rules = store.memory_rules("payee")
        self.subcat_rules = store.memory_subcategories("merchant")
        self.payee_subcat_rules = store.memory_subcategories("payee")
        self.purpose_matcher = PurposeMatcher(
            threshold=store.get_config("fuzzy_threshold", 90))
        # User category renames: dictionary emits standard taxonomy names;
        # aliases remap them to the user's chosen names (e.g. Dining -> Food).
        self.aliases: dict = store.get_config("category_aliases", {})
        self.fallback = TfidfClassifier(model_path=store.home / "fallback.joblib")

    def run(self, txns: list[Transaction]) -> PipelineStats:
        stats = PipelineStats(total=len(txns))

        # Stage 2: normalize everything first (structural stages need it)
        for t in txns:
            result = self.normalizer.normalize(t.description_raw)
            t.merchant_norm = result.merchant
            t.payee_handle = result.payee_handle

        # Stage 3: structural — transfers first (they're not spending at all)
        detect_transfers(txns)
        detect_recurrence(txns)

        for t in txns:
            if t.is_transfer:
                stats.bump(Stage.STRUCTURAL)
                continue

            # Income: salary credits are structural, not merchant-based
            if t.direction == Direction.CREDIT and \
                    INCOME_MARKERS.search(t.description_raw):
                self._assign(t, "Income", Stage.STRUCTURAL, 0.95)
                stats.bump(Stage.STRUCTURAL)
                continue

            # P2P: only payee memory can resolve a payment to a person
            if t.payee_handle:
                if t.payee_handle in self.payee_rules:
                    self._assign(t, self.payee_rules[t.payee_handle],
                                 Stage.MEMORY_EXACT, 1.0,
                                 subcategory=self.payee_subcat_rules.get(
                                     t.payee_handle, ""))
                    stats.bump(Stage.MEMORY_EXACT)
                elif not self._try_purpose(t, stats):
                    stats.bump(Stage.NONE)
                continue

            # Stage 4: memory then dictionary
            match = self.matcher.match(t.merchant_norm)
            if match:
                stage = (Stage.MEMORY_EXACT if match.score == 100 and
                         match.source == "memory"
                         else Stage.MEMORY_FUZZY if match.source == "memory"
                         else Stage.DICTIONARY)
                subcat = (self.subcat_rules.get(match.matched_pattern, "")
                         if match.source == "memory" else "")
                self._assign(t, match.category, stage, match.score / 100,
                             subcategory=subcat)
                stats.bump(stage)
                continue

            # All merchant sources missed. If the string looks like a person's
            # name, route to payee memory (review will remember it there).
            if self._looks_like_person(t.merchant_norm):
                if t.merchant_norm in self.payee_rules:
                    self._assign(t, self.payee_rules[t.merchant_norm],
                                 Stage.MEMORY_EXACT, 1.0,
                                 subcategory=self.payee_subcat_rules.get(
                                     t.merchant_norm, ""))
                    stats.bump(Stage.MEMORY_EXACT)
                else:
                    t.payee_handle, t.merchant_norm = t.merchant_norm, ""
                    if not self._try_purpose(t, stats):
                        stats.bump(Stage.NONE)
                continue

            # Last-resort keyword signal, tried before the probabilistic
            # fallback since a literal purpose word is more explainable
            # (and usually more reliable) than an ML guess.
            if self._try_purpose(t, stats):
                continue

            # Stage 5: fallback classifier (provisional, optional)
            pred = self.fallback.predict(t.merchant_norm)
            if pred and pred[1] >= FALLBACK_MIN_CONFIDENCE:
                self._assign(t, pred[0], Stage.FALLBACK, pred[1])
                stats.bump(Stage.FALLBACK)
            else:
                stats.bump(Stage.NONE)

        return stats

    def _try_purpose(self, t: Transaction, stats: PipelineStats) -> bool:
        """Last resort: the raw narration's purpose tail (e.g. '...-food
        Value Dt...') against the purpose keyword dictionary. Only ever
        reached after merchant/payee memory and the community dictionary
        have already missed."""
        purpose = self.normalizer.normalize(t.description_raw).purpose
        match = self.purpose_matcher.match(purpose)
        if not match:
            return False
        self._assign(t, match.category, Stage.PURPOSE, match.score / 100)
        stats.bump(Stage.PURPOSE)
        return True

    @staticmethod
    def _looks_like_person(merchant: str) -> bool:
        if not merchant or not NAME_LIKE.match(merchant):
            return False
        return not any(w in BUSINESS_WORDS for w in merchant.split())

    def _assign(self, t: Transaction, category: str, stage: Stage,
                conf: float, subcategory: str = "") -> None:
        t.category = self.aliases.get(category, category)
        t.subcategory = subcategory
        t.stage = stage
        t.confidence = round(conf, 3)
        # is_transfer must track category here too, not just the
        # structural detector's own pass — every non-structural stage
        # (memory, dictionary, purpose, fallback) routes through this
        # function, and reports/dashboard check is_transfer, not the
        # category string.
        t.is_transfer = t.category == "Transfers"
        # A user-memory exact hit is as good as confirmed — the user taught it.
        t.status = (Status.CONFIRMED if stage == Stage.MEMORY_EXACT
                    else Status.PROVISIONAL)

    # ---- Loop 2: retraining ------------------------------------------
    def retrain_fallback(self) -> bool:
        """Dictionary patterns + the user's confirmed labels -> fresh model."""
        if not SKLEARN_AVAILABLE:
            return False
        samples: list[tuple[str, str]] = list(self.store.confirmed_labels())
        for pattern, category in self.matcher.dictionary.items():
            samples.append((pattern, category))
        return self.fallback.train(samples)
