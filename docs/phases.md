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
**Status: planned**

Move the existing classifier into `packages/classify/`, add a uv
workspace root, keep every existing command/test/eval behavior
identical. No new features, no behavior change — a pure relocation.

Plan: [superpowers/plans/2026-08-28-monorepo-restructure.md](superpowers/plans/2026-08-28-monorepo-restructure.md)

## Phase 1 — Ingest: Gmail fetch
**Status: not started**

New `packages/ingest/` package. IMAP + app-password connection to
Gmail (no OAuth, no Google Cloud project — keeps the "no account, no
API key" ethos), keyword/sender search, attachment download to a local
folder. Bank search rules (from-domain, subject keywords) live in a
pack file, mirroring the existing region-pack pattern in
[adding-a-bank-adapter.md](adding-a-bank-adapter.md).

Plan: not yet written.

## Phase 2 — Ingest: PDF extraction (per-bank adapters)
**Status: not started**

Per-bank adapters, starting with South Indian Bank, HDFC Bank, and
SBI. All three banks' statement PDFs are password-protected, so the
adapter must decrypt on open. Produces the same canonical JSONL
contract as Phase 1's Gmail fetch, so both feed `classify` identically.

Plan: not yet written.

## Phase 3 — Viz package
**Status: deferred**

Split `report` / `stats` / `web` / `export` out of the classify
package into `packages/viz/`, reading the same JSONL/SQLite contract.
Intentionally last — nothing else depends on it.

Plan: not yet written.
