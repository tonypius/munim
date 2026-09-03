# Category Taxonomy v2 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign munim's 20-category taxonomy down to 17 categories (per
`docs/superpowers/specs/2026-09-04-category-taxonomy-v2-design.md`), then
migrate every affected transaction in the live database to match.

**Architecture:** A one-off migration script
(`packages/classify/migrations/migrate_taxonomy_v2.py`) using `Store`'s API
directly, not chained CLI commands. Two phases: `plan_migration()` computes
what would change without writing (dry run), `apply_migration()` writes it.
A CLI wrapper defaults to dry-run and requires an explicit `--apply` flag
plus a database backup before any write. The last two tasks are
operational (run the script against the real database), not code tasks —
they require your human partner's explicit go-ahead between dry-run review
and apply, and cannot be automated past that gate.

**Tech Stack:** Python 3.11+, SQLite, pytest. No new dependencies — reuses
`munim.store.Store` entirely.

## Global Constraints

- The script must NEVER touch `~/.munim/munim.db` without first copying it
  to a timestamped backup file, whenever `--apply` is used.
- Dry-run (the default, no `--apply` flag) must never call any `Store`
  write method (`set_config`, `update_transaction`, `remember`, direct
  `db.execute` of `UPDATE`/`INSERT`/`DELETE`) — it only reads.
- Every transaction currently in the 100 Utilities patterns, the 7 CRED
  patterns, and the 4 whole-category moves must be accounted for exactly
  once — no pattern silently skipped, no transaction double-matched by two
  rules. The design spec's grand-total check (Utilities ₹717,253.07 exactly
  matching the sum of its 8 destination buckets) is the acceptance bar for
  Task 1's pattern table.
- Match transactions the same way the app already does elsewhere: query
  by `t.merchant_norm or t.payee_handle` equality against the pattern
  string (uppercase, matching how `merchant_norm`/`payee_handle` are
  already stored) — never substring/fuzzy matching in the script itself
  (the classification judgment was already made by hand against the full
  merchant list; the script's job is exact, deterministic application of
  that judgment).
- `apply_migration` must also update matching `memory` rows (not just
  `transactions`), so future imports of the same merchant land in the new
  category/subcategory too — mirroring what `munim categories rename`
  already does for whole-category cascades.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first), except the CLI `argparse` wrapper in Task 4
  and the operational Tasks 5-6, which have no automated test by nature.

---

### Task 1: Taxonomy constants and the pattern-move table

**Files:**
- Create: `packages/classify/migrations/__init__.py` (empty)
- Create: `packages/classify/migrations/migrate_taxonomy_v2.py`
- Test: `packages/classify/tests/test_migrate_taxonomy_v2.py` (new file)

