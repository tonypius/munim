# Web UI: Balance Sheet Fold-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the balance-sheet feature into the existing Accounts tab in
`munim web` — a net-worth summary band, an opening-balance column
(editable inline) and a computed current-balance column per account —
giving full interactive parity with `munim accounts set-opening-balance`
and `munim balance-sheet`. Per
`docs/superpowers/specs/2026-09-07-web-ui-transfers-balance-sheet-design.md`
Section 2. Independent of, and built after, the Transfers tab plan — this
plan does not depend on anything from it.

**Architecture:** Extend the existing `Handler._accounts()` method (fix
its account-list gap the same way the CLI's `munim balance-sheet` fixed
it, then add opening/current balance + a net-worth rollup) and add one
new POST handler for setting an opening balance, both in
`packages/classify/munim/web/server.py`. Extend the existing `accounts()`
JS render function with a net-worth band (reusing the Dashboard's
`.roots`/`.root` CSS classes) and two new columns with an inline
edit-in-place form, in `packages/classify/munim/web/index.html`.

**Tech Stack:** Python 3.11+ stdlib `http.server` (no new dependencies),
vanilla JS (no build step).

## Global Constraints

- No new dependencies, frontend or backend.
- Every new backend function needs a test before being considered done
  (TDD), using the exact `HTTPServer` + `urllib.request` pattern already
  established in `packages/classify/tests/test_tags.py` and this
  project's own `test_web_transfers.py` (from the Transfers-tab plan,
  already merged before this plan starts).
- The frontend has no JS test harness. Each frontend task requires: (a) a
  real HTTP assertion on the served `index.html`'s static markup, and (b)
  a live browser-driven verification step using the Browser tool with a
  screenshot as evidence in the task report. Both are required.
