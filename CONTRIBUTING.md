# Contributing to Munim

The most valuable contributions, in order:

## 1. Merchant dictionary patterns (3-line PR)

Add patterns to `munim/data/dictionary/<region>.yaml`:

```yaml
Dining:
  - THIRD WAVE COFFEE
```

Rules:
- **Patterns only.** Never amounts, dates, account details, or anything
  from your personal statements.
- Pattern must be a real merchant identifier, >= 4 characters, uppercase.
- Use categories from `munim/data/categories.yaml`.
- One merchant per line; alphabetical within category preferred.

## 2. Labeled fixture data (the gold standard)

Anonymized labeled statements make the benchmark real. To donate:
take real description strings, replace any personal names/handles with
fictional ones, keep the structural noise intact (that's the point), and
add ground-truth categories. Format: see `eval/fixtures/synthetic_in.csv`.

## 3. Region packs and bank profiles

See `docs/adding-a-bank-adapter.md`. Every regex rule needs a fixture
line proving it. Run `make eval` — PRs that regress the benchmark are
rejected automatically.

## 4. Code

- `make test` and `make eval` must pass.
- New pipeline stages must set provenance (`stage`, `confidence`) and
  respect the core invariant: **nothing enters memory or training data
  without user confirmation.** PRs that violate this are rejected
  regardless of accuracy gains — see `docs/philosophy.md`.

## Privacy line (non-negotiable)

No PR may add telemetry, network calls in the default path, or any
mechanism that moves user data off the machine. LLM/cloud integrations
must be opt-in plugins, off by default.
