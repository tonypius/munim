"""SQLite persistence. One file, owned by the user, at ~/.munim/munim.db.

Tables:
  transactions   — every imported transaction with full provenance
  memory         — user-CONFIRMED pattern -> category rules (the accuracy engine)
  corrections    — log of (predicted, corrected) pairs, feeds threshold calibration
  config         — key/value settings (region, currency, categories)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .schema import Transaction, Status, Stage

DEFAULT_HOME = Path.home() / ".munim"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    direction TEXT NOT NULL,
    description_raw TEXT NOT NULL,
    account TEXT NOT NULL,
    balance REAL,
    merchant_norm TEXT DEFAULT '',
    payee_handle TEXT DEFAULT '',
    category TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    stage TEXT DEFAULT 'none',
    status TEXT DEFAULT 'unresolved',
    is_transfer INTEGER DEFAULT 0,
    is_recurring INTEGER DEFAULT 0,
    subcategory TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memory (
    pattern TEXT NOT NULL,          -- normalized merchant string or payee handle
    kind TEXT NOT NULL,             -- 'merchant' | 'payee'
    category TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    subcategory TEXT DEFAULT '',
    PRIMARY KEY (pattern, kind)
);
CREATE TABLE IF NOT EXISTS corrections (
    txn_id TEXT NOT NULL,
    predicted_category TEXT,
    predicted_stage TEXT,
    predicted_confidence REAL,
    final_category TEXT NOT NULL,
    was_correct INTEGER NOT NULL,
    at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    txn_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (txn_id, tag)
);
"""