- **"Never silently zero."** An account with no opening balance must
  never contribute to the net-worth total and must never render as `0` —
  render `—`/null and let the coverage line ("N/M accounts have a
  starting point") carry the caveat. This is the single most
  safety-critical rule in this plan; both the CLI's `munim balance-sheet`
  and its own final review enforced it, and the web version must match.
- **Reuse `.roots`/`.root`/`.rootl`/`.rootv` CSS classes verbatim** for
  the net-worth band — do not introduce new CSS for it. These classes
  already exist in `index.html` for the Dashboard tab's five-root
  rollup and are visually and structurally exactly what this band needs.
- The Accounts tab's account list must include every account known via
  `transactions`, `config["account_opening_balances"]`, OR
  `config["account_types"]` — not `transactions` alone. This is the exact
  gap the CLI's `munim balance-sheet` had and fixed during its own final
  review (twice — first for `account_opening_balances`, then again for
  `account_types`); do not reintroduce either half of it here.

---

### Task 1: Backend — extend `/api/accounts`, add opening-balance endpoint

**Files:**
- Modify: `packages/classify/munim/web/server.py`
- Test: `packages/classify/tests/test_web_balance_sheet.py` (new file)

**Interfaces:**
- Consumes: `compute_account_balance` (from
  `packages/classify/munim/balance_sheet.py`), `Store.get_config`,
  `Store.set_config`, `account_root` (from `packages/classify/munim/tree.py`).
- Produces:
  - `GET /api/accounts` — each row in the existing response gains
    `"opening_balance": {"balance": float, "as_of": str} | null` and
    `"current_balance": float | null`; the response gains a top-level
    `"net_worth": {"assets": float, "liabilities": float, "net": float,
    "counted": int, "total": int}`. The row list itself is now the union
    described in Global Constraints, not `transactions`-only.
  - `POST /api/accounts/opening-balance` `{account, balance, as_of}` →
    `{"ok": true}` or a 400 error on an invalid date.

- [ ] **Step 1: Write the failing tests**

Create `packages/classify/tests/test_web_balance_sheet.py`:

```python
"""Tests for the web UI's balance-sheet support on the Accounts endpoint."""
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


def _get(port, path):
    return json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=3).read())


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=3)


def test_api_accounts_includes_opening_and_current_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        row = next(r for r in d["rows"] if r["account"] == "bank")
        assert row["opening_balance"] == {"balance": 1000.0, "as_of": "2026-06-01"}
        assert row["current_balance"] == 1500.0
    finally:
        srv.shutdown()


def test_api_accounts_reports_no_balance_as_null(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.DEBIT,
                    description_raw="X", account="untracked"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        row = next(r for r in d["rows"] if r["account"] == "untracked")
        assert row["opening_balance"] is None
        assert row["current_balance"] is None
    finally:
        srv.shutdown()


def test_api_accounts_includes_account_known_only_via_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"fixed-deposit": {"balance": 50000.0, "as_of": "2026-06-01"}})
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        accounts = {r["account"] for r in d["rows"]}
        assert "fixed-deposit" in accounts
        row = next(r for r in d["rows"] if r["account"] == "fixed-deposit")
        assert row["current_balance"] == 50000.0
        assert row["n"] == 0
    finally:
        srv.shutdown()


def test_api_accounts_includes_account_known_only_via_account_types(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_types", {"hdfc-cc": "Liabilities"})
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        accounts = {r["account"] for r in d["rows"]}
        assert "hdfc-cc" in accounts
    finally:
        srv.shutdown()


def test_api_accounts_net_worth_totals_and_coverage(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_types", {"cc": "Liabilities"})
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "cc": {"balance": 200.0, "as_of": "2026-06-01"},
    })
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
        Transaction(date="2026-06-05", amount=50, direction=Direction.DEBIT,
                    description_raw="PURCHASE", account="cc"),
        Transaction(date="2026-06-05", amount=10, direction=Direction.DEBIT,
                    description_raw="NO OPENING BALANCE", account="untracked"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        nw = d["net_worth"]
        assert nw["assets"] == 1500.0
        assert nw["liabilities"] == 250.0
        assert nw["net"] == 1250.0
        assert nw["counted"] == 2
        assert nw["total"] == 3
    finally:
        srv.shutdown()


def test_post_opening_balance_writes_config(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        res = _post(port, "/api/accounts/opening-balance",
                    {"account": "bank", "balance": 1000.0, "as_of": "2026-06-01"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        balances = reloaded.get_config("account_opening_balances", {})
        assert balances["bank"] == {"balance": 1000.0, "as_of": "2026-06-01"}
    finally:
        srv.shutdown()


def test_post_opening_balance_rejects_invalid_date(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/accounts/opening-balance",
                 {"account": "bank", "balance": 1000.0, "as_of": "not-a-date"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert reloaded.get_config("account_opening_balances", {}) == {}
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/classify/tests/test_web_balance_sheet.py -v`
Expected: FAIL — `opening_balance`/`current_balance`/`net_worth` keys
don't exist on today's `/api/accounts` response, and
`/api/accounts/opening-balance` returns 404 (unrecognized route).

- [ ] **Step 3: Replace `_accounts()`**

In `packages/classify/munim/web/server.py`, replace the current
`_accounts()` method body entirely with:

```python
    def _accounts(self):
        from ..doctor import _month_range
        from ..tree import account_root
        from ..balance_sheet import compute_account_balance
        by_acct: dict[str, list] = defaultdict(list)
        for t in self.store.all_transactions():
            by_acct[t.account].append(t)
        opening_balances = self.store.get_config(
            "account_opening_balances", {}) or {}
        account_types = self.store.get_config("account_types", {}) or {}
        all_accounts = (set(by_acct.keys()) | set(opening_balances.keys())
                       | set(account_types.keys()))
        rows = []
        total_assets = total_liabilities = 0.0
        counted = 0
        for acct in sorted(all_accounts):
            ts = by_acct.get(acct, [])
            opening = opening_balances.get(acct)
            current = compute_account_balance(self.store, acct)
            acct_type = account_root(self.store, acct)
            if current is not None:
                counted += 1
                if acct_type == "Liabilities":
                    total_liabilities += current
                else:
                    total_assets += current
            if ts:
                dates = sorted(t.date for t in ts)
                have = {d.isoformat()[:7] for d in dates}
                missing = [m for m in _month_range(dates[0], dates[-1])
                          if m not in have]
                row = {
                    "account": acct, "type": acct_type, "n": len(ts),
                    "first": dates[0].isoformat(), "last": dates[-1].isoformat(),
                    "debit": sum(t.amount for t in ts
                                if t.direction.value == "debit" and not t.is_transfer),
                    "credit": sum(t.amount for t in ts
                                 if t.direction.value == "credit" and not t.is_transfer),
                    "transfers": sum(1 for t in ts if t.is_transfer),
                    "months": len(have), "missing_months": missing,
                }
            else:
                row = {
                    "account": acct, "type": acct_type, "n": 0,
                    "first": None, "last": None,
                    "debit": 0.0, "credit": 0.0, "transfers": 0,
                    "months": 0, "missing_months": [],
                }
            row["opening_balance"] = opening
            row["current_balance"] = current
            rows.append(row)
        return {"rows": rows, "net_worth": {
            "assets": total_assets, "liabilities": total_liabilities,
            "net": total_assets - total_liabilities,
            "counted": counted, "total": len(all_accounts),
        }}
```

- [ ] **Step 4: Add the opening-balance POST handler**

Add this method to `Handler` (place it near `_handle_tag`):

```python
    def _handle_set_opening_balance(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        account = data.get("account")
        balance = data.get("balance")
        as_of = data.get("as_of")
        if not account or balance is None or not as_of:
            self._send({"error": "need account, balance, and as_of"}, status=400)
            return
        from datetime import date as _date
        try:
            _date.fromisoformat(as_of)
        except (ValueError, TypeError):
            self._send({"error": f"{as_of} is not a valid date (use YYYY-MM-DD)"},
                       status=400)
            return
        balances = self.store.get_config("account_opening_balances", {}) or {}
        balances[account] = {"balance": float(balance), "as_of": as_of}
        self.store.set_config("account_opening_balances", balances)
        self._send({"ok": True})
```

- [ ] **Step 5: Wire the POST route**

In `do_POST`, add this branch to the existing dispatch chain:

```python
        if path == "/api/accounts/opening-balance":
            self._handle_set_opening_balance()
            return
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/classify/tests/test_web_balance_sheet.py -v`
Expected: PASS (7 passed)

- [ ] **Step 7: Run the full existing suite**

Run: `uv run pytest packages/classify/tests -q`
Expected: all passing (226 baseline, after the Transfers-tab plan has
landed + 7 new = 233).

- [ ] **Step 8: Commit**

```bash
git add packages/classify/munim/web/server.py packages/classify/tests/test_web_balance_sheet.py
git commit -m "Add opening/current balance and net worth to /api/accounts"
```

---

### Task 2: Frontend — net-worth band and editable balance columns

**Files:**
- Modify: `packages/classify/munim/web/index.html`
- Test: `packages/classify/tests/test_web_balance_sheet.py` (append one markup test)

**Interfaces:**
- Consumes: the extended `GET /api/accounts` and new
  `POST /api/accounts/opening-balance` (Task 1).
- Produces: a net-worth band and two new columns on the Accounts tab,
  with an inline "set/edit opening balance" form per row.

- [ ] **Step 1: Write the failing markup test**

Append to `packages/classify/tests/test_web_balance_sheet.py`:

```python
def test_index_page_includes_net_worth_band(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        html = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=3).read().decode()
        assert 'id="netWorth"' in html
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/classify/tests/test_web_balance_sheet.py::test_index_page_includes_net_worth_band -v`
Expected: FAIL — `id="netWorth"` doesn't exist in `index.html` yet.

- [ ] **Step 3: Add the net-worth band container**

In `packages/classify/munim/web/index.html`, inside `<section
id="accounts">`, add a new div right after the `<p class="note">...
</p>` and before `<div id="acctBody">`:

```html
  <div id="netWorth" class="roots"></div>
```

- [ ] **Step 4: Replace the `accounts()` JS function**

Replace the existing `accounts()` function in the `<script>` block
entirely with:

```javascript
async function accounts(){
  const {rows,net_worth}=await api("/api/accounts");
  $("#netWorth").innerHTML=net_worth.counted===0?"":
    `<div class="root"><div class="rootl">Assets</div><div class="rootv credit">${fmt(net_worth.assets,CUR)}</div></div>
     <div class="root"><div class="rootl">Liabilities</div><div class="rootv debit">${fmt(net_worth.liabilities,CUR)}</div></div>
     <div class="root"><div class="rootl">Net worth</div><div class="rootv ${net_worth.net>=0?"credit":"debit"}">${fmt(net_worth.net,CUR)}</div></div>
     <div class="root"><div class="rootl">Coverage</div><div class="rootv">${net_worth.counted}/${net_worth.total} accounts</div></div>`;
  $("#acctBody").innerHTML=rows.length?`<table><thead><tr>
    <th>Account</th><th>Type</th><th class="num">Entries</th><th>Coverage</th>
    <th class="num">Spend</th><th class="num">Credits</th><th class="num">Transfers</th><th>Gaps</th>
    <th>Opening balance</th><th class="num">Current balance</th>
  </tr></thead><tbody>`+rows.map(r=>`<tr>
    <td class="merchant">${esc(r.account)}</td>
    <td><span class="tag ${r.type==="Liabilities"?"person":""}">${r.type}</span></td>
    <td class="num">${r.n}</td>
    <td class="num">${r.first?`${r.first} → ${r.last} (${r.months} mo)`:"—"}</td>
    <td class="num debit">${fmt(r.debit,CUR)}</td>
    <td class="num credit">${fmt(r.credit,CUR)}</td>
    <td class="num">${r.transfers}</td>
    <td>${r.missing_months.length?`<span class="tag" style="color:var(--ledger-red);border-color:var(--ledger-red)">${r.missing_months.join(", ")}</span>`:r.first?'<span class="tag confirmed">complete</span>':"—"}</td>
    <td>${openingBalanceCell(r)}</td>
    <td class="num">${r.current_balance==null?"—":fmt(r.current_balance,CUR)}</td>
  </tr>`).join("")+`</tbody></table>`
  :`<p class="empty">No accounts yet — import a statement.</p>`;
}
function openingBalanceCell(r){
  if(r.opening_balance){
    return `<div class="merchant">${fmt(r.opening_balance.balance,CUR)} as of ${r.opening_balance.as_of}</div>
      <button class="obEdit" data-account="${esc(r.account)}" data-balance="${r.opening_balance.balance}" data-asof="${r.opening_balance.as_of}" style="font-size:12px">edit</button>`;
  }
  return `<button class="obEdit" data-account="${esc(r.account)}" data-balance="" data-asof="" style="font-size:12px">set opening balance</button>`;
}
```

- [ ] **Step 5: Add the inline-form event handlers**

Add these near the existing `accounts()`-related code (after the
function above):

```javascript
$("#acctBody").addEventListener("click",e=>{
  const btn=e.target.closest(".obEdit");
  if(!btn)return;
  const td=btn.closest("td");
  const{account,balance,asof}=btn.dataset;
  td.innerHTML=`<form class="obForm" data-account="${esc(account)}">
    <input type="number" step="0.01" name="balance" value="${esc(balance)}" placeholder="Amount" style="width:100px" required>
    <input type="date" name="as_of" value="${esc(asof)}" required>
    <button type="submit" class="confirm" style="padding:4px 9px">Save</button>
  </form>`;
  td.querySelector("input").focus();
});
$("#acctBody").addEventListener("submit",async e=>{
  const form=e.target.closest(".obForm");
  if(!form)return;
  e.preventDefault();
  const account=form.dataset.account;
  const balance=parseFloat(form.balance.value);
  const as_of=form.as_of.value;
  const btn=form.querySelector("button");
  btn.disabled=true;
  try{
    await api("/api/accounts/opening-balance",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({account,balance,as_of})});
    await accounts();
  }catch(err){
    alert("Couldn't save opening balance: "+err.message);
    btn.disabled=false;
  }
});
```

- [ ] **Step 6: Run the markup test to verify it passes**

Run: `uv run pytest packages/classify/tests/test_web_balance_sheet.py::test_index_page_includes_net_worth_band -v`
Expected: PASS

- [ ] **Step 7: Run the full existing suite**

Run: `uv run pytest packages/classify/tests -q`
Expected: all passing (233 baseline + 1 new = 234).

- [ ] **Step 8: Live browser verification**

No pytest equivalent exists for this step — required regardless of
Step 7's green suite.

1. Write this throwaway script (to a temp directory of your choosing,
   e.g. your scratchpad directory) and run it with Bash in the
   background — it seeds one Asset account with an opening balance and
   transactions, one Liability account with an opening balance and
   transactions, and one account with NO opening balance, starts the web
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

store = Store(home=Path("/tmp/munim-verify-balance-sheet"))
store.set_config("account_types", {"cc": "Liabilities"})
store.set_config("account_opening_balances", {
    "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
    "cc": {"balance": 200.0, "as_of": "2026-06-01"},
})
store.upsert_transactions([
    Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                description_raw="SALARY", account="bank"),
    Transaction(date="2026-06-05", amount=50, direction=Direction.DEBIT,
                description_raw="PURCHASE", account="cc"),
    Transaction(date="2026-06-05", amount=10, direction=Direction.DEBIT,
                description_raw="NO OPENING BALANCE", account="untracked"),
])

