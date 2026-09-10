# Chart Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Dashboard tab's hand-rolled CSS-bar charts with real Chart.js charts, add a new net-worth-over-time panel, and give the assistant a correctness-guaranteed way to produce ad hoc conversational charts — all backed by one new pure aggregation module and two new API endpoints.

**Architecture:** A new `munim/reporting.py` module exposes two pure functions (`flow_query`, `balance_series`) that never touch the DB or HTTP layer directly. Two thin GET endpoints (`/api/chart/flow`, `/api/chart/balance`) in `server.py` wrap them. `index.html` gets Chart.js's minified UMD build inlined directly into its existing `<script>` block (no CDN, no build step — the whole page stays one self-contained file), and its `dashboard()` render function is rewritten to build real `Chart` instances instead of CSS divs.

**Tech Stack:** Python 3 (stdlib `http.server`, no new Python dependencies), Chart.js 4.4.4 (vendored, not a project dependency — inlined as static JS text).

## Global Constraints

- Chart.js is pinned to **exact version 4.4.4**, sourced from
  `https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js` and
  inlined into `index.html` — never loaded via `<script src=...>` at
  runtime. The project's "works fully offline" promise (stated in
  `index.html`'s own CSS comment) must remain literally true even on a
  fresh clone with zero internet access.
- Sign convention (from `balance_sheet.py` / `CLAUDE.md`, do not get this
  backwards): **Assets** — a credit increases the balance, a debit
  decreases it. **Liabilities** — inverted (a debit, i.e. a purchase,
  increases what's owed; a credit, i.e. a payment, decreases it).
- `flow_query`'s default `exclude_transfers=True` must match
  `_dashboard()`'s existing spend filter exactly: `t.direction ==
  "debit" and not t.is_transfer`.
- No new JS test framework. Frontend tasks (Task 4, Task 5) are verified
  by manually driving a real browser against the dev server (screenshot,
  console/network check) — none exists anywhere in this project today.
- No `saved_charts` persistence, no user-facing chart-builder UI, no
  pie/doughnut charts, no dark-mode chart theming. All explicitly out of
  scope per `docs/superpowers/specs/2026-09-10-chart-engine-design.md`'s
  Non-goals section.

---

### Task 1: `flow_query` — the flow-metric aggregation function

**Files:**
- Create: `packages/classify/munim/reporting.py`
- Test: `packages/classify/tests/test_reporting.py`

**Interfaces:**
- Produces: `flow_query(txns: list[Transaction], group_by: str, *, direction: str = "", exclude_transfers: bool = True, account: str = "", category: str = "", subcategory: str = "", date_from: str = "", date_to: str = "") -> list[dict]` — each dict is `{"label": str, "value": float}`. Raises `ValueError` for an unrecognized `group_by`.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for munim/reporting.py -- the aggregation module shared by the
Dashboard tab and on-the-go conversational charts (see
docs/superpowers/specs/2026-09-10-chart-engine-design.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from munim.schema import Transaction, Direction
from munim.reporting import flow_query


def _txn(date, amount, direction, **kw):
    return Transaction(date=date, amount=amount, direction=direction,
                       description_raw=kw.pop("description_raw", "X"), **kw)


def test_flow_query_groups_by_month_sorted_chronologically():
    txns = [
        _txn("2026-07-01", 100, Direction.DEBIT),
        _txn("2026-06-01", 50, Direction.DEBIT),
        _txn("2026-06-15", 25, Direction.DEBIT),
    ]
    rows = flow_query(txns, "month")
    assert rows == [
        {"label": "2026-06", "value": 75.0},
        {"label": "2026-07", "value": 100.0},
    ]


def test_flow_query_groups_by_category_sorted_by_descending_value():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, category="Dining"),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Groceries"),
        _txn("2026-06-03", 5, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category")
    assert rows == [
        {"label": "Groceries", "value": 50.0},
        {"label": "Dining", "value": 15.0},
    ]


def test_flow_query_uncategorized_label_for_empty_category():
    txns = [_txn("2026-06-01", 10, Direction.DEBIT, category="")]
    rows = flow_query(txns, "category")
    assert rows == [{"label": "(uncategorized)", "value": 10.0}]


def test_flow_query_groups_by_subcategory_none_label_when_empty():
    txns = [_txn("2026-06-01", 10, Direction.DEBIT, category="Groceries", subcategory="")]
    rows = flow_query(txns, "subcategory")
    assert rows == [{"label": "(none)", "value": 10.0}]


def test_flow_query_groups_by_merchant_falls_back_to_payee_handle():
    t = _txn("2026-06-01", 10, Direction.DEBIT)
    t.merchant_norm = ""
    t.payee_handle = "RAMESH KUMAR"
    rows = flow_query([t], "merchant")
    assert rows == [{"label": "RAMESH KUMAR", "value": 10.0}]


def test_flow_query_merchant_unknown_label_when_both_empty():
    rows = flow_query([_txn("2026-06-01", 10, Direction.DEBIT)], "merchant")
    assert rows == [{"label": "(unknown)", "value": 10.0}]


def test_flow_query_groups_by_account():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, account="hdfc"),
        _txn("2026-06-02", 20, Direction.DEBIT, account="sib"),
        _txn("2026-06-03", 5, Direction.DEBIT, account="hdfc"),
    ]
    rows = flow_query(txns, "account")
    assert rows == [
        {"label": "sib", "value": 20.0},
        {"label": "hdfc", "value": 15.0},
    ]


def test_flow_query_excludes_transfers_by_default():
    txns = [
        _txn("2026-06-01", 100, Direction.DEBIT, category="Transfers", is_transfer=True),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category")
    assert rows == [{"label": "Dining", "value": 50.0}]


def test_flow_query_can_include_transfers_when_asked():
    txns = [_txn("2026-06-01", 100, Direction.DEBIT, category="Transfers", is_transfer=True)]
    rows = flow_query(txns, "category", exclude_transfers=False)
    assert rows == [{"label": "Transfers", "value": 100.0}]


def test_flow_query_filters_by_direction():
    txns = [
        _txn("2026-06-01", 100, Direction.CREDIT, category="Income"),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category", direction="credit")
    assert rows == [{"label": "Income", "value": 100.0}]


def test_flow_query_filters_by_account_category_subcategory():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, account="a", category="Groceries", subcategory="Alcohol"),
        _txn("2026-06-02", 20, Direction.DEBIT, account="b", category="Groceries", subcategory="Alcohol"),
        _txn("2026-06-03", 30, Direction.DEBIT, account="a", category="Groceries", subcategory="Meat"),
        _txn("2026-06-04", 40, Direction.DEBIT, account="a", category="Dining"),
    ]
    rows = flow_query(txns, "month", account="a", category="Groceries", subcategory="Alcohol")
    assert rows == [{"label": "2026-06", "value": 10.0}]


def test_flow_query_filters_by_date_range_inclusive():
    txns = [
        _txn("2026-05-31", 1, Direction.DEBIT),
        _txn("2026-06-01", 2, Direction.DEBIT),
        _txn("2026-06-30", 4, Direction.DEBIT),
        _txn("2026-07-01", 8, Direction.DEBIT),
    ]
    rows = flow_query(txns, "month", date_from="2026-06-01", date_to="2026-06-30")
    assert rows == [{"label": "2026-06", "value": 6.0}]


def test_flow_query_unknown_group_by_raises():
    with pytest.raises(ValueError, match="group_by"):
        flow_query([], "not-a-real-dimension")


def test_flow_query_empty_input_returns_empty_list():
    assert flow_query([], "month") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && uv run pytest tests/test_reporting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'munim.reporting'`

- [ ] **Step 3: Write the implementation**

```python
"""Generic chart-data aggregation, shared by the Dashboard tab and
on-the-go conversational charts (see docs/superpowers/specs/
2026-09-10-chart-engine-design.md). Pure functions only -- no HTTP, no
direct SQL access -- testable against a plain list of Transaction
objects, the same way balance_sheet.py's compute_account_balance() is.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as Date

from .schema import Direction, Transaction
from .store import Store

_VALID_GROUP_BY = ("month", "category", "subcategory", "merchant", "account")


def flow_query(
    txns: list[Transaction],
    group_by: str,
    *,
    direction: str = "",
    exclude_transfers: bool = True,
    account: str = "",
    category: str = "",
    subcategory: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Sums `amount` across `txns` grouped by `group_by`, after applying
    every given filter. Returns [{"label": str, "value": float}, ...] --
    chronologically sorted for group_by="month", by descending value
    otherwise (so a "top N" caller gets that ordering for free without a
    separate sort step).

    `exclude_transfers=True` (the default) matches _dashboard()'s
    existing spend calculation exactly (`t.direction == "debit" and not
    t.is_transfer`) -- pass `exclude_transfers=False` for a caller that
    genuinely wants transfers included (e.g. a raw account-activity
    view). Raises ValueError for an unrecognized `group_by`.
    """
    if group_by not in _VALID_GROUP_BY:
        raise ValueError(f"Unknown group_by {group_by!r}; expected one of {_VALID_GROUP_BY}")

    d_from = Date.fromisoformat(date_from) if date_from else None
    d_to = Date.fromisoformat(date_to) if date_to else None

    totals: dict[str, float] = defaultdict(float)
    for t in txns:
        if exclude_transfers and t.is_transfer:
            continue
        if direction and t.direction.value != direction:
            continue
        if account and t.account != account:
            continue
        if category and t.category != category:
            continue
        if subcategory and t.subcategory != subcategory:
            continue
        if d_from and t.date < d_from:
            continue
        if d_to and t.date > d_to:
            continue

        if group_by == "month":
            label = t.date.isoformat()[:7]
        elif group_by == "category":
            label = t.category or "(uncategorized)"
        elif group_by == "subcategory":
            label = t.subcategory or "(none)"
        elif group_by == "merchant":
            label = t.merchant_norm or t.payee_handle or "(unknown)"
        else:  # "account"
            label = t.account
        totals[label] += t.amount

    rows = [{"label": k, "value": v} for k, v in totals.items()]
    if group_by == "month":
        rows.sort(key=lambda r: r["label"])
    else:
        rows.sort(key=lambda r: -r["value"])
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && uv run pytest tests/test_reporting.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/reporting.py packages/classify/tests/test_reporting.py
git commit -m "Add flow_query, the flow-metric chart aggregation function"
```

---

### Task 2: `balance_series` — the running-balance aggregation function

**Files:**
- Modify: `packages/classify/munim/reporting.py` (append to the file created in Task 1)
- Test: `packages/classify/tests/test_reporting.py` (append)

**Interfaces:**
- Consumes: `Store` (from `munim.store`), `Direction` (from `munim.schema`) — both already imported in Task 1's `reporting.py`.
- Produces: `balance_series(store: Store, accounts: list[str] | None = None, *, group_by: str = "month", date_from: str = "", date_to: str = "") -> list[dict]` — each dict is `{"label": "YYYY-MM", "value": float}`. Raises `ValueError` for any `group_by` other than `"month"`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/classify/tests/test_reporting.py`:

```python
from munim.store import Store
from munim.reporting import balance_series


def test_balance_series_single_asset_account_month_end_values(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
        Transaction(date="2026-07-10", amount=200, direction=Direction.DEBIT,
                    description_raw="RENT", account="bank"),
    ])
    rows = balance_series(store, ["bank"])
    assert rows == [
        {"label": "2026-06", "value": 1500.0},
        {"label": "2026-07", "value": 1300.0},
    ]


