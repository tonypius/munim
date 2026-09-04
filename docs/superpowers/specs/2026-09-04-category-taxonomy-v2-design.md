# Design: category taxonomy v2 (17 categories) + migration

Status: designed, not yet implemented. Redesigns the 20-category taxonomy
(already at the hard cap, `MAX_LEAVES` in `tree.py`) down to 17 categories
using real usage data across all 5,046 transactions in the live database,
then migrates every affected transaction to match.

## Context

The category-subcategories feature shipped in the previous session, but no
subcategory has actually been taught yet — the taxonomy itself needed a
pass first. Auditing spend volume per category surfaced real problems, not
just aesthetic ones:

- **Miscategorized data**: CRED-app credit-card bill payments (routed
  through the VPA `cred.club@axisb` and its RAZP/PAYU variants) were
  sitting in `Subscriptions` alongside genuine SaaS spend — some single
  payments over ₹1.5L, clearly not a subscription.
- **Overloaded categories**: `Utilities` (100 distinct merchant patterns,
  ₹7.17L total) was quietly holding four unrelated things: society
  maintenance dues, property tax, home repairs, and actual metered
  utilities (electricity/gas/telecom) — plus a maid's recurring salary
  payments that had nothing to do with utilities at all.
- **A mixed-purpose catch-all**: `Fees & Charges` (439 transactions) was
  almost entirely small genuine bank/card fees (GST lines, forex markup,
  EMI interest), but hid one large personal payment stream worth pulling
  out.
- **Conceptual overlap eating top-level slots**: `Fuel` and `Rent` are
  each single facets of a broader existing category (`Transport`,
  `Housing` respectively) and don't need their own top-level slot.

## Final taxonomy (17 categories, down from 20)

| Category | Subcategories | Ledger path |
|---|---|---|
| Groceries | Meat, Alcohol, Produce | Expenses:Groceries |
| Dining | Delivery, Dining Out | Expenses:Dining |
| Transport | Fuel, Cabs/Rideshare, Public Transit, Parking | Expenses:Transport |
| Shopping | *(none yet)* | Expenses:Shopping |
| Subscriptions | Business Tools, Personal | Expenses:Subscriptions |
| Utilities | Electricity, Gas, Telecom/Internet | Expenses:Utilities |
| **Housing** *(new)* | Rent, Maintenance/Dues, Property Tax, Repairs, Household Help | Expenses:Housing |
| Health | Insurance, Care | Expenses:Health |
| Entertainment | *(none)* | Expenses:Entertainment |
| Travel | Flights, Hotels/Packages, Forex/Prepaid Cards | Expenses:Travel |
| Education | *(none)* | Expenses:Education |
| Income | *(none)* | Income |
| Investments | FD/Deposits, Mutual Funds, Crypto, Chit/Kuri | Assets:Investments |
| Transfers | Credit Card Payment | Equity:Transfers |
| Family & Friends | Gifts/Support, Loans | Expenses:Family & Friends |
| Other | *(none)* | Expenses:Other |
| Cash | *(none)* | Expenses:Cash |

**Retired top-level categories** (folded into the above): `Fuel` →
`Transport:Fuel`. `Rent` → `Housing:Rent`. `Household Help` →
`Housing:Household Help`. `Fees & Charges` → entirely `Other` (see
migration rules).

`MAX_LEAVES` (top-level cap) stays untouched at 20 — this redesign lands
at 17, leaving 3 free slots for future growth. `MAX_SUBCATEGORIES_PER_PARENT`
(soft cap ~10) is unaffected; the largest subcategory list here (Housing,
5 entries; Transport, 4) is well under it.

## Migration scope — what this covers and what it doesn't

This migration handles **structural moves only**: transactions whose
*category* needs to change because their old category is retiring or
being split. It does **not** attempt to teach subcategories inside
categories that keep their existing name and aren't being split
(Groceries, Health, Subscriptions, Travel, Investments, Dining,
Transport's non-Fuel subcategories, Family & Friends' Gifts/Loans split
beyond the one rule below). Those subcategory lists exist in config from
today onward, but assigning them to the thousands of already-categorized
transactions is a separate, ongoing effort — the same "teach once via
`munim learn --subcategory`, let it propagate" workflow the feature was
built for, not a one-time bulk migration. Explicitly out of scope for
this plan.

