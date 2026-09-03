# Design: category subcategories + tags

Status: designed, not yet implemented. Two independent features, sketched
together for context but intended as separate specs/plans/PRs.

## Context

Two related but distinct needs surfaced while reviewing real transaction
data this session:

1. Some categories are too coarse for the analysis the user actually
   wants — "Groceries" lumps meat, alcohol, and produce together;
   "Health" lumps actual healthcare with insurance premiums. The user
   wants a real second level under specific category heads.
2. Separately, some transactions need an ownership/purpose label that
   has nothing to do with what was bought — "business" vs "personal" vs
   a specific family member — because the same merchant (an Uber ride, a
   SaaS subscription) can serve different purposes on different
   occasions. This was flagged earlier and deferred to "Phase 3, when
   the viz package starts" (see the `next-phase-tags-feature` memory
   note); this spec is that feature, pulled forward because a concrete
   trigger (wanting to add more bank data) raised the question of doing
   it now vs. later.

These were briefly considered as one unified "tags" mechanism. They are
not: subcategories correlate strongly with the merchant (a beer shop is
always alcohol) and are naturally auto-appliable via the existing memory
system; ownership tags do not correlate with the merchant (the same Uber
ride can be either) and must stay manual. Conflating them would force
one of the two into the wrong application model.

Both are designed as purely additive changes — no schema migration risk
to the ~5,000 already-categorized transactions, no forced re-review, and
the current 20-category cap (`MAX_LEAVES` in `tree.py`) is completely
unaffected since neither subcategories nor tags are top-level categories.

## Feature 1: Category subcategories

### Decisions made (and why)

- **Optional, not required.** A transaction can sit at `Groceries`
  (unrefined) or `Groceries:Meat` (refined). Forcing every transaction
  under a subcategorized head to pick one would turn an opt-in
  refinement into mandatory extra review work.
- **Capped per-parent, not against the shared 20-leaf budget.** The
  20-category cap exists because "more heads means less consistent
  labeling" at the top level, where every category competes for the
  same review-menu slot. Subcategories only ever show up once you've
  already committed to a parent, so they get their own smaller budget
  (soft cap, e.g. 10 per parent) rather than eating into the scarce
  top-level 20.
- **Stored as a separate `subcategory` column, not a path string in
  `category`.** Keeping `category` untouched means every existing piece
  of logic that does exact string equality on it — transfer detection,
  `INCOME_MARKERS`, memory rule keys, the community dictionary,
  `category_tree` root mapping, the fallback classifier — needs zero
  changes. `subcategory` rides alongside as a second, independent,
  always-optional field.
- **Auto-applied via memory rules, same mechanic as category.** Given
  how strongly subcategories correlate with merchant identity, and
  given the app's whole design principle is "teach once, it propagates
  forever," manual-only subcategorization would work against the grain
  of the entire system and mean re-doing hundreds of rows by hand.
  Scoped to **memory rules only** for v1 — not the community dictionary,
  not purpose-tail keyword matching — since subcategory is a personal,
  fine-grained judgment call, not generic seed knowledge. Can extend to
  dictionary-level subcategories later if that proves useful.
- **A separate pass, not inline in the core review flow.** `munim
  review` is explicitly designed as a fast weekly ritual; adding a
  second optional prompt to every single transaction works against
  that. Subcategorizing is something done deliberately (teach a rule,
  let it propagate), not something injected into the primary loop.

### Schema

```sql
ALTER TABLE transactions ADD COLUMN subcategory TEXT DEFAULT '';
ALTER TABLE memory ADD COLUMN subcategory TEXT DEFAULT '';
```

New config key:

```json
"subcategories": {"Groceries": ["Meat", "Alcohol", "Produce"], "Health": ["Insurance"]}
```

### Pipeline / memory

- `Transaction.subcategory: str = ""` added to the pydantic schema.
- `Pipeline._assign()` sets `t.subcategory` when the matched **memory**
  rule (`Stage.MEMORY_EXACT` / `Stage.MEMORY_FUZZY`) carries one.
  Dictionary and purpose-tail matches never set it.
- `store.remember()` and `store.propagate()` gain an optional
  `subcategory` parameter, threaded through identically to `category`.
- `munim reclassify` resets `subcategory` to `''` on unconfirmed rows
  before re-running the pipeline, same as `category` — confirmed rows
  keep whatever subcategory they had.

### CLI

- `munim categories subcategories add <parent> <name>` — validates the
  parent category exists, enforces name uniqueness within that parent,
  soft-caps the count per parent.
- `munim categories subcategories list [<parent>]`
- `munim learn <pattern> <category> --subcategory <sub>` — one new
  optional flag on the existing command.

### Web UI

