# Design: voucher redemption tracking (GYFTR / Amazon Pay)

Status: designed, not yet implemented.

## Context

The user buys gift vouchers through GYFTR (via HDFC PayZapp) — either
brand-specific vouchers (Swiggy Money, Bata, Zepto) or an Amazon Pay
gift card that then gets spent broadly across merchants (FreshToHome,
Zomato District Dining, etc.). The voucher purchase itself is a real,
already-imported bank transaction, correctly categorized `Transfers`
(money converted into a voucher, not yet spent). What's missing is the
**redemption** — what the voucher money was actually spent on, at
which merchant, in which category. That spend never touches the bank
account, so it's invisible to munim entirely, which undercounts
Groceries/Dining spend for anything routed through a voucher.

GYFTR, Amazon Pay, Swiggy, and Instamart all send confirmation emails
with no attachment — the spend detail is in the email body/subject.
Gmail fetching stays a user-run terminal command (`munim-ingest gmail
fetch-vouchers`, mirroring the existing `gmail fetch` command) per
this project's standing rule that the assistant never touches the
Gmail app password — see CLAUDE.md.

The existing `munim-ingest` gmail pipeline (`packages/ingest/`) is
built entirely around **attachment** extraction (`BankPack` in
`packs.py` keyed on `from_domains` + `attachment_extensions`,
`extract_attachments`/`save_attachments` in `attachments.py`). None of
these four email types have an attachment — the data lives in the body
— so this is a new, parallel path, not an extension of `BankPack`.

## Decisions made (and why)

- **A virtual `Assets` account per voucher brand** (`voucher-amazonpay`,
  `voucher-swiggy`, `voucher-bata`, ...), auto-created the first time a
  GYFTR purchase names that brand. Reuses the double-entry pattern
  already established for `house-sgs`: a real payment becomes a credit
  into the virtual account, linked via `store.link_transfer()` to the
  real card debit; each redemption is a debit out of the virtual
  account in the transaction's real category. This was chosen over
  directly injecting spend-categorized transactions without any wallet
  account, because the Swiggy Money voucher case is explicitly
  multi-hop (one purchase funds many separate Swiggy/Instamart orders
  over time) — a running balance per brand is the only model that
  handles a 1-to-many purchase→redemption relationship correctly, and
  it's free once the account exists (visible in `/api/accounts`
  exactly like `house-sgs`).
- **GYFTR's "Value" field is the linked-transfer amount as-is** —
  confirmed with the user that voucher face value always equals what
  was actually paid (no discounted purchases to reconcile).
- **No Wallet/Gift-Card/Voucher balance-bucket tracking for Amazon
  Pay.** The email shows a 3-way balance breakdown after each spend,
  which could in principle attribute a spend to "was this real bank
  money or voucher money," but it doesn't matter: confirmed the user
  sometimes also tops up Amazon Pay directly from the bank (not GYFTR-
  only), and *both* funding paths already land as a credit into the
  same `voucher-amazonpay` account under this design. Every spend is a
  debit from that one shared pool regardless of which literal top-up
  funded it — money is fungible once inside the account. This
  eliminates a whole layer of historical-balance-diffing complexity
  that would otherwise be needed to attribute buckets.
- **Direct (non-GYFTR) Amazon Pay top-ups are out of scope for now** —
  confirmed rare enough to ignore. If one happens, the shared account's
  running balance will simply undercount by that amount; category-spend
  accuracy (the actual goal) is unaffected since redemptions are still
  recorded correctly regardless of the wallet's total-balance accuracy.
- **An explicit brand-mapping table, not slug-guessing from free
  text.** GYFTR's body repeats a product-line string ("Swiggy Money
  Voucher") that could be slugified heuristically, but one sample
  isn't enough to trust auto-derivation for brands not yet seen (Bata,
  Zepto, Amazon Pay's own wording are all unconfirmed). An unrecognized
  product-line string is skipped and logged rather than silently
  creating a wrongly-named account; the user adds one mapping-table
  line the first time a new brand appears.
- **The bank cross-check is the redemption signal for Instamart and
  the deciding signal for Swiggy** — confirmed by the user: "there
  will be an HDFC transaction if paid by card, else it'll be using
  GYFTR coupons." Swiggy's own email additionally carries an explicit
  `Paid Via` line naming the payment rail per order, which is used
  directly when present (skip on card/UPI/netbanking, redeem on a
  voucher-branded value); Instamart's email carries no such field, so
  its redemption decision is *only* the bank cross-check: search real
  transactions within a small date window (±2 days, for settlement
  lag) for a debit matching the order's Grand Total — found means
  already real spend (skip), not found means voucher-funded (create
  the redemption debit).
- **Natural order/code identifiers as the dedup key, not munim's
  content-hash scheme.** Every source email carries a guaranteed-unique
  real-world identifier (GYFTR's E-Gift Card Code; Order ID for Amazon
  Pay/Swiggy/Instamart) — using that (or a stable hash of it) as the
  synthetic transaction's id sidesteps the duplicate-identical-
  narration bug class (CLAUDE.md) entirely for this data source, and
  makes re-fetching idempotent by construction (upsert-by-id, not by
  content hash).