## Migration rules

Every rule below is either (a) a full merchant-pattern list verified
against the live database, or (b) a keyword-matched bucket built from
that pattern list and spot-checked against raw UPI narrations (not just
the normalized merchant string) for every ambiguous case. Where a
narration check reversed an initial guess or left real ambiguity, that's
called out explicitly — these are the two points needing your sign-off
before this runs.

### Rule 1 — Fuel → Transport, subcategory Fuel

Every transaction currently `category='Fuel'` (47 transactions,
₹68,927.20) → `category='Transport', subcategory='Fuel'`. Mechanical,
no per-merchant judgment needed.

### Rule 2 — Rent → Housing, subcategory Rent

Every transaction currently `category='Rent'` (3 transactions,
₹33,656.00) → `category='Housing', subcategory='Rent'`. Mechanical.

### Rule 3 — Household Help → Housing, subcategory Household Help

Every transaction currently `category='Household Help'` (45 transactions,
₹201,623.82) → `category='Housing', subcategory='Household Help'`.
Mechanical.

### Rule 4 — CRED credit-card bill payments → Transfers

Verified via raw UPI narration that each of these routes through the
`cred.club@...` VPA specifically (the credit-card-bill-pay feature),
**not** `cred.utility@...` or `credpay.<biller>@...` (CRED's separate
bill-pay integrations for other billers, which stay wherever they
already are — already correctly categorized). Exact patterns, all
currently `category='Subscriptions'`:

```
AXIS CRED CLUB
CRED CRED CLUB
CREDCLUB1 CRED CLUB
HI2PVCTTXO1SC8 RAZPCREDCLUB
HVKZDKG4QCYSHU RAZPCREDCLUB
KQSHY4UOARZKHPOSD4 PAYUCREDCLUB
UPI AXIS CRED CLUB AXISB UTIB0000114 PAYM ENT ON CRED
```

7 patterns, 29 transactions, ₹993,891.74 total → `category='Transfers',
subcategory='Credit Card Payment'`.

**Explicitly excluded** (verified genuinely different, left untouched):
`CRED` (bare), `CRED CRED CCBP`, `CRED CRED UTILITY`, `CRED DUNZO`,
`CRED FASTAG`, `CRED FASTAGBANGALORE`, `CRED SWIGGY`, `CREDPAYDUNZO CREDPAY
DUNZO`, `CREDPAYZEPTO CREDPAY ZEPTO`, `RAZ CRED MOHALI`, `UPI JIO CREDPAY
JIO AXISB UTIB0000114 PAYM ENT ON CRED` — these either use a different
CRED VPA (bill-pay for a specific biller/merchant, already correctly
categorized under that merchant) or are already correctly in `Transfers`.

### Rule 5 — Utilities split

100 distinct merchant patterns audited, classified by keyword match
against the merchant string, cross-checked against raw narration for
every ambiguous or low-volume case. Full pattern list is in the
implementation plan (too long to inline here); summary:

| Bucket | Patterns | Total | Destination |
|---|---:|---:|---|
| Housing:Maintenance/Dues | 20 | ₹392,866.73 | MyGate, Sattva Gold Summit, Aisshwarya Excellence — apartment-association dues |
| Housing:Property Tax | 4 | ₹59,791.02 | BBMP, Khata-related |
| Housing:Repairs | 13 | ₹9,598.00 | Named plumbers/electricians, hardware stores, UrbanClap |
| Housing:Household Help | 9 | ₹46,000.00 | Cook-salary UPI narrations (already identified as miscategorized in Context) |
| Housing (unsubcategorized) | 2 | ₹72,872.77 | "Rural Development And" (₹72,872.77, likely a property-registration cess — **low confidence, flagged below**) and a ₹0 reversal narrated "House Miscellaneous" |
| Stays Utilities | 32 | ₹88,532.47 | BESCOM, KSEB, GAIL, Airtel, Jio, Vodafone, BSNL, recharge/wallet/broadband — genuine metered-utility and telecom bills |
| Other (ambiguous) | 19 | ₹47,080.00 | Small (₹15–₹14,000) one-off or low-signal individual-name UPI payments with no purpose keyword — see below |
| Transport (unsubcategorized) | 1 | ₹512.08 | "Bangalore Traffic Poli[ce]" — a traffic fine, not a utility |

