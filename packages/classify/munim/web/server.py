"""munim web — a local one-page UI over the engine.

Deliberately built on the stdlib http.server: zero new dependencies, binds
127.0.0.1 only, launched on demand, dies with Ctrl-C.

This is a UI TRANSPORT, not an integration surface. The /api/* routes here
are private and may change in any release. Apps integrate with Munim through
the SQLite data contract (docs/data-contract.md) and the classify/learn
commands (docs/embedding.md) — never through these endpoints.
"""
from __future__ import annotations

import json
import webbrowser
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from ..schema import Stage, Status
from ..store import Store
from ..contribute import collect_candidates

INDEX = Path(__file__).parent / "index.html"


class Handler(BaseHTTPRequestHandler):
    # ---- plumbing ------------------------------------------------------
    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    def _send(self, payload, status=200, content_type="application/json"):
        body = (json.dumps(payload).encode()
                if content_type == "application/json"
                else payload.encode() if isinstance(payload, str) else payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the terminal quiet
        pass

    # ---- GET -----------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        route = url.path
        if route == "/":
            self._send(INDEX.read_text(encoding="utf-8"), content_type="text/html")
        elif route == "/api/overview":
            self._send(self._overview())
        elif route == "/api/transactions":
            self._send(self._transactions(q))
        elif route == "/api/queue":
            self._send(self._queue(q))
        elif route == "/api/categories":
            self._send(self._categories())
        elif route == "/api/rules":
            self._send(self._rules())
        elif route == "/api/accounts":
            self._send(self._accounts())
        elif route == "/api/dashboard":
            self._send(self._dashboard(q))
        elif route == "/api/contribute":
            candidates, skipped = collect_candidates(self.store)
            self._send({"candidates": candidates, "skipped": skipped})
        else:
            self._send({"error": "not found"}, status=404)

    # ---- POST ----------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/rule/subcategory":
            self._handle_rule_subcategory()
            return
        if path != "/api/confirm":
            self._send({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        category = data.get("category")
        cats = self.store.get_config("categories", [])
        if category not in cats:
            self._send({"error": "need id/ids and a valid category"}, status=400)
            return

        ids = data.get("ids")
        if ids is not None:
            # Bulk path: the review page's select-several-then-assign-one-
            # category action. Each id is confirmed with the same sequence
            # as the single-id path (log, remember, propagate) — a missing
            # id (e.g. a stale client-side selection) is reported, not a
            # hard failure for the whole batch.
            if not isinstance(ids, list) or not ids:
                self._send({"error": "ids must be a non-empty list"}, status=400)
                return
            confirmed = 0
            propagated_total = 0
            missing = []
            for txn_id in ids:
                propagated = self._confirm_one(txn_id, category)
                if propagated is None:
                    missing.append(txn_id)
                    continue
                confirmed += 1
                propagated_total += propagated
            self._send({"ok": True, "confirmed": confirmed,
                       "propagated": propagated_total, "missing": missing})
            return

        txn_id = data.get("id")
        if not txn_id:
            self._send({"error": "need id/ids and a valid category"}, status=400)
            return
        propagated = self._confirm_one(txn_id, category)
        if propagated is None:
            self._send({"error": "unknown transaction"}, status=404)
            return
        self._send({"ok": True, "propagated": propagated})

    def _confirm_one(self, txn_id, category):
        """Same sequence as `munim review` confirm: log, remember,
        propagate. Returns the propagated count, or None if txn_id doesn't
        exist (a transaction resolved earlier in the same batch by another
        id's propagate() is still found here and simply re-confirmed with
        the same category — harmless, not an error)."""
        t = self.store.get_transaction(txn_id)
        if t is None:
            return None
        self.store.log_correction(t, category)
        propagated = 0
        if t.payee_handle:
            self.store.remember(t.payee_handle, category, kind="payee")
            propagated = self.store.propagate(t.payee_handle, category,
                                              "payee", t.id)
        elif t.merchant_norm:
            self.store.remember(t.merchant_norm, category, kind="merchant")
            propagated = self.store.propagate(t.merchant_norm, category,
                                              "merchant", t.id)
        t.category = category
        # is_transfer must track the category, not just the structural
        # auto-detector: a transaction the auto-detector couldn't pair
        # (e.g. a credit-card bill payment where only the card's own
        # statement is imported) still needs this set when the user
        # confirms "Transfers" here — reports/dashboard check
        # is_transfer, not the category string. Also clears it when a
        # user corrects a mis-flagged transfer to a real category.
        t.is_transfer = category == "Transfers"
        t.stage = Stage.USER
        t.status = Status.CONFIRMED
        self.store.update_transaction(t)
        return propagated

    def _handle_rule_subcategory(self):
        """Set a rule's subcategory (keeping its existing category) and
        backfill every currently-matching transaction, confirmed or not
        — the deliberate 'refine my history' action from the Rules page,
        never triggered automatically from review/confirm."""
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        pattern = (data.get("pattern") or "").upper().strip()
        kind = data.get("kind") or "merchant"
        subcategory = data.get("subcategory") or ""
        row = self.store.db.execute(
            "SELECT category FROM memory WHERE pattern=? AND kind=?",
            (pattern, kind)).fetchone()
        if row is None:
            self._send({"error": "unknown rule"}, status=404)
            return
        self.store.remember(pattern, row["category"], kind=kind,
                            subcategory=subcategory)
        n = self.store.apply_subcategory(pattern, subcategory, kind)
        self._send({"ok": True, "updated": n})

    # ---- data assembly --------------------------------------------------
    def _overview(self):
        txns = self.store.all_transactions()
        by_stage: dict[str, int] = defaultdict(int)
        for t in txns:
            by_stage[t.stage.value] += 1
        return {
            "total": len(txns),
            "queue": sum(1 for t in txns if t.status != Status.CONFIRMED),
            "by_stage": dict(by_stage),
            "memory_rules": len(self.store.memory_rules("merchant"))
            + len(self.store.memory_rules("payee")),
            "currency": self.store.get_config("currency", "INR"),
            "region": self.store.get_config("region", "in"),
        }

    def _transactions(self, q):
        # Same filter surface as /api/queue (month, q, plus a category
        # filter — the sentinel "__none__" here means "no category
        # assigned yet", mirroring queue's "no suggestion" case) — the
        # ledger page needs the same search/filter a large review queue
        # needs, once thousands of already-classified rows pile up.
        month, needle = q.get("month", ""), q.get("q", "").upper()
        category = q.get("category", "")
        all_txns = self.store.all_transactions()
        rows = []
        for t in sorted(all_txns, key=lambda x: x.date, reverse=True):
            iso = t.date.isoformat()
            if month and not iso.startswith(month):
                continue
            if category == "__none__" and t.category:
                continue
            if category and category != "__none__" and t.category != category:
                continue
            hay = f"{t.merchant_norm} {t.payee_handle} {t.category} " \
                  f"{t.description_raw}".upper()
            if needle and needle not in hay:
                continue
            rows.append(self._row(t))
            if len(rows) >= 300:
                break
        months = sorted({t.date.isoformat()[:7] for t in all_txns}, reverse=True)
        categories = sorted({t.category for t in all_txns if t.category})
        return {"rows": rows, "months": months, "categories": categories}

    def _queue(self, q):
        # Same param names as /api/transactions (month, q) for a consistent
        # filter surface, plus `suggested` — a category name to show only
        # rows currently suggested as that category (pairs with bulk-
        # assign: filter to one suggestion, select-all, confirm in one
        # shot), or the sentinel "__none__" for rows with no suggestion at
        # all. review_queue() is already ordered lowest-confidence-first;
        # filtering narrows that same ordered list, it doesn't reorder it.
        month, needle = q.get("month", ""), q.get("q", "").upper()
        suggested = q.get("suggested", "")
        filtered = bool(month or needle or suggested)
        limit = 500 if filtered else 100
        queue = self.store.review_queue()
        rows = []
        for t in queue:
            if month and not t.date.isoformat().startswith(month):
                continue
            if suggested == "__none__" and t.category:
                continue
            if suggested and suggested != "__none__" and t.category != suggested:
                continue
            if needle:
                hay = f"{t.merchant_norm} {t.payee_handle} {t.category} " \
                      f"{t.description_raw}".upper()
                if needle not in hay:
                    continue
            rows.append(self._row(t))
            if len(rows) >= limit:
                break
        months = sorted({t.date.isoformat()[:7] for t in queue}, reverse=True)
        suggestions = sorted({t.category for t in queue if t.category})
        return {"rows": rows, "months": months, "suggestions": suggestions}

    def _categories(self):
        cats = self.store.get_config("categories", [])
        usage: dict[str, dict] = defaultdict(lambda: {"n": 0, "total": 0.0})
        for t in self.store.all_transactions():
            if t.category and t.direction.value == "debit" and not t.is_transfer:
                usage[t.category]["n"] += 1
                usage[t.category]["total"] += t.amount
        from ..tree import get_tree, resolve
        tree = get_tree(self.store)
        return {"categories": cats,
                "paths": {c: resolve(tree, c) for c in cats},
                "usage": {c: usage.get(c, {"n": 0, "total": 0.0})
                          for c in set(cats) | set(usage)},
                "subcategories": self.store.get_config("subcategories", {}) or {}}

    def _rules(self):
        learned = self.store.db.execute(
            "SELECT pattern, kind, category, subcategory, created_at FROM memory "
            "ORDER BY created_at DESC").fetchall()
        from ..memory import MemoryMatcher
        dictionary = MemoryMatcher(
            user_rules={}, region=self.store.get_config("region", "in")
        ).dictionary
        # A pattern that never equals any real transaction's complete
        # merchant_norm/payee_handle can only ever have matched (or will
        # match) via substring/fuzzy containment, never a literal
        # equality lookup — a genuinely checkable "this rule is broad"
        # signal, not a length guess. Two rules can look identical in
        # this table (a full narration-derived string vs. a hand-typed
        # keyword like "CREDCLUB" meant to catch every payment-processor
        # variant of one recurring fee) while behaving very differently.
        exact_strings = {
            t.merchant_norm or t.payee_handle
            for t in self.store.all_transactions()
            if t.merchant_norm or t.payee_handle
        }
        return {
            "learned": [
                {**dict(r), "broad": r["pattern"] not in exact_strings}
                for r in learned
            ],
            "dictionary": sorted(
                [{"pattern": p, "category": c, "broad": p not in exact_strings}
                 for p, c in dictionary.items()],
                key=lambda r: (r["category"], r["pattern"])),
        }

    def _accounts(self):
        from ..doctor import _month_range
        by_acct: dict[str, list] = defaultdict(list)
        for t in self.store.all_transactions():
            by_acct[t.account].append(t)
        rows = []
        for acct, ts in sorted(by_acct.items()):
            dates = sorted(t.date for t in ts)
            have = {d.isoformat()[:7] for d in dates}
            missing = [m for m in _month_range(dates[0], dates[-1])
                       if m not in have]
            from ..tree import account_root
            rows.append({
                "account": acct, "type": account_root(self.store, acct),
                "n": len(ts),
                "first": dates[0].isoformat(), "last": dates[-1].isoformat(),
                "debit": sum(t.amount for t in ts
                             if t.direction.value == "debit" and not t.is_transfer),
                "credit": sum(t.amount for t in ts
                              if t.direction.value == "credit" and not t.is_transfer),
                "transfers": sum(1 for t in ts if t.is_transfer),
                "months": len(have), "missing_months": missing,
            })
        return {"rows": rows}

    def _dashboard(self, q=None):
        from ..tree import get_tree, resolve, root_of
        q = q or {}
        month, account = q.get("month", ""), q.get("account", "")
        all_txns = [t for t in self.store.all_transactions()
                    if (not month or t.date.isoformat().startswith(month))
                    and (not account or t.account == account)]
        # five-root rollup: every categorized entry flows to its root
        tree = get_tree(self.store)
        roots: dict[str, float] = defaultdict(float)
        for t in all_txns:
            if t.category:
                roots[root_of(resolve(tree, t.category))] += t.amount
        spend = [t for t in all_txns
                 if t.direction.value == "debit" and not t.is_transfer]
        months: dict[str, float] = defaultdict(float)
        cats: dict[str, float] = defaultdict(float)
        merchants: dict[str, float] = defaultdict(float)
        recurring = 0.0
        for t in spend:
            months[t.date.isoformat()[:7]] += t.amount
            cats[t.category or "(uncategorized)"] += t.amount
            merchants[t.merchant_norm or t.payee_handle or "(unknown)"] += t.amount
            if t.is_recurring:
                recurring += t.amount
        total = sum(months.values())
        return {
            "months": [{"month": m, "total": v}
                       for m, v in sorted(months.items())],
            "top_categories": sorted(
                ({"name": k, "total": v} for k, v in cats.items()),
                key=lambda x: -x["total"])[:8],
            "top_merchants": sorted(
                ({"name": k, "total": v} for k, v in merchants.items()),
                key=lambda x: -x["total"])[:10],
            "total": total,
            "avg_month": total / max(1, len(months)),
            "recurring_share": recurring / total if total else 0,
            "roots": {r: roots.get(r, 0.0) for r in
                      ("Income", "Expenses", "Assets", "Liabilities", "Equity")},
            "net": roots.get("Income", 0.0) - roots.get("Expenses", 0.0),
            "filter_months": sorted({t.date.isoformat()[:7]
                                     for t in self.store.all_transactions()},
                                    reverse=True),
            "filter_accounts": sorted({t.account
                                       for t in self.store.all_transactions()}),
        }

    @staticmethod
    def _row(t):
        return {
            "id": t.id, "date": t.date.isoformat(), "amount": t.amount,
            "currency": t.currency, "direction": t.direction.value,
            "merchant": t.merchant_norm or t.payee_handle,
            "is_person": bool(t.payee_handle),
            "category": t.category, "subcategory": t.subcategory,
            "confidence": t.confidence,
            "stage": t.stage.value, "status": t.status.value,
            "account": t.account, "transfer": t.is_transfer,
            "recurring": t.is_recurring, "raw": t.description_raw,
        }


def run_server(store: Store, port: int = 8646, open_browser: bool = True):
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.store = store  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}"
    print(f"Munim web at {url}  (local only — Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nThe munim closes the ledger.")