- **Rules page**: an optional subcategory dropdown appears next to
  category when teaching/viewing a rule whose category has
  subcategories defined. Rules with one show as `Groceries · Alcohol`.
- **Transactions page**: the category filter gains a second-level
  dropdown that appears once a category with subcategories is selected.
  Rows with a subcategory show it as a secondary label next to the
  category chip.

### Export

`category_tree` lookup extends at read time —
`category_tree[category] + ":" + subcategory` when subcategory is set
(e.g. `Expenses:Groceries:Alcohol`) — no new config structure needed
beyond what already exists for `category_tree`.

## Feature 2: Tags

### Decisions made (and why)

- **Multi-tag, curated list.** A transaction can carry any number of
  tags (a trip could be both "Business" and involve a specific family
  member). The list itself is managed like `categories` — a fixed,
  named set you add to deliberately — rather than freeform text, so
  filtering/analysis later isn't fighting typo variants ("spouse" vs
  "wife").
- **Manual only, always — no auto-application via rules.** This is the
  key way tags differ from subcategories: ownership/purpose doesn't
  correlate with the merchant, so a rule-based "SHETTY BEER SHOP always
  means X" approach would actively produce wrong answers here. Every
  tag assignment is a human decision about a specific transaction.
- **Surfaced in the web UI now, not deferred to the future viz layer.**
  The transactions page already has search/category filtering from
  earlier this session; tags plug into that same surface immediately,
  giving real value ("show me all business spend") well before Phase 3
  (the dedicated viz package) exists.

### Schema

```sql
CREATE TABLE IF NOT EXISTS tags (
    txn_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (txn_id, tag)
);
```

New config key: `"tags": ["Business", "Personal", "Spouse"]` — same
flat-list-in-config shape as `categories`.

### CLI

- `munim tags add <name>` / `munim tags list` / `munim tags remove
  <name>` — mirrors `munim categories add/list/remove`, with a more
  generous soft cap (e.g. 30) since tags aren't fighting the same
  top-level "labeling consistency" pressure a mutually-exclusive
  category list has.
- `munim tag <txn-id> <tag> [<tag2> ...]` — sets a transaction's tags
  directly (replace-all semantics). Same spirit as `munim classify` —
  a scriptable, host-app-friendly entry point.
- `munim tag --pattern "<merchant text>" <tag>` — a **one-time bulk
  apply**, explicitly not a saved rule. Tags every currently-matching
  transaction once; does not enter memory and has no effect on future
  imports. This is the escape hatch for "I know this whole batch was
  business" without violating the manual-only guarantee — it's still a
  deliberate one-time human decision, just applied in bulk instead of
  row by row.

### Web UI

- Transactions page gains a tag filter (multi-select) alongside the
  existing category filter.
- Each row gets a small tag-chip area; clicking opens a picker
  (checkboxes against the curated list) to add/remove tags on that
  transaction.
- New endpoints: `GET /api/tags` (list + usage counts, mirrors
  `/api/categories`), `POST /api/tag` (set tags on one transaction,
  mirrors `/api/confirm`).

No pipeline, memory, or `reclassify` involvement anywhere in this
feature.

## Migration / rollout

Both features are additive only:

```sql
ALTER TABLE transactions ADD COLUMN subcategory TEXT DEFAULT '';
ALTER TABLE memory ADD COLUMN subcategory TEXT DEFAULT '';
CREATE TABLE IF NOT EXISTS tags (...);
```

SQLite has no `ADD COLUMN IF NOT EXISTS`, so `store.py`'s schema
bootstrap needs a `PRAGMA table_info` check before each `ALTER TABLE`,
guarding against re-running on an already-migrated database (the same
pattern any future added column would need — this is the first time
one's been added post-launch, so the check itself is new machinery, not
just its two callers).

No backfill of existing data is required or intended. Every current
transaction simply has `subcategory=''` and no tag rows — indistinguishable
from "not yet refined" — and stays that way until the user deliberately
subcategorizes or tags something. This mirrors how the review queue
itself already works: nothing is forced, everything is opt-in at the
user's own pace.

## Explicit non-goals (this spec)

- No inline subcategory prompt during `munim review`.
- No auto-tagging, ever, by any mechanism (rules, dictionary, ML).
- No community-dictionary-level subcategories in v1.
- No expense↔reimbursement *linking* (pairing a business expense with
  the Income credit that reimbursed it) — flagged separately in the
  `next-phase-tags-feature` memory note as a related but distinct
  future requirement, not solved by tags alone.
- No decision yet on build order between the two features — sketched
  together for shared context, but each gets its own implementation
  plan and can ship independently.

## Open question for the next session

Which feature to implement first (or whether to do subcategories,
tags, or both before importing more bank accounts) — deferred to a
follow-up decision, not blocking this spec being written down now.