def test_balance_series_last_value_matches_compute_account_balance(tmp_path):
    from munim.balance_sheet import compute_account_balance
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
    ])
    rows = balance_series(store, ["bank"])
    assert rows[-1]["value"] == compute_account_balance(store, "bank")


def test_balance_series_combines_asset_and_negated_liability(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_types", {"cc": "Liabilities"})
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "cc": {"balance": 200.0, "as_of": "2026-06-01"},
    })
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=50, direction=Direction.DEBIT,
                    description_raw="PURCHASE", account="cc"),
    ])
    rows = balance_series(store, ["bank", "cc"])
    # bank: 1000 (no txns). cc: 200 + 50 (debit/purchase) = 250 owed, negated -> -250.
    # combined: 1000 - 250 = 750.
    assert rows == [{"label": "2026-06", "value": 750.0}]


def test_balance_series_defaults_to_every_account_with_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "savings": {"balance": 500.0, "as_of": "2026-06-01"},
    })
    rows = balance_series(store)
    assert rows == [{"label": "2026-06", "value": 1500.0}]


def test_balance_series_excludes_account_with_no_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    rows = balance_series(store, ["bank", "no-opening-balance-account"])
    assert rows == [{"label": "2026-06", "value": 1000.0}]


def test_balance_series_no_tracked_accounts_returns_empty(tmp_path):
    store = Store(home=tmp_path)
    assert balance_series(store, ["nonexistent"]) == []


