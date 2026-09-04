# Design: subcategory classification pass v1

Status: designed, not yet implemented. Assigns subcategories to
transactions in categories that kept their name through the taxonomy v2
migration (Groceries, Health, Dining, Transport, Subscriptions, Travel,
Investments) — the "separate, ongoing effort" explicitly deferred by that
migration's spec. Family & Friends is explicitly skipped this pass.

## Context

The taxonomy v2 migration moved whole categories and fixed miscategorized
merchants, but never assigned subcategories to transactions inside
categories that didn't change name. This pass does that, following the
same principle as the taxonomy work: classify high-confidence merchant
clusters verified against real data, leave genuine long-tail ambiguity
unsubcategorized rather than guess.

Every list below was built by a full (not sampled) scan of each category's
distinct merchant patterns, keyword-matched and then read individually to
catch false positives — this caught two real mistakes before they became
bugs:

- `THURUTHUMMEL ENERGY HUBERNAKULAM` matched a naive "UBER" substring
  search but is an energy company hub in Ernakulam ("...HUB-ERNAKULAM"),
  nothing to do with the rideshare company. Excluded.
- `CRED CRED UTILITY`-style false positives from the taxonomy migration
  (see that spec) established the pattern of verifying every match against
  its actual context, applied again here.

One direct miscategorization was found and fixed via user review, not
pattern matching (see "Melvin transaction fix" below).

## Scope

**In scope**: pattern-based subcategory assignment for Groceries, Health,
Dining, Transport (beyond the Fuel already assigned by the taxonomy
migration), Subscriptions, Travel, Investments. One individual
transaction-level correction (Melvin loan repayments).

