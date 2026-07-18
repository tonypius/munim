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
            self._send(self._queue())
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
        if urlparse(self.path).path != "/api/confirm":
            self._send({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        txn_id, category = data.get("id"), data.get("category")
        cats = self.store.get_config("categories", [])
        if not txn_id or category not in cats:
            self._send({"error": "need id and a valid category"}, status=400)
            return
        t = self.store.get_transaction(txn_id)
        if t is None:
            self._send({"error": "unknown transaction"}, status=404)
            return
        # Same sequence as `munim review` confirm: log, remember, propagate
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
        t.stage = Stage.USER
        t.status = Status.CONFIRMED
        self.store.update_transaction(t)
        self._send({"ok": True, "propagated": propagated})

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
        month, needle = q.get("month", ""), q.get("q", "").upper()
        rows = []
        for t in sorted(self.store.all_transactions(),
                        key=lambda x: x.date, reverse=True):
            iso = t.date.isoformat()
            if month and not iso.startswith(month):
                continue
            hay = f"{t.merchant_norm} {t.payee_handle} {t.category} " \
                  f"{t.description_raw}".upper()
            if needle and needle not in hay:
                continue
            rows.append(self._row(t))
            if len(rows) >= 300:
                break
        months = sorted({t.date.isoformat()[:7]
                         for t in self.store.all_transactions()}, reverse=True)
        return {"rows": rows, "months": months}

    def _queue(self):
        return {"rows": [self._row(t) for t in self.store.review_queue()[:100]]}

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
                          for c in set(cats) | set(usage)}}

    def _rules(self):
        learned = self.store.db.execute(
            "SELECT pattern, kind, category, created_at FROM memory "
            "ORDER BY created_at DESC").fetchall()
        from ..memory import MemoryMatcher
        dictionary = MemoryMatcher(
            user_rules={}, region=self.store.get_config("region", "in")
        ).dictionary
        return {
            "learned": [dict(r) for r in learned],
            "dictionary": sorted(
                [{"pattern": p, "category": c} for p, c in dictionary.items()],
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
            "category": t.category, "confidence": t.confidence,
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