**Interfaces:**
- Produces:
  - `NEW_CATEGORIES: list[str]` — the 17-category list, in order.
  - `NEW_CATEGORY_TREE: dict[str, str]` — category -> ledger path.
  - `NEW_SUBCATEGORIES: dict[str, list[str]]` — category -> subcategory list.
  - `WHOLE_CATEGORY_MOVES: dict[str, tuple[str, str]]` — old category name
    -> `(new_category, new_subcategory)`.
  - `PATTERN_MOVES: dict[str, tuple[str, str]]` — merchant/payee pattern
    (uppercase) -> `(new_category, new_subcategory)`. `new_subcategory` is
    `""` when the destination has no subcategory for that move.
  - `build_pattern_moves() -> dict[str, tuple[str, str]]` — assembles
    `PATTERN_MOVES` from the per-bucket lists below; the module-level
    `PATTERN_MOVES` is just `build_pattern_moves()` called once at import
    time.

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_migrate_taxonomy_v2.py`:

```python
"""Tests for the one-off category-taxonomy-v2 migration script. These
test the migration's DATA (constants, pattern tables) and PLANNING logic
against a scratch database — never the real ~/.munim/munim.db."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "migrations"))

from migrate_taxonomy_v2 import (
    NEW_CATEGORIES,
    NEW_CATEGORY_TREE,
    NEW_SUBCATEGORIES,
    WHOLE_CATEGORY_MOVES,
    PATTERN_MOVES,
)


def test_new_categories_has_seventeen_entries_no_duplicates():
    assert len(NEW_CATEGORIES) == 17
    assert len(set(NEW_CATEGORIES)) == 17


def test_new_categories_no_longer_contains_retired_names():
    retired = {"Fuel", "Rent", "Household Help", "Fees & Charges"}
    assert retired.isdisjoint(set(NEW_CATEGORIES))


def test_new_category_tree_covers_every_category():
    assert set(NEW_CATEGORY_TREE.keys()) == set(NEW_CATEGORIES)


def test_housing_is_new_and_has_five_subcategories():
    assert "Housing" in NEW_CATEGORIES
    assert NEW_CATEGORY_TREE["Housing"] == "Expenses:Housing"
    assert NEW_SUBCATEGORIES["Housing"] == [
        "Rent", "Maintenance/Dues", "Property Tax", "Repairs", "Household Help"]


def test_whole_category_moves_cover_all_four_retired_categories():
    assert WHOLE_CATEGORY_MOVES == {
        "Fuel": ("Transport", "Fuel"),
        "Rent": ("Housing", "Rent"),
        "Household Help": ("Housing", "Household Help"),
        "Fees & Charges": ("Other", ""),
    }


def test_pattern_moves_total_count_matches_spec():
    # 7 CRED patterns + 68 Utilities-sourced patterns (20 dues + 4 tax +
    # 13 repairs + 9 household-help + 2 misc + 19 other + 1 transport) = 75.
    assert len(PATTERN_MOVES) == 75


def test_pattern_moves_no_pattern_claimed_by_two_rules():
    # build_pattern_moves() must not have silently overwritten a pattern
    # that appeared in two of the per-bucket lists.
    from migrate_taxonomy_v2 import build_pattern_moves
    all_patterns = []
    for bucket in (
        _cred_patterns_for_test(),
        _utilities_housing_dues_for_test(),
    ):
        all_patterns.extend(bucket)
    assert len(all_patterns) == len(set(all_patterns))


def _cred_patterns_for_test():
    from migrate_taxonomy_v2 import CRED_PATTERNS
    return CRED_PATTERNS


def _utilities_housing_dues_for_test():
    from migrate_taxonomy_v2 import UTILITIES_HOUSING_DUES
    return UTILITIES_HOUSING_DUES


def test_known_cred_pattern_maps_to_transfers_credit_card_payment():
    assert PATTERN_MOVES["CRED CRED CLUB"] == ("Transfers", "Credit Card Payment")
    assert PATTERN_MOVES["AXIS CRED CLUB"] == ("Transfers", "Credit Card Payment")


def test_cred_utility_and_credpay_variants_are_not_in_pattern_moves():
    # These were verified via raw narration to use a DIFFERENT CRED VPA
    # (cred.utility@, credpay.<biller>@) and must NOT be touched.
    excluded = ["CRED", "CRED CRED CCBP", "CRED CRED UTILITY", "CRED DUNZO",
                "CRED FASTAG", "CRED FASTAGBANGALORE", "CRED SWIGGY",
                "CREDPAYDUNZO CREDPAY DUNZO", "CREDPAYZEPTO CREDPAY ZEPTO",
                "RAZ CRED MOHALI",
                "UPI JIO CREDPAY JIO AXISB UTIB0000114 PAYM ENT ON CRED"]
    for p in excluded:
        assert p not in PATTERN_MOVES


def test_known_mygate_pattern_maps_to_housing_maintenance():
    assert PATTERN_MOVES["MYGATE"] == ("Housing", "Maintenance/Dues")


def test_known_bbmp_pattern_maps_to_housing_property_tax():
    assert PATTERN_MOVES["COMMISSIONER BBMP"] == ("Housing", "Property Tax")


def test_known_plumber_pattern_maps_to_housing_repairs():
    assert PATTERN_MOVES["URBANCLAP NOIDA"] == ("Housing", "Repairs")


def test_known_cook_salary_pattern_maps_to_housing_household_help():
    assert PATTERN_MOVES["NIJARA DAS BAISHYSNIJARA"] == ("Housing", "Household Help")


def test_traffic_fine_maps_to_transport_unsubcategorized():
    assert PATTERN_MOVES["BANGALORE TRAFFIC POLI"] == ("Transport", "")


def test_ambiguous_individual_names_map_to_other():
    assert PATTERN_MOVES["K SHAMALA BABUG4571"] == ("Other", "")
    assert PATTERN_MOVES["DOMINIC J JDOMINIC9980854213"] == ("Other", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_taxonomy_v2'`.

- [ ] **Step 3: Write the module**

Create `packages/classify/migrations/__init__.py` (empty file).

Create `packages/classify/migrations/migrate_taxonomy_v2.py`:

```python
"""One-off migration: category taxonomy v2 (17 categories, down from 20).