**Out of scope**: Family & Friends (all 14 transactions lack any purpose
keyword distinguishing gift from loan — a genuine judgment call, not
guessed at here). Shopping, Entertainment, Education, Income, Other, Cash,
Transfers (no subcategories defined for these, or not addressed this
pass). Completing full coverage of every category — several clusters
(general supermarkets in Groceries, most of Subscriptions' and Travel's
long tail, Transport's Parking subcategory) have no confident pattern and
are deliberately left unsubcategorized.

## Classification rules

Every pattern list is a full scan, not a sample — verified against the
live database. Totals shown are debit-direction only, matching how the
taxonomy migration's own dry-run reported.

### Groceries

- **Meat** (13 patterns, ₹76,261.41): all `FRESHTOHOME*` variants (10
  patterns, ₹72,820.41 — a fresh fish/meat delivery service, not general
  produce), plus `MY CHICKEN AND MORE` (₹956.00), `5 STAR MEAT
  PAYTMQR61EFA6` (₹485.00), `PICKET FENCE FARMS E PICKETFENCEFARMS`
  (₹2,000.00 — a farm-to-table meat/poultry brand).
- **Alcohol** (15 patterns, ₹74,600.75): `KERALA STATE BEVERAGES*` (all
  variants), `S S LIQUORS`, `LIVING LIQUIDZ`, `TONIQUE*`, `MR SPIRITS
  LLP`, `AR LIQUORS*`, `LIQUOR ZONEBENGALURU`.
- **Produce** (2 patterns, ₹249.00): `UPI K V R VEGETABLES VYAPAR
  175208945306HDFCB ANK HDFC0MERUPI VEGETA BLE`, `LULU S VEGETABLES SH
  PAYTMQR281005050101F2X0K15ZHZEQ`.
- **Left unsubcategorized**: general-basket grocery delivery/supermarkets
  (BigBasket, Grofers, Blinkit, Zepto, Swiggy Instamart, named local
  vendors) — these sell a mix of everything, not specifically meat,
  alcohol, or produce.

### Health

- **Insurance** (5 patterns, ₹58,352.51): `STAR HEALTH AND ALLIED
  CHENNAI`, `STAR HEALTH AND ALLI STARHEALTH INSURANCE`, `EMI STAR HEALTH
  AND ALLIEDCHENNAI`, `POLICYBAZAAR COM GURGAON`, `UPI XXXXXX0900
  INDB0000007 HEALTH INSURANCE`.
- **Care**: every OTHER transaction currently in `category='Health'` —
  applied as a default, not a pattern list. This is the one category
  where a default is safe: anything landing in Health is, by definition,
  either an insurance payment or care-related spending (dental, diagnostics,
  pharmacy, doctors, salons) — there is no third possibility the way there
  is for Groceries (a supermarket sells everything) or Dining (a P2P
  payment could be anything). Achieves full category coverage.

### Dining

- **Delivery** (48 patterns, ₹274,014.51): all `ZOMATO*` and `SWIGGY*`
  variants, including `CRED SWIGGY` (CRED used as a payment method for a
  Swiggy order — still Dining, still Delivery) and `SWIGGY GENIE` (a
  parcel/errand product, not food, but Swiggy-branded and already
  correctly sitting in Dining at the category level — included for
  simplicity given its small size, ₹360.00 across 4 transactions).
- **Dining Out** (21 patterns, ₹103,075.55): named restaurants/bars —
  `BREWSKY*`, `DISTRICT DINING*`, `BOSCO EATERYBANGALORE`, `EMI THE
  COMMISSIONERBLR EABANGALORE`, `AAVAKAY THE ANDHRA KITCMUMBAI`, `THE
  RENAI COCHIN COCHIN`, `EMI HOTEL SOUZA LOBONORTH GOA`, `AAM VICTUALS
  LIMIMUMBAI`, `BUFFALO WILD WINGS`, `ANUPAMS COAST TO COAST`, `BLABBER
  ALL DAY`, `BEER WORKS RESTAURANTS`, `EMI HOTEL SHADABRANGA REDDY`, `THE
  KINGS FIELD RESTAU`.
- **Left unsubcategorized**: P2P payments to named individuals (most of
  Melvin Manoj Mathew's transactions, Robin K Francis, etc.) — bill-splits
  for food/drinks that aren't a delivery app or a direct restaurant
  charge, correctly staying in Dining at the category level with no
  subcategory forced on them.

### Transport (beyond Fuel, already assigned by the taxonomy migration)

- **Fuel — additional patterns** (12 patterns, ₹34,973.90): actual fuel
  stations that were sitting under `category='Transport'` all along
  (never top-level `Fuel`, so missed by the taxonomy migration's
  whole-category move) — `GOKULA SERVICE STATION`, `PATEL SERVICE
  STATION*`, `BHARAT PETROLEUM CORPOR*`, `SOUTHERN PETROLEUM ANGAMALLY`,
  `AVARAN PETROLEUM*`, `MS NEW BOMBAY PETROLEUM THANE`, `HINDUSTAN
  PETROLEUM CORKRISHNAGIRI`, `MAHIM SERVICE STATION`, `HIGHWAY PETROLEUM
  ERNAKULAM`.
- **Cabs/Rideshare** (20 patterns, ₹58,899.58): all `UBER*` variants,
  `PAYTM UBERINDIASYSTE NOIDA`, `UPI SREEJITH S IBL SBIN0070038 UBER TAXI
  VALUE DT 19 03 2026` (explicit "UBER TAXI" purpose, routed to an
  individual — a cab paid via a driver's personal UPI handle). Excludes
  `THURUTHUMMEL ENERGY HUBERNAKULAM` (false positive — see Context).
- **Public Transit** (14 patterns, ₹118,462.11): `REDBUS*`, `IRCTC*`,
  `ROAD TRANSPORT CORPORATMUMBAI`, `KARNATAKA STATE ROAD*`, `KERALA STATE
  ROAD*`.
- **Parking**: no confident pattern found — left with zero assignments
  this pass, available for future use.
- **Left unsubcategorized**: car service/tire shops (Road Runner Autohub,
  Rudraa Ford, Sri Lakshmi Tyres, Cauvery Ford), bike registration —
  none of the four subcategories fit vehicle maintenance or registration.

### Subscriptions

- **Business Tools** (74 patterns, ₹1,456,834.79): `GOOGLE WORKSPACE*`,
  `DIGITALOCEAN*` (many distinct patterns — DigitalOcean's normalized
  merchant string embeds the exact USD conversion amount per transaction,
  a known normalization quirk, not a bug introduced here), `PAYPAL
  DIGITALOCEA`, `SLACK*` (same per-transaction-amount quirk), `GODADDY*`,
  `GOOGLE AD*`/`GOOGLE ADWORDS*`, `ADOBE*`, `ANTHROPIC*`/`CLAUDE AI
  SUBSCRIPTION*`, `OPENAI*`, `STRIPE*`.
- **Personal** (4 patterns, ₹43,235.00): `NETFLIX*` variants.
- **Left unsubcategorized**: everything else — this is partial coverage
  by design (₹1.5M of the category's ₹1.64M total is classified; the
  remainder is unreviewed long tail, not verified either way).

### Travel

- **Forex/Prepaid Cards** (2 patterns, ₹440,925.49): `HDFC BANK PREPAID
  CARD`, `HF80280921131730 HDFCBANKFOREXCARD`.
- **Flights** (5 patterns, ₹214,827.08): `EMIRATES`, `INDIGO AINE
  GURGAON`, `EMI INDIGO AINEGURGAON`, `TICKETS FLIG114504381 ABU DHABI`,
  `INDIGO PAYTM`.
- **Hotels/Packages** (23 patterns, ₹795,583.28): `MAKEMYTRIP*`, `ETI
  GLOBAL HOLIDAYS*`/`TPT * TICKETS ETI GLOBAL HOLIDAYS`, `EASE MY TRIP
  NEW`, `IXIGO`, `CLEARTRIP*`/`PAYTM CLEARTRIPPRIVATE`, `AGODA*`,
  `AIRBNB*`/`UPI RAJESH R YESTP HDFC0007131 AIRBNB VALUE DT 30 11 2025`
  (P2P reimbursement, explicit "AIRBNB" purpose), `MACHAN RESORTS LLP`,
  `HOTEL VILLA DES GOUVERNEUPONDICHERR`.
- **Left unsubcategorized**: visa fees (DS Visa Fee VFS, UKVI London —
  not travel spend in the sense any of the three subcategories capture),
  a couple of ambiguous named-individual payments (Kabilan Raveendran
  ₹75,000, purpose unclear).

### Investments

Small enough (14 distinct merchants total) that every one was reviewed
individually, not just pattern-matched:

- **FD/Deposits**: `FD THROUGH MOBILE TONY PIUS ALAPATT` (₹600,000.00).
- **Mutual Funds**: `TPT NORAH MUTUAL FUND NIPPON MULTI CAP FUND
  SUBSCRIPTION` (₹222,000.00), `ICCLGROWW GROWW BSE GROWWPAY` (₹5,000.00
  — Groww is a mutual-fund/stock investing platform).
- **Crypto**: `TONY PIUS ALAPATT SIBL XXXXXXXXXXXX2504 SAVE FROM SATOSHI`
  (₹100,000.00 — a bitcoin-savings platform), `AWLENCAN INNOVATIONS IBKL
  XXXXXXXXXXXX6569 ZEBPAY` (₹50,000.00 — a known Indian crypto exchange).
- **Chit/Kuri**: `UPI XXXXXX7770 SBIN0008627 KURI` (₹60,000.00, 12
  transactions), `UPI XXXXXX0005 SIBL0000517 KURI` (₹2,000.00).
- **Left unsubcategorized**: the two `FELIX REGINALD SALDANHA` payments
  (₹240,000 + ₹200,000 — the house-purchase seller, per prior session
  memory; real-estate acquisition doesn't fit FD/MutualFund/Crypto/Chit),
  the two `TPT INVEST PART 1/2 ROSHAN FRANCIS` payments (₹10,000 +
  ₹90,000 — a personal investment partnership with a named individual,
  not a fund), one opaque hash-like UPI reference (₹15,000, no purpose
  signal), `UPI XXXXXX7770 SBIN0008627 UPI` (₹5,000 — same source account
  as the Kuri payments but the narration itself doesn't confirm Kuri, not
  guessed at), `ESCROW AC PRESTIGE SHANTIBANGALORE` (₹60.00 — tiny,
  real-estate-escrow-adjacent, doesn't fit).

### Melvin transaction fix (not a subcategory rule — a category correction)

Two specific transactions, found via user review of a flagged anomaly (a
₹48,683 aggregate under one Dining merchant looked too high for casual
food bill-splits):

- Transaction `addd98a49577e4a7` (2024-07-11, ₹20,000.00 debit, raw
  narration contains "loanrepayment")
- Transaction `67ee8f18e8565db8` (2024-08-06, ₹15,000.00 debit, raw
  narration contains "loanrepayment")

Both currently `category='Dining'` (correct for the pattern's OTHER
transactions — food/alcohol/chocolate bill-splits with the same person —
but wrong for these two specifically). User-confirmed: this was a
₹35,000 loan, repaid in these two installments. Fixed by transaction ID,
not merchant pattern, since the same merchant's other transactions
correctly stay in Dining. Both move to `category='Family & Friends',
subcategory='Loans'`.

The remaining transactions under this same merchant (`MELVIN MANOJ
MATHEW MELVINMANOJ92`) with narrations containing "ALCOHOL" (₹1,650),
"FOOD" (₹800, ₹748) stay in Dining, unsubcategorized — correctly
food/drink bill-splits, not delivery or dining-out.

## Migration mechanism

Same approach as the taxonomy v2 migration
(`packages/classify/migrations/migrate_taxonomy_v2.py`): a script with a
dry-run mode (default) and an `--apply` mode requiring a database backup
first. Given the structural similarity, this will extend or mirror that
script rather than reinvent the mechanism — exact file structure is an
implementation-plan decision, not a design one.

**This pass is purely additive to `subcategory`** — it never changes
`category`, except for the two Melvin transactions, which is the only
category-level write in this entire pass. No config changes are needed
(the subcategory lists already exist in `config["subcategories"]` from
the taxonomy migration) beyond what the two Melvin transactions imply
(no new subcategory names — `Family & Friends: Loans` and `Health: Care`
are both already-defined subcategories).

Match transactions the same way the taxonomy migration did: exact
equality against `merchant_norm` or `payee_handle` (independently, not a
fallback), never substring matching in the script itself — the
classification judgment above was already made against full merchant
lists; the script's job is deterministic application of that judgment.
The one exception is the Melvin fix and the Health "Care" default, both
called out explicitly above as different in kind from pattern matching.

## Non-goals

- No attempt at full coverage of any category — every "left
  unsubcategorized" note above is deliberate, not a gap to close now.
- No changes to Family & Friends.
- No new subcategory names or config changes.
- No further miscategorization audits beyond the one Melvin fix — this
  pass assumes the taxonomy v2 migration's category assignments are
  otherwise correct; it is not a second full audit pass.
