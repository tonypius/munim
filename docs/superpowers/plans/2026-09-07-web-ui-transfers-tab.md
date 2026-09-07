# Web UI: Transfers Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Transfers" tab to `munim web` giving full interactive
parity with `munim transfers link/review/dismiss/status` — a coverage
line, a queue for resolving ambiguous debit/credit pairs, a list of
pending (zero-candidate) transfers with a dismiss action, and a
re-run-auto-link button. Per
`docs/superpowers/specs/2026-09-07-web-ui-transfers-balance-sheet-design.md`
Section 1.

**Architecture:** One new data-assembly method (`Handler._transfers()`)
and three new POST handlers in `packages/classify/munim/web/server.py`,
reusing the existing `_row()` shape so the frontend's existing
merchant/amount rendering helpers apply unchanged. One new tab (nav
button + `<section>`) and matching JS in
`packages/classify/munim/web/index.html`, following the Review tab's
existing queue-with-select-and-confirm pattern.

**Tech Stack:** Python 3.11+ stdlib `http.server` (no new dependencies),
vanilla JS (no build step, no framework — this page has never had one).

## Global Constraints

- No new dependencies, frontend or backend — this page is deliberately
  framework-free and the server is deliberately stdlib-only (see the
  module docstring in `server.py`).
- Every new backend function needs a test before being considered done
  (TDD), using the exact `HTTPServer` + `urllib.request` pattern already
  established in `packages/classify/tests/test_tags.py` and
  `test_pipeline.py`'s `test_web_server_endpoints` — a real server on an
  ephemeral port, real HTTP requests, no mocking of the HTTP layer.
- The frontend has no JS test harness in this codebase and none is being
  added here. Each frontend task instead requires: (a) a real HTTP
  assertion on the served `index.html`'s static markup (extends the same
  test file, checking the new elements exist — the same technique
  `test_web_server_endpoints` already uses for `"मुनीम".encode() in get("/")`),
  and (b) a live browser-driven verification step using the Browser tool,
  described precisely in the task, with a screenshot as evidence in the
  task report. Both are required; neither substitutes for the other.
- `confidence="confirmed"` for every link created through the web UI's
  "Link" button (never `"auto"` — that confidence is reserved for the
  unattended `apply_auto_links` pass, exactly as `munim transfers review`
  already enforces).
- Delegate every click/change handler on the stable container div (e.g.
  `#transfersBody`), never on individual rendered rows — rows are
  recreated on every render, a listener attached directly to one is gone
  after the first refresh. This is a hard-won lesson already recorded in
  this codebase (see the `v0.1.1` comment on the Review tab's confirm
  handler in `index.html`) and applies identically here.
- Reuse the existing `_row()` method, `esc()`/`fmt()`/`amountCell()` JS
  helpers, and `.tag`/`.merchant`/`.raw`/`.num`/`.confirm`/`.empty` CSS
  classes wherever the existing Review/Transactions tabs already solved
  the same rendering problem — no new CSS classes needed for this plan.

---

### Task 1: Backend — `/api/transfers` and the three transfer actions

**Files:**
- Modify: `packages/classify/munim/web/server.py`
- Test: `packages/classify/tests/test_web_transfers.py` (new file)

**Interfaces:**
- Consumes: `Store.transfer_link_map`, `Store.dismissed_ids`,
  `Store.all_transfer_links`, `Store.is_linked`, `Store.link_transfer`,
  `Store.dismiss_transfer`, `Store.get_transaction`,
  `find_transfer_candidates`, `apply_auto_links` (all pre-existing, from
  the already-shipped transfer-linking feature).
