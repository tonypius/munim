# Pipeline reference

Every transaction flows through these stages in order. The first stage that
resolves it wins, and the decision carries provenance (stage + confidence).

A matched memory rule (stage 4) may also carry a `subcategory` — an
optional, user-taught second level under the category (e.g.
`Groceries` -> `Alcohol`), applied only when the rule itself has one. No
other stage ever sets `subcategory`.

| # | Stage | Module | Resolves | Status produced |
|---|-------|--------|----------|-----------------|
| 1 | Ingest | `packages/classify/munim/ingest/` | CSV -> canonical `Transaction` | — |
| 2 | Normalize | `packages/classify/munim/normalize/` | raw string -> merchant candidate / payee handle / purpose tail, via region pack | — |
| 3 | Structural | `packages/classify/munim/structural/` | transfers, income, recurrence tags | provisional (0.95+) |
| 4 | Memory | `packages/classify/munim/memory/` | exact -> containment -> fuzzy vs user rules, then community dictionary | user-exact = confirmed; rest provisional |
| 5 | Purpose | `packages/classify/munim/memory/purpose.py` | the raw narration's trailing purpose word (e.g. "food", "taxi") vs a keyword dictionary — last resort, only reached after stage 4 misses | provisional |
| 6 | Fallback | `packages/classify/munim/fallback/` | TF-IDF char n-grams + logistic regression | provisional |
| 7 | Review | `packages/classify/munim/cli.py review` | the user | **confirmed** |

## Precedence rules

1. Transfer detection short-circuits everything (not spending).
2. User memory > community dictionary > purpose keywords > model. Always.
3. A payment routed to a person (payee) is resolved by payee memory first;
   if that misses, the purpose-tail keyword dictionary gets a shot before
   the transaction is given up as unresolved — but never by the merchant
   dictionary or the model, since neither of those ever sees payee text.
4. Nothing enters memory or the training set without user confirmation.

## The four feedback loops

| Loop | Input | Output | Cadence |
|------|-------|--------|---------|
| 1 Memory | a confirmation in review | permanent pattern->category rule | instant |
| 2 Retraining | accumulated confirmed labels | fresh fallback model | after each review session |
| 3 Calibration | corrections log (predicted vs final) | per-stage measured accuracy -> threshold tuning | `munim stats` |
| 4 Community | opt-in pattern PRs | better dictionaries for everyone | releases |
