# Supporting your bank

Munim needs two things: a **CSV column mapping** and (optionally) better
**normalization rules** for your region.

## 1. Column mapping (no code)

Run `munim import yourbank.csv` — the wizard asks which columns hold the
date, description, and amounts, then saves the mapping under a name you
choose. Next time: `munim import file.csv --profile yourbank`.

To share the mapping with others, add it to `packages/classify/munim/ingest/profiles/` as
YAML and open a PR:

```yaml
# packages/classify/munim/ingest/profiles/hdfc_in.yaml
date_col: "Date"
description_col: "Narration"
debit_col: "Withdrawal Amt."
credit_col: "Deposit Amt."
date_format: "%d/%m/%y"
currency: "INR"
```

## 2. Region pack rules (regex, tested)

If your bank's strings aren't cleaned well, improve the region pack at
`packages/classify/munim/normalize/packs/<region>.yaml`. Each rule needs a fixture line in
`packages/classify/eval/fixtures/` proving it works — run `make eval` before submitting.

Rule types:
- `extract`: first capture group becomes the merchant candidate
- `strip`: pattern is deleted (reference numbers, city codes)
- `payee`: explicit P2P markers only — person-vs-merchant ambiguity is
  handled by the pipeline heuristic, not regex (see docs/philosophy.md)
