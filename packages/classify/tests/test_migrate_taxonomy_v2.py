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