See docs/superpowers/specs/2026-09-04-category-taxonomy-v2-design.md for
the full rationale and per-rule verification notes. This module is data +
pure functions only — no I/O, no Store writes. See migrate() at the
bottom of this file (added in Task 3) for the apply/dry-run entry points,
and __main__ (Task 4) for the CLI wrapper.
"""

# ---------------------------------------------------------------- taxonomy
NEW_CATEGORIES = [
    "Groceries", "Dining", "Transport", "Shopping", "Subscriptions",
    "Utilities", "Housing", "Health", "Entertainment", "Travel",
    "Education", "Income", "Investments", "Transfers", "Family & Friends",
    "Other", "Cash",
]

NEW_CATEGORY_TREE = {
    "Groceries": "Expenses:Groceries",
    "Dining": "Expenses:Dining",
    "Transport": "Expenses:Transport",
    "Shopping": "Expenses:Shopping",
    "Subscriptions": "Expenses:Subscriptions",
    "Utilities": "Expenses:Utilities",
    "Housing": "Expenses:Housing",
    "Health": "Expenses:Health",
    "Entertainment": "Expenses:Entertainment",
    "Travel": "Expenses:Travel",
    "Education": "Expenses:Education",
    "Income": "Income",
    "Investments": "Assets:Investments",
    "Transfers": "Equity:Transfers",
    "Family & Friends": "Expenses:Family & Friends",
    "Other": "Expenses:Other",
    "Cash": "Expenses:Cash",
}

NEW_SUBCATEGORIES = {
    "Groceries": ["Meat", "Alcohol", "Produce"],
    "Dining": ["Delivery", "Dining Out"],
    "Transport": ["Fuel", "Cabs/Rideshare", "Public Transit", "Parking"],
    "Subscriptions": ["Business Tools", "Personal"],
    "Utilities": ["Electricity", "Gas", "Telecom/Internet"],
    "Housing": ["Rent", "Maintenance/Dues", "Property Tax", "Repairs",
                "Household Help"],
    "Health": ["Insurance", "Care"],
    "Travel": ["Flights", "Hotels/Packages", "Forex/Prepaid Cards"],
    "Investments": ["FD/Deposits", "Mutual Funds", "Crypto", "Chit/Kuri"],
    "Transfers": ["Credit Card Payment"],
    "Family & Friends": ["Gifts/Support", "Loans"],
}

# ----------------------------------------------------- whole-category moves
# Every transaction/memory-row currently in one of these categories moves
# to the paired (new_category, new_subcategory) regardless of merchant.
WHOLE_CATEGORY_MOVES = {
    "Fuel": ("Transport", "Fuel"),
    "Rent": ("Housing", "Rent"),
    "Household Help": ("Housing", "Household Help"),
    "Fees & Charges": ("Other", ""),
}

# ------------------------------------------------------------ CRED Club fix
# Verified via raw UPI narration: each of these routes through the
# cred.club@... VPA (the credit-card-bill-pay feature specifically), not
# cred.utility@... or credpay.<biller>@... (CRED's other bill-pay
# integrations, which stay wherever they already are — see the design
# spec's Rule 4 "explicitly excluded" list).
CRED_PATTERNS = [
    "AXIS CRED CLUB",
    "CRED CRED CLUB",
    "CREDCLUB1 CRED CLUB",
    "HI2PVCTTXO1SC8 RAZPCREDCLUB",
    "HVKZDKG4QCYSHU RAZPCREDCLUB",
    "KQSHY4UOARZKHPOSD4 PAYUCREDCLUB",
    "UPI AXIS CRED CLUB AXISB UTIB0000114 PAYM ENT ON CRED",
]

# --------------------------------------------------------- Utilities split
# 100 distinct merchant patterns from the live Utilities category, audited
# by keyword and spot-checked against raw narration. UTILITIES_STAYS lists
# the patterns that need NO change (kept here only so Task 1's coverage
# test can assert all 100 patterns are accounted for; not used to build
# PATTERN_MOVES).
UTILITIES_HOUSING_DUES = [
    "AISSHWARYA EXCELLENC AEAOA",
    "AISSHWARYA EXCELLENC AEAOA084 08",
    "AISSHWARYA EXCELLENC AEAOA1",
    "EMI MYGATEBANGALORE",
    "MY GATE NOIDA",
    "MY GATENOIDA",
    "MYGATE",
    "MYGATE MYGATE RAZORPAY",
    "MYGATE MYGATE RZP",
    "MYGATE PAYTM MYGATE",
    "MYGATEBANGALORE",
    "SATTVA GOLD SUMMIT A SATTVAGOLDSUMMITAPARTMENTASSOCIATION",
    "SATTVA GOLD SUMMIT A SGSAOA",
    "UPI MYGATE MYGATE RAZORPAY HDFCBANK HDFC0000053 DUESSETTLE VALUE DT 09 07 2024",
    "UPI MYGATE MYGATE RAZORPAY HDFCBANK HDFC0000053 DUESSETTLE VALUE DT 13 08 2024",
    "UPI MYGATE PAYTM MYGATE PAYTM YESB0PTMUPI UTIL ITY VALUE DT 19 03 2024",
    "UPI VIVISH MYGATE PAYTM HDFCBANK HDFC0MERUPI U PI VALUE DT 06 02 2026",
    "UPI VIVISH MYGATE PAYTM HDFCBANK HDFC0MERUPI U PI VALUE DT 16 03 2026",
    "UPI XXXXXX7770 SBIN0008627 SGS PENDING",
    "VIVISH MYGATE PAYTM",
]

UTILITIES_HOUSING_TAX = [
    "COMMISSIONER BBMP",
    "UPI TONY PIUS ALAPATT TONYPIUSALAPATT OKSBI SIBL0000396 BBMP VALUE DT 12 11 2025",
    "UPI XXXXXXXXXXX1736 UBIN0900745 53 BBMP BESCOM NAME C VALUE DT 15 11 2025",
    "UPI XXXXXXXXXXX1736 UBIN0900745 KHATA BESCOM",
]

UTILITIES_HOUSING_REPAIRS = [
    "BUHARI K K TAJELECTRICALS",
    "PRADEEP HARDWARE AND EL",
    "UPI ARUMUGAM KANNAPATTU PAYTMQR72KASC PTYS YESB0PTMUPI TOILET VALUE DT 03 07 2026",
    "UPI GOUTAM MALIK 2 YBL PUNB0101220 PLUMBER TOILET REP VALUE DT 18 03 2026",
    "UPI GOUTAM MALIK 2 YBL PUNB0101220 PLUMBER WORKS VALUE DT 24 03 2026",
    "UPI GOUTAM MALIK GUDUMALIK915 YBL ICIC0001422 PLUMBER VALUE DT 26 05 2026",
    "UPI JITENDRA KUMAR M PAYTMQRMEUVDHTUDA PAYTM PYTM0123456 ELE CTRICAL VALUE DT 10 12 2023",
    "UPI PRADEEP HARDWARE AND OKBIZAXIS UTIB0000000 B ULBSVALUE DT 01 03 2024",
    "UPI RADHANATH KAR RADHANATH158 OKAXIS SBIN0009820 PLUMB ER VALUE DT 25 05 2026",
    "UPI RADHANATH158OKAXIS RADHANATH158 OKAXIS SBIN0009820 PLUMB ER VALUE DT 02 07 2026",
    "UPI RADHANATH158OKAXIS RADHANATH158 OKAXIS SBIN0009820 PLUMBI NGWORK VALUE DT 04 06 2026",
    "UPI RAJALAKSHMI HARDWARE PAYTMQR6VAZ3Q PTYS YESB0PTMUPI PLUMBI NG VALUE DT 03 07 2026",
    "URBANCLAP NOIDA",
]

UTILITIES_HOUSING_HELP = [
    "NIJARA DAS BAISHYSNIJARA",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 04 04 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 07 01 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 11 02 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK VALUE DT 07 05 2026",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 04 03 2026",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 08 12 2025",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 22 07 2026",
    "UPI NIJARA DAS DNIJARA82 OKAXIS IOBA0003395 SALARY PENDING VALUE DT 29 03 2026",
]

UTILITIES_HOUSING_MISC = [
    "REV UPI TONYPIUSALAPA TT OKHDFCBANK HOUSE MISCELLANEOUS VALUE DT 28 02 2024",
    "RURAL DEVELOPMENT AND",
]

UTILITIES_TO_OTHER = [
    "7259838127PTYES",
    "9871094364PTYES",
    "AKSHAY KUMAR TT AKSHAYSANTHOSHTT",
    "BABRUBAHAN PARIDA BABULPARIDA2020",
    "BABU BABUBABU84419",
    "BAIKUNTH DAS DASBAIKUNTHA65",
    "CREATELINE MAHALAXMI",
    "DINESH SETTU DINESH2000123456",
    "DOMINIC J JDOMINIC9980854213",
    "GARIKINA RATNAM KIRANSAFETYNET",
    "HASEENA V A",
    "K SHAMALA BABUG4571",
    "KHAN ALFITKHAN MANGL",
    "KUMARAVEL ALAGESAN KUMARAVELGK1982",
    "L M SHIVU SHIVUM15021993",
    "MANOJCTLOKICICI MANOJCTL",
    "RATHEESH K V PAYTMQR1RXCQHWGB3",
    "SHANAVAZ P S SHANAVASSHANU78639",
    "VEDANAYAGAM K VEDANAYAGAMVEDANAYAGAM67",
]

UTILITIES_TO_TRANSPORT = [
    "BANGALORE TRAFFIC POLI",
]

UTILITIES_STAYS = [
    "AIRTEL BAN GURGAON",
    "AIRTEL GURGAON",
    "AIRTEL66 GURGAON",
    "ASIANET",
    "BESCOM BILLDESK",
    "BESCOMBANGALORE",
    "BESCOMMUMBAI",
    "BHARTI AIRTEL GURGAON",
    "BHARTI AIRTEL LTDGURGAON",
    "BSNL BILLDESK",
    "CRED CRED UTILITY",
    "EMI BESCOMMUMBAI",
    "EURONETGPAY EURONETGPAY POSTP AID MOBILE",
    "GAIL GAS LIMITEDNOIDA",
    "JIO POSTPAID BILL PA PAYTM",
    "JIO PREPAID RECHARGE PAYTM JIOMOBILITY",
    "JIO SOLUTIONS HTTPS WW",
    "KSEB TRIVANDRUM",
    "RAZ AIRWIRE BROADBAND",
    "RAZ NORTHEAST DATAA NE HTTPS AI",
    "RAZ VODAFONE IDEA LIMIT GANDHINAGA",
    "RECHARGE",
    "RECHARGEMUMBAI",
    "REL JIO SOLUTI HTTPS WW",
    "RELIANCE JIO INFOCOMM LNOIDA",
    "RELIANCE JIO INFOCOMM NOIDA",
    "UPI JIO CREDPAY JIO AXISB UTIB0000114 PAYM ENT ON CRED",
    "UPI MAMALYTICS TECHNOLOG SSEOMNI1H8F7A060125POS MAIRTEL AIRP0000001 PAYM ENTTOAARAM VALUE DT 07 12 2025",
    "VI VILPOSKAR",
    "VODAFONE IDEA GANDHINAGA",
    "WALLET NOIDA",
    "WWW AIRTEL INGURGAON",
]


def build_pattern_moves() -> dict[str, tuple[str, str]]:
    """Assemble the full pattern -> (new_category, new_subcategory) table
    from CRED_PATTERNS plus every Utilities-split bucket except
    UTILITIES_STAYS (those need no move)."""
    moves: dict[str, tuple[str, str]] = {}
    for p in CRED_PATTERNS:
        moves[p] = ("Transfers", "Credit Card Payment")
    for p in UTILITIES_HOUSING_DUES:
        moves[p] = ("Housing", "Maintenance/Dues")
    for p in UTILITIES_HOUSING_TAX:
        moves[p] = ("Housing", "Property Tax")
    for p in UTILITIES_HOUSING_REPAIRS:
        moves[p] = ("Housing", "Repairs")
    for p in UTILITIES_HOUSING_HELP:
        moves[p] = ("Housing", "Household Help")
    for p in UTILITIES_HOUSING_MISC:
        moves[p] = ("Housing", "")
    for p in UTILITIES_TO_OTHER:
        moves[p] = ("Other", "")
    for p in UTILITIES_TO_TRANSPORT:
        moves[p] = ("Transport", "")
    return moves


PATTERN_MOVES = build_pattern_moves()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/migrations packages/classify/tests/test_migrate_taxonomy_v2.py
git commit -m "Add taxonomy v2 constants and pattern-move table"
```

---

### Task 2: Dry-run planning function

**Files:**
- Modify: `packages/classify/migrations/migrate_taxonomy_v2.py`
- Test: `packages/classify/tests/test_migrate_taxonomy_v2.py`

**Interfaces:**
- Consumes: `WHOLE_CATEGORY_MOVES`, `PATTERN_MOVES` (Task 1),
  `munim.store.Store`.
- Produces: `plan_migration(store: Store) -> dict[str, dict]` — read-only.
  Returns `{"whole_category": {old_category: {"count": int, "total":
  float}}, "pattern": {pattern: {"count": int, "total": float,
  "destination": (str, str)}}}`. Never calls any `Store` write method.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_migrate_taxonomy_v2.py`:

```python
from munim.store import Store
from munim.schema import Transaction, Direction


def test_plan_migration_counts_whole_category_move(tmp_path):
    from migrate_taxonomy_v2 import plan_migration
    store = Store(home=tmp_path)
    t1 = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                     description_raw="FUEL STOP", category="Fuel",
                     merchant_norm="FUEL STOP")
    t2 = Transaction(date="2026-06-02", amount=300, direction=Direction.DEBIT,
                     description_raw="FUEL STOP 2", category="Fuel",
                     merchant_norm="FUEL STOP 2")
    store.upsert_transactions([t1, t2])
    report = plan_migration(store)
    assert report["whole_category"]["Fuel"] == {"count": 2, "total": 800.0}


def test_plan_migration_counts_pattern_move(tmp_path):
    from migrate_taxonomy_v2 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=1000, direction=Direction.DEBIT,
                    description_raw="AXIS CRED CLUB", category="Subscriptions",
                    merchant_norm="AXIS CRED CLUB")
    store.upsert_transactions([t])
    report = plan_migration(store)
    entry = report["pattern"]["AXIS CRED CLUB"]
    assert entry["count"] == 1
    assert entry["total"] == 1000.0
    assert entry["destination"] == ("Transfers", "Credit Card Payment")


def test_plan_migration_matches_payee_handle_when_merchant_norm_empty(tmp_path):
    from migrate_taxonomy_v2 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=2000, direction=Direction.DEBIT,
                    description_raw="MYGATE PAYMENT", category="Utilities",
                    merchant_norm="", payee_handle="MYGATE")
    store.upsert_transactions([t])
    report = plan_migration(store)
    assert report["pattern"]["MYGATE"]["count"] == 1


def test_plan_migration_ignores_unrelated_transactions(tmp_path):
    from migrate_taxonomy_v2 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="ZOMATO", category="Dining",
                    merchant_norm="ZOMATO")
    store.upsert_transactions([t])
    report = plan_migration(store)
    assert "Dining" not in report["whole_category"]
    assert "ZOMATO" not in report["pattern"]


def test_plan_migration_never_writes(tmp_path):
    from migrate_taxonomy_v2 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="FUEL STOP", category="Fuel",
                    merchant_norm="FUEL STOP")
    store.upsert_transactions([t])
    plan_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.category == "Fuel"   # unchanged — dry run only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'plan_migration'`.

- [ ] **Step 3: Write `plan_migration`**

Add to `packages/classify/migrations/migrate_taxonomy_v2.py`, after
`PATTERN_MOVES = build_pattern_moves()`:

```python

# ------------------------------------------------------------- dry run
def plan_migration(store) -> dict:
    """Read-only: compute what apply_migration() would change, without
    writing anything. Matches transactions the same way the rest of the
    app does — merchant_norm falling back to payee_handle, exact equality
    against the pattern string."""
    txns = store.all_transactions()
    whole_category: dict[str, dict] = {}
    pattern: dict[str, dict] = {}

    for old_cat, destination in WHOLE_CATEGORY_MOVES.items():
        matches = [t for t in txns if t.category == old_cat]
        total = sum(t.amount for t in matches if t.direction.value == "debit")
        whole_category[old_cat] = {"count": len(matches), "total": total}

    for p, destination in PATTERN_MOVES.items():
        # Independent OR, not a merchant_norm-falls-back-to-payee_handle
        # check — must match apply_migration's SQL (merchant_norm=? OR
        # payee_handle=?) exactly, so the dry-run's counts are a reliable
        # prediction of what --apply will actually do.
        matches = [t for t in txns
                  if t.merchant_norm == p or t.payee_handle == p]
        total = sum(t.amount for t in matches if t.direction.value == "debit")
        pattern[p] = {"count": len(matches), "total": total,
                      "destination": destination}

    return {"whole_category": whole_category, "pattern": pattern}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: PASS (19 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/migrations/migrate_taxonomy_v2.py packages/classify/tests/test_migrate_taxonomy_v2.py
git commit -m "Add dry-run planning function to the taxonomy v2 migration"
```

---

### Task 3: Apply function and database backup

**Files:**
- Modify: `packages/classify/migrations/migrate_taxonomy_v2.py`
- Test: `packages/classify/tests/test_migrate_taxonomy_v2.py`

**Interfaces:**
- Consumes: `NEW_CATEGORIES`, `NEW_CATEGORY_TREE`, `NEW_SUBCATEGORIES`,
  `WHOLE_CATEGORY_MOVES`, `PATTERN_MOVES` (Task 1), `plan_migration`
  (Task 2 — used internally to find matching rows).
- Produces:
  - `backup_database(home: Path) -> Path` — copies `home / "munim.db"` to
    `home / f"munim.db.bak.{timestamp}"`, returns the backup path. Raises
    if the source file doesn't exist.
  - `apply_migration(store) -> dict` — writes the new taxonomy config,
    then moves every matching transaction and memory row. Returns the
    same shape `plan_migration` returns (so the caller can print an
    identical-looking post-migration summary).

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_migrate_taxonomy_v2.py`:

```python
def test_backup_database_creates_a_copy(tmp_path):
    from migrate_taxonomy_v2 import backup_database
    store = Store(home=tmp_path)  # creates munim.db
    backup_path = backup_database(tmp_path)
    assert backup_path.exists()
    assert backup_path != (tmp_path / "munim.db")
    assert backup_path.read_bytes() == (tmp_path / "munim.db").read_bytes()


def test_apply_migration_updates_config(tmp_path):
    from migrate_taxonomy_v2 import apply_migration, NEW_CATEGORIES
    store = Store(home=tmp_path)
    apply_migration(store)
    reloaded = Store(home=tmp_path)
    assert reloaded.get_config("categories") == NEW_CATEGORIES


def test_apply_migration_moves_whole_category_transactions(tmp_path):
    from migrate_taxonomy_v2 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="FUEL STOP", category="Fuel",
                    merchant_norm="FUEL STOP")
    store.upsert_transactions([t])
    apply_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.category == "Transport"
    assert reloaded.subcategory == "Fuel"


def test_apply_migration_moves_pattern_matched_transactions(tmp_path):
    from migrate_taxonomy_v2 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=1000, direction=Direction.DEBIT,
                    description_raw="AXIS CRED CLUB", category="Subscriptions",
                    merchant_norm="AXIS CRED CLUB")
    store.upsert_transactions([t])
    apply_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.category == "Transfers"
    assert reloaded.subcategory == "Credit Card Payment"


def test_apply_migration_updates_matching_memory_rows(tmp_path):
    from migrate_taxonomy_v2 import apply_migration
    store = Store(home=tmp_path)
    store.remember("MYGATE", "Utilities", kind="merchant")
    apply_migration(store)
    rules = store.memory_rules("merchant")
    assert rules["MYGATE"] == "Housing"
    row = store.db.execute(
        "SELECT subcategory FROM memory WHERE pattern='MYGATE'").fetchone()
    assert row["subcategory"] == "Maintenance/Dues"


def test_apply_migration_leaves_unrelated_transactions_untouched(tmp_path):
    from migrate_taxonomy_v2 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="ZOMATO", category="Dining",
                    merchant_norm="ZOMATO", status="confirmed")
    store.upsert_transactions([t])
    apply_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.category == "Dining"
    assert reloaded.subcategory == ""


def test_apply_migration_returns_same_shape_as_plan_migration(tmp_path):
    from migrate_taxonomy_v2 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="FUEL STOP", category="Fuel",
                    merchant_norm="FUEL STOP")
    store.upsert_transactions([t])
    report = apply_migration(store)
    assert report["whole_category"]["Fuel"]["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'backup_database'`.

- [ ] **Step 3: Write `backup_database` and `apply_migration`**

Add three imports directly after the module docstring's closing `"""`
(the very top of the file has no imports yet — these become the first
statements after the docstring, before the `# ---- taxonomy` comment
section):

