# Session bootstrap notes

Read this first after any context compaction. It covers operational
gotchas and this user's own conventions that aren't visible from reading
the code alone. For architecture/design, see `docs/philosophy.md`,
`docs/pipeline.md`, `docs/data-contract.md`, `docs/adding-a-bank-adapter.md`.

## Critical: which DB is real

The **live database is `~/.munim/munim.db`**, not
`packages/classify/munim.db` — that second path exists but is an empty/
stale file. Always query `~/.munim/munim.db` directly (or go through the
CLI/web API, which use it automatically via `_store()`).

The web UI (`munim web`, from `packages/classify`) runs on **port 8646**
by default. Check `curl -s localhost:8646/api/accounts` before assuming
it isn't running — it's often already up in a background terminal.

## Accounts on file (as of 2026-09)

| Account | Type | Notes |
|---|---|---|
| `tony-sib-savings` | Assets | South Indian Bank savings — primary account |
| `tony-hdfc-savings` | Assets | HDFC savings |
| `tony-hdfc-regalia-cc` | Liabilities | HDFC Regalia credit card |
| `tony-sbi-elite-cc` | Liabilities | SBI Elite credit card |
| `house-sgs` | Assets | Manually-tracked house purchase (see below) |

Naming convention: `tony-<bank>-<product>`. Real-estate/manually-tracked
assets get a short descriptive slug instead (`house-sgs`), not
`tony-house-<name>` — confirmed by the user explicitly.

## The bank-statement debit/credit convention (important, easy to get backwards)

`balance_sheet.py`'s convention: **for Assets, a credit increases the
balance and a debit decreases it; for Liabilities it's inverted.** This is
the bank-statement convention and is the **opposite of classical
textbook double-entry bookkeeping** (where a debit increases an Asset).
This distinction caused real confusion once already — when in doubt,
re-derive from `compute_account_balance` in `balance_sheet.py`, don't
assume classical rules.

## Double-entry pattern for non-liquid assets (e.g. a house)

Don't model a big one-off purchase as a category label or a frozen
opening-balance snapshot — that throws away the whole point of double-entry
(tracking the asset's own running cost basis and future related expenses
separately). Instead:

1. Create a real account, type `Assets` (e.g. `house-sgs`).
2. Every real payment toward it (purchase installments, and later any
   maintenance/renovation/property-tax cost) becomes its own transaction
   *on that account* — a **credit** (per the convention above, since
   Assets grow via credit here), category `Transfers`.
3. Link each such credit to its funding-side debit on the real paying
   account via `store.link_transfer(id_a, id_b, confidence)` (or
   `POST /api/transfer/link`). This only records the pairing — it does
   **not** touch either side's category/direction, so both sides can
   stay independently meaningful (`Transfers` on both is correct here
   since it's genuinely a transfer between two of the user's own
   holdings, not spending).
4. The account's balance *is* the running total invested — no opening
   balance needed beyond 0.

`house-sgs` is the reference implementation of this pattern (4 linked
transfer pairs, see git log around commit range `8fd5881..61f9eca`).

## The duplicate-identical-narration bug class

Multiple *real, distinct* transactions on the same day can share
byte-identical description text — e.g. several ₹500 SIP debits via the
same NACH batch reference, or a bounce-charge pair with no per-instance
reference. munim's content-hash dedup
(`date + amount + direction + description + account`) will silently
collapse these into "already imported," **losing real transactions**.

Every new parser must be checked for this before being trusted: dump the
extracted rows, group by `(date, description, amount)`, and look for
groups with count > 1. Fix pattern (see `sib_account_pdf.py`,
`sib_account.py`): a `Counter`-based pass that suffixes the 2nd+
occurrence of an exact repeat with `" (N)"`, applied at the parser level
before CSV/tuple output — never left for the importer to catch.

## Borderless PDF bank statements: word-position clustering

When `pdfplumber` finds no ruled table (a statement laid out by bare word
position, where a wrapped narration's fragments land on separate physical
lines from their own Withdrawals/Deposits/Balance figures), don't try to
parse line-by-line. Instead: read `page.extract_words()`, cluster by each
word's vertical distance to the nearest date (midpoint between neighboring
dates as cluster boundaries), then classify each cluster's non-date words
by x0 position + regex shape into columns. Reference implementations:
`packages/ingest/munim_ingest/sbi_credit_card.py` and
`packages/ingest/munim_ingest/sib_account_pdf.py` (the latter's docstring
has a full worked example of the fragment-scrambling problem).

## Gmail fetch — security rule

The user always runs `gmail fetch` commands **themselves**, in their own
terminal, never through the assistant's Bash tool — the Gmail app
password must never pass through the assistant. If gmail fetching comes
up, give the exact command and let the user run it and paste back the
output.

## Category tree (leaf categories in use)

`Investments`, `Transfers`, `Cash`, `Dining`, `Education`, `Entertainment`,
`Family & Friends`, `Groceries`, `Health`, `Housing`, `Other`, `Shopping`,
`Subscriptions`, `Transport`, `Travel`, `Utilities`, `Income`. Run
`munim categories tree` for the live leaf → ledger-path mapping — it's
config, not hardcoded, so re-check rather than assuming this list is
current.

`Family & Friends` has subcategories `Loans` and `Gifts/Support`. `Loans`
is direction-agnostic: a debit (money sent) and a credit (money repaid)
between the same two people can both be `Loans` — the category doesn't
encode direction, only the transaction's own `direction` field does.

## Review queue triage

`munim reclassify` re-runs the pipeline over everything not yet
`confirmed` — safe to run any time the review queue is nonzero, since it
never touches confirmed rows. It will *not* invent categories for
one-off P2P payments to individuals with no purpose keyword and no
prior memory rule; those need a human judgment call. When triaging the
queue by hand, prefer bulk `POST /api/confirm` with `ids` (grouped by
target category) over per-row calls, then a direct `UPDATE
transactions SET subcategory=...` for subcategories (the API derives
subcategory from existing payee memory, which is usually empty for
one-off patterns). Always verify a bulk confirm's `propagated` count
didn't sweep in unrelated amounts (e.g. `SELECT amount, direction,
COUNT(*) ... GROUP BY amount, direction` on the affected pattern) before
considering the batch safe.

## On-the-go conversational charts

When the user asks for a chart mid-conversation ("show my alcohol spend
by month," "plot my Axis vs HDFC balance this year"), call
`GET /api/chart/flow` or `GET /api/chart/balance` on the running web
server (default `http://127.0.0.1:8646`) rather than hand-writing SQL —
these endpoints already encode the transfer-exclusion convention
correctly. Sign conventions differ, though: only `/api/chart/balance`
(via `balance_series`) applies the Assets-credit-grows/Liabilities-inverted
sign convention automatically. `/api/chart/flow` with no `direction`
param sums `amount` across BOTH debit and credit — rarely what's
wanted (e.g. a debit purchase and a credit refund in the same category
would be added together instead of netting out) — so a spend query
against `/api/chart/flow` MUST pass `&direction=debit` explicitly, and
an income query needs `&direction=credit`.
Render the returned `{"labels": [...], "values": [...]}` immediately via
your own visualization tool, inline in the conversation. This is
intentionally ephemeral: nothing is written back to munim's database or
web UI. See `docs/superpowers/specs/2026-09-10-chart-engine-design.md`
if the user wants a chart to persist in the app instead — that's an
explicit non-goal of the current implementation, a follow-up to design
separately.
