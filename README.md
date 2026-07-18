# Munim

**A local-first transaction classifier that gets smarter every week — because it learns from you, not from a cloud.**

*Munim (मुनीम): the trusted bookkeeper who knew every merchant in town and never forgot a ledger entry.*

```
$ munim import statement.csv
  412 transactions imported
  381 resolved automatically (92.5%)
   31 waiting for you → run: munim review

$ munim review
  [1/31] "UPI-SWIGGY8102 ST BLR@okaxis"  ₹340.00  Tue 8:41 PM
         Suggested: Dining (fuzzy match: SWIGGY, 96)
         [Enter] accept · [n]ew category · [s]kip · [q]uit
```

---

## Why this exists

Every transaction categorizer makes the same two mistakes:

1. **It sends your financial data to someone else's server.** Your bank statements are the most intimate dataset you own.
2. **It bets everything on a model** — and models plateau. They misread `AMAZON PAY` vs `AMAZON FRESH` forever, because they have no memory of *your* corrections.

Munim is built on three convictions:

### 1. Local-first, privacy-absolute
Your data never leaves your machine. Everything runs on CPU, offline, in a SQLite file you own. There is no telemetry, no account, no API key required. (An LLM fallback exists as an opt-in plugin, off by default, bring-your-own-key.)

### 2. Memory over models
Personal spending is brutally repetitive: your top ~50 merchants cover the vast majority of your transactions. So the accuracy engine here is not a neural network — it's a **verified memory** of merchant→category mappings that you confirm once and benefit from forever. Models are only for the long tail, and even their predictions stay *provisional* until you confirm them.

This gives Munim a property almost no auto-categorizer can claim: **accuracy is monotonically improving.** Errors get caught in the review queue instead of silently poisoning a cache, so every week the system is at least as good as last week.

### 3. Measured, not vibed
`munim eval` runs the full pipeline against labeled fixture data and prints per-category precision/recall and per-stage coverage. Every accuracy claim in this repo is reproducible. No update to the models or dictionaries ships if it regresses the benchmark.

## How it works

```
 statement.csv
      │
      ▼
 ┌─────────────┐   ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
 │ 1 INGEST    │ → │ 2 NORMALIZE  │ → │ 3 STRUCTURE │ → │ 4 MEMORY     │
 │ CSV adapters│   │ region packs │   │ transfers,  │   │ exact+fuzzy  │
 │ → canonical │   │ strip rail   │   │ recurrence, │   │ match against│
 │ schema      │   │ noise        │   │ P2P routing │   │ YOUR rules   │
 └─────────────┘   └──────────────┘   └─────────────┘   └──────┬───────┘
                                                          miss  │  hit → done
                                                                ▼
 ┌──────────────┐        ┌───────────────┐          ┌──────────────────┐
 │ 6 REVIEW     │   ←    │ 5 FALLBACK    │    ←     │ community        │
 │ 2 min/week,  │        │ TF-IDF + LR,  │          │ merchant         │
 │ confirms →   │        │ trained on    │          │ dictionary       │
 │ memory+model │        │ your labels   │          │ (seed knowledge) │
 └──────────────┘        └───────────────┘          └──────────────────┘
```

Every classification carries **provenance**: which stage decided, with what confidence. You can always ask *why*.

The feedback loops (the actual product):

| Loop | Trigger | Effect |
|---|---|---|
| **Memory** | you confirm a merchant once | every future occurrence resolves instantly, forever |
| **Retraining** | your labels accumulate | the fallback model becomes a model of *your* spending |
| **Calibration** | corrections are logged | confidence thresholds adapt to measured error rates |
| **Community** | opt-in pattern contribution | new users cold-start with better dictionaries |

## Quick start

```bash
pip install munim            # (or: pip install -e . from this repo)
munim init                   # choose region, currency, category set
munim import statement.csv   # generic CSV wizard maps your columns once
munim review                 # confirm the unknowns — 2 minutes
munim report                 # monthly spend by category
munim web                    # or do all of it in a local browser page
```

By month three, expect the review queue to be near-empty except for genuinely new merchants.

Stage 5 (the fallback classifier for merchants outside your memory and the
community dictionary) needs scikit-learn, which is an optional extra:

```bash
pip install 'munim[ml]'      # note the quotes — zsh treats [] as a glob
```

Without it, unmatched merchants simply fall through to the review queue
unlabeled; the rest of the pipeline is unaffected.

## What Munim deliberately is NOT

- **Not a budgeting app.** It classifies; your spreadsheet/Firefly/Actual does the budgeting. `munim export` gives you clean categorized CSV.
- **Not a bank scraper.** No credentials, no APIs, no PDF parsing tar pit. You export a CSV from your bank; Munim takes it from there.
- **Not a cloud service.** And never will be.

## Engine, not app

Munim has no server and no REST API — **your SQLite file is the API** (see [docs/data-contract.md](docs/data-contract.md) for the schema stability guarantee). Everything downstream builds on that:

```bash
munim report --json | jq '.categories'   # every read command speaks JSON
munim report --by-month --json           # month x category matrix for trend tools
munim export --format ledger             # plain-text accounting (ledger/hledger)
munim export --format firefly            # Firefly III importer-ready
munim export --format jsonl              # notebooks & pipelines
munim doctor                             # data-quality gate: month gaps, missing
                                         #   accounts, dedup risk, review backlog
munim contribute                         # PR-ready anonymized dictionary bundle
                                         #   (merchant patterns only, never people)
munim web                                # local reference UI over the data contract
                                         #   (127.0.0.1 only, zero dependencies)
```

Trends, trajectories, dashboards, and budgets belong to the tools you already use. Munim's job is to hand them clean, provenance-tagged, verified categories — nothing more.

## Region packs & community dictionary

Bank-string noise is regional. Munim ships **region packs** — pluggable normalization rules — starting with:

- `in` — UPI handles, PAYTM*/BHIM prefixes, IFSC noise, NEFT/IMPS/RTGS markers
- `us` — POS*/SQ*/TST* prefixes, trailing state codes, terminal IDs

and a **community merchant dictionary** (`munim/data/dictionary/`) — versioned, human-reviewed pattern→category mappings. Contributing a pattern for your region is a 3-line PR and improves cold-start for everyone. Patterns only — never amounts, dates, or anything personal. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Benchmarks

Run `make eval`. Results on the synthetic Indian fixture set ship with each release in [eval/RESULTS.md](eval/RESULTS.md). If you can donate an anonymized labeled statement (descriptions + categories only), open an issue — real fixtures are the most valuable contribution possible.

## Design docs

- [docs/philosophy.md](docs/philosophy.md) — memory-over-models, and why autonomous learning loops poison themselves
- [docs/pipeline.md](docs/pipeline.md) — stage-by-stage reference
- [docs/adding-a-bank-adapter.md](docs/adding-a-bank-adapter.md) — support your bank in ~20 lines of YAML

## License

MIT. Your ledger is yours; so is this code.