class Store:
    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else DEFAULT_HOME
        self.home.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: `munim web` serves requests from a single
        # server thread that may differ from the creating thread. The HTTP
        # server is deliberately NOT threaded, so access stays serialized.
        self.db = sqlite3.connect(self.home / "munim.db",
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """One-time column additions for databases created before a given
        column existed. SQLite has no ADD COLUMN IF NOT EXISTS, so each
        addition needs its own existence check. New columns always land
        at the physical end of the table, same as a fresh CREATE TABLE
        with the column listed last — keeps positional INSERTs valid
        either way."""
        def has_column(table: str, col: str) -> bool:
            return any(r["name"] == col for r in
                       self.db.execute(f"PRAGMA table_info({table})").fetchall())

        if not has_column("transactions", "subcategory"):
            self.db.execute(
                "ALTER TABLE transactions ADD COLUMN subcategory TEXT DEFAULT ''")
        if not has_column("memory", "subcategory"):
            self.db.execute(
                "ALTER TABLE memory ADD COLUMN subcategory TEXT DEFAULT ''")
        self.db.commit()

    # ---- config -------------------------------------------------------
    def set_config(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO config(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.db.commit()

    def get_config(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    # ---- transactions -------------------------------------------------
    def upsert_transactions(self, txns: Iterable[Transaction]) -> tuple[int, int]:
        """Insert new transactions; skip duplicates. Returns (inserted, skipped)."""
        inserted = skipped = 0
        for t in txns:
            try:
                self.db.execute(
                    "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.id, t.date.isoformat(), t.amount, t.currency,
                        t.direction.value, t.description_raw, t.account, t.balance,
                        t.merchant_norm, t.payee_handle, t.category, t.confidence,
                        t.stage.value, t.status.value,
                        int(t.is_transfer), int(t.is_recurring), t.subcategory,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
        self.db.commit()
        return inserted, skipped

    def update_transaction(self, t: Transaction) -> None:
        self.db.execute(
            "UPDATE transactions SET merchant_norm=?, payee_handle=?, category=?, "
            "subcategory=?, confidence=?, stage=?, status=?, is_transfer=?, "
            "is_recurring=? WHERE id=?",
            (
                t.merchant_norm, t.payee_handle, t.category, t.subcategory,
                t.confidence, t.stage.value, t.status.value,
                int(t.is_transfer), int(t.is_recurring), t.id,
            ),
        )
        self.db.commit()

    def _row_to_txn(self, r: sqlite3.Row) -> Transaction:
        return Transaction(
            id=r["id"], date=r["date"], amount=r["amount"], currency=r["currency"],
            direction=r["direction"], description_raw=r["description_raw"],
            account=r["account"], balance=r["balance"],
            merchant_norm=r["merchant_norm"], payee_handle=r["payee_handle"],
            category=r["category"], confidence=r["confidence"],
            stage=Stage(r["stage"]), status=Status(r["status"]),
            is_transfer=bool(r["is_transfer"]), is_recurring=bool(r["is_recurring"]),
            subcategory=r["subcategory"],
        )

    def all_transactions(self) -> list[Transaction]:
        rows = self.db.execute("SELECT * FROM transactions ORDER BY date").fetchall()
        return [self._row_to_txn(r) for r in rows]

    def get_transaction(self, txn_id: str) -> Optional[Transaction]:
        row = self.db.execute(
            "SELECT * FROM transactions WHERE id=?", (txn_id,)).fetchone()
        return self._row_to_txn(row) if row else None

    def review_queue(self) -> list[Transaction]:
        """Everything the user hasn't confirmed yet, lowest confidence first."""
        rows = self.db.execute(
            "SELECT * FROM transactions WHERE status != 'confirmed' "
            "ORDER BY confidence ASC, date DESC"
        ).fetchall()
        return [self._row_to_txn(r) for r in rows]

    def confirmed_labels(self) -> list[tuple[str, str]]:
        """(merchant_norm, category) pairs from confirmed txns — the training set."""
        rows = self.db.execute(
            "SELECT merchant_norm, category FROM transactions "
            "WHERE status='confirmed' AND merchant_norm != '' AND category != ''"
        ).fetchall()
        return [(r["merchant_norm"], r["category"]) for r in rows]

    # ---- memory (Loop 1) ----------------------------------------------
    def remember(self, pattern: str, category: str, kind: str = "merchant",
                 subcategory: str = "") -> None:
        if not pattern:
            return
        self.db.execute(
            "INSERT INTO memory(pattern,kind,category,subcategory) VALUES(?,?,?,?) "
            "ON CONFLICT(pattern,kind) DO UPDATE SET category=excluded.category, "
            "subcategory=excluded.subcategory",
            (pattern.upper().strip(), kind, category, subcategory),
        )
        self.db.commit()

    def existing_subcategory(self, pattern: str, kind: str, category: str) -> str:
        """The subcategory already on file for this pattern, but only if
        `category` matches what memory has — a category change invalidates
        whatever subcategory was taught under the old one."""
        row = self.db.execute(
            "SELECT category, subcategory FROM memory WHERE pattern=? AND kind=?",
            (pattern.upper().strip(), kind)).fetchone()
        if row and row["category"] == category:
            return row["subcategory"] or ""
        return ""

    def propagate(self, pattern: str, category: str, kind: str = "merchant",
                  exclude_id: str = "", subcategory: str = "") -> int:
        """Apply a just-confirmed rule to every other unconfirmed transaction
        with the identical merchant/payee string. This is what makes bulk
        backfill sane: confirm SWIGGY once, all 40 occurrences resolve.
        Exact string matches only — fuzzy variants stay in the queue for
        `munim reclassify` so the user still sees anything ambiguous.
        """
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        # is_transfer must track the category, not just the structural
        # auto-detector's own pass: a transaction the auto-detector
        # couldn't pair (e.g. a credit-card bill payment where only the
        # card's own statement is imported) still needs is_transfer=True
        # once the user confirms "Transfers" here — reports/dashboard
        # check is_transfer, not the category string.
        is_transfer = 1 if category == "Transfers" else 0
        cur = self.db.execute(
            f"UPDATE transactions SET category=?, subcategory=?, status='confirmed', "
            f"stage='memory_exact', confidence=1.0, is_transfer=? "
            f"WHERE {col}=? AND status != 'confirmed' AND id != ?",
            (category, subcategory, is_transfer, pattern, exclude_id),
        )
        self.db.commit()
        return cur.rowcount

    def memory_rules(self, kind: str = "merchant") -> dict[str, str]:
        rows = self.db.execute(
            "SELECT pattern, category FROM memory WHERE kind=?", (kind,)
        ).fetchall()
        return {r["pattern"]: r["category"] for r in rows}

    def memory_subcategories(self, kind: str = "merchant") -> dict[str, str]:
        """pattern -> subcategory, for patterns that have one set. The
        pipeline uses this to attach a subcategory when a memory rule
        resolves a transaction — never for dictionary or purpose-tail
        matches, which never carry one."""
        rows = self.db.execute(
            "SELECT pattern, subcategory FROM memory "
            "WHERE kind=? AND subcategory != ''", (kind,)
        ).fetchall()
        return {r["pattern"]: r["subcategory"] for r in rows}

    def apply_subcategory(self, pattern: str, subcategory: str,
                          kind: str = "merchant") -> int:
        """Backfill a subcategory onto every transaction matching pattern,
        confirmed or not. Unlike propagate(), this never touches
        category, status, stage, or confidence — subcategorizing is a
        refinement on top of an already-settled category decision, not a
        re-opening of it, so already-confirmed history is fair game."""
        col = "payee_handle" if kind == "payee" else "merchant_norm"
        cur = self.db.execute(
            f"UPDATE transactions SET subcategory=? WHERE {col}=?",
            (subcategory, pattern),
        )
        self.db.commit()
        return cur.rowcount

    # ---- corrections (Loop 3) -----------------------------------------
    def log_correction(self, t: Transaction, final_category: str) -> None:
        self.db.execute(
            "INSERT INTO corrections(txn_id,predicted_category,predicted_stage,"
            "predicted_confidence,final_category,was_correct) VALUES(?,?,?,?,?,?)",
            (
                t.id, t.category or None, t.stage.value, t.confidence,
                final_category, int(t.category == final_category),
            ),
        )
        self.db.commit()

    def stage_accuracy(self) -> list[sqlite3.Row]:
        """Measured correction rate per stage — feeds threshold calibration."""
        return self.db.execute(
            "SELECT predicted_stage AS stage, COUNT(*) AS n, "
            "AVG(was_correct) AS accuracy FROM corrections "
            "WHERE predicted_category IS NOT NULL GROUP BY predicted_stage"
        ).fetchall()

    # ---- tags -----------------------------------------------------------
    def set_tags(self, txn_id: str, tags: list[str]) -> None:
        """Replace-all: a transaction's tag set becomes exactly `tags`.
        Manual assignment only — never called from the pipeline."""
        self.db.execute("DELETE FROM tags WHERE txn_id=?", (txn_id,))
        for tag in tags:
            self.db.execute(
                "INSERT OR IGNORE INTO tags(txn_id, tag) VALUES(?,?)",
                (txn_id, tag))
        self.db.commit()

    def tags_for(self, txn_id: str) -> list[str]:
        rows = self.db.execute(
            "SELECT tag FROM tags WHERE txn_id=? ORDER BY tag", (txn_id,)
        ).fetchall()
        return [r["tag"] for r in rows]

    def all_tags(self) -> dict[str, list[str]]:
        """txn_id -> sorted tags, for every transaction that has at least
        one. Bulk lookup to avoid N+1 queries when listing transactions."""
        rows = self.db.execute(
            "SELECT txn_id, tag FROM tags ORDER BY txn_id, tag").fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["txn_id"], []).append(r["tag"])
        return out

    def tag_counts(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag").fetchall()
        return {r["tag"]: r["n"] for r in rows}
