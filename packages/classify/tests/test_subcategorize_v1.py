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


def test_plan_migration_health_care_default_excludes_insurance_pattern_in_either_field(tmp_path):
    from subcategorize_v1 import plan_migration
    store = Store(home=tmp_path)
    # merchant_norm does NOT match a HEALTH_INSURANCE pattern, but
    # payee_handle does. The buggy `(merchant_norm or payee_handle)`
    # short-circuits on the truthy merchant_norm and never checks
    # payee_handle, wrongly counting this toward the Care default.
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="SOME UNRELATED THING", category="Health",
                    merchant_norm="SOME UNRELATED THING",
                    payee_handle="POLICYBAZAAR COM GURGAON")
    store.upsert_transactions([t])
    report = plan_migration(store)
    assert report["health_care_default"]["count"] == 0


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