srv = HTTPServer(("127.0.0.1", 0), Handler)
srv.store = store
port = srv.server_address[1]
print(f"PORT={port}")
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(3600)
```

2. Run it with Bash in the background, note the printed port.
3. Use the Browser tool to open `http://127.0.0.1:<port>/` and click the
   "Accounts" tab.
4. Verify: the net-worth band shows correct Assets/Liabilities/Net
   worth/Coverage figures; the account with no opening balance shows a
   "set opening balance" button, not a `0` or blank cell, and its Current
   balance column shows `—`.
5. Click "set opening balance" on that account, enter an amount and date,
   submit — verify the row updates with the new value, the Current
   balance column now shows a computed figure, and the net-worth band's
   totals and coverage count update to reflect it.
6. Click "edit" on an account that already has an opening balance —
   verify the form pre-fills with the existing value, and that changing
   it and saving updates the row correctly (not creating a duplicate).
7. Take a screenshot of the Accounts tab after step 4 (before any edits)
   and include it in the task report as evidence.
8. Stop the throwaway server.

- [ ] **Step 9: Commit**

```bash
git add packages/classify/munim/web/index.html packages/classify/tests/test_web_balance_sheet.py
git commit -m "Fold the balance sheet into the Accounts tab"
```

---

## Post-plan documentation touch-ups (not a task with tests — quick doc sync)

After both tasks land, append one sentence to the end of the existing
`## Balance sheet / net worth` paragraph in `README.md:156` (currently
ending "...excluded from the total and called out explicitly rather than
silently treated as zero. See `munim balance-sheet --help` and `munim
accounts set-opening-balance --help`."):

```
 `munim web`'s Accounts tab shows and edits the same opening balances and net worth from the browser.
```

Documentation-only, no tests — do this in one small commit after Task
2's full-suite pass is green.
