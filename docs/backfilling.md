# Backfilling a full financial year

There is no import limit — years of personal data classify in seconds.
The constraint is *your review time*, so the workflow is designed to
front-load memory and let propagation do the rest.

## The workflow

```bash
# 1. Export FY statements (Apr-Mar in India) from every account
# 2. Import each with a distinct --account name (this matters — see below)
munim import hdfc_fy26.csv    --profile hdfc  --account hdfc-savings
munim import icici_cc_fy26.csv --profile icici --account icici-cc

# 3. One review session. Each confirmation auto-applies to every
#    identical transaction across the whole year ("+39 identical").
munim review

# 4. Re-run the pipeline over what's left with your grown memory —
#    fuzzy variants and model predictions resolve in bulk.
munim reclassify

# 5. Repeat 3-4 once if needed. Then:
munim report --by-month
```

## Why per-account imports matter

Transfer detection mirror-matches a debit in one account against an
equal credit in another within 3 days. If you import everything as one
account (or only import one side), credit card bill payments and
savings sweeps get counted as spending. Import **all accounts for the
same period** for clean numbers.

## What to expect

A year has far fewer *unique* merchants than transactions — typically
60-120 unknowns for thousands of rows. Expect one 15-30 minute review
session for a full year (not the weekly 2 minutes), heavily front-loaded:
the first month you review teaches most of what the other eleven need.

## Duplicate safety

Overlapping exports are deduplicated by transaction hash (date + amount +
direction + raw description + account). Indian bank descriptions embed
unique UPI/NEFT reference numbers, so identical-looking purchases still
hash uniquely. Caveat: if your bank's CSV strips reference numbers AND
you buy the same thing twice in one day for the same amount, the second
row is dropped as a duplicate — check `munim stats` counts against your
statement if your bank's exports are that bare.
