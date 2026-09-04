# Subcategory Classification v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assign subcategories to transactions across Groceries, Health,
Dining, Transport, Subscriptions, Travel, and Investments, per
`docs/superpowers/specs/2026-09-04-subcategory-classification-v1-design.md`.
Family & Friends is explicitly out of scope.

**Architecture:** A one-off migration script
(`packages/classify/migrations/subcategorize_v1.py`), mirroring
`migrate_taxonomy_v2.py`'s dry-run/apply/backup structure. Unlike that
migration, this one is almost entirely additive to `subcategory` — it
never changes `category` except for two specific transactions (the
Melvin loan-repayment fix), corrected by transaction id, not pattern.

**Tech Stack:** Python 3.11+, SQLite, pytest. No new dependencies.

## Global Constraints

- Every pattern-based subcategory assignment must verify the transaction
  is currently in the EXPECTED category before writing — even though
  cross-category merchant-string collisions are unlikely, this is a
  cheap safety check and this plan's tests must cover it (a transaction
  matching a pattern string but sitting in a different category must NOT
  be touched).
- Pattern-based assignments must update BOTH `transactions.subcategory`
  AND any EXISTING `memory.subcategory` row for that pattern — but must
  NEVER create a new memory row. Per the original subcategories design,
  dictionary-resolved merchants intentionally do not carry a subcategory
  forward to future imports unless the user explicitly teaches one via
  `munim learn --subcategory`; this migration must not silently change
  that by promoting a dictionary match into an owned memory rule.
- The Health "Care" default must be applied AFTER the Health "Insurance"
  patterns, and must only touch transactions whose `subcategory` is still
  empty at that point — never overwrite a subcategory this same run just
  set.
- The Melvin fix touches exactly two transaction ids, changes BOTH
  `category` and `subcategory`, and must not affect any other transaction
  under the same merchant pattern.
- The script must NEVER touch the real database without a timestamped
  backup first, exactly as `migrate_taxonomy_v2.py` already does — reuse
  that pattern, including taking the backup before any write in
  `--apply` mode.
- Dry-run (default, no `--apply`) must never call any write path.
- Match transactions by exact equality against `merchant_norm`/
  `payee_handle` (independently — `t.merchant_norm == p or
  t.payee_handle == p`, not a fallback), matching the convention already
  established in `migrate_taxonomy_v2.py` and its own dry-run/apply
  consistency requirement.
- Every new/changed function needs a test before being considered done
  (TDD: failing test first).

---

### Task 1: Subcategory pattern tables and the Melvin fix constant

**Files:**
- Create: `packages/classify/migrations/subcategorize_v1.py`
- Test: `packages/classify/tests/test_subcategorize_v1.py` (new file)

**Interfaces:**
- Produces:
  - `SUBCATEGORY_MOVES: dict[str, tuple[str, str]]` — pattern (uppercase,
    exact) -> `(expected_category, subcategory)`. `expected_category` is
    used only to verify the transaction's current category before
    writing — it is never written, since these patterns don't change
    category.
  - `HEALTH_CARE_DEFAULT_CATEGORY = "Health"` and
    `HEALTH_CARE_DEFAULT_SUBCATEGORY = "Care"` — the two literals the
    Health-default logic (Task 3) needs; kept as named constants rather
    than inlined so tests can reference them without magic strings.
  - `MELVIN_LOAN_FIX: dict[str, tuple[str, str]]` — transaction id ->
    `(new_category, new_subcategory)`, exactly the two ids from the
    design spec.

- [ ] **Step 1: Write the failing test**

Create `packages/classify/tests/test_subcategorize_v1.py`:

```python
"""Tests for the one-off subcategory-classification-v1 migration script.
These test the migration's DATA (constants, pattern tables) — never the
real ~/.munim/munim.db."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "migrations"))

from subcategorize_v1 import (
    SUBCATEGORY_MOVES,
    HEALTH_CARE_DEFAULT_CATEGORY,
    HEALTH_CARE_DEFAULT_SUBCATEGORY,
    MELVIN_LOAN_FIX,
)


def test_subcategory_moves_total_count_matches_spec():
    # 30 Groceries + 5 Health(Insurance) + 69 Dining + 46 Transport +
    # 78 Subscriptions + 30 Travel + 7 Investments = 265.
    assert len(SUBCATEGORY_MOVES) == 265


def test_no_pattern_appears_twice_with_different_destinations():
    # dict construction already guarantees uniqueness per key, but this
    # documents the invariant: 265 distinct keys, not fewer (which would
    # mean two buckets silently collided and one overwrote the other).
    assert len(set(SUBCATEGORY_MOVES.keys())) == 265


def test_known_groceries_meat_pattern():
    assert SUBCATEGORY_MOVES["FRESHTOHOME FOODS PRIVA"] == ("Groceries", "Meat")


def test_known_groceries_alcohol_pattern():
    assert SUBCATEGORY_MOVES["KERALA STATE BEVERAGES THRISSUR"] == ("Groceries", "Alcohol")


def test_known_groceries_produce_pattern():
    assert SUBCATEGORY_MOVES["LULU S VEGETABLES SH PAYTMQR281005050101F2X0K15ZHZEQ"] == ("Groceries", "Produce")


def test_known_health_insurance_pattern():
    assert SUBCATEGORY_MOVES["POLICYBAZAAR COM GURGAON"] == ("Health", "Insurance")


def test_known_dining_delivery_pattern():
    assert SUBCATEGORY_MOVES["ZOMATO NEW"] == ("Dining", "Delivery")
    assert SUBCATEGORY_MOVES["SWIGGY"] == ("Dining", "Delivery")
    assert SUBCATEGORY_MOVES["CRED SWIGGY"] == ("Dining", "Delivery")


def test_known_dining_out_pattern():
    assert SUBCATEGORY_MOVES["BREWSKY HENNUR BREWERY"] == ("Dining", "Dining Out")


def test_known_transport_fuel_extra_pattern():
    assert SUBCATEGORY_MOVES["GOKULA SERVICE STATION"] == ("Transport", "Fuel")


def test_known_transport_cabs_pattern():
    assert SUBCATEGORY_MOVES["UBER SYSTE NOIDA"] == ("Transport", "Cabs/Rideshare")


def test_transport_false_positive_excluded():
    assert "THURUTHUMMEL ENERGY HUBERNAKULAM" not in SUBCATEGORY_MOVES


def test_known_transport_public_transit_pattern():
    assert SUBCATEGORY_MOVES["REDBUS"] == ("Transport", "Public Transit")


def test_known_subscriptions_business_tools_pattern():
    assert SUBCATEGORY_MOVES["GOOGLE WORKSPACE CYBS SI"] == ("Subscriptions", "Business Tools")


def test_known_subscriptions_personal_pattern():
    assert SUBCATEGORY_MOVES["NETFLIX NETFLIX"] == ("Subscriptions", "Personal")


def test_known_travel_forex_pattern():
    assert SUBCATEGORY_MOVES["HDFC BANK PREPAID CARD"] == ("Travel", "Forex/Prepaid Cards")


def test_known_travel_flights_pattern():
    assert SUBCATEGORY_MOVES["EMIRATES"] == ("Travel", "Flights")


def test_known_travel_hotels_pattern():
    assert SUBCATEGORY_MOVES["MAKEMYTRIP L NEW"] == ("Travel", "Hotels/Packages")


def test_known_investments_patterns():
    assert SUBCATEGORY_MOVES["FD THROUGH MOBILE TONY PIUS ALAPATT"] == ("Investments", "FD/Deposits")
    assert SUBCATEGORY_MOVES["TPT NORAH MUTUAL FUND NIPPON MULTI CAP FUND SUBSCRIPTION"] == ("Investments", "Mutual Funds")
    assert SUBCATEGORY_MOVES["TONY PIUS ALAPATT SIBL XXXXXXXXXXXX2504 SAVE FROM SATOSHI"] == ("Investments", "Crypto")
    assert SUBCATEGORY_MOVES["UPI XXXXXX7770 SBIN0008627 KURI"] == ("Investments", "Chit/Kuri")


def test_health_care_default_constants():
    assert HEALTH_CARE_DEFAULT_CATEGORY == "Health"
    assert HEALTH_CARE_DEFAULT_SUBCATEGORY == "Care"


def test_melvin_loan_fix_has_exactly_two_transactions():
    assert MELVIN_LOAN_FIX == {
        "addd98a49577e4a7": ("Family & Friends", "Loans"),
        "67ee8f18e8565db8": ("Family & Friends", "Loans"),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'subcategorize_v1'`.

- [ ] **Step 3: Write the module**

Create `packages/classify/migrations/subcategorize_v1.py`. The full
`SUBCATEGORY_MOVES` table, built as separate per-bucket lists then merged
(so a future contributor can see the provenance of each pattern, and so
Task 1's own test can be extended per-bucket later without re-deriving
counts):