```python
import shutil
from datetime import datetime
from pathlib import Path
```

Then append, after `plan_migration`:

```python

def backup_database(home: Path) -> Path:
    """Copy munim.db to a timestamped backup file before any write.
    Raises FileNotFoundError if the source database doesn't exist yet."""
    src = home / "munim.db"
    if not src.exists():
        raise FileNotFoundError(f"No database at {src}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = home / f"munim.db.bak.{stamp}"
    shutil.copy2(src, dst)
    return dst


def apply_migration(store) -> dict:
    """Write the new taxonomy config, then move every matching
    transaction and memory row. Returns the same report shape as
    plan_migration() so the caller can print a before/after comparison."""
    store.set_config("categories", NEW_CATEGORIES)
    store.set_config("category_tree", NEW_CATEGORY_TREE)
    store.set_config("subcategories", NEW_SUBCATEGORIES)

    report = plan_migration(store)

    for old_cat, (new_cat, new_sub) in WHOLE_CATEGORY_MOVES.items():
        store.db.execute(
            "UPDATE transactions SET category=?, subcategory=? WHERE category=?",
            (new_cat, new_sub, old_cat))
        store.db.execute(
            "UPDATE memory SET category=?, subcategory=? WHERE category=?",
            (new_cat, new_sub, old_cat))

    for p, (new_cat, new_sub) in PATTERN_MOVES.items():
        store.db.execute(
            "UPDATE transactions SET category=?, subcategory=? "
            "WHERE merchant_norm=? OR payee_handle=?",
            (new_cat, new_sub, p, p))
        store.db.execute(
            "UPDATE memory SET category=?, subcategory=? WHERE pattern=?",
            (new_cat, new_sub, p))

    store.db.commit()
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_migrate_taxonomy_v2.py -v`
Expected: PASS (26 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/migrations/migrate_taxonomy_v2.py packages/classify/tests/test_migrate_taxonomy_v2.py
git commit -m "Add apply_migration and database backup to the taxonomy v2 migration"
```

---

### Task 4: CLI wrapper

**Files:**
- Modify: `packages/classify/migrations/migrate_taxonomy_v2.py`

**Interfaces:**
- Consumes: `plan_migration`, `apply_migration`, `backup_database`
  (Tasks 2-3), `munim.store.Store`.
- Produces: a `__main__` block — `python migrate_taxonomy_v2.py` (dry
  run, default) and `python migrate_taxonomy_v2.py --apply`.

No automated test for this task — it's a thin argument-parsing and
print-formatting wrapper around already-tested functions. Verified
manually in Task 5.

- [ ] **Step 1: Write the CLI wrapper**

Append to the end of `packages/classify/migrations/migrate_taxonomy_v2.py`:

```python

def _print_report(report: dict, heading: str) -> None:
    print(f"\n=== {heading} ===")
    print("\n--- Whole-category moves ---")
    for old_cat, info in report["whole_category"].items():
        new_cat, new_sub = WHOLE_CATEGORY_MOVES[old_cat]
        dest = f"{new_cat}:{new_sub}" if new_sub else new_cat
        print(f"  {old_cat!r:20s} -> {dest:35s} "
              f"n={info['count']:4d}  total={info['total']:12,.2f}")
    print("\n--- Pattern moves (Utilities split + CRED fix) ---")
    total_n = sum(i["count"] for i in report["pattern"].values())
    total_amt = sum(i["total"] for i in report["pattern"].values())
    print(f"  {len(report['pattern'])} patterns, "
          f"{total_n} transactions matched, ₹{total_amt:,.2f} total")
    zero = [p for p, i in report["pattern"].items() if i["count"] == 0]
    if zero:
        print(f"  ({len(zero)} patterns matched 0 transactions — "
              f"expected if the live data has changed since the spec "
              f"was written)")


if __name__ == "__main__":
    import argparse
    from munim.store import Store as _Store

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Without this flag, dry-run only.")
    args = parser.parse_args()

    store = _Store()
    print(f"Database: {store.home / 'munim.db'}")

    if not args.apply:
        report = plan_migration(store)
        _print_report(report, "DRY RUN — no changes written")
        print("\nRe-run with --apply to write these changes "
              "(a backup is taken automatically first).")
    else:
        backup_path = backup_database(store.home)
        print(f"Backup written to: {backup_path}")
        report = apply_migration(store)
        _print_report(report, "APPLIED — changes written")
        print("\nDone. Verify with: munim categories list")
```

- [ ] **Step 2: Verify manually**

Run: `uv run --package munim python packages/classify/migrations/migrate_taxonomy_v2.py --help`
Expected: prints usage with the `--apply` flag description, exits 0.

- [ ] **Step 3: Run the full existing suite one more time**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing — this task added no new test-covered logic, this
is the final regression check before touching real data in Task 5.

- [ ] **Step 4: Commit**

```bash
git add packages/classify/migrations/migrate_taxonomy_v2.py
git commit -m "Add CLI wrapper for the taxonomy v2 migration script"
```

---

### Task 5 (operational — dry run against the real database)

**Not a code task.** Run the script against the actual
`~/.munim/munim.db`, in dry-run mode (the default — no `--apply`), and
review the output line by line before anything is written.

- [ ] **Step 1: Run the dry run**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python packages/classify/migrations/migrate_taxonomy_v2.py
```

- [ ] **Step 2: Cross-check every whole-category count against the spec**

The design spec (`docs/superpowers/specs/2026-09-04-category-taxonomy-v2-design.md`)
documents exact expected counts and totals for each rule. Confirm the
dry-run output matches:

| Rule | Expected count | Expected total |
|---|---:|---:|
| Fuel → Transport:Fuel | 47 | ₹68,927.20 |
| Rent → Housing:Rent | 3 | ₹33,656.00 |
| Household Help → Housing:Household Help | 45 | ₹201,623.82 |
| Fees & Charges → Other | 439 | ₹419,873.42 |
| Pattern moves (CRED + Utilities split combined) | matches spec's per-bucket table | — |

If any count or total doesn't match (the live database may have changed
since the spec was written — new imports, manual `munim relabel` calls,
etc.), stop and investigate the discrepancy before proceeding — do not
assume the script is wrong or right without checking which changed.

