# Design: web UI for transfer-pair linking and the balance sheet

Status: designed, not yet implemented.

## Context

Two features shipped CLI-only in the previous work cycle:

- **Transfer-pair linking** (`munim transfers link/review/dismiss/status`) —
  matches debit/credit pairs across accounts, auto-linking exact matches
  and queuing ambiguous ones for a human decision.
- **Balance sheet / net worth** (`munim accounts set-opening-balance`,
  `munim balance-sheet`) — a per-account opening balance plus every
  transaction since, rolled up into Assets/Liabilities totals and a net
  worth figure.

Both are invisible in `munim web` today. The web UI
(`packages/classify/munim/web/{server.py,index.html}`) is a single static
page with seven tabs (Review, Dashboard, Transactions, Accounts,
Categories, Rules, Contribute), each backed by a small JSON API on the
same stdlib `http.server` handler. Every existing feature in this app
that has both a CLI form and ongoing user interaction (categorization,
tagging, subcategory rules) also has a web form — transfers and the
balance sheet are the exception, not by original design but simply
because they were built after the web UI's last update.

## Decisions made (and why)

- **Full interactive parity, not read-only reporting.** The web UI can
  already resolve category-review decisions, set subcategory rules, and
  bulk-tag transactions — every other "thing awaiting a human decision"
  in this app is actionable from the browser, not just visible. Making
  transfer-review and opening-balance-setting CLI-only would be a
  regression in consistency, not a smaller feature.
- **Transfers gets its own new tab**, mirroring the Review tab's
  established pattern (a queue of decisions, one row each, a `<select>`
  plus an action button) rather than folding into Review itself. Review
  is about category classification; transfer-linking is about pairing two
  existing transactions — different enough decisions that conflating them
  in one queue would confuse both.
- **Balance sheet folds into the existing Accounts tab**, not a new tab.
  Accounts already lists one row per account with import-coverage stats
  (spend, credits, transfers, date range, gaps) — opening balance and
  current balance are just two more facts about the same row, and the
  page's existing job ("everything about one account") already fits.
- **Single-pick only for the ambiguous-transfer queue, no bulk.** The
  Review tab's bulk-assign works because many rows often share one
  correct category. Ambiguous transfer pairs don't have that property —
  each debit's correct credit is usually a *different* transaction, so a
  "select several, act once" control would have nothing useful to act on.
- **No per-transaction running balance on the Transactions page.** Net
  worth and current balance are per-account, point-in-time facts computed
  from the full account history — a correct running balance per row would
  need the whole account's transactions sorted ahead of any filter, is
  easy to get subtly wrong under a search/category filter, and isn't
  something the CLI's own `munim balance-sheet` does either (it reports
  today's balance, not a statement). Out of scope here.
- **The Accounts tab's account list needs the same union fix the CLI
  already got.** `_accounts()` in `server.py` currently builds its row
  list from `SELECT DISTINCT account FROM transactions` alone — exactly
  the gap `munim balance-sheet` had before a fix during its own final
  review (an account with an opening balance or an `accounts type` entry
  but zero transactions imported yet would silently have no row to set a
  balance against). The web endpoint gets the identical three-way union
  (`transactions` ∪ `account_opening_balances` keys ∪ `account_types`
  keys) rather than re-introducing a gap already found and fixed once.

## Section 1: the Transfers tab

**Layout**, in `index.html`, added as a new `<section id="transfers">` and
a new nav button, positioned after Accounts (transfer-linking is
account-adjacent) and before Categories:

- **Coverage line**, styled like the existing `#meta` header line:
  `N linked (X auto, Y confirmed) · Z dismissed · W still pending`.
- **"Re-run auto-link"** button above the queue — the web UI never
  imports, so this is the browser's equivalent of `munim transfers link`,
  useful after a CLI import happens while the tab is open.
- **Ambiguous queue** — one row per debit with 2+ candidates: date,
  amount, account on the left; a `<select>` listing each candidate credit
  (account · date · amount) on the right; a "Link" button per row. Same
  select-then-confirm shape as the Review tab, adapted to link two
  transactions instead of assigning one category.
- **Pending list** — debits/credits with zero candidates (nothing to
  choose between yet), each row showing date/amount/account and a
  "Dismiss" button only. Rendered as a second table below the ambiguous
  queue, both inside the same `#transfersBody` container the way Rules
  renders "Learned" then "Community dictionary" as two tables in one
  section.

**New API surface** (`server.py`):

