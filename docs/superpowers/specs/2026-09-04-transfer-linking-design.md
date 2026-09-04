# Design: transfer-pair linking (double-entry foundation, phase 1)

Status: designed, not yet implemented. First phase of a larger
double-entry accounting effort — see Context and Non-goals for what's
deliberately deferred to future phases.

## Context

Raised in a side conversation: should munim adopt double-entry
accounting for handling transactions across multiple bank/credit-card
accounts, versus the current single-entry-with-a-clearing-category
approach? Investigated and found the framing needed correcting —
`to_ledger()` already emits syntactically valid double-entry ledger-cli
output (every transaction becomes two balanced postings: a category leg
and an account leg). The actual gap is narrower: **transfers between the
user's own accounts post against a generic `Equity:Transfers` clearing
bucket instead of the real counterparty account**, with no explicit link
between the two independently-imported statement lines that represent
one real-world event (e.g. a bank debit paying a credit-card bill, and
that bill's corresponding credit on the card statement).

That gap is real, not hypothetical: while investigating it, a live bug
was found and fixed separately (`Pipeline._assign()` never set
`is_transfer` for memory/dictionary/fallback-resolved transactions — only
the structural detector did), which had silently left 130 real
transactions (₹73L) wrongly counted in spend/income totals since 2021.
Fixing that bug is unrelated to this design (already shipped, commit
`049f2b1`) but it's the concrete evidence that "transfers aren't linked
or verified" is a real, not theoretical, gap.

**Scope decision**: the full double-entry vision (this transfer-linking
piece, plus investment-holdings tracking, plus business-reimbursement
accounts-receivable) was evaluated together but explicitly decomposed
into independent phases — this spec covers phase 1 only. See Non-goals.

## Decisions made (and why)

- **Additive schema, not a `Transaction` redesign.** munim's `Transaction`
  is a stable, semver-pinned contract consumed by the `munim classify`
  embedding API, JSONL export, and `docs/data-contract.md`. A "true"
  double-entry redesign (postings as the primary unit, `Transaction` as
  a derived view) would break that contract and touch the entire
  classification pipeline for a single-user, single-pipeline tool where
  the main practical benefit of write-time-enforced balancing (preventing
  *other* systems from writing bad data) doesn't apply — one pipeline,
  fully controlled, gets equivalent practical safety from a verification
  pass instead. Investment-holdings and AR-reimbursement (the other two
  double-entry use cases evaluated) were both walked through concretely
  and found buildable as small additive tables too, not requiring a
  schema redesign — reinforcing this choice rather than being a reason to
  revisit it.
- **A dedicated `transfer_links` table, no changes to `Transaction` at
  all** — not even an additive column. Whether a transaction is linked is
  answered by querying `transfer_links`, not by a stored flag on the
  transaction itself, so the existing contract is untouched in every
  sense, not just "no breaking changes."
- **No `link_type` field yet.** AR-reimbursement linking (a future phase)
  would reuse this same table's shape (linking two `Transaction`s), but
  adding a `link_type` column now would be speculative for a single
  current use case. Adding it later is a trivial additive column, not a
  migration.
- **Auto-link only exact, unambiguous matches; queue everything else for
  review.** Mirrors the existing category-memory-rule philosophy (auto-
  apply when confident, review queue for the rest) rather than the tags
  feature's always-manual philosophy — transfer identity is a much more
  mechanical, low-judgment decision than "is this business or personal,"
  so high auto-confidence is achievable and desirable.
- **Matching runs across the whole unlinked pool, not just same-import
  batches.** The existing structural transfer detector's mirror-matching
  (`structural/transfers.py`) already does amount+date-window pairing,
  but only within one `Pipeline.run()` call — useless for the common case
  of importing a bank statement today and the matching credit-card
  statement weeks later. This phase's matching pass is a separate,
  broader pass over all currently-unlinked `is_transfer=True` rows.
- **Explicit dismissal, not silent indefinite pending.** Some transfers
  genuinely never get a counterpart imported (money sent to an untracked
  account, a wallet outside munim's scope) — without a way to mark that
  deliberately, they'd clutter an "unlinked" report forever with no way
  to distinguish "genuinely pending" from "will never link."
- **Unlinked transfers fall back to today's behavior, never block.** A
  transfer with no link yet (or a dismissed one) exports exactly as it
  does today — posted against `Equity:Transfers`. The export gets more
  accurate as linking coverage grows; it's never wrong or incomplete in
  the meantime. Same opt-in, gradual-refinement philosophy as
  subcategories and tags.
- **Opening balances via config, not a new table** — following the
  existing `account_types` config-dict convention rather than introducing
  a new table for a small, rarely-written piece of per-account metadata.
- **A real correction made during design, not silently absorbed**: a
  balance-continuity check using `Transaction.balance` was initially
  proposed as "free" (already-populated data). Verified against the live
  database and found `balance` is `None` for all 5,046 transactions —
  no ingest adapter populates it; the HDFC bank-account parser's own
  `HEADER_ROW` has no balance column. That check is dropped from this
  phase (it would require adding balance-column extraction to every
  bank-format parser first, separate scoped work) rather than built on a
  false premise.

## Schema

```sql
CREATE TABLE IF NOT EXISTS transfer_links (
    id TEXT PRIMARY KEY,        -- stable hash of (txn_id_a, txn_id_b)
    txn_id_a TEXT NOT NULL,     -- the debit leg
    txn_id_b TEXT NOT NULL,     -- the credit leg
    confidence TEXT NOT NULL,   -- 'auto' | 'confirmed'
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_dismissals (
    txn_id TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL
);
```

New config keys (following the existing flat-dict convention already
used by `account_types`):

```python
config["account_opening_balances"] = {
    "<account>": {"balance": <float>, "as_of": "<YYYY-MM-DD>"},
    ...
}
```

No changes to `transactions`, `memory`, or any existing table.

## Matching mechanism

Runs as a new pass at the end of `munim import` (same extension point
where structural detection already runs), checking newly-imported
`is_transfer=True` transactions against **every** currently-unlinked
`is_transfer=True` transaction in the database — not just the current
import batch. Also exposed as an explicit `munim transfers link` command
to re-run matching without a fresh import.

For each unlinked debit, find unlinked credits in a **different account**
with an exact amount match within a date window (matching the existing
structural detector's mirror-match window):

- **Exactly one candidate** → auto-link, `confidence='auto'`.
- **Multiple candidates** → queue for review (ambiguous — the system
  cannot tell which pairs with which).
- **Zero candidates** → leave unlinked; retried on the next import or
  explicit `transfers link` run, since the counterpart likely just hasn't
  been imported yet.

## Review queue

New: `munim transfers review` (CLI) plus a web equivalent, modeled on the
existing `munim review` pattern. Shows only the **ambiguous** case — a
debit with multiple candidate credits, pick the correct one (or none).
Zero-candidate transfers do **not** appear here (no decision to make yet);
they're a reporting concern, not a review-queue item.

`munim transfers dismiss <id>` (and a web equivalent) marks a transaction
as intentionally, permanently unlinked — removes it from future matching
consideration and from the "still unlinked" report.

## Ledger export changes

`to_ledger()` (`packages/classify/munim/export_formats.py`) gains
awareness of `transfer_links`:

- **Linked transfer**: post the two legs against each other's real
  account paths directly (e.g. `Assets:tony-hdfc-savings` ↔
  `Liabilities:tony-hdfc-regalia-cc`), eliminating the `Equity:Transfers`
  wash-through for known pairs.
- **Unlinked or dismissed transfer**: unchanged from today — posts
  against `Equity:Transfers` as the counter-leg.

## Reporting: transfer-link coverage and balance sheet

**Transfer-link coverage** (`munim transfers status` or similar): counts
and totals of linked (auto + confirmed), unlinked-pending, and dismissed
transfers, ideally broken down by account to surface "you're probably
missing an import for account X."

**Balance sheet / net worth** (`munim balance-sheet`, computed on demand,
not stored): for each account with an opening balance set —

- **Assets**: `current = opening + credits − debits` (after the
  opening-balance date) — credit is inflow, debit is outflow, the
  intuitive direction.
- **Liabilities**: `current = opening + debits − credits` — inverted,
  because the statement's "balance" represents amount owed: a debit
  (purchase) increases it, a credit (payment) decreases it.

Net worth = sum of Asset current balances − sum of Liability current
balances. Any account with no opening balance set contributes nothing,
and the output must clearly state "N of M accounts have a starting
point" rather than silently presenting a partial total as complete.

Set via `munim accounts set-opening-balance <account> <amount>
<as-of-date>` — a one-time, per-account entry copied from the oldest
available statement.

## Non-goals (this phase)

- **Investment-holdings tracking** (FD/mutual-fund/crypto/chit cost
  basis, redemption gain/loss splitting) — evaluated and found buildable
  additively (a `holdings` table plus an optional `posting_splits`
  override for the 3-leg redemption case), but scoped to its own future
  design/plan/build cycle, not this one.
- **Business-reimbursement / accounts-receivable linking** — the tags
  feature already provides the "mark this as Business" half; the
  linking-to-a-reimbursement-credit half reuses this phase's
  `transfer_links` mechanism conceptually (same "link two Transactions"
  shape, different account pair) but is deferred as its own phase, since
  the fully-correct version (an expense's ledger posting changing after
  the fact based on a later reimbursement event) is the single most
  structurally complex piece of the whole double-entry effort and
  deserves its own design pass.
- **Per-account balance continuity checking** using `Transaction.balance`
  — dropped from this phase entirely; the field is unpopulated by every
  current ingest adapter, so this would require adding balance-column
  extraction to each bank-format parser first. Not attempted here.
- **Market-value / unrealized-gain net worth** — the balance sheet in
  this phase is cost-basis only (what you actually put in/took out of
  each account). Live NAV/crypto pricing to show *current market value*
  of unsold holdings needs a price-feed integration munim has no version
  of today — out of scope regardless of the double-entry question.
- **Web UI for any of this** — the review queue, `transfers status`, and
  `balance-sheet` are specified as CLI-first; a web equivalent is
  reasonable future work but not required for this phase to ship value,
  matching how several earlier features in this project shipped CLI-first
  with web support added once the CLI-side design proved out.
