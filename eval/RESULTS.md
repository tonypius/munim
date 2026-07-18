# Benchmark results

Run `make eval` to reproduce.

## v0.1.0 — synthetic_in.csv (30 transactions, cold start: no user memory)

| Metric | Value |
|---|---|
| Coverage (classified with zero user input) | 90.0% |
| Precision of classifications | 100.0% |
| Unresolved -> review queue | 3 (two P2P person payments, one local shop) |

The three unresolved items are *by design*: payments to individuals carry
no category signal and local merchants aren't in any dictionary. Both are
one-tap fixes in `munim review` and are remembered forever after.

Note: this is a synthetic cold-start fixture. Real-world month-one coverage
will be lower (more local merchants); month-three coverage will be higher
(memory has learned them). Donate anonymized fixtures to make this table
more honest — see CONTRIBUTING.md.