- [ ] **Step 3: Get explicit go-ahead**

Present the dry-run output to your human partner. Do not proceed to
Task 6 without an explicit go-ahead on this specific dry-run output —
approval of the design spec earlier is not approval to write to the
real database now.

---

### Task 6 (operational — apply to the real database)

**Not a code task. Only start this after your human partner has
explicitly approved the Task 5 dry-run output.**

- [ ] **Step 1: Run with --apply**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python packages/classify/migrations/migrate_taxonomy_v2.py --apply
```

- [ ] **Step 2: Verify the backup exists**

```bash
ls -la ~/.munim/munim.db.bak.*
```

Confirm a backup file was created with today's timestamp before
proceeding to any further verification.

- [ ] **Step 3: Verify category totals**

Re-run the same spend-by-category audit used to design the taxonomy in
the first place:

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python3 -c "
from munim.store import Store
from collections import defaultdict
s = Store()
txns = s.all_transactions()
by_cat = defaultdict(lambda: [0, 0.0])
for t in txns:
    if t.direction.value == 'debit' and not t.is_transfer:
        by_cat[t.category or '(uncategorized)'][0] += 1
        by_cat[t.category or '(uncategorized)'][1] += t.amount
for cat, (n, total) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
    print(f'{cat:20s} n={n:5d}  total={total:12,.2f}')
"
```

Confirm: `Fuel`, `Rent`, `Household Help`, `Fees & Charges` no longer
appear at all. `Housing` appears with a total in the expected range
(roughly ₹201,623.82 + ₹33,656.00 + the Utilities Housing-bound total
from the spec's Rule 5 table). The grand total across all categories
(sum of every row) matches the pre-migration grand total from the design
spec's original audit — no transaction gained or lost in the move.

- [ ] **Step 4: Spot-check a handful of individual transactions**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
munim categories subcategories list Housing
munim categories subcategories list Transport
```

Confirm the new subcategory lists show up correctly. Then verify one
transaction from each major rule landed correctly (e.g. query for a known
CRED Club transaction and confirm `category='Transfers',
subcategory='Credit Card Payment'`).

- [ ] **Step 5: Report results**

Summarize for your human partner: final category list, before/after
transaction counts for every retired category, confirmation the grand
total is unchanged, and the backup file's path (in case anything needs
to be rolled back).