```python
"""One-off migration: subcategory classification pass v1.

See docs/superpowers/specs/2026-09-04-subcategory-classification-v1-design.md
for the full rationale, per-bucket verification notes, and the two
things this script does NOT do the way a pattern-move table would
suggest: the Health Care default (applied to every remaining Health
transaction, not a pattern list) and the Melvin loan fix (two
transaction ids, not a merchant pattern — see apply_migration in a
later task).
"""
import shutil
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------- Groceries: Meat
GROCERIES_MEAT = [
    "FRESHTOHOME FOODS PRIVA",
    "RAZ FRESHTOHOME FOODS HTTPS WW",
    "FRESHTOHOME INR",
    "FRESHTOHOME",
    "EMI FRESHTOHOME FOODS PRIVA",
    "FRESHTOHOME FOODS PRIV HTTPS WW",
    "FRESHTOHOME FOODS PRIV",
    "FRESHTOHOMEBANGALORE",
    "RAZ FRESHTOHOME MOHALI",
    "UPI FRESHTOHOME FRESHTOHOME ESBZ MAIRTEL AIRP0000001 PAY VALUE DT 15 04 2026",
    "MY CHICKEN AND MORE",
    "5 STAR MEAT PAYTMQR61EFA6",
    "PICKET FENCE FARMS E PICKETFENCEFARMS",
]

# ---------------------------------------------------- Groceries: Alcohol
GROCERIES_ALCOHOL = [
    "KERALA STATE BEVERAGES THRISSUR",
    "KERALA STATE BEVERAGES TRICHUR",
    "S S LIQUORS",
    "LIVING LIQUIDZ",
    "TONIQUE BEVERAGES",
    "TONIQUE",
    "MR SPIRITS LLP",
    "EMI KERALA STATE BEVERAGESCOTHRISSUR",
    "AR LIQUORS A UNIT OF A",
    "KERALA STATE BEVERAGESCOTHRISSUR",
    "AR LIQUORS A UNIT OF ARBANGALORE",
    "TONIQUEBANGALORE",
    "LIQUOR ZONEBENGALURU",
    "KERALA STATE BEVERAGESERNAKULAM",
    "KERALA STATE BEVERAGES COTHRISSUR",
]

# ---------------------------------------------------- Groceries: Produce
GROCERIES_PRODUCE = [
    "UPI K V R VEGETABLES VYAPAR 175208945306HDFCB ANK HDFC0MERUPI VEGETA BLE",
    "LULU S VEGETABLES SH PAYTMQR281005050101F2X0K15ZHZEQ",
]

# --------------------------------------------------------- Health: Insurance
HEALTH_INSURANCE = [
    "STAR HEALTH AND ALLIED CHENNAI",
    "STAR HEALTH AND ALLI STARHEALTH INSURANCE",
    "POLICYBAZAAR COM GURGAON",
    "EMI STAR HEALTH AND ALLIEDCHENNAI",
    "UPI XXXXXX0900 INDB0000007 HEALTH INSURANCE",
]

HEALTH_CARE_DEFAULT_CATEGORY = "Health"
HEALTH_CARE_DEFAULT_SUBCATEGORY = "Care"

# ---------------------------------------------------------- Dining: Delivery
DINING_DELIVERY = [
    "CRED SWIGGY",
    "EMI RAZ SWIGGYBENGALURU",
    "EMI SWIGGYBENGALURU",
    "EMI ZOMATO LIMITEDGURUGRAM",
    "PAY SWIGGYBANGALORE",
    "PAYTM ZOMATOLIMITED GURGAON",
    "RAZ SWIGGYBANGALORE",
    "RAZ ZOMATO HTTPS HY",
    "RAZ ZOMATO HYPERPURE HTTPS HY",
    "RAZ ZOMATO ONLINE ORDER GURGAON",
    "SWIGGY",
    "SWIGGY DASH",
    "SWIGGY E COMBANGALORE",
    "SWIGGY FOOD",
    "SWIGGY FOOD1BENGALURU",
    "SWIGGY FOODBANGALORE",
    "SWIGGY GENIE",
    "SWIGGY GO",
    "SWIGGY IN",
    "SWIGGY INBANGALORE",
    "SWIGGY LIMITEDBANGALORE",
    "SWIGGY LIMITEDBENGALURU",
    "SWIGGYBANGALORE",
    "SWIGGYBENGALURU",
    "UPI SWIGGY SWIGGY STORES AXB UTIB0000100 PAY FOR INTENT VALUE DT 03 04 2026",
    "UPI SWIGGY SWIGGYSTORES ICICI ICIC0DC0099 FOOD VALUE DT 04 02 2026",
    "WWW SWIGGY COM GURGAON",
    "WWW SWIGGY IN GURGAON",
    "WWW SWIGGY INBANGALORE",
    "ZOMATO",
    "ZOMATO COM GURGAON",
    "ZOMATO GURGAON",
    "ZOMATO GURUGRAM",
    "ZOMATO HTTPS WW",
    "ZOMATO HYPERPURGURGAON",
    "ZOMATO INTERNET PRIV WWW HYPERP",
    "ZOMATO MEDIA GURGAON",
    "ZOMATO MEDIA L GURGAON",
    "ZOMATO MEDIA L NOIDA",
    "ZOMATO MEDIA L WWW ZOMATO",
    "ZOMATO MEDIA LINOIDA",
    "ZOMATO MEDIA WWW ZOMATO",
    "ZOMATO NEW",
    "ZOMATO WWW ZOMATO",
    "ZOMATO ZOMATO ORDER",
    "ZOMATO ZOMATO1 GPAY",
    "ZOMATO ZOMATOORDER1 GPAY",
    "ZOMATONEW",
]

# --------------------------------------------------------- Dining: Dining Out
DINING_OUT = [
    "BREWSKY HENNUR BREWERY",
    "EMI DISTRICT DINING CYBSGURGAON",
    "EMI THE COMMISSIONERBLR EABANGALORE",
    "DISTRICT DINING CYBSGURGAON",
    "BOSCO EATERYBANGALORE",
    "BREWSKYBREWERYHENNUR",
    "AAVAKAY THE ANDHRA KITCMUMBAI",
    "THE RENAI COCHIN COCHIN",
    "EMI HOTEL SOUZA LOBONORTH GOA",
    "AAM VICTUALS LIMIMUMBAI",
    "BUFFALO WILD WINGS",
    "ANUPAMS COAST TO COAST",
    "BLABBER ALL DAY",
    "DISTRICT DINING CYBS GURGAON",
    "EMI DISTRICT DININGNEW",
    "BEER WORKS RESTAURANTS",
    "EMI HOTEL SHADABRANGA REDDY",
    "THE KINGS FIELD RESTAU",
    "DISTRICT DINING CYBSNEWDELHI",
    "DISTRICT DININGNEW",
    "DISTRICT DINING DISTRICTDINING PAYU",
]

# ----------------------------------------------- Transport: Fuel (additional)
TRANSPORT_FUEL_EXTRA = [
    "GOKULA SERVICE STATION",
    "PATEL SERVICE STATIONBANGALORE",
    "BHARAT PETROLEUM CORPOR DHARMAPURI",
    "SOUTHERN PETROLEUM ANGAMALLY",
    "PATEL SERVICE STATIONPBANGALORE",
    "AVARAN PETROLEUM IRINJALAKU",
    "MS NEW BOMBAY PETROLEUM THANE",
    "BHARAT PETROLEUM CORPOR",
    "HINDUSTAN PETROLEUM CORKRISHNAGIRI",
    "AVARAN PETROLEUMIRINJALAKU",
    "MAHIM SERVICE STATION",
    "HIGHWAY PETROLEUM ERNAKULAM",
]

# -------------------------------------------- Transport: Cabs/Rideshare
TRANSPORT_CABS = [
    "PAYTM UBERINDIASYSTE NOIDA",
    "UBER SYSTE NOIDA",
    "UBER SYSTEMS GURGAON",
    "UBER SYSTEMS P UBER",
    "UBER SYSTEMS P UBER1 RZP",
    "UBER SYSTEMS P UBERRIDES",
    "UBER SYSTEMS PRI HTTPS WW",
    "UBER SYSTEMS PRI NOIDA",
    "UBER SYSTEMS PRIV GURGAON",
    "UBER SYSTEMS PRIVNOIDA",
    "UBER TRIP HELP UBER COM LONDON",
    "UBERINDIASYSTEMSPRIVAT NOIDA",
    "UPI SREEJITH S IBL SBIN0070038 UBER TAXI VALUE DT 19 03 2026",
    "UPI UBER SYSTEMS P UBER AXISBANK UTIB0000000 C HARGEVALUE DT 08 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 02 02 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 04 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 08 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 04 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 23 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 25 01 2024",
]
# NOTE: 'THURUTHUMMEL ENERGY HUBERNAKULAM' matched a naive "UBER"
# substring search but is an energy company hub in Ernakulam
# ("...HUB-ERNAKULAM") -- deliberately excluded, not an oversight.

# ------------------------------------------- Transport: Public Transit
TRANSPORT_PUBLIC_TRANSIT = [
    "REDBUS",
    "IRCTC",
    "ROAD TRANSPORT CORPORATMUMBAI",
    "KARNATAKA STATE ROAD T GURGAON",
    "REDBUS BANGALORE",
    "IRCTC E TICKETING",
    "IRCTC NEW",
    "KARNATAKA STATE ROAD T",
    "RAZ IRCTC HTTPS WW",
    "REDBUS L",
    "EMI RAZ KARNATAKA STATE ROAD",
    "IRCTC AUTOPE GURGAON",
    "KERALA STATE ROAD TR KERALARTCONLINE",
    "KARNATAKA STATE ROAD KARNATAKASTATEROADTRANSPORTCORPORATION RZP",
]

# ------------------------------------------ Subscriptions: Business Tools
SUBSCRIPTIONS_BUSINESS_TOOLS = [
    "GOOGLE WORKSPACE CYBS SI",
    "DIGITALOCEAN COM AMSTERDAM",
    "DIGITALOCEAN COM DIGITALOCE",
    "PAYPAL DIGITALOCEA",
    "SLACK T63PG8P6H DUBLIN",
    "GOOGLE WORKSPACE CYBS SMUMBAI",
    "GODADDY DOMAIN",
    "GODADDY DOMAINS AMUMBAI",
    "GODADDY DOMAINS",
    "GOOGLE ADS",
    "GOOGLE WORKSPACE",
    "ADOBE ADOBE LY E",
    "DIGITALOCEAN COM GROSVENOR",
    "EMI ANTHROPIC CLAUDE TEAMANTHROPIC USD 225 00",
    "GOOGLE WORKSPACE CYBSSI",
    "EMI GOOGLE WORKSPACE CYBSSI",
    "EMI STRIPE Z AISINGAPORE USD 182 35",
    "GOOGLE ADWORDS",
    "OPENAI OPENAI COM",
    "DIGITALOCEAN COM AMSTERDAM USD 10 42",
    "DIGITALOCEAN COM AMSTERDAM USD 8 50",
    "ADOBE SOFTWARE WWW ADOBE",
    "ADOBE CREATIVE CLOUD ADOBE LY E",
    "WWW GODADDY COM PGSI WWW GODADD",
    "GOOGLE ADWORDS NAVI",
    "EMI STRIPE Z AISINGAPORE USD 84 37",
    "EMI STRIPE Z AISINGAPORE USD 81 00",
    "ANTHROPIC CLAUDE SUBANTHROPIC",
    "SLACK T63PG8P6H DUBLIN USD 74 17",
    "DIGITALOCEAN COMAMSTERDAM USD 9 92",
    "SLACK T63PG8P6H DUBLIN USD 73 39",
    "SLACK T63PG8P6H DUBLIN USD 70 79",
    "SLACK T63PG8P6H DUBLIN USD 69 30",
    "SLACK T63PG8P6H DUBLIN USD 66 73",
    "SLACK T63PG8P6H DUBLIN USD 64 13",
    "SLACK T63PG8P6H DUBLIN USD 65 68",
    "SLACK T63PG8P6H DUBLIN USD 65 49",
    "SLACK T63PG8P6H DUBLIN USD 62 10",
    "GOOGLE ADWORDS PGSI PLAY GOOGL",
    "DIGITALOCEAN COM AMSTERDAM USD 58 42",
    "SLACK T63PG8P6H DUBLIN USD 57 46",
    "SLACK T63PG8P6H DUBLIN USD 56 70",
    "SLACK T63PG8P6H DUBLIN USD 56 00",
    "SLACK T63PG8P6H DUBLIN USD 55 42",
    "SLACK T63PG8P6H DUBLIN USD 54 19",
    "SLACK T63PG8P6H DUBLIN USD 51 82",
    "SLACK T63PG8P6H DUBLIN USD 52 36",
    "OPENAI HTTPSOPENA USD 51 00",
    "CLAUDE AI SUBSCRIPTIONANTHROPIC USD 23 60",
    "OPENAI HTTPSOPENA USD 50 00",
    "GODADDY DOMAINS AN GURGAON",
    "EMI GODADDYMUMBAI",
    "WWW GODADDY COM",
    "EMI ANTHROPICANTHROPIC USD 29 50",
    "GODADDY DOMAINMUMBAI",
    "ADOBE SYSTEMS SOFTWARE I",
    "OPENAI HTTPSOPENA USD 25 00",
    "GODADDYMUMBAI",
    "STRIPE Z AISINGAPORE USD 18 00",
    "OPENAI HTTPSOPENA USD 10 00",
    "GODADDY DOMAINSMUMBAI",
    "GOOGLE WORKSPACEMUMBAI",
    "OPENAIOPENAI COM USD 11 80",
    "ANTHROPICANTHROPIC USD 11 80",
    "DIGITALOCEAN COM AMSTERDAM USD 10 92",
    "OPENAI HTTPSOPENA USD 10 25",
    "OPENAI HTTPSOPENA",
    "DIGITALOCEAN COM AMSTERDAM USD 9 94",
    "STRIPE Z AISINGAPORE USD 8 10",
    "DIGITALOCEAN COMAMSTERDAM USD 1 43",
    "DIGITALOCEAN COMAMSTERDAM USD 3 16",
    "DIGITALOCEAN COM AMSTERDAM USD 2 90",
    "DIGITALOCEAN COM AMSTERDAM USD 1 43",
    "DIGITALOCEAN COMAMSTERDAM USD 2 07",
]

# ------------------------------------------------ Subscriptions: Personal
SUBSCRIPTIONS_PERSONAL = [
    "NETFLIX NETFLIX",
    "NETFLIX",
    "NETFLIX DI SIMUMBAI",
    "NETFLIX ENTERTAINMENT SGURGAON",
]

# ------------------------------------------- Travel: Forex/Prepaid Cards
TRAVEL_FOREX = [
    "HDFC BANK PREPAID CARD",
    "HF80280921131730 HDFCBANKFOREXCARD",
]

# -------------------------------------------------------- Travel: Flights
TRAVEL_FLIGHTS = [
    "EMIRATES",
    "INDIGO AINE GURGAON",
    "EMI INDIGO AINEGURGAON",
    "TICKETS FLIG114504381 ABU DHABI",
    "INDIGO PAYTM",
]

# ------------------------------------------------- Travel: Hotels/Packages
TRAVEL_HOTELS_PACKAGES = [
    "ETI GLOBAL HOLIDAYS PVTMUMBAI",
    "MAKEMYTRIP L NEW",
    "MAKEMYTRIP LTGURGAON",
    "TPT TONYNAVIA TICKETS ETI GLOBAL HOLIDAYS",
    "MAKEMYTRIP NEW",
    "MACHAN RESORTS LLP",
    "EASE MY TRIP NEW",
    "MAKEMYTRIP LTNEW",
    "HOTEL VILLA DES GOUVERNEUPONDICHERR",
    "IXIGO",
    "TPT DOH TICKETS ETI GLOBAL HOLIDAYS",
    "CLEARTRIP LIMITEDMUMBAI",
    "TPT TONY NAVIA TICKETS ETI GLOBAL HOLIDAYS",
    "AGODA COM INTERNET",
    "AGODA",
    "AIRBNB PRIGURGAON",
    "UPI RAJESH R YESTP HDFC0007131 AIRBNB VALUE DT 30 11 2025",
    "AGODA COMPANY PTE",
    "EMI AIRBNB INDGURGAON",
    "AGODA COM THE MERCHA LONDON",
    "AIRBNB PVTGURGOAN",
    "PAYTM CLEARTRIPPRIVATE",
    "WWW AIRBNB COM GURGAON",
]

# ---------------------------------------------------------- Investments
INVESTMENTS_FD = ["FD THROUGH MOBILE TONY PIUS ALAPATT"]
INVESTMENTS_MUTUAL_FUNDS = [
    "TPT NORAH MUTUAL FUND NIPPON MULTI CAP FUND SUBSCRIPTION",
    "ICCLGROWW GROWW BSE GROWWPAY",
]
INVESTMENTS_CRYPTO = [
    "TONY PIUS ALAPATT SIBL XXXXXXXXXXXX2504 SAVE FROM SATOSHI",
    "AWLENCAN INNOVATIONS IBKL XXXXXXXXXXXX6569 ZEBPAY",
]
INVESTMENTS_CHIT_KURI = [
    "UPI XXXXXX7770 SBIN0008627 KURI",
    "UPI XXXXXX0005 SIBL0000517 KURI",
]

# ----------------------------------------------------------- Melvin fix
# See design spec: two specific transactions under "MELVIN MANOJ MATHEW
# MELVINMANOJ92" whose raw narration contains "loanrepayment" -- the
# rest of that merchant's transactions correctly stay Dining, so this is
# fixed by transaction id, not merchant pattern.
MELVIN_LOAN_FIX: dict[str, tuple[str, str]] = {
    "addd98a49577e4a7": ("Family & Friends", "Loans"),
    "67ee8f18e8565db8": ("Family & Friends", "Loans"),
}


def _build_subcategory_moves() -> dict[str, tuple[str, str]]:
    moves: dict[str, tuple[str, str]] = {}
    for pattern_list, category, subcategory in [
        (GROCERIES_MEAT, "Groceries", "Meat"),
        (GROCERIES_ALCOHOL, "Groceries", "Alcohol"),
        (GROCERIES_PRODUCE, "Groceries", "Produce"),
        (HEALTH_INSURANCE, "Health", "Insurance"),
        (DINING_DELIVERY, "Dining", "Delivery"),
        (DINING_OUT, "Dining", "Dining Out"),
        (TRANSPORT_FUEL_EXTRA, "Transport", "Fuel"),
        (TRANSPORT_CABS, "Transport", "Cabs/Rideshare"),
        (TRANSPORT_PUBLIC_TRANSIT, "Transport", "Public Transit"),
        (SUBSCRIPTIONS_BUSINESS_TOOLS, "Subscriptions", "Business Tools"),
        (SUBSCRIPTIONS_PERSONAL, "Subscriptions", "Personal"),
        (TRAVEL_FOREX, "Travel", "Forex/Prepaid Cards"),
        (TRAVEL_FLIGHTS, "Travel", "Flights"),
        (TRAVEL_HOTELS_PACKAGES, "Travel", "Hotels/Packages"),
        (INVESTMENTS_FD, "Investments", "FD/Deposits"),
        (INVESTMENTS_MUTUAL_FUNDS, "Investments", "Mutual Funds"),
        (INVESTMENTS_CRYPTO, "Investments", "Crypto"),
        (INVESTMENTS_CHIT_KURI, "Investments", "Chit/Kuri"),
    ]:
        for pattern in pattern_list:
            moves[pattern] = (category, subcategory)
    return moves


SUBCATEGORY_MOVES = _build_subcategory_moves()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: PASS (20 passed)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/migrations/subcategorize_v1.py packages/classify/tests/test_subcategorize_v1.py
git commit -m "Add subcategory-classification-v1 pattern tables and Melvin fix constant"
```

