# Design philosophy

## Memory over models

Personal spending follows a brutal power law: your top ~50 merchants cover
the overwhelming majority of your transactions. A system that *remembers*
a confirmed mapping resolves those instantly and perfectly, forever. A
system that *predicts* re-derives the answer every time — and keeps making
the same mistakes (`AMAZON PAY` vs `AMAZON FRESH`) because it has no memory
of your corrections.

Munim therefore inverts the usual architecture: memory is the primary
classifier, and the ML model is a fallback for the shrinking long tail.

## Why the learning loop is human-gated

Many auto-categorizers feed their own predictions back into a cache to
"learn". This poisons itself: one misclassification gets frozen and then
propagated to every future similar transaction. Errors compound.

Munim's invariant: **machine outputs are provisional; only user-confirmed
labels enter memory or training data.** Errors get caught at the review
queue instead of amplified, which means accuracy is monotonically
improving — every week the system is at least as good as last week.
The cost is ~2 minutes/week of review, front-loaded and shrinking.

## Why fuzzy string matching, not embeddings

Bank-string noise is *orthographic* — truncation, weird spacing, appended
terminal IDs — not semantic. `SWIG GY` is a typo of SWIGGY, not a related
concept. Character-level matching (RapidFuzz token_set_ratio) handles this
directly. Sentence embeddings were trained on natural language, are poorly
calibrated on uppercase bank gibberish, and happily score `AMAZON PAY` and
`AMAZON FRESH` as near-identical when they are different categories.
Fuzzy matching is also 100x smaller, faster, and — crucially — explainable.

## Why people are not merchants

In UPI markets, a large share of transactions are payments to individuals.
`RAMESH KUMAR@okhdfc` carries zero category signal — it could be rent, a
loan repayment, or dinner. No model can resolve it; pretending otherwise
produces confident garbage. Munim routes person-payments to a separate
payee-memory that only the user can populate.

## Why transfers come first

Credit card bill payments, savings sweeps, and wallet top-ups are not
spending. Categorizing them as spending double-counts money and corrupts
every report downstream. Transfer detection runs before any merchant
logic and short-circuits the pipeline.

## Why an eval harness ships in the repo

"Very high accuracy" is marketing until it is measured. `munim eval` runs
the full pipeline against labeled fixtures and prints per-category
precision/recall and per-stage coverage. Updates that regress the benchmark
don't merge. Every claim in the README is reproducible by anyone.

## Why categories are flat (and the tree is a view)

Hierarchy multiplies leaf classes while your n=1 training data stays fixed,
turns every community-dictionary placement into an argument, and makes the
two-minute review a navigation exercise — which produces inconsistent
labels, and inconsistent confirmations are poisoned ground truth. So the
engine holds a hard limit of 20 flat leaves, and the five-root accounting
tree (Assets, Liabilities, Equity, Income, Expenses) exists only as a
display mapping at the edges: exporters, dashboard, and any downstream
consumer. Labeling consistency is the product; trees are a view, not a truth.
