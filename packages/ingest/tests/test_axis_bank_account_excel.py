"""Tests for Axis Bank's own netbanking "Download Statement" .xls export —
a clean tabular export (one row per transaction, columns SRL NO / Tran
Date / CHQNO / PARTICULARS / DR / CR / BAL / SOL) with no page-merging or
line-wrapping to reconstruct.

Fictional data shaped after two real statements (verified 2026-09-10,
spanning April 2025 - September 2026): xlrd reads DR/CR as
whitespace-padded strings, with a single space ' ' standing in for "no
amount on this side" rather than an empty string or None.
"""
from munim_ingest.axis_bank_account_excel import (
    HEADER_ROW,
    _find_header_row,
    _rows_to_transactions,
)


def _sheet(*data_rows):
    """A sheet shaped like a real export: preamble, header, data rows,
    footer — mirroring what _rows_to_transactions must skip."""
    return [
        ["Name :- MR RAMESH KUMAR", "", "", "", "", "", "", ""],
        ["IFSC Code :- UTIB0000009", "", "", "", "", "", "", ""],
        ["Statement of Axis Account No - 925010016476380 for the period ...", "", "", "", "", "", "", ""],
        ["SRL NO ", "Tran Date ", "CHQNO", "PARTICULARS ", "DR ", "CR ", "BAL ", "SOL "],
        *data_rows,
        ["Unless the constituent notifies the bank immediately ...", "", "", "", "", "", "", ""],
        ["This is a system generated output and requires no signature.", "", "", "", "", "", "", ""],
    ]


def test_finds_header_row_by_tran_date_and_particulars_columns():
    rows = _sheet([1.0, "04-08-2025", "", "SOME NARRATION", " ", "100.00", "1000.00", "009"])
    assert _find_header_row(rows) == 3


def test_header_not_found_returns_none():
    assert _find_header_row([["nothing", "here"], ["at", "all"]]) is None


def test_withdrawal_becomes_negative_amount():
    rows = _sheet([1.0, "08-08-2025", "", "IMPS/MRT/1/919686526569//",
                   "100000.00", " ", "50134.00", "009"])
    result = _rows_to_transactions(rows)
    assert result == [["08-08-2025", "IMPS/MRT/1/919686526569//", "-100000.00"]]


def test_deposit_becomes_positive_amount():
    rows = _sheet([1.0, "04-08-2025", "", "IFT/SCCPLL/Stirrup Communi/",
                   " ", "150134.00", "150134.00", "248"])
    result = _rows_to_transactions(rows)
    assert result == [["04-08-2025", "IFT/SCCPLL/Stirrup Communi/", "150134.00"]]


def test_multiple_transactions_same_day_all_kept_in_order():
    rows = _sheet(
        [1.0, "06-11-2025", "", "FIRST", "120000.00", " ", "35863.00", "009"],
        [2.0, "06-11-2025", "", "SECOND", "30000.00", " ", "5863.00", "009"],
    )
    result = _rows_to_transactions(rows)
    assert result == [
        ["06-11-2025", "FIRST", "-120000.00"],
        ["06-11-2025", "SECOND", "-30000.00"],
    ]


def test_footer_and_preamble_rows_are_skipped():
    rows = _sheet([1.0, "24-12-2025", "", "ATM-CASH/KATTOOR/THRISSUR/241225",
                   "7000.00", " ", "28996.00", "009"])
    result = _rows_to_transactions(rows)
    assert len(result) == 1
    assert result[0][0] == "24-12-2025"


def test_particulars_stripped_of_surrounding_whitespace():
    rows = _sheet([1.0, "01-01-2026", "", "  PADDED NARRATION  ",
                   " ", "217.00", "29213.00", "009"])
    result = _rows_to_transactions(rows)
    assert result[0][1] == "PADDED NARRATION"


def test_row_with_unparseable_amount_is_skipped():
    rows = _sheet([1.0, "01-01-2026", "", "BAD ROW",
                   "not-a-number", " ", "29213.00", "009"])
    result = _rows_to_transactions(rows)
    assert result == []


def test_no_header_found_returns_empty():
    assert _rows_to_transactions([["random"], ["junk"]]) == []


def test_empty_sheet_returns_empty():
    assert _rows_to_transactions([]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Narration", "Amount"]