---

### Task 2: Dry-run planning function

**Files:**
- Modify: `packages/classify/migrations/subcategorize_v1.py`
- Test: `packages/classify/tests/test_subcategorize_v1.py`

**Interfaces:**
- Consumes: `SUBCATEGORY_MOVES`, `HEALTH_CARE_DEFAULT_CATEGORY`,
  `HEALTH_CARE_DEFAULT_SUBCATEGORY`, `MELVIN_LOAN_FIX` (Task 1),
  `munim.store.Store`.
- Produces: `plan_migration(store) -> dict` — read-only. Returns:
  ```python
  {
      "pattern": {pattern: {"count": int, "already_matches_category": bool,
                             "destination": (category, subcategory)}, ...},
      "health_care_default": {"count": int},  # Health txns that would get
                                                # subcategory='Care'
      "melvin_fix": {"count": int},  # of the 2 ids, how many still need it
                                       # (0 if already applied in a prior run)
  }
  ```
  `already_matches_category` is `True` when every currently-matching
  transaction is already in the pattern's expected category (the normal
  case) and `False` when at least one matching transaction is in a
  DIFFERENT category — a signal to investigate before applying, not an
  error.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategorize_v1.py`:

```python
from munim.store import Store
from munim.schema import Transaction, Direction


def test_plan_migration_counts_pattern_match_in_expected_category(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Dining",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    report = plan_migration(store)
    entry = report["pattern"]["ZOMATO NEW"]
    assert entry["count"] == 1
    assert entry["already_matches_category"] is True
    assert entry["destination"] == ("Dining", "Delivery")


def test_plan_migration_flags_pattern_in_wrong_category(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Shopping",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    report = plan_migration(store)
    entry = report["pattern"]["ZOMATO NEW"]
    assert entry["count"] == 1
    assert entry["already_matches_category"] is False


def test_plan_migration_counts_health_care_default(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    insured = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                          description_raw="POLICYBAZAAR COM GURGAON", category="Health",
                          merchant_norm="POLICYBAZAAR COM GURGAON")
    other_health = Transaction(date="2026-06-02", amount=300, direction=Direction.DEBIT,
                               description_raw="SOME DENTIST", category="Health",
                               merchant_norm="SOME DENTIST")
    store.upsert_transactions([insured, other_health])
    report = plan_migration(store)
    # Only the non-insurance Health transaction counts toward the default
    assert report["health_care_default"]["count"] == 1


def test_plan_migration_counts_melvin_fix_pending(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    t1 = Transaction(id="addd98a49577e4a7", date="2024-07-11", amount=20000,
                     direction=Direction.DEBIT, description_raw="loanrepayment",
                     category="Dining", merchant_norm="MELVIN MANOJ MATHEW MELVINMANOJ92")
    store.upsert_transactions([t1])
    report = plan_migration(store)
    assert report["melvin_fix"]["count"] == 1  # only 1 of the 2 ids present


def test_plan_migration_never_writes(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Dining",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    plan_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.subcategory == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: FAIL — `ImportError: cannot import name 'plan_migration'`.

- [ ] **Step 3: Write `plan_migration`**

Add to `packages/classify/migrations/subcategorize_v1.py`, after
`SUBCATEGORY_MOVES = _build_subcategory_moves()`:

```python

def plan_migration(store) -> dict:
    """Read-only: compute what apply_migration() would change, without
    writing anything."""
    txns = store.all_transactions()
    by_id = {t.id: t for t in txns}

    pattern: dict[str, dict] = {}
    for p, destination in SUBCATEGORY_MOVES.items():
        expected_category, _ = destination
        matches = [t for t in txns
                  if t.merchant_norm == p or t.payee_handle == p]
        already_matches = all(t.category == expected_category for t in matches) \
            if matches else True
        pattern[p] = {
            "count": len(matches),
            "already_matches_category": already_matches,
            "destination": destination,
        }

    health_care_count = sum(
        1 for t in txns
        if t.category == HEALTH_CARE_DEFAULT_CATEGORY
        and t.merchant_norm not in HEALTH_INSURANCE
        and t.payee_handle not in HEALTH_INSURANCE
    )

    melvin_pending = sum(1 for tid in MELVIN_LOAN_FIX if tid in by_id)

    return {
        "pattern": pattern,
        "health_care_default": {"count": health_care_count},
        "melvin_fix": {"count": melvin_pending},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: PASS (25 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/migrations/subcategorize_v1.py packages/classify/tests/test_subcategorize_v1.py
git commit -m "Add dry-run planning function to subcategory-classification-v1"
```

---

### Task 3: Apply function and database backup

**Files:**
- Modify: `packages/classify/migrations/subcategorize_v1.py`
- Test: `packages/classify/tests/test_subcategorize_v1.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces:
  - `backup_database(home: Path) -> Path` — identical implementation to
    `migrate_taxonomy_v2.py`'s function of the same name (copy it, don't
    import across migration scripts — each one-off migration is a
    self-contained historical artifact).
  - `apply_migration(store) -> dict` — writes, in this order: (1) the
    265 pattern-based subcategory assignments, each scoped to its
    expected category; (2) the Health Care default over whatever Health
    transactions are still unsubcategorized after step 1; (3) the Melvin
    fix by transaction id. Returns the same shape `plan_migration`
    returns.

- [ ] **Step 1: Write the failing test**

Add to `packages/classify/tests/test_subcategorize_v1.py`:

```python
def test_backup_database_creates_a_copy(tmp_path):
    from subcategorize_v1 import backup_database
    store = Store(home=tmp_path)
    backup_path = backup_database(tmp_path)
    assert backup_path.exists()
    assert backup_path != (tmp_path / "munim.db")
    assert backup_path.read_bytes() == (tmp_path / "munim.db").read_bytes()


def test_apply_migration_sets_subcategory_when_category_matches(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Dining",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    apply_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.subcategory == "Delivery"
    assert reloaded.category == "Dining"  # unchanged


def test_apply_migration_skips_pattern_match_in_wrong_category(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Shopping",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    apply_migration(store)
    reloaded = Store(home=tmp_path).get_transaction(t.id)
    assert reloaded.subcategory == ""  # NOT touched -- wrong category
    assert reloaded.category == "Shopping"


def test_apply_migration_updates_existing_memory_row_but_never_creates_one(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    store.remember("ZOMATO NEW", "Dining", kind="merchant")
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Dining",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    apply_migration(store)
    row = store.db.execute(
        "SELECT subcategory FROM memory WHERE pattern='ZOMATO NEW'").fetchone()
    assert row["subcategory"] == "Delivery"

    # A pattern with NO existing memory row must not gain one.
    t2 = Transaction(date="2026-06-02", amount=100, direction=Direction.DEBIT,
                     description_raw="REDBUS", category="Transport",
                     merchant_norm="REDBUS")
    store.upsert_transactions([t2])
    apply_migration(store)
    row2 = store.db.execute(
        "SELECT COUNT(*) AS n FROM memory WHERE pattern='REDBUS'").fetchone()
    assert row2["n"] == 0


def test_apply_migration_health_care_default_after_insurance(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    insured = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                          description_raw="POLICYBAZAAR COM GURGAON", category="Health",
                          merchant_norm="POLICYBAZAAR COM GURGAON")
    other_health = Transaction(date="2026-06-02", amount=300, direction=Direction.DEBIT,
                               description_raw="SOME DENTIST", category="Health",
                               merchant_norm="SOME DENTIST")
    store.upsert_transactions([insured, other_health])
    apply_migration(store)
    reloaded_insured = Store(home=tmp_path).get_transaction(insured.id)
    reloaded_other = Store(home=tmp_path).get_transaction(other_health.id)
    assert reloaded_insured.subcategory == "Insurance"
    assert reloaded_other.subcategory == "Care"


def test_apply_migration_melvin_fix_changes_category_and_subcategory(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    loan_txn = Transaction(id="addd98a49577e4a7", date="2024-07-11", amount=20000,
                           direction=Direction.DEBIT, description_raw="loanrepayment",
                           category="Dining", merchant_norm="MELVIN MANOJ MATHEW MELVINMANOJ92")
    food_txn = Transaction(date="2023-04-04", amount=800, direction=Direction.DEBIT,
                           description_raw="FOOD", category="Dining",
                           merchant_norm="MELVIN MANOJ MATHEW MELVINMANOJ92")
    store.upsert_transactions([loan_txn, food_txn])
    apply_migration(store)
    reloaded_loan = Store(home=tmp_path).get_transaction(loan_txn.id)
    reloaded_food = Store(home=tmp_path).get_transaction(food_txn.id)
    assert reloaded_loan.category == "Family & Friends"
    assert reloaded_loan.subcategory == "Loans"
    # The OTHER transaction under the same merchant must be untouched --
    # this is the whole reason the fix is by transaction id, not pattern.
    assert reloaded_food.category == "Dining"
    assert reloaded_food.subcategory == ""


def test_apply_migration_returns_same_shape_as_plan_migration(tmp_path):
    from subcategorize_v1 import apply_migration
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="ZOMATO NEW", category="Dining",
                    merchant_norm="ZOMATO NEW")
    store.upsert_transactions([t])
    report = apply_migration(store)
    assert report["pattern"]["ZOMATO NEW"]["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: FAIL — `ImportError: cannot import name 'backup_database'`.

- [ ] **Step 3: Write `backup_database` and `apply_migration`**

Add three imports directly after the module docstring's closing `"""`
(Task 1's implementer should have left no imports there — if you find
`import shutil`, `from datetime import datetime`, `from pathlib import
Path` already present and unused, that's a leftover from an earlier
task-brief draft; otherwise add them now, as the first statements after
the docstring, before the `# ---- taxonomy` comment section):

```python
import shutil
from datetime import datetime
from pathlib import Path
```

Then append to `packages/classify/migrations/subcategorize_v1.py`, after
`plan_migration`:

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
    """Write every subcategory assignment: pattern-based moves (scoped to
    their expected category), the Health Care default, then the Melvin
    fix by transaction id. Returns the same report shape as
    plan_migration() so the caller can print a before/after comparison."""
    report = plan_migration(store)

    for p, (expected_category, subcategory) in SUBCATEGORY_MOVES.items():
        store.db.execute(
            "UPDATE transactions SET subcategory=? "
            "WHERE (merchant_norm=? OR payee_handle=?) AND category=?",
            (subcategory, p, p, expected_category))
        store.db.execute(
            "UPDATE memory SET subcategory=? WHERE pattern=?",
            (subcategory, p))

    insurance_patterns = set(HEALTH_INSURANCE)
    all_txns = store.all_transactions()
    for t in all_txns:
        if t.category != HEALTH_CARE_DEFAULT_CATEGORY:
            continue
        if t.merchant_norm in insurance_patterns or t.payee_handle in insurance_patterns:
            continue
        if t.subcategory:
            continue  # a pattern rule already set something -- don't override
        store.db.execute(
            "UPDATE transactions SET subcategory=? WHERE id=?",
            (HEALTH_CARE_DEFAULT_SUBCATEGORY, t.id))

    for txn_id, (new_category, new_subcategory) in MELVIN_LOAN_FIX.items():
        store.db.execute(
            "UPDATE transactions SET category=?, subcategory=? WHERE id=?",
            (new_category, new_subcategory, txn_id))

    store.db.commit()
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package munim pytest packages/classify/tests/test_subcategorize_v1.py -v`
Expected: PASS (32 passed)

- [ ] **Step 5: Run the full existing suite**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add packages/classify/migrations/subcategorize_v1.py packages/classify/tests/test_subcategorize_v1.py
git commit -m "Add apply_migration and database backup to subcategory-classification-v1"
```

---

### Task 4: CLI wrapper

**Files:**
- Modify: `packages/classify/migrations/subcategorize_v1.py`

**Interfaces:**
- Consumes: `plan_migration`, `apply_migration`, `backup_database`
  (Tasks 2-3), `munim.store.Store`.
- Produces: a `__main__` block — `python subcategorize_v1.py` (dry run,
  default) and `python subcategorize_v1.py --apply`.

No automated test for this task — a thin argument-parsing and
print-formatting wrapper, verified manually in Task 5.

- [ ] **Step 1: Write the CLI wrapper**

Append to the end of `packages/classify/migrations/subcategorize_v1.py`:

```python

def _print_report(report: dict, heading: str) -> None:
    print(f"\n=== {heading} ===")
    print("\n--- Pattern-based subcategory assignments, by destination ---")
    by_dest: dict[tuple, dict] = {}
    flagged = []
    for p, info in report["pattern"].items():
        agg = by_dest.setdefault(info["destination"], {"count": 0})
        agg["count"] += info["count"]
        if not info["already_matches_category"] and info["count"] > 0:
            flagged.append(p)
    for (category, subcategory), agg in sorted(by_dest.items()):
        print(f"  -> {category}:{subcategory:25s} n={agg['count']:4d}")
    if flagged:
        print(f"\n  WARNING: {len(flagged)} pattern(s) matched at least one "
              f"transaction OUTSIDE their expected category -- these will "
              f"be silently skipped by apply_migration, investigate before "
              f"relying on that: {flagged}")
    print(f"\n--- Health Care default ---")
    print(f"  Health transactions -> subcategory='Care': "
          f"n={report['health_care_default']['count']}")
    print(f"\n--- Melvin loan fix ---")
    print(f"  Transactions pending fix (of 2 total): "
          f"n={report['melvin_fix']['count']}")


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
        print("\nDone. Verify with the Transactions page's subcategory filter.")
```

- [ ] **Step 2: Verify manually**

Run: `uv run --package munim python packages/classify/migrations/subcategorize_v1.py --help`
Expected: prints usage with the `--apply` flag description, exits 0.

- [ ] **Step 3: Run the full existing suite one more time**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add packages/classify/migrations/subcategorize_v1.py
git commit -m "Add CLI wrapper for subcategory-classification-v1"
```

---

### Task 5 (operational — dry run against the real database)

**Not a code task.** Run the script against the actual
`~/.munim/munim.db`, in dry-run mode, and review the output before
anything is written.

- [ ] **Step 1: Run the dry run**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python packages/classify/migrations/subcategorize_v1.py
```

- [ ] **Step 2: Cross-check every destination's count against the spec**

Cross-check against `docs/superpowers/specs/2026-09-04-subcategory-classification-v1-design.md`'s
per-bucket pattern counts and totals. Pay particular attention to the
`already_matches_category` warning list, if non-empty — the design spec
scoped every pattern to a specific category based on a snapshot of the
database; if any transaction has since moved category (e.g. via
`munim relabel` or a later review session), that pattern's assignment
will be silently skipped rather than applied to the wrong category. This
is a case to investigate, not necessarily a bug — decide whether the
skip is correct or whether the pattern list needs updating.

- [ ] **Step 3: Get explicit go-ahead**

Present the dry-run output to your human partner. Do not proceed to
Task 6 without an explicit go-ahead on this specific dry-run output.

---

### Task 6 (operational — apply to the real database)

**Not a code task. Only start this after your human partner has
explicitly approved the Task 5 dry-run output.**

- [ ] **Step 1: Run with --apply**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python packages/classify/migrations/subcategorize_v1.py --apply
```

- [ ] **Step 2: Verify the backup exists**

```bash
ls -la ~/.munim/munim.db.bak.*
```

Confirm a NEW backup file was created with today's timestamp (there will
already be one from the taxonomy v2 migration — confirm this run added
another, don't mistake the old one for this run's).

- [ ] **Step 3: Verify subcategory assignments landed**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
munim categories subcategories list Groceries
munim categories subcategories list Health
munim categories subcategories list Dining
munim categories subcategories list Transport
munim categories subcategories list Subscriptions
munim categories subcategories list Travel
munim categories subcategories list Investments
```

Confirm each shows non-zero counts matching (or reasonably close to,
accounting for any `already_matches_category` skips from Task 5) the
design spec's documented pattern counts.

- [ ] **Step 4: Verify the Melvin fix specifically**

```bash
cd /Users/tonyalapatt/Desktop/Work/claude/munim
uv run --package munim python3 -c "
from munim.store import Store
s = Store()
for tid in ['addd98a49577e4a7', '67ee8f18e8565db8']:
    t = s.get_transaction(tid)
    print(tid, t.category, t.subcategory, t.amount)
"
```

Confirm both print `Family & Friends Loans` and the OTHER Melvin
transactions (query by merchant pattern) still show `Dining` with no
subcategory forced on them.

- [ ] **Step 5: Report results**

Summarize for your human partner: per-category subcategory counts,
confirmation of the Melvin fix, the backup file's path, and a note on
anything flagged by the `already_matches_category` warning during Task 5
and how it was resolved.