Grand total ₹717,253.07 matches Utilities' full current total exactly —
every transaction accounted for, nothing silently dropped.

**The 19 "Other (ambiguous)" patterns** are small individually-named UPI
payments (K Shamala Babu, Ratheesh K V, Dominic J, and 16 others, mostly
under ₹5,000 each, several under ₹200) with no purpose keyword in their
raw narration to anchor a confident guess. They resemble the
Housing:Repairs / Housing:Household Help clusters in shape (a named
individual, a small-to-moderate one-off or recurring amount) but without
a "PLUMBER"/"COOK"/"MAID" keyword to confirm it. Routing to `Other`
rather than guessing Housing — consistent with the app's own
never-force-a-guess design principle. These remain individually
`munim relabel`-able later once you recognize a specific name.

### Rule 6 — Fees & Charges → Other (entire category)

439 transactions, ₹419,873.42 total, all → `category='Other'` (no
subcategory). The overwhelming majority are small genuine bank/card
fees: GST line items on card transactions (`IGST-VPS...`), EMI interest
lines (`SMARTEMI ,INT NBR:...`), forex markup fees, bank-verification
test deposits, loan processing charges.

The two largest outliers — `T A THOMACHEN CATHOM1987` (6 transactions,
₹110,062.00) and `JOE PAUL K` (1 transaction, ₹86,400.00, narrated
"...TAX OFFICE") — were both initially suspected to be personal
loans/gifts based on the individual names. **Confirmed by the user
during spec review: both are the user's CA/accountant, and these are tax
filing-related payments** — professional service fees, not personal
transfers. No `Family & Friends` split needed; the entire category
folds into `Other` as a single rule. The `Family & Friends:Loans`
subcategory stays in the taxonomy as an available (currently unused)
option, not removed.

## Judgment calls needing explicit sign-off

One lower-confidence call remains open (the T A THOMACHEN / JOE PAUL K
question from the first draft was resolved during spec review — both
are the user's accountant, routed to `Other` per Rule 6 above):

1. **"Rural Development And Bangalore"** (₹72,872.77, one transaction) →
   proposed `Housing` (unsubcategorized). No narration detail beyond the
   merchant name; plausibly a property-registration-related government
   cess given its size and proximity (same account, similar era) to
   other house-purchase transactions already in `Investments`
   (`FELIX REGINALD SALDANHA`, the seller). Could also be an unrelated
   one-off donation/fee. If you recognize this transaction, let me know
   where it should actually go — otherwise this placement stands.

## Migration mechanism

A one-off Python script using `Store`'s API directly (not chained CLI
commands — avoids order-of-operations bugs from renaming a category
before capturing which rows need a follow-up subcategory stamp). Runs in
two modes:

1. **Dry run** (default): prints every rule's matched transaction count
   and total amount against the *live* database, without writing
   anything. You review this output before anything is touched.
2. **Apply**: after dry-run review, re-run with a `--apply` flag. Writes
   in one pass, transaction-by-transaction: updates `transactions.category`
   / `transactions.subcategory`, and updates any matching `memory` rows
   (so future imports of the same merchant land correctly too) via the
   same category/subcategory pair.

**Safety**: the script copies `~/.munim/munim.db` to a timestamped
backup file before the `--apply` pass runs, unconditionally. The config
update (new `categories`/`category_tree`/`subcategories` in
`store.set_config`) happens in the same script, before the row-level
migration, so every row lands in a config state that already recognizes
its new home.

**Verification after apply**: re-run the same spend-by-category query
used to audit the taxonomy in the first place, confirm category totals
sum correctly (no transaction gained or lost), and confirm the affected
merchant patterns no longer appear under their old categories.

## Non-goals

- No fresh subcategory assignment for categories that aren't being
  split (see Migration scope above) — deferred to ongoing
  `munim learn --subcategory` usage.
- No changes to the pipeline, memory-matching logic, or the
  subcategory/tag features themselves — this is a data + config
  migration on top of already-shipped functionality.
- No attempt to resolve the 19 ambiguous Utilities patterns or refine
  the remaining flagged judgment call beyond what's stated above — those
  are explicit, intentional low-confidence placements, not gaps to
  solve now.
