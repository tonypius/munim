"""Benchmark harness: run the full pipeline against a labeled fixture and
print per-category precision/recall + stage coverage.

This is what makes the repo's accuracy claims falsifiable. Ships in CI:
model or dictionary updates that regress the benchmark don't merge.

Runs in a throwaway store — never touches your real ~/.munim data.
"""
from __future__ import annotations

import csv
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.schema import Transaction, Direction  # noqa: E402
from munim.store import Store                     # noqa: E402
from munim.pipeline import Pipeline               # noqa: E402

DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_in.csv"


def load_fixture(path: Path):
    txns, truths = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            debit = float(row["debit"]) if row["debit"] else 0
            credit = float(row["credit"]) if row["credit"] else 0
            txns.append(Transaction(
                date=row["date"],
                amount=debit or credit,
                direction=Direction.DEBIT if debit else Direction.CREDIT,
                description_raw=row["description"],
            ))
            truths.append(row["true_category"])
    return txns, truths


def evaluate(fixture: Path | None = None) -> float:
    fixture = fixture or DEFAULT_FIXTURE
    txns, truths = load_fixture(fixture)

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(home=Path(tmp))
        store.set_config("region", "in")
        pipeline = Pipeline(store)
        stats = pipeline.run(txns)

    # ---- metrics ----
    tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
    correct = attempted = 0
    for t, truth in zip(txns, truths):
        pred = t.category
        if pred:
            attempted += 1
            if pred == truth:
                tp[truth] += 1
                correct += 1
            else:
                fp[pred] += 1
                fn[truth] += 1
        else:
            fn[truth] += 1

    n = len(txns)
    coverage = attempted / n
    precision = correct / attempted if attempted else 0
    print(f"\nFixture: {fixture.name} ({n} transactions)")
    print(f"Coverage  (classified without user input): {coverage:.1%}")
    print(f"Precision (of those, correct):             {precision:.1%}")
    print("\nBy stage:")
    for stage, count in sorted(stats.by_stage.items(), key=lambda x: -x[1]):
        print(f"  {stage:<14} {count:>4}  ({100*count/n:.0f}%)")
    print("\nPer-category:")
    cats = sorted(set(truths) | set(fp.keys()))
    print(f"  {'category':<18}{'prec':>7}{'recall':>8}")
    for c in cats:
        p = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else float("nan")
        r = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else float("nan")
        print(f"  {c:<18}{p:>7.0%}{r:>8.0%}")
    print("\nUnresolved (would go to review queue):")
    for t, truth in zip(txns, truths):
        if not t.category:
            print(f"  {t.merchant_norm or t.payee_handle or t.description_raw[:40]!r}"
                  f"  (true: {truth})")
    return precision


if __name__ == "__main__":
    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    evaluate(fixture)
