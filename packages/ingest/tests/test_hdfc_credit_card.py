"""Tests for HDFC credit-card-specific amount normalization, using
fictional data shaped after the real convention observed on an actual
HDFC statement — never the user's real financial data.

HDFC credit card statements never use a minus sign: every amount is a
positive magnitude, and a trailing Cr suffix marks a credit (refund or
payment received) rather than the default debit (a purchase). munim's
CSV importer expects a single signed column instead (negative = debit,
positive = credit, no letter suffix) — this bridges the two conventions
for the HDFC 5-column layout only (Date, Description, Feature Reward
Points, Amount, trailing-empty), not as a generic claim about any other
bank's format.
"""
from munim_ingest.hdfc_credit_card import normalize_hdfc_credit_card_amounts


def test_bare_amount_becomes_negative_debit():
    rows = [["21/01/2024", "GROFERS INDIA", None, "379.00", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["21/01/2024", "GROFERS INDIA", None, "-379.00", None]]


def test_cr_suffix_becomes_positive_credit_with_suffix_stripped():
    rows = [["23/01/2024", "RAZ*IRCTC HTTPS://WW", "- 68", "2,600.00Cr", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["23/01/2024", "RAZ*IRCTC HTTPS://WW", "- 68", "2600.00", None]]


def test_dr_suffix_stays_negative_debit_with_suffix_stripped():
    """Not observed in the one real statement checked so far, but HDFC
    statements are known to sometimes mark debits explicitly with Dr —
    support it defensively rather than assume Cr is the only marker."""
    rows = [["01/02/2024", "SOME PURCHASE", None, "1,000.00Dr", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["01/02/2024", "SOME PURCHASE", None, "-1000.00", None]]


def test_suffix_matching_is_case_insensitive():
    rows = [["01/02/2024", "X", None, "50.00CR", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["01/02/2024", "X", None, "50.00", None]]


def test_preserves_all_other_columns_unchanged():
    rows = [["21/01/2024 12:55:34", "GROFERS INDIA PRIVATE BANGALORE", "4", "379.00", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result[0][0] == "21/01/2024 12:55:34"
    assert result[0][1] == "GROFERS INDIA PRIVATE BANGALORE"
    assert result[0][2] == "4"
    assert result[0][4] is None


def test_empty_input_returns_empty():
    assert normalize_hdfc_credit_card_amounts([]) == []


def test_row_with_fewer_than_four_columns_is_left_unchanged():
    """Defensive: this function is only meaningful for HDFC's expected
    5-column shape (amount at index 3). A row that doesn't match that
    shape shouldn't crash — leave it as-is rather than guess at which
    field might be the amount."""
    rows = [["not", "enough", "columns"]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["not", "enough", "columns"]]


def test_unparseable_amount_is_left_unchanged_not_crashed():
    """Defensive: if the amount field doesn't look like a number at all
    (an unexpected extraction artifact), leave it untouched rather than
    raise — munim import's own parser will surface the problem clearly
    when it tries to import that row, which is more informative than a
    crash here with no context."""
    rows = [["21/01/2024", "X", None, "not-a-number", None]]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result == [["21/01/2024", "X", None, "not-a-number", None]]


def test_real_extracted_data_shape_end_to_end():
    """Mirrors the exact real rows (fictionalized) seen after
    filter_transaction_rows on a real HDFC statement, including the
    largest real value observed (a ~68,000 rupee autopay credit) and a
    small one, to catch any comma-formatting edge case."""
    rows = [
        ["21/01/2024", "IGST-VPS2402242546613-RATE 18.0 -32 (Ref# ST240220083000010599286)",
         None, "6.45", None],
        ["10/02/2024 07:49:09", "AUTOPAY THANK YOU (Ref# ST240420083000010120983)",
         None, "68,037.00Cr", None],
        ["19/02/2024", "Apollo Pharmacies Ltd Chennai", None, "49.46Cr", None],
    ]
    result = normalize_hdfc_credit_card_amounts(rows)
    assert result[0][3] == "-6.45"
    assert result[1][3] == "68037.00"
    assert result[2][3] == "49.46"