- `GET /api/transfers` → one combined payload, matching the existing
  `/api/rules` precedent of returning multiple related lists in one call:
  ```json
  {
    "coverage": {"auto": 12, "confirmed": 3, "dismissed": 2, "pending": 5},
    "ambiguous": [
      {"debit": {...row...}, "candidates": [{...row...}, ...]}
    ],
    "pending": [{...row...}, ...]
  }
  ```
  `...row...` reuses the existing `Handler._row()` shape already used by
  `/api/transactions` and `/api/queue`, so the frontend's existing
  merchant/amount/date rendering helpers apply unchanged.
- `POST /api/transfer/link` — body `{debit_id, credit_id}` → calls
  `store.link_transfer(debit_id, credit_id, confidence="confirmed")`,
  mirroring `munim transfers review`'s confirmed-link semantics exactly
  (never `"auto"` — that confidence is reserved for the unattended pass).
- `POST /api/transfer/dismiss` — body `{id}` → calls
  `store.dismiss_transfer(id)` after the same existence/not-already-linked
  validation `munim transfers dismiss` already does, returning the same
  error shape (`{"error": "..."}`, 404/400) other POST handlers use.
- `POST /api/transfer/relink` — no body, calls
  `apply_auto_links(store)` and returns `{"ok": true, "linked": n}`.

**Frontend JS**: a new `transfers()` render function following the
`review()`/`rules()` pattern — fetch `/api/transfers`, render coverage
text + two tables, delegate click/change handlers on the stable
`#transfersBody` container (never re-attached per render, per the
existing `#reviewBody`/`#rulesBody` convention this codebase already
learned the hard way — see the `v0.1.1` comment on the Review confirm
handler).

## Section 2: Accounts tab — balance sheet fold-in

**Net-worth summary band**, added above the existing accounts table,
visually matching the Dashboard's `.roots` band (same CSS classes reused,
not new ones):

```
[ Assets: ₹X ]  [ Liabilities: ₹Y ]  [ Net worth: ₹(X−Y) ]   "2/3 accounts have a starting point"
```

Hidden entirely (not shown as zeroes) when zero accounts have an opening
balance set, matching the "never silently present a partial total as
complete" rule from the balance-sheet design.

**Two new columns** on the existing accounts table: **Opening balance**
and **Current balance**, inserted after the existing "Type" column.

- **No opening balance set**: cell renders a compact inline form — an
  amount `<input type=number>`, a date `<input type=date>`, a "Save"
  button — in place of a value.
- **Opening balance set**: cell shows the value and date (e.g.
  `₹1,25,000.00 as of 2021-01-01`) plus a small "edit" link that swaps in
  the same form, prefilled with the current value, on click.
- **Current balance**: read-only, computed via `compute_account_balance`;
  renders `—` when no opening balance exists (never a silent zero).

**The account-list union fix** (see Decisions above) applies to
`Handler._accounts()`: the row set becomes `transactions` accounts ∪
`config["account_opening_balances"]` keys ∪ `config["account_types"]`
keys, so an account known only through one of the latter two still gets a
row to act on.

**API changes**:

- `GET /api/accounts` — each row gains
  `"opening_balance": {"balance": float, "as_of": "YYYY-MM-DD"} | null`
  and `"current_balance": float | null` (via `compute_account_balance`).
  The response gains a top-level `"net_worth"` object:
  ```json
  {"rows": [...], "net_worth": {
    "assets": 0.0, "liabilities": 0.0, "net": 0.0,
    "counted": 2, "total": 3
  }}
  ```
- `POST /api/accounts/opening-balance` — body
  `{"account": str, "balance": float, "as_of": "YYYY-MM-DD"}` → validates
  the date (`datetime.date.fromisoformat`, same as the CLI command),
  writes `config["account_opening_balances"][account]`, returns
  `{"ok": true}` or `{"error": "..."}` (400) on an invalid date.

**Frontend JS**: extend the existing `accounts()` render function with
the net-worth band and the two new columns; a small inline-form helper
(open/prefill/submit/re-render) shared by both the "set" and "edit" cell
states, following the same open-a-form-on-click pattern already used
nowhere else in this codebase yet, so it's new but small — a single
function toggling a `<form>` into a table cell and posting on submit,
then re-running `accounts()` to redraw from fresh data (same
refresh-after-write pattern every other mutating action in this UI
already uses).

## Non-goals

- **Per-transaction running balance** on the Transactions page — see
  Decisions above.
- **Web-triggered import or CSV upload** — out of scope for this design;
  the "Re-run auto-link" button only re-runs matching over what's already
  in the store, it does not import anything.
- **Editing or deleting an existing transfer link** from the web UI (or
  the CLI — no `unlink` command exists yet in either surface, a
  deliberately deferred piece of the transfer-linking phase itself, not
  something this web-UI pass should get ahead of).
- **Mobile-specific layout work** for the two new sections beyond what
  the existing responsive rules (`@media (max-width:700px)`) already do
  for every other table in this page.