- Produces:
  - `GET /api/transfers` → `{"coverage": {...}, "ambiguous": [...],
    "pending": [...]}` (exact shape in Step 1's test).
  - `POST /api/transfer/link` `{debit_id, credit_id}` → `{"ok": true}` or
    a 400/404 error.
  - `POST /api/transfer/dismiss` `{id}` → `{"ok": true}` or a 400/404
    error.
  - `POST /api/transfer/relink` (no body needed) → `{"ok": true,
    "linked": <int>}`.

- [ ] **Step 1: Write the failing tests**

Create `packages/classify/tests/test_web_transfers.py`:

```python
"""Tests for the web UI's transfer-pair linking endpoints."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.web.server import Handler


def _server(store):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _transfer(id_, date, amount, direction, account):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"TRANSFER {id_}", account=account,
                       is_transfer=True, category="Transfers")


def _get(port, path):
    return json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=3).read())


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=3)


def test_api_transfers_reports_coverage_and_buckets(tmp_path):
    store = Store(home=tmp_path)
    linked_a = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    linked_b = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    ambiguous_debit = _transfer("d2", "2026-06-01", 7000, Direction.DEBIT, "bank")
    ambiguous_c1 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "card")
    ambiguous_c2 = _transfer("c3", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    pending = _transfer("d3", "2026-06-05", 3000, Direction.DEBIT, "bank")
    dismissed = _transfer("d4", "2026-06-06", 2000, Direction.DEBIT, "wallet")
    store.upsert_transactions([linked_a, linked_b, ambiguous_debit,
                               ambiguous_c1, ambiguous_c2, pending, dismissed])
    store.link_transfer("d1", "c1", confidence="auto")
    store.dismiss_transfer("d4")
    srv, port = _server(store)
    try:
        d = _get(port, "/api/transfers")
        # coverage.pending matches the CLI's own transfers_status semantics:
        # every is_transfer transaction that's neither linked nor dismissed,
        # which includes BOTH legs of the still-open ambiguous pair (d2,
        # c2, c3) AND the genuinely zero-candidate d3 -- four rows total,
        # not just the one zero-candidate transaction.
        assert d["coverage"] == {"auto": 1, "confirmed": 0,
                                 "dismissed": 1, "pending": 4}
        assert len(d["ambiguous"]) == 1
        assert d["ambiguous"][0]["debit"]["id"] == "d2"
        assert {c["id"] for c in d["ambiguous"][0]["candidates"]} == {"c2", "c3"}
        # d["pending"] (the display list, distinct from coverage.pending
        # above) is narrower by design: it excludes anything already
        # actionable in the ambiguous queue, showing only genuinely
        # zero-candidate transactions -- so just d3 here, not d2/c2/c3.
        assert [p["id"] for p in d["pending"]] == ["d3"]
    finally:
        srv.shutdown()


def test_post_transfer_link_confirms_a_pair(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/link",
                    {"debit_id": "d1", "credit_id": "c1"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
        rows = reloaded.all_transfer_links()
        assert rows[0]["confidence"] == "confirmed"
    finally:
        srv.shutdown()


def test_post_transfer_link_rejects_already_linked(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 5000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    store.link_transfer("d1", "c1")
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/link",
                 {"debit_id": "d1", "credit_id": "c2"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
    finally:
        srv.shutdown()


def test_post_transfer_link_rejects_unknown_transaction(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/link",
                 {"debit_id": "d1", "credit_id": "nonexistent"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_marks_dismissed(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/dismiss", {"id": "d1"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        assert reloaded.is_dismissed("d1")
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_rejects_already_linked(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/dismiss", {"id": "d1"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert not reloaded.is_dismissed("d1")
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_rejects_unknown_id(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/dismiss", {"id": "nonexistent"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_post_transfer_relink_runs_auto_linking(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/relink", {})
        assert json.loads(res.read()) == {"ok": True, "linked": 1}
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/classify/tests/test_web_transfers.py -v`
Expected: FAIL — `/api/transfers` returns 404 (`{"error": "not found"}`)
and the three POST routes are unrecognized (also 404), since none of
these routes exist yet.

- [ ] **Step 3: Add the `_transfers()` data-assembly method**

In `packages/classify/munim/web/server.py`, add this method to `Handler`
(place it near `_accounts()`, in the "data assembly" section):

```python
    def _transfers(self):
        from ..structural.transfer_matching import find_transfer_candidates
        txns = {t.id: t for t in self.store.all_transactions() if t.is_transfer}
        linked_ids = set(self.store.transfer_link_map().keys())
        dismissed_ids = self.store.dismissed_ids()
        links = self.store.all_transfer_links()
        n_auto = sum(1 for l in links if l["confidence"] == "auto")
        n_confirmed = sum(1 for l in links if l["confidence"] == "confirmed")
        candidates = find_transfer_candidates(self.store)
        ambiguous_ids = {d for d, _ in candidates["ambiguous"]}
        for _, cs in candidates["ambiguous"]:
            ambiguous_ids.update(cs)
        pending_all = [t for tid, t in txns.items()
                       if tid not in linked_ids and tid not in dismissed_ids]
        pending_only = [t for t in pending_all if t.id not in ambiguous_ids]
        ambiguous_rows = [
            {"debit": self._row(txns[d]),
             "candidates": [self._row(txns[c]) for c in cs]}
            for d, cs in candidates["ambiguous"]
        ]
        return {
            "coverage": {"auto": n_auto, "confirmed": n_confirmed,
                        "dismissed": len(dismissed_ids),
                        "pending": len(pending_all)},
            "ambiguous": ambiguous_rows,
            "pending": [self._row(t) for t in
                       sorted(pending_only, key=lambda t: t.date, reverse=True)],
        }
```

- [ ] **Step 4: Wire the GET route**

In `do_GET`, add a branch alongside the existing `elif route ==
"/api/accounts":` line:

```python
        elif route == "/api/transfers":
            self._send(self._transfers())
```

- [ ] **Step 5: Add the three POST handlers**

Add these three methods to `Handler` (place them near `_handle_tag`):

```python
    def _handle_transfer_link(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        debit_id = data.get("debit_id")
        credit_id = data.get("credit_id")
        if not debit_id or not credit_id:
            self._send({"error": "need debit_id and credit_id"}, status=400)
            return
        if (self.store.get_transaction(debit_id) is None
                or self.store.get_transaction(credit_id) is None):
            self._send({"error": "unknown transaction"}, status=404)
            return
        if self.store.is_linked(debit_id) or self.store.is_linked(credit_id):
            self._send({"error": "already linked elsewhere"}, status=400)
            return
        self.store.link_transfer(debit_id, credit_id, confidence="confirmed")
        self._send({"ok": True})

    def _handle_transfer_dismiss(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        txn_id = data.get("id")
        t = self.store.get_transaction(txn_id) if txn_id else None
        if t is None:
            self._send({"error": "unknown transaction"}, status=404)
            return
        if self.store.is_linked(txn_id):
            self._send({"error": "already linked — nothing to dismiss"},
                       status=400)
            return
        self.store.dismiss_transfer(txn_id)
        self._send({"ok": True})

    def _handle_transfer_relink(self):
        from ..structural.transfer_matching import apply_auto_links
        n = apply_auto_links(self.store)
        self._send({"ok": True, "linked": n})
```

- [ ] **Step 6: Wire the three POST routes**

In `do_POST`, add these branches to the existing dispatch chain (near the
`/api/rule/subcategory` check):

```python
        if path == "/api/transfer/link":
            self._handle_transfer_link()
            return
        if path == "/api/transfer/dismiss":
            self._handle_transfer_dismiss()
            return
        if path == "/api/transfer/relink":
            self._handle_transfer_relink()
            return
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest packages/classify/tests/test_web_transfers.py -v`
Expected: PASS (8 passed)

- [ ] **Step 8: Run the full existing suite**

Run: `uv run pytest packages/classify/tests -q`
Expected: all passing (217 baseline + 8 new = 225).

- [ ] **Step 9: Commit**

```bash
git add packages/classify/munim/web/server.py packages/classify/tests/test_web_transfers.py
git commit -m "Add /api/transfers and transfer link/dismiss/relink endpoints"
```

---

### Task 2: Frontend — the Transfers tab

**Files:**
- Modify: `packages/classify/munim/web/index.html`
- Test: `packages/classify/tests/test_web_transfers.py` (append one markup test)

**Interfaces:**
- Consumes: `GET /api/transfers`, `POST /api/transfer/link`,
  `POST /api/transfer/dismiss`, `POST /api/transfer/relink` (Task 1).
- Produces: a new "Transfers" tab, visible and functional in the browser.

- [ ] **Step 1: Write the failing markup test**

Append to `packages/classify/tests/test_web_transfers.py`:

```python
def test_index_page_includes_transfers_tab(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        html = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=3).read().decode()
        assert 'data-tab="transfers"' in html
        assert 'id="transfersBody"' in html
        assert 'id="transfersMeta"' in html
        assert 'id="relinkBtn"' in html
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/classify/tests/test_web_transfers.py::test_index_page_includes_transfers_tab -v`
Expected: FAIL — none of these strings exist in `index.html` yet.

- [ ] **Step 3: Add the nav button**

In `packages/classify/munim/web/index.html`, inside `<nav role="tablist"
id="tabs">`, add a new button right after the Accounts button:

```html
  <button data-tab="transfers">Transfers</button>
```

- [ ] **Step 4: Add the section**

Add this new `<section>` right after `</section>` that closes `<section
id="accounts">` and before `<section id="review"...>`:

```html
<section id="transfers">
  <h2>Settling accounts</h2>
  <p class="note">Debits and credits across your own accounts, paired up.
  Auto-linked pairs are exact, unambiguous matches; the rest need your
  pick. Dismiss a transfer that will genuinely never have a counterpart
  (e.g. money sent to an untracked account) so it stops appearing here.</p>
  <div id="transfersMeta" class="note"></div>
  <div class="controls"><button id="relinkBtn" class="confirm">Re-run auto-link</button></div>
  <div id="transfersBody"></div>
</section>
```

- [ ] **Step 5: Add the JS render function and row helpers**

In the `<script>` block, add these functions near `accounts()` (order in
the file doesn't matter functionally, but keep related tab code
together):

```javascript
function candOption(c){
  return `<option value="${c.id}">${esc(c.account)} · ${c.date} · ${fmt(c.amount,c.currency)}</option>`;
}
function ambiguousRow(r){
  const d=r.debit;
  return `<tr data-debit="${d.id}">
    <td class="num">${d.date}</td>
    <td><div class="merchant">${esc(d.merchant)||"—"}</div><div class="raw">${esc(d.raw)}</div></td>
    ${amountCell(d)}
    <td class="merchant">${esc(d.account)}</td>
    <td><select>${r.candidates.map(candOption).join("")}</select></td>
    <td><button class="confirm linkBtn">Link</button> <button class="dismissBtn">Dismiss</button></td>
  </tr>`;
}
function pendingRow(r){
  return `<tr data-id="${r.id}">
    <td class="num">${r.date}</td>
    <td><div class="merchant">${esc(r.merchant)||"—"}</div><div class="raw">${esc(r.raw)}</div></td>
    ${amountCell(r)}
    <td class="merchant">${esc(r.account)}</td>
    <td><button class="dismissBtn">Dismiss</button></td>
  </tr>`;
}
async function transfers(){
  const d=await api("/api/transfers");
  const cov=d.coverage;
  $("#transfersMeta").innerHTML=`<b>${cov.auto+cov.confirmed}</b> linked (${cov.auto} auto, ${cov.confirmed} confirmed) · <b>${cov.dismissed}</b> dismissed · <b>${cov.pending}</b> still pending`;
  const ambTable=d.ambiguous.length?`<table><thead><tr>
    <th>Date</th><th>Entry</th><th class="num">Amount</th><th>Account</th><th>Candidate</th><th></th>
  </tr></thead><tbody>`+d.ambiguous.map(ambiguousRow).join("")+`</tbody></table>`
    :`<p class="empty">Nothing ambiguous — the queue is empty.</p>`;
  const pendTable=d.pending.length?`<table><thead><tr>
    <th>Date</th><th>Entry</th><th class="num">Amount</th><th>Account</th><th></th>
  </tr></thead><tbody>`+d.pending.map(pendingRow).join("")+`</tbody></table>`
    :`<p class="empty">Nothing pending — every transfer has a candidate or a decision.</p>`;
  $("#transfersBody").innerHTML=
    `<h2 style="font-size:16px">Ambiguous (${d.ambiguous.length})</h2>${ambTable}
     <h2 style="font-size:16px;margin-top:26px">Pending, no candidate yet (${d.pending.length})</h2>${pendTable}`;
}
```

- [ ] **Step 6: Add the event handlers**

Add these near the other tab-specific event listener blocks (e.g. after
the Accounts section's code, or anywhere after the functions above are
defined):

```javascript
$("#transfersBody").addEventListener("click", async e=>{
  const linkBtn=e.target.closest(".linkBtn");
  const dismissBtn=e.target.closest(".dismissBtn");
  if(linkBtn){
    const tr=linkBtn.closest("tr");
    const debit_id=tr.dataset.debit;
    const credit_id=tr.querySelector("select").value;
    linkBtn.disabled=true;
    try{
      await api("/api/transfer/link",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({debit_id,credit_id})});
      await transfers();
    }catch(err){
      alert("Link failed: "+err.message);
      linkBtn.disabled=false;
    }
    return;
  }
  if(dismissBtn){
    const tr=dismissBtn.closest("tr");
    const id=tr.dataset.debit||tr.dataset.id;
    dismissBtn.disabled=true;
    try{
      await api("/api/transfer/dismiss",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({id})});
      await transfers();
    }catch(err){
      alert("Dismiss failed: "+err.message);
      dismissBtn.disabled=false;
    }
  }
});
$("#relinkBtn").addEventListener("click",async()=>{
  const btn=$("#relinkBtn");const orig=btn.textContent;
  btn.disabled=true;btn.textContent="…";
  try{
    const res=await api("/api/transfer/relink",{method:"POST"});
    await transfers();
    btn.textContent=`✓ ${res.linked} linked`;
    setTimeout(()=>{btn.textContent=orig;btn.disabled=false},1200);
  }catch(err){
    alert("Re-link failed: "+err.message);
    btn.disabled=false;btn.textContent=orig;
  }
});
```

- [ ] **Step 7: Register the tab in the `load` dispatcher**

Find this line near the end of the `<script>` block:

```javascript
const load=t=>({review,dashboard,transactions,accounts,categories,rules,contribute}[t]||(()=>{}))();
```

Change it to:

```javascript
const load=t=>({review,dashboard,transactions,accounts,transfers,categories,rules,contribute}[t]||(()=>{}))();
```

- [ ] **Step 8: Run the markup test to verify it passes**

Run: `uv run pytest packages/classify/tests/test_web_transfers.py::test_index_page_includes_transfers_tab -v`
Expected: PASS

- [ ] **Step 9: Run the full existing suite**

Run: `uv run pytest packages/classify/tests -q`
Expected: all passing (225 baseline + 1 new = 226).

- [ ] **Step 10: Live browser verification**

This step has no pytest equivalent — it is the real acceptance check for
the JS behavior the markup test cannot exercise. Do NOT skip it or treat
Step 9's green suite as sufficient on its own.

1. Write this throwaway script (to a temp directory of your choosing,
   e.g. your scratchpad directory) and run it with Bash in the
   background — it seeds a store with a representative mix of transfer
   transactions covering all three buckets (auto-linked, ambiguous with
   2+ candidates, dismissed, and zero-candidate pending), starts the web
   server on an ephemeral port, and keeps running so you can drive it
   with the Browser tool:

```python
import threading
import time
from http.server import HTTPServer
from pathlib import Path

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.web.server import Handler


def _transfer(id_, date, amount, direction, account):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"TRANSFER {id_}", account=account,
                       is_transfer=True, category="Transfers")


store = Store(home=Path("/tmp/munim-verify-transfers"))
linked_a = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
linked_b = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
ambiguous_debit = _transfer("d2", "2026-06-01", 7000, Direction.DEBIT, "bank")
ambiguous_c1 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "card")
ambiguous_c2 = _transfer("c3", "2026-06-02", 7000, Direction.CREDIT, "wallet")
pending = _transfer("d3", "2026-06-05", 3000, Direction.DEBIT, "bank")
dismissed = _transfer("d4", "2026-06-06", 2000, Direction.DEBIT, "wallet")
store.upsert_transactions([linked_a, linked_b, ambiguous_debit,
                           ambiguous_c1, ambiguous_c2, pending, dismissed])
store.link_transfer("d1", "c1", confidence="auto")
store.dismiss_transfer("d4")

srv = HTTPServer(("127.0.0.1", 0), Handler)
srv.store = store
port = srv.server_address[1]
print(f"PORT={port}")
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(3600)
```

2. Run it with Bash in the background, note the printed port.
3. Use the Browser tool (`mcp__Claude_Browser__preview_start` with that
   `url`, or `navigate`) to open `http://127.0.0.1:<port>/`.
4. Click the "Transfers" tab. Verify: the coverage line shows the correct
   counts, the ambiguous queue lists the seeded ambiguous debit with both
   candidates in the `<select>`, and the pending list shows the seeded
   zero-candidate transfer.
5. Pick a candidate from the `<select>` and click "Link" — verify the row
   disappears from the ambiguous queue and the coverage line's confirmed
   count increments.
6. Click "Dismiss" on a pending row — verify it disappears and the
   dismissed count increments.
7. Click "Re-run auto-link" — verify it completes without error (0 linked
   is fine if nothing new qualifies).
8. Take a screenshot of the Transfers tab mid-verification (after step 4,
   before any actions) and include it in the task report as evidence.
9. Stop the throwaway server.

- [ ] **Step 11: Commit**

```bash
git add packages/classify/munim/web/index.html packages/classify/tests/test_web_transfers.py
git commit -m "Add the Transfers tab to munim web"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After both tasks land, append one sentence to the end of the existing
`## Transfer linking` paragraph in `README.md:152` (currently ending
"...counterparty account instead of a generic clearing bucket. See
`munim transfers --help`."):

```
 `munim web`'s Transfers tab does the same review/dismiss/relink actions from the browser.
```

Documentation-only, no tests — do this in one small commit after Task
2's full-suite pass is green.
