# Roadmap: monorepo split & ingestion buildout

Tracks the multi-package restructure and the ingestion tools, phase by
phase. Each phase links to its detailed implementation plan (if it has
one) and shows current status. Update the status line when a phase's
plan finishes execution.

## Data contract between packages

`ingest` never touches the classify package's SQLite store directly.
The boundary is a canonical transaction JSONL, one object per line —
the same shape `munim classify` already reads on stdin (see
[embedding.md](embedding.md)):

```json
{"date": "2026-06-01", "amount": 340.0, "direction": "debit",
 "description": "UPI-SWIGGY8102 ST BLR@okaxis-513324498812",
 "account": "hdfc", "currency": "INR"}
```

`ingest` produces this; `classify` consumes it. Neither package imports
the other.

## Phase 0 — Monorepo restructure (uv workspace)
**Status: done**

Move the existing classifier into `packages/classify/`, add a uv
workspace root, keep every existing command/test/eval behavior
identical. No new features, no behavior change — a pure relocation.

Plan: [superpowers/plans/2026-08-28-monorepo-restructure.md](superpowers/plans/2026-08-28-monorepo-restructure.md)

## Phase 1 — Ingest: Gmail fetch
**Status: done**

New `packages/ingest/` package. IMAP + app-password connection to
Gmail (no OAuth, no Google Cloud project — keeps the "no account, no
API key" ethos), keyword/sender search, attachment download to a local
folder. Bank search rules (from-domain, subject keywords) live in a
pack file, mirroring the existing region-pack pattern in
[adding-a-bank-adapter.md](adding-a-bank-adapter.md).

Plan: [superpowers/plans/2026-08-29-gmail-ingest.md](superpowers/plans/2026-08-29-gmail-ingest.md)

## Phase 2 — Ingest: PDF extraction
**Status: done**

`munim-ingest pdf extract <file.pdf>` decrypts a password-protected
statement PDF (pdfplumber's native password support — no per-bank
knowledge needed) and extracts its rows generically: ruled tables where
found, one row per line of text otherwise. Output is a CSV file, fed into
the existing `munim import` command's interactive column-mapping wizard
(from `packages/classify`) rather than a bank-specific parser — nobody
implementing this had a real HDFC/SBI/SIB statement PDF to build or
verify a column parser against, and reusing the proven wizard avoided
guessing at layouts that determine real transaction amounts.

Plan: [superpowers/plans/2026-08-29-pdf-extraction.md](superpowers/plans/2026-08-29-pdf-extraction.md)

## Phase 3 — Viz package
**Status: deferred**

Split `report` / `stats` / `web` / `export` out of the classify
package into `packages/viz/`, reading the same JSONL/SQLite contract.
Intentionally last — nothing else depends on it.

Plan: not yet written.