- **A `recheck` pass, safe to re-run anytime, rather than a one-shot
  import.** The bank cross-check's correctness depends on the
  corresponding bank statement period already being imported — running
  voucher-email fetch for a month before that month's card statement
  lands would misattribute every order as voucher-funded by default.
  Since only `voucher-<brand>` accounts ever hold these synthetic
  transactions, `recheck` can safely delete-and-regenerate every
  transaction on those accounts against current bank data, correcting
  any earlier false "voucher-funded" guess once the real card
  transaction eventually shows up. The user is expected to import bank
  statements for a period before running voucher fetch/recheck for
  that period, but a stale/early run is self-correcting on the next
  `recheck`, not a permanent data error.

## Schema

No new tables. `voucher-<brand>` accounts are ordinary values in the
existing `account` column of `transactions` — an account "exists" the
moment any transaction references it, same as every other account
today. On first creation, the wallet resolver sets
`account_types["voucher-<brand>"] = "Assets"` explicitly (config
already defaults unknown accounts to `Assets`, but an explicit entry
matches how `house-sgs` was registered and keeps `munim accounts` output
self-documenting). Linking reuses `transfer_links` exactly as-is.

## New ingest components (`packages/ingest/`)

```
munim_ingest/
  voucher_packs/
    gyftr.yaml          # sender, subject match, brand->slug/category map
    amazonpay.yaml
    swiggy.yaml
    instamart.yaml
  voucher_parse.py       # one parse_<sender>(raw_email) -> record per type
```

Each `parse_<sender>` function takes the raw fetched email (already
available via the existing IMAP client) and returns a plain dict, not
a `Transaction` — matching this package's existing separation between
"extract raw rows" (ingest) and "turn rows into `Transaction`s"
(classify):

```python
# GYFTR
{"kind": "purchase", "brand": "swiggy", "value": 2000.0,
 "code": "VGHDR7VACB6SD15E", "purchased_at": "2026-09-14"}

# Amazon Pay
{"kind": "spend", "brand": "amazonpay", "amount": 132.0,
 "merchant": "Amazon.in", "order_id": "171-9035274-8173116",
 "order_date": "2026-09-01"}

# Swiggy
{"kind": "spend", "brand": "swiggy", "amount": 391.0,
 "merchant": "Cafe Iftar", "paid_via": "Credit/Debit card",
 "order_id": "246907327135063", "order_date": "2024-08-28"}

# Instamart
{"kind": "spend", "brand": "swiggy", "amount": 395.0,
 "merchant": "Instamart", "paid_via": None,
 "order_id": "248336149154232", "order_date": "2026-09-14"}
```

An unrecognized GYFTR brand line, or a source email that doesn't match
any known template, is skipped with a printed warning — never guessed.

## Wallet resolver (`packages/classify/munim/voucher_wallet.py`, new)

Consumes the ingest records above and is the only piece that touches
the store:

1. **Purchase record** → ensure `voucher-<brand>` exists as an `Assets`
   account (create on first sight); insert a credit transaction on
   that account for `value`, dated `purchased_at`, id derived from
   `code`; find the matching real card debit (amount match, small date
   window) and `link_transfer()` the two, confidence `auto` if exactly
   one candidate else queued the same way unlinked transfers already
   are today.
2. **Spend record with `paid_via` naming a real payment rail** → skip
   entirely (already a real bank transaction elsewhere).
3. **Spend record with `paid_via` naming a wallet/voucher balance, or
   no `paid_via` at all** → run the bank cross-check (real transactions
   within ±2 days matching `amount`). Match found → skip. No match →
   insert a debit on `voucher-<brand>` for `amount`, dated
   `order_date`, id derived from `order_id`, category resolved by
   running `merchant` through munim's existing classification (same
   memory/dictionary lookup normal transactions use — no new
   category-mapping rules for this feature).
4. **`recheck`** → for every existing synthetic transaction on a
   `voucher-<brand>` account (identifiable because *only* synthetic
   transactions ever live on these accounts), delete and re-run step 3
   against current bank data. Idempotent: a still-unmatched redemption
   is deleted and recreated with the same id, a newly-matched one is
   deleted and not recreated.

## CLI

- `munim-ingest gmail fetch-vouchers` — fetches the four email types
  (mirrors `gmail fetch`'s IMAP/app-password handling exactly), writes
  raw parsed records to a local file (same "fetch, don't auto-import"
  separation as bank statement fetch).
- `munim vouchers import <file>` — runs the wallet resolver over
  fetched records, prints a summary (N vouchers purchased, N
  redemptions created, N skipped as already-real, N skipped as
  unrecognized).
- `munim vouchers recheck` — re-runs step 4 above across all voucher
  accounts.

## Non-goals (this phase)

- **Auto-deriving brand slugs from GYFTR free text.** Explicit mapping
  table only; see Decisions.
- **Direct (non-GYFTR) Amazon Pay top-up detection.** Confirmed rare;
  the shared-account model degrades gracefully (balance drifts, spend
  categorization is unaffected) if it happens anyway.
- **Split-payment orders** (one order partially paid by voucher,
  partially by card). Not mentioned as a real scenario by the user;
  the `Paid Via` / bank-cross-check logic assumes one payment rail per
  order. If this turns out to be real, it needs its own follow-up pass.
- **A web UI for voucher import/recheck.** CLI-first, matching how
  transfer-linking and balance-sheet shipped CLI-first before any web
  surface was added.
- **Parsers for brand-specific redemption emails** (Bata's own
  purchase-confirmation-style redemption, Zepto's order emails, etc.)
  beyond Swiggy/Instamart/Amazon Pay. The account-creation and linking
  mechanism is brand-agnostic and ready for them, but no sample emails
  exist yet for these — added the same way Swiggy/Instamart were, once
  a real sample is available.
