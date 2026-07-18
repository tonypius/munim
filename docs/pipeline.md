# Pipeline reference

Every transaction flows through these stages in order. The first stage that
resolves it wins, and the decision carries provenance (stage + confidence).

| # | Stage | Module | Resolves | Status produced |
|---|-------|--------|----------|-----------------|
| 1 | Ingest | `munim/ingest/` | CSV -> canonical `Transaction` | — |
| 2 | Normalize | `munim/normalize/` | raw string -> merchant candidate / payee handle, via region pack | — |
| 3 | Structural | `munim/structural/` | transfers, income, recurrence tags | provisional (0.95+) |
| 4 | Memory | `munim/memory/` | exact -> containment -> fuzzy vs user rules, then community dictionary | user-exact = confirmed; rest provisional |
| 5 | Fallback | `munim/fallback/` | TF-IDF char n-grams + logistic regression | provisional |
| 6 | Review | `munim/cli.py review` | the user | **confirmed** |

## Precedence rules

1. Transfer detection short-circuits everything (not spending).
2. User memory > community dictionary > model. Always.
3. A payment routed to a person (payee) can only be resolved by payee
   memory — never by the merchant dictionary or the model.
4. Nothing enters memory or the training set without user confirmation.

## The four feedback loops

| Loop | Input | Output | Cadence |
|------|-------|--------|---------|
| 1 Memory | a confirmation in review | permanent pattern->category rule | instant |
| 2 Retraining | accumulated confirmed labels | fresh fallback model | after each review session |
| 3 Calibration | corrections log (predicted vs final) | per-stage measured accuracy -> threshold tuning | `munim stats` |
| 4 Community | opt-in pattern PRs | better dictionaries for everyone | releases |