def test_balance_series_starts_at_latest_as_of_across_accounts(tmp_path):
    """The combined series never reports a month before EVERY tracked
    account has a known starting point -- an account with a later as_of
    pulls the whole reported range's start forward, rather than showing
    a partial/incomplete combined total for earlier months."""
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances", {
        "old-account": {"balance": 100.0, "as_of": "2026-01-01"},
        "new-account": {"balance": 200.0, "as_of": "2026-06-01"},
    })
    rows = balance_series(store, ["old-account", "new-account"])
    assert rows[0]["label"] == "2026-06"


def test_balance_series_respects_date_from_and_date_to(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-01-01"}})
    store.upsert_transactions([
        Transaction(date="2026-03-01", amount=100, direction=Direction.CREDIT,
                    description_raw="X", account="bank"),
    ])
    rows = balance_series(store, ["bank"], date_from="2026-02-01", date_to="2026-02-28")
    assert rows == [{"label": "2026-02", "value": 1000.0}]


def test_balance_series_rejects_non_month_group_by(tmp_path):
    store = Store(home=tmp_path)
    with pytest.raises(ValueError, match="group_by"):
        balance_series(store, ["bank"], group_by="year")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && uv run pytest tests/test_reporting.py -v -k balance_series`
Expected: FAIL with `ImportError: cannot import name 'balance_series'`

- [ ] **Step 3: Write the implementation**

Append to `packages/classify/munim/reporting.py`:

```python
def balance_series(
    store: Store,
    accounts: list[str] | None = None,
    *,
    group_by: str = "month",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Returns [{"label": "YYYY-MM", "value": float}, ...] -- the combined
    balance across every account in `accounts` at each month's end.

    `accounts=None` means "every account with a known opening balance"
    (used for the Dashboard's net-worth-over-time panel). An account
    named in `accounts` but with no opening balance set is silently
    excluded -- like compute_account_balance(), there is no defined
    starting point to walk forward from for it.

    Each tracked account's own running balance uses the same convention
    compute_account_balance() does (Assets: credit grows it, debit
    shrinks it; Liabilities: inverted, since the balance there represents
    what's owed). When several accounts are combined into one series, a
    Liabilities account's contribution is NEGATED before summing --
    owing money reduces net worth, it doesn't add to it.

    The reported range starts at the LATEST opening-balance `as_of`
    month across every tracked account, never earlier -- this guarantees
    every reported month has a complete combined number with no account
    silently missing from it, rather than showing an undercounted total
    for a period before every account had a known starting point.
    `date_from`/`date_to` narrow the range further; they never widen it
    past that floor or past the latest known transaction date.
    """
    if group_by != "month":
        raise ValueError(f"balance_series only supports group_by='month', got {group_by!r}")

    account_types = store.get_config("account_types", {}) or {}
    opening_balances = store.get_config("account_opening_balances", {}) or {}

    if accounts is None:
        accounts = list(opening_balances.keys())

    tracked = [a for a in accounts if a in opening_balances]
    if not tracked:
        return []

    all_txns = store.all_transactions()
    account_txns = {
        a: sorted(
            (t for t in all_txns if t.account == a
             and t.date >= Date.fromisoformat(opening_balances[a]["as_of"])),
            key=lambda t: t.date)
        for a in tracked
    }

    start = max(Date.fromisoformat(opening_balances[a]["as_of"]) for a in tracked)
    if date_from:
        start = max(start, Date.fromisoformat(date_from))

    txn_dates = [t.date for txns in account_txns.values() for t in txns]
    end = max([start, *txn_dates])
    if date_to:
        end = min(end, Date.fromisoformat(date_to))
    if end < start:
        return []

    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1

    combined = {mo: 0.0 for mo in months}
    for a in tracked:
        running = opening_balances[a]["balance"]
        is_liability = account_types.get(a, "Assets") == "Liabilities"
        txns_sorted = account_txns[a]
        idx = 0
        for mo in months:
            mo_y, mo_m = int(mo[:4]), int(mo[5:7])
            while (idx < len(txns_sorted)
                   and (txns_sorted[idx].date.year, txns_sorted[idx].date.month) <= (mo_y, mo_m)):
                t = txns_sorted[idx]
                if is_liability:
                    running += t.amount if t.direction == Direction.DEBIT else -t.amount
                else:
                    running += t.amount if t.direction == Direction.CREDIT else -t.amount
                idx += 1
            combined[mo] += -running if is_liability else running

    return [{"label": mo, "value": combined[mo]} for mo in months]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && uv run pytest tests/test_reporting.py -v`
Expected: PASS (24 tests total — 15 from Task 1, 9 new)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/reporting.py packages/classify/tests/test_reporting.py
git commit -m "Add balance_series, the running-balance chart aggregation function"
```

---

### Task 3: `/api/chart/flow` and `/api/chart/balance` endpoints

**Files:**
- Modify: `packages/classify/munim/web/server.py`
- Test: `packages/classify/tests/test_pipeline.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `flow_query` and `balance_series` from Task 1/2's `munim/reporting.py`.
- Produces: `GET /api/chart/flow` and `GET /api/chart/balance`, both returning `{"labels": [...], "values": [...]}` on success or `{"error": "..."}` with HTTP 400 on a bad `group_by` or malformed date — the two endpoints Task 4 and Task 5's frontend code call.

- [ ] **Step 1: Write the failing tests**

Append to `packages/classify/tests/test_pipeline.py`:

```python
def test_chart_flow_endpoint_groups_by_month(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Groceries"])
    store.upsert_transactions([
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="X", category="Groceries", subcategory="Alcohol"),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="Y", category="Groceries", subcategory="Alcohol"),
    ])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    d = get("/api/chart/flow?group_by=month&category=Groceries&subcategory=Alcohol")
    assert d == {"labels": ["2026-06", "2026-07"], "values": [100.0, 200.0]}
    srv.shutdown()


def test_chart_flow_endpoint_excludes_transfers_by_default(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Transfers", "Dining"])
    store.upsert_transactions([
        Transaction(date="2026-06-01", amount=999, direction=Direction.DEBIT,
                    description_raw="CC PAYMENT", category="Transfers", is_transfer=True),
        Transaction(date="2026-06-02", amount=50, direction=Direction.DEBIT,
                    description_raw="LUNCH", category="Dining"),
    ])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/flow?group_by=category", timeout=3).read())
    assert d == {"labels": ["Dining"], "values": [50.0]}
    srv.shutdown()


def test_chart_flow_endpoint_rejects_unknown_group_by(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/chart/flow?group_by=bogus", timeout=3)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    srv.shutdown()


def test_chart_balance_endpoint_defaults_to_all_tracked_accounts(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/balance", timeout=3).read())
    assert d == {"labels": ["2026-06"], "values": [1000.0]}
    srv.shutdown()


def test_chart_balance_endpoint_accepts_comma_separated_accounts(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "other": {"balance": 5000.0, "as_of": "2026-06-01"},
    })

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/balance?accounts=bank", timeout=3).read())
    assert d == {"labels": ["2026-06"], "values": [1000.0]}
    srv.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && uv run pytest tests/test_pipeline.py -v -k chart`
Expected: FAIL — every request 404s (`{"error": "not found"}`) since the routes don't exist yet.

- [ ] **Step 3: Add the routes and handler methods**

In `packages/classify/munim/web/server.py`, add two new `elif` branches to `do_GET` right after the existing `/api/dashboard` branch (server.py:69-70):

```python
        elif route == "/api/dashboard":
            self._send(self._dashboard(q))
        elif route == "/api/chart/flow":
            self._handle_chart_flow(q)
        elif route == "/api/chart/balance":
            self._handle_chart_balance(q)
        elif route == "/api/contribute":
```

Add the two handler methods anywhere among the other `def _handle_*` methods (e.g. right before `_handle_transfer_link`):

```python
    def _handle_chart_flow(self, q):
        from ..reporting import flow_query
        try:
            rows = flow_query(
                self.store.all_transactions(), q.get("group_by", ""),
                direction=q.get("direction", ""),
                exclude_transfers=q.get("exclude_transfers", "1") != "0",
                account=q.get("account", ""),
                category=q.get("category", ""),
                subcategory=q.get("subcategory", ""),
                date_from=q.get("date_from", ""),
                date_to=q.get("date_to", ""),
            )
        except ValueError as e:
            self._send({"error": str(e)}, status=400)
            return
        self._send({"labels": [r["label"] for r in rows],
                    "values": [r["value"] for r in rows]})

    def _handle_chart_balance(self, q):
        from ..reporting import balance_series
        accounts_param = q.get("accounts", "")
        accounts = accounts_param.split(",") if accounts_param else None
        try:
            rows = balance_series(
                self.store, accounts,
                date_from=q.get("date_from", ""),
                date_to=q.get("date_to", ""),
            )
        except ValueError as e:
            self._send({"error": str(e)}, status=400)
            return
        self._send({"labels": [r["label"] for r in rows],
                    "values": [r["value"] for r in rows]})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && uv run pytest tests/test_pipeline.py -v -k chart`
Expected: PASS (5 tests)

Then run the full suite to confirm nothing else broke:
Run: `cd packages/classify && uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 5: Document the on-the-go conversational chart workflow in CLAUDE.md**

Add this new section to `CLAUDE.md` (anywhere after the existing "Review queue triage" section is a natural fit):

```markdown
## On-the-go conversational charts

When the user asks for a chart mid-conversation ("show my alcohol spend
by month," "plot my Axis vs HDFC balance this year"), call
`GET /api/chart/flow` or `GET /api/chart/balance` on the running web
server (default `http://127.0.0.1:8646`) rather than hand-writing SQL —
these endpoints already encode the transfer-exclusion and
Assets-credit-grows/Liabilities-inverted sign conventions correctly.
Render the returned `{"labels": [...], "values": [...]}` immediately via
your own visualization tool, inline in the conversation. This is
intentionally ephemeral: nothing is written back to munim's database or
web UI. See `docs/superpowers/specs/2026-09-10-chart-engine-design.md`
if the user wants a chart to persist in the app instead — that's an
explicit non-goal of the current implementation, a follow-up to design
separately.
```

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/web/server.py packages/classify/tests/test_pipeline.py CLAUDE.md
git commit -m "Add /api/chart/flow and /api/chart/balance endpoints"
```

---

### Task 4: Vendor Chart.js and upgrade the three existing Dashboard panels

**Files:**
- Modify: `packages/classify/munim/web/index.html`

**Interfaces:**
- Consumes: `/api/dashboard` (existing, unchanged) — same `months`, `top_categories`, `top_merchants` shapes `dashboard()` already fetches today.
- Produces: a global `Chart` constructor available to all of `index.html`'s existing inline JS (used again by Task 5).

- [ ] **Step 1: Download the pinned Chart.js build**

```bash
curl -sL -o /tmp/chart.umd.min.js "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
```

Verify it downloaded correctly (should be roughly 200KB, single line of minified JS after the header comment):

```bash
wc -c /tmp/chart.umd.min.js
head -c 200 /tmp/chart.umd.min.js
```

- [ ] **Step 2: Inline it into `index.html`**

In `packages/classify/munim/web/index.html`, add a new `<script>` block immediately after the closing `</style>` tag and before the existing `<body>` tag — its entire content is `/tmp/chart.umd.min.js`'s contents, verbatim:

```html
</style>
</head>
<body>
<script>
/* Chart.js 4.4.4, vendored inline (not CDN-loaded) so this page's
   "works fully offline" promise stays literally true on a fresh clone
   with no internet access at all. Source: https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js */
...(paste /tmp/chart.umd.min.js's full content here, unmodified)...
</script>
<main>
```

Use the Edit tool to insert this — read `/tmp/chart.umd.min.js`'s content and place it between the comment and the closing `</script>`, immediately before the existing `<main>` opening tag (`index.html:44` in the file as it stands before this task).

- [ ] **Step 3: Verify `Chart` loads with no console errors**

Start the dev server and open it in a browser:

```bash
cd packages/classify && uv run munim web
```

Using the Browser tool: navigate to `http://127.0.0.1:8646`, then run `typeof Chart` via the JS console tool — expect `"function"`. Check `read_console_messages` for zero errors on page load.

- [ ] **Step 4: Add a small CSS-variable-reading helper**

In `index.html`'s existing app `<script>` block (the one containing `dashboard()`), add near the top, alongside other small helpers like `esc`/`fmt`:

```js
const cssVar=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let monthsChart,catsChart,merchantsChart;
const destroyChart=c=>{if(c)c.destroy()};
```

- [ ] **Step 5: Replace the monthly-trend panel's rendering code**

Find this block in `dashboard()` (the existing hand-rolled bar-chart HTML):

```js
  const max=Math.max(...d.months.map(m=>m.total));
  $("#dashMonths").innerHTML=`<div class="chart">`+d.months.map(m=>
    `<div class="col" title="${m.month}: ${fmt(m.total,CUR)}">
       <div class="colv"><i style="height:${(100*m.total/max).toFixed(1)}%"></i></div>
       <div class="coll">${m.month.slice(2)}</div>
     </div>`).join("")+`</div>`;
```

Replace it with:

```js
  $("#dashMonths").innerHTML=`<canvas id="dashMonthsCanvas" height="90"></canvas>`;
  destroyChart(monthsChart);
  monthsChart=new Chart($("#dashMonthsCanvas"),{type:"bar",
    data:{labels:d.months.map(m=>m.month),
          datasets:[{data:d.months.map(m=>m.total),backgroundColor:cssVar("--ledger-red")}]},
    options:{plugins:{legend:{display:false},
              tooltip:{callbacks:{label:c=>fmt(c.parsed.y,CUR)}}},
             scales:{y:{beginAtZero:true,ticks:{callback:v=>fmt(v,CUR)}}}}});
```

- [ ] **Step 6: Replace the top-categories and top-merchants panels' rendering code**

Find this block (the shared horizontal-bar-table helper and its two call sites):

```js
  const hbar=(rows,maxv)=>`<table><tbody>`+rows.map(r=>`<tr>
    <td style="width:42%">${esc(r.name)}</td>
    <td class="num" style="width:22%">${fmt(r.total,CUR)}</td>
    <td><div class="bar"><i style="width:${(100*r.total/maxv).toFixed(1)}%"></i></div></td>
  </tr>`).join("")+`</tbody></table>`;
  $("#dashCats").innerHTML=hbar(d.top_categories,d.top_categories[0]?.total||1);
  $("#dashMerchants").innerHTML=hbar(d.top_merchants,d.top_merchants[0]?.total||1);
```

Replace it with:

```js
  const hbarChart=(containerId,rows,prevChart)=>{
    $(containerId).innerHTML=`<canvas id="${containerId.slice(1)}Canvas"></canvas>`;
    destroyChart(prevChart);
    return new Chart($(`${containerId}Canvas`),{type:"bar",
      data:{labels:rows.map(r=>r.name),
            datasets:[{data:rows.map(r=>r.total),backgroundColor:cssVar("--ledger-red")}]},
      options:{indexAxis:"y",plugins:{legend:{display:false},
                tooltip:{callbacks:{label:c=>fmt(c.parsed.x,CUR)}}},
               scales:{x:{beginAtZero:true,ticks:{callback:v=>fmt(v,CUR)}}}}});
  };
  catsChart=hbarChart("#dashCats",d.top_categories,catsChart);
  merchantsChart=hbarChart("#dashMerchants",d.top_merchants,merchantsChart);
```

- [ ] **Step 7: Verify in the browser**

With the dev server running (`uv run munim web`), navigate to the Dashboard tab. Confirm:
- The monthly trend renders as a bar chart with a real y-axis and hover tooltips showing formatted currency.
- Top categories and top merchants render as horizontal bar charts, same red as before.
- No console errors (`read_console_messages`).
- Switching the month/account filter re-renders without leaking chart instances (open the same tab twice via the filter dropdown a few times — no visual doubling or slowdown, which would indicate `destroyChart` isn't being called correctly).

Take a screenshot to confirm visually before moving on.

- [ ] **Step 8: Commit**

```bash
git add packages/classify/munim/web/index.html
git commit -m "Vendor Chart.js and replace hand-rolled Dashboard bars with real charts"
```

---

### Task 5: Net worth over time panel

**Files:**
- Modify: `packages/classify/munim/web/index.html`

**Interfaces:**
- Consumes: `GET /api/chart/balance` (Task 3), `Chart` global (Task 4).

- [ ] **Step 1: Add the panel's HTML container**

In `packages/classify/munim/web/index.html`'s `<section id="dashboard">`, insert a new block right after the existing `<div id="dashMonths"></div>` line and before the "Heads of account" / "Where the money goes" flex row:

```html
  <div id="dashMonths"></div>
  <h2 style="font-size:16px;margin-top:26px">Net worth over time</h2>
  <div id="dashNetWorth"></div>
  <div style="display:flex;gap:40px;flex-wrap:wrap;margin-top:26px">
```

- [ ] **Step 2: Fetch and render it in `dashboard()`**

Task 4 Step 4 added `let monthsChart,catsChart,merchantsChart;` — modify that same line to add `netWorthChart` to it, rather than adding a second `let` line (redeclaring the same names with a second `let` in one scope is a JS `SyntaxError`):

```js
let monthsChart,catsChart,merchantsChart,netWorthChart;
```

`dashboard()` has an early `return` when `d.months` is empty (a
month/account filter with no matching spend) that skips everything after
it — including, if placed there, this panel. Since this panel
deliberately ignores those filters (Section 3 of the design spec), it
must render *before* that early return, not after it. Insert the new
code immediately after the existing `$("#dashRoots").innerHTML=...`
block's closing `;` and *before* the `if(!d.months.length){...return}`
line:

```js
  const nw=await api("/api/chart/balance");
  if(nw.labels.length){
    $("#dashNetWorth").innerHTML=`<canvas id="dashNetWorthCanvas" height="90"></canvas>`;
    destroyChart(netWorthChart);
    netWorthChart=new Chart($("#dashNetWorthCanvas"),{type:"line",
      data:{labels:nw.labels,
            datasets:[{data:nw.values,borderColor:cssVar("--pen-blue"),
                       backgroundColor:cssVar("--pen-blue"),tension:0.15,fill:false}]},
      options:{plugins:{legend:{display:false},
                tooltip:{callbacks:{label:c=>fmt(c.parsed.y,CUR)}}},
               scales:{y:{ticks:{callback:v=>fmt(v,CUR)}}}}});
  } else {
    $("#dashNetWorth").innerHTML=`<p class="empty">No accounts have an opening balance set yet — run <code>munim accounts set-opening-balance</code> to start tracking net worth.</p>`;
  }
```

This panel intentionally ignores the Dashboard's existing `#dMonth`/`#dAccount` filters — it always calls `/api/chart/balance` with no `accounts` param, showing the combined trend across every tracked account, per the design spec.

- [ ] **Step 3: Verify in the browser**

With the dev server running and at least one account's opening balance set (`uv run munim accounts set-opening-balance <account> <balance> <date>` against a test store, or check against your real data if already configured), navigate to the Dashboard tab and confirm:
- A line chart titled "Net worth over time" renders below the monthly trend chart.
- Hovering a point shows a formatted currency tooltip.
- If no account has an opening balance set, the empty-state message renders instead of a broken/empty canvas.

Take a screenshot to confirm visually.

- [ ] **Step 4: Commit**

```bash
git add packages/classify/munim/web/index.html
git commit -m "Add a net-worth-over-time panel to the Dashboard tab"
```
