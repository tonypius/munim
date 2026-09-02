"""Canonical transaction schema. Every ingest adapter must produce this."""
from __future__ import annotations

import hashlib
from datetime import date as Date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Status(str, Enum):
    CONFIRMED = "confirmed"      # user-verified: enters memory & training data
    PROVISIONAL = "provisional"  # machine-suggested: displayed, never trusted
    UNRESOLVED = "unresolved"    # nothing matched: goes to review queue


class Stage(str, Enum):
    """Provenance: which pipeline stage produced the category."""
    STRUCTURAL = "structural"      # transfer / recurrence / P2P rules
    MEMORY_EXACT = "memory_exact"
    MEMORY_FUZZY = "memory_fuzzy"
    DICTIONARY = "dictionary"      # community merchant dictionary
    PURPOSE = "purpose"            # keyword in the raw narration's purpose tail
    FALLBACK = "fallback"          # trained classifier
    USER = "user"                  # manually set in review
    NONE = "none"


class Transaction(BaseModel):
    id: str = ""                     # stable hash, set on ingest
    date: Date
    amount: float = Field(gt=0)
    currency: str = "INR"
    direction: Direction
    description_raw: str
    account: str = "default"
    balance: Optional[float] = None

    # pipeline outputs
    merchant_norm: str = ""          # normalized merchant candidate
    payee_handle: str = ""           # UPI/P2P handle if extracted
    category: str = ""
    confidence: float = 0.0
    stage: Stage = Stage.NONE
    status: Status = Status.UNRESOLVED
    is_transfer: bool = False
    is_recurring: bool = False

    def compute_id(self) -> str:
        raw = f"{self.date}|{self.amount}|{self.direction}|{self.description_raw}|{self.account}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = self.compute_id()
