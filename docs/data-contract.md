# The data contract: your SQLite file is the API

Munim is an engine, not an app. It has no server, no REST API, and no
plugin SDK — because it doesn't need one. Everything Munim knows lives in
one SQLite file you own:

```
~/.munim/munim.db
```

Any dashboard, spreadsheet, notebook, or budgeting tool can read it
directly. This page is the contract.

## Stability guarantee (semver)

- **Patch/minor releases** may ADD tables or columns. They will never
  rename, remove, or change the meaning of existing columns.
- **Major releases** may change the schema, and will ship a migration
  plus a documented changelog entry.
- The `config` table always contains `schema_version`.

If you build on these tables, pin against the major version.

## Tables

### transactions
| column | type | meaning |
|---|---|---|
| id | TEXT PK | sha1(date, amount, direction, raw description, account) — stable dedup key |
| date | TEXT | ISO date |
| amount | REAL | always positive; see direction |
| currency | TEXT | ISO code |
| direction | TEXT | `debit` / `credit` |
| description_raw | TEXT | untouched bank string |
| account | TEXT | user-chosen account name (`--account` at import) |
| balance | REAL | nullable, as exported by the bank |
| merchant_norm | TEXT | normalized merchant candidate ('' if P2P) |
| payee_handle | TEXT | person/payee string for P2P ('' if merchant) |
| category | TEXT | current category ('' = uncategorized) |
| subcategory | TEXT | optional second level under category ('' = unrefined); see `config.subcategories` |
| confidence | REAL | 0–1 |
| stage | TEXT | provenance: `structural`, `memory_exact`, `memory_fuzzy`, `dictionary`, `purpose`, `fallback`, `user`, `none` |
| status | TEXT | `confirmed` (user-verified) / `provisional` (machine) / `unresolved` |
| is_transfer | INTEGER | 1 = not spending; exclude from expense analytics |
| is_recurring | INTEGER | 1 = detected subscription/EMI/salary pattern |

**Consumer rules of thumb:** for spending analytics filter
`direction='debit' AND is_transfer=0`; treat `status` as your data-quality
signal (confirmed rows are ground truth, provisional rows are suggestions).

### memory
User-confirmed rules. `pattern` (uppercase), `kind` (`merchant`/`payee`),
`category`, `subcategory` (optional, '' = none), `created_at`. Treat as
read-only from outside — writing rules without a confirmation event
breaks the provenance guarantees.

### corrections
Prediction audit log: `txn_id`, `predicted_category`, `predicted_stage`,
`predicted_confidence`, `final_category`, `was_correct`, `at`. This is the
raw material for accuracy-over-time trend lines.

### tags
Manually-assigned ownership/purpose labels — `txn_id`, `tag`, primary key
on the pair. Multi-valued (a transaction may carry any number of tags) and
never touched by the pipeline, memory, or the community dictionary; every
row here is a deliberate human action. Not a column on `transactions` —
look tags up separately, the same way `corrections` already works.

### transfer_links
Confirmed transfer pairs — `id`, `txn_id_a`, `txn_id_b`, `confidence`
(`auto` / `manual`), `created_at`. Not columns on `transactions` — look
links up separately, the same way `corrections` already works. Ledger
export uses this table to post a linked transfer's counter-leg against
the real counterparty account instead of a generic clearing bucket.

### transfer_dismissals
Transactions a user has confirmed are one-sided, not part of a transfer
pair — `txn_id`, `dismissed_at`. Also not a column on `transactions`;
excludes a transaction from future transfer-matching candidates.

### config
Key/value JSON: `region`, `currency`, `categories`, `category_aliases`,
`csv_profiles`, `schema_version`, `category_tree` (leaf -> ledger path under
the five roots: Assets, Liabilities, Equity, Income, Expenses),
`subcategories` (category -> list of allowed subcategory names), `tags`
(the curated tag list), and `account_types` (account -> Assets | Liabilities).

The tree is a DISPLAY mapping consumed by exporters and the dashboard;
`transactions.category` always stores the flat leaf. Consumers wanting
hierarchy should resolve leaves through `category_tree` themselves.

## Structured output without touching SQL

Every read command speaks JSON for scripting:

```bash
munim report --json | jq '.categories'
munim report --by-month --json      # month x category matrix
munim stats --json                  # stage coverage + measured accuracy
munim export --format jsonl        # one transaction per line
```

## Downstream export formats

- `munim export --format csv` — flat categorized CSV
- `munim export --format jsonl` — for pipelines/notebooks
- `munim export --format ledger` — plain-text accounting (ledger/hledger/beancount-convertible)
- `munim export --format firefly` — Firefly III importer-ready CSV
