# Design: a real chart engine, plus on-the-go conversational charts

Status: designed, not yet implemented.

## Context

munim's `docs/phases.md` has long carried a deferred "Phase 3 — Viz
package" with no plan ever written. Separately, a parked memory note
(`next_phase_tags_feature.md`) flagged that tags for cross-cutting spend
dimensions were needed "for the future viz layer" — this is that layer
starting.

Today the Dashboard tab (`packages/classify/munim/web/{server.py,
index.html}`) has **no real charting at all**: `_dashboard()` in
`server.py` computes month/category/merchant rollups, and `index.html`
renders them as hand-rolled CSS — bar heights via inline `style` on `<i>`
elements, horizontal bars via `width%` on table cells. No axes, no
gridlines, no tooltips beyond the `title` attribute, no line charts.

The whole web UI is a single self-contained `index.html` — embedded CSS
and JS, no separate asset files, no build step, no `<script src>` or
`<link>` pointing anywhere external. The page is explicitly designed to
work fully offline (stated directly in the file's own CSS comment), and
the project as a whole (`README.md`) is built on "local-first,
privacy-absolute" — no telemetry, no account, no API key, everything on
one machine.

This design covers two related pieces, scoped together because they
share one data layer:

1. **A real chart engine** for the Dashboard tab's existing panels, plus
   one new panel (net worth over time) that doesn't exist today.
2. **On-the-go chart creation** — the ability for the assistant to
   produce a correct, well-designed chart from an arbitrary query,
   conversationally, without writing ad hoc SQL each time.

## Decisions made (and why)

- **No Flint, no Node/npm dependency.** The user's opening reference was
  [microsoft/flint-chart](https://github.com/microsoft/flint-chart), a
  Node/TypeScript library + MCP server that compiles semantic chart specs
  into Vega-Lite/ECharts/Chart.js/Plotly output. It has no Python port
  (source-only preview). munim's stack is pure Python + vanilla JS with
  zero Node/npm anywhere — adding one just for chart authoring would be a
  real architectural shift for a project that has deliberately stayed
  dependency-light. The user explicitly agreed to skip it once this
  tradeoff was surfaced: the assistant plays Flint's role directly
  (producing well-designed chart configs from semantic understanding of
  the data) rather than shipping the software.
- **Chart.js, vendored inline, not CDN-loaded.** Chart.js is one of
  Flint's own supported output backends, ships as a single ~200KB
  minified UMD file with no companion libraries, and covers every chart
  type this dashboard needs (bar, horizontal bar, line — no pie/doughnut
  needed per the panel list below). It gets inlined directly into
  `index.html`'s existing `<script>` block, not loaded from a CDN
  `<script src>` — the project's "works fully offline" promise is
  currently *literally* true (zero external resources of any kind), and
  a CDN dependency would quietly break that on a fresh clone with no
  internet. Consistent with the existing convention: one self-contained
  page, not a page plus a growing set of served assets.
- **Two generic aggregation endpoints, not one-off queries per panel.**
  `_dashboard()` today hand-rolls its own groupby loops per metric. The
  new `/api/chart/flow` and `/api/chart/balance` endpoints become the
  single shared data path for the Dashboard panels *and* for on-the-go
  conversational charts — the same correctness guarantees (transfer
  exclusion, the Assets-credit-grows/Liabilities-inverted sign
  convention already documented in `CLAUDE.md`) apply everywhere instead
  of being re-derived per feature. This is also why the aggregation logic
  lives in a new pure module (`munim/reporting.py`) rather than inline in
  `server.py` — unit-testable without an HTTP server, importable directly
  by anything that needs a number.
- **Flow vs. balance as two separate concerns, not one flexible query
  language.** A flow metric (`SUM(amount)` grouped by month/category/
  merchant/account, filtered) and a balance metric (cumulative running
  balance over time, respecting the Assets/Liabilities sign convention)
  have genuinely different computations — forcing them into one generic
  query shape would either bloat that shape with balance-only options
  that make no sense for a flow query, or silently produce wrong numbers
  if a caller mixes them up. Two small, honest endpoints beat one
  overloaded one.
- **On-the-go charts are ephemeral only in this pass — no
  `saved_charts` table, no persisted "Custom" dashboard section.**
  Considered and explicitly deferred: which ad hoc charts are actually
  worth pinning is much easier to know after real usage than to guess
  now, and shipping ephemeral-only is both the higher-value and
  lower-effort piece. Persistence is a natural, small follow-up once
  there's evidence of what gets re-asked for.
- **No JS test framework added.** None exists anywhere in this project
  today (confirmed by search — no `.test.js`, no Jest/Playwright config).
  The new Chart.js dashboard panels get verified the way the rest of the
  vanilla-JS UI already is: driven through a real browser (dev server,
  screenshot, console/network check), not new test infrastructure.

## Section 1: `munim/reporting.py` — the aggregation module

Two pure functions, taking already-loaded `Transaction` objects (never
touching the DB directly) so they're unit-testable with plain in-memory
lists, the same pattern `balance_sheet.py` already uses.

```python
def flow_query(
    txns: list[Transaction],
    group_by: str,              # "month" | "category" | "subcategory" | "merchant" | "account"
    *,
    direction: str = "",        # "debit" | "credit" | "" (both)
    exclude_transfers: bool = True,
    account: str = "",
    category: str = "",
    subcategory: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Returns [{"label": str, "value": float}, ...], sorted by label for
    group_by="month" (chronological), by descending value otherwise (so
    "top categories" falls out for free without a separate sort step).
    A merchant's `label` is `t.merchant_norm or t.payee_handle or
    "(unknown)"`, matching _dashboard()'s existing fallback exactly, so
    behavior is unchanged for callers migrating off the old inline logic.
    """


def balance_series(
    store: Store,
    accounts: list[str],        # one or more account names; summed into one series
    *,
    group_by: str = "month",    # "month" is the only supported value for v1
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """Returns [{"label": "2026-01", "value": float}, ...] — the combined
    balance across every account in `accounts` at each period's end,
    computed by walking each account's transactions in date order and
    applying the same Assets-credit-grows/Liabilities-inverted convention
    compute_account_balance() already uses (re-derived here as a running
    series rather than one final number). A Liabilities account's balance
    is negated before summing into the combined series, so a combined
    "net worth" call (assets + liabilities together) nets correctly
    instead of just adding two positive-looking numbers.
    """
```

`flow_query`'s `exclude_transfers=True` default matches `_dashboard()`'s
existing spend calculation (`t.direction == "debit" and not
t.is_transfer`) — passing `direction=""` and `exclude_transfers=False`
recovers the old un-filtered behavior for a caller that genuinely wants
every transaction.

## Section 2: two new API endpoints

Both added to `server.py`'s existing `do_GET` dispatch, thin wrappers
that parse query params and call into `reporting.py`:

- **`GET /api/chart/flow?group_by=month&category=Groceries&subcategory=Alcohol&date_from=2025-01-01&date_to=2025-12-31`**
  → `{"labels": [...], "values": [...]}` (two parallel arrays — Chart.js's
  native input shape, so the frontend never needs to unzip a list of
  objects). Every keyword argument on `flow_query` — `direction`,
  `exclude_transfers`, `account`, `category`, `subcategory`, `date_from`,
  `date_to` — is exposed as a same-named query param, all optional
  except `group_by`; the example above only shows the subset a
  category-drill-down request needs.
- **`GET /api/chart/balance?accounts=tony-hdfc-savings,tony-sib-savings&date_from=2024-01-01`**
  → `{"labels": [...], "values": [...]}`, same shape. `accounts` is
  comma-separated; omitting it means "every Asset and Liability account"
  (the net-worth-over-time default the Dashboard panel uses).

Both routes 400 on an unrecognized `group_by` or a malformed date, same
error shape (`{"error": "..."}`) every other endpoint in this file
already uses.

## Section 3: Dashboard tab upgrade

`index.html`'s `dashboard()` render function changes from building HTML
strings for CSS bars to constructing `Chart.js` `Chart` instances against
`<canvas>` elements, styled from the page's existing CSS custom
properties (read via `getComputedStyle` so the palette never drifts out
of sync with the rest of the page):

| Panel | Today | New |
|---|---|---|
| Monthly spend trend | CSS bar-heights, `#dashMonths` | Chart.js bar chart, `--ledger-red` bars, real axis + tooltips |
| Top categories | manual `<table>` + width% divs, `#dashCats` | Chart.js horizontal bar, same color |
| Top merchants | manual `<table>` + width% divs, `#dashMerchants` | Chart.js horizontal bar, same color |
| **Net worth over time** *(new)* | doesn't exist | Chart.js line chart, `--pen-blue`, backed by `/api/chart/balance` with no `accounts` filter |

The five-root rollup line (Income/Expenses/Assets/Liabilities/Equity) at
the top of the Dashboard stays plain text — a single point-in-time number
per root isn't a series, so a chart adds nothing there.

Each `<canvas>` is destroyed and recreated on every `dashboard()` call
(month/account filter change) rather than updated in place — this
dashboard already fully re-fetches and re-renders on every filter change
today, and Chart.js instances must be explicitly destroyed before their
canvas is reused or they leak and double-render.

## Section 4: on-the-go conversational charts

No new persisted feature — this section documents the assistant's own
workflow, added to `CLAUDE.md` as an operational note (mirroring how the
review-queue-triage guidance already lives there):

1. On a request like "show my alcohol spend by month" or "plot my Axis
   vs. HDFC balance this year," the assistant calls `/api/chart/flow` or
   `/api/chart/balance` with the appropriate filters — never hand-writes
   ad hoc SQL, so the transfer-exclusion and sign-convention guarantees
   `reporting.py` already encodes apply automatically.
2. The returned `{"labels", "values"}` gets rendered immediately via the
   assistant's own visualization tool, inline in the conversation.
   Nothing is written back to munim's database or web UI — this is
   intentionally ephemeral (see the Decisions section above).
3. If the user later asks for a chart to be kept in the app permanently,
   that is out of scope for this design and becomes a follow-up
   (`saved_charts` table + a "Custom" Dashboard section, both already
   sketched in the Decisions section as the natural next step).

## Non-goals

- **No `saved_charts` persistence layer** in this pass (see Decisions).
- **No dark mode / theming system for charts.** The page has no dark
  mode anywhere today (confirmed by search — no `prefers-color-scheme`
  rule exists); charts inherit the one fixed "ledger paper" light
  palette like everything else on the page.
- **No pie/doughnut charts.** Every panel in scope is naturally a
  bar or line series; a pie chart isn't part of this design purely
  because nothing here calls for one, not as a stated restriction on
  future panels.
- **No arbitrary user-facing chart-builder UI** (a form where the human,
  not the assistant, picks dimensions/filters and gets a chart). The
  on-the-go path in this design is assistant-mediated only; a self-serve
  builder is a distinct, larger feature that would need its own design.
- **No changes to `_dashboard()`'s existing five-root rollup or spend
  summary line** — those stay exactly as they are; only the panels in
  the Section 3 table change.
