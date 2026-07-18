"""munim doctor — data-quality checks. Catches the errors that silently
corrupt every downstream trend: missing months, missing accounts (unmirrored
transfers), dedup-risky exports, and unreviewed backlog.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from .schema import Transaction, Direction
from .store import Store

HAS_REF = re.compile(r"\d{6,}|[A-Z]\d{8,}")
MIRROR_WINDOW_DAYS = 3


def _month_range(start: date, end: date) -> list[str]:
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def run_checks(store: Store) -> dict:
    txns = store.all_transactions()
    report: dict = {"total": len(txns), "checks": []}

    def check(name, ok, detail):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    # 0. Installation health — an empty dictionary silently destroys
    #    classification quality (this exact bug shipped once; never again).
    #    Runs even with zero data: it's the first thing to verify.
    from .memory import MemoryMatcher
    dict_size = len(MemoryMatcher(
        user_rules={}, region=store.get_config("region", "in")).dictionary)
    check("Dictionary loaded", dict_size > 50,
          f"{dict_size} community patterns available."
          if dict_size > 50 else
          f"Only {dict_size} patterns loaded — broken installation. "
          f"Reinstall munim (pip install --force-reinstall).")

    if not txns:
        report["ok"] = all(c["ok"] for c in report["checks"])
        return report

    # 1. Date coverage per account — gaps mean missing statements
    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_account[t.account].append(t)
    gap_lines = []
    for acct, ts in sorted(by_account.items()):
        dates = sorted(t.date for t in ts)
        have = {d.isoformat()[:7] for d in dates}
        expected = _month_range(dates[0], dates[-1])
        missing = [m for m in expected if m not in have]
        if missing:
            gap_lines.append(f"{acct}: no data for {', '.join(missing)}")
    check("Month coverage", not gap_lines,
          gap_lines or [f"{a}: {len(ts)} txns, "
                        f"{sorted(t.date for t in ts)[0]} to "
                        f"{sorted(t.date for t in ts)[-1]}"
                        for a, ts in sorted(by_account.items())])

    # 2. Unmirrored transfers — usually means an account wasn't imported
    unmirrored = []
    credits = [t for t in txns if t.direction == Direction.CREDIT]
    for t in txns:
        if not (t.is_transfer and t.direction == Direction.DEBIT):
            continue
        mirror = any(
            abs(c.amount - t.amount) < 0.01 and c.account != t.account
            and abs((c.date - t.date).days) <= MIRROR_WINDOW_DAYS
            for c in credits
        )
        if not mirror:
            unmirrored.append(f"{t.date} {t.currency} {t.amount:,.2f} "
                              f"from {t.account}: {t.description_raw[:44]}")
    check("Transfer mirrors", not unmirrored,
          (["Debits marked transfer with no matching credit in another "
            "account — did you import all account statements?"] + unmirrored)
          if unmirrored else "All transfer debits have a plausible mirror.")

    # 3. Dedup risk — descriptions without reference numbers
    bare = [t for t in txns if not HAS_REF.search(t.description_raw)]
    pct = 100 * len(bare) / len(txns)
    check("Dedup safety", pct < 10,
          f"{len(bare)}/{len(txns)} descriptions ({pct:.0f}%) lack a "
          f"reference number. "
          + ("Identical same-day purchases could be dropped as duplicates — "
             "verify counts against your statement." if pct >= 10
             else "Hash-based dedup is safe."))

    # 4. Review backlog
    unconfirmed = sum(1 for t in txns if t.status.value != "confirmed")
    uncategorized = sum(1 for t in txns if not t.category)
    check("Review backlog", unconfirmed == 0,
          f"{unconfirmed} unconfirmed ({uncategorized} with no category at "
          f"all). Run: munim review, then munim reclassify.")

    report["ok"] = all(c["ok"] for c in report["checks"])
    return report
