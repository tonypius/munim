"""Tests for HDFC's own website "Download Statement" Excel export —
a different source and format from the emailed PDF handled by
hdfc_bank_account.py: a clean tabular export (one row per transaction,
columns Date / Narration / Chq./Ref.No. / Value Dt / Withdrawal Amt. /
Deposit Amt. / Closing Balance) with no page-merging or line-wrapping to
reconstruct.

Fictional data shaped after real statements (verified 2026-09-01,
spanning April 2021 - April 2025): xlrd (.xls) represents an empty
Withdrawal/Deposit cell as an empty string, openpyxl (.xlsx) represents
it as None — _rows_to_transactions must handle both, since HDFC's own
site exports both formats depending on when the statement was
downloaded.
"""
from munim_ingest.hdfc_bank_account_excel import (
    HEADER_ROW,
    _find_header_row,
    _rows_to_transactions,
)


def _sheet(*data_rows):
    """A sheet shaped like a real export: preamble, header, mask row,
    data rows, footer — mirroring what _rows_to_transactions must skip."""
    return [
        ["HDFC BANK Ltd.", None, None],
        [None, None, None],
        ["MR. TONY PIUS ALAPATT", None, "Account No :50100130659482"],
        ["Date", "Narration", "Chq./Ref.No.", "Value Dt",
         "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"],
        ["********", "**********", "****", "********", "****", "****", "****"],
        *data_rows,
        ["---  End Of Statement ---", None, None, None, None, None, None],
    ]


def test_finds_header_row_by_date_and_narration_columns():
    rows = _sheet(["01/04/23", "SOME NARRATION", "REF1", "01/04/23", "", 100.0, 900.0])
    assert _find_header_row(rows) == 3


def test_header_not_found_returns_none():
    assert _find_header_row([["nothing", "here"], ["at", "all"]]) is None


def test_withdrawal_becomes_negative_amount_xls_empty_string_style():
    """xlrd represents an empty numeric cell as ''."""
    rows = _sheet(["01/04/23", "IMPS-X-Y-PAYMENT", "REF1", "01/04/23",
                   500.0, "", 9500.0])
    result = _rows_to_transactions(rows)
    assert result == [["01/04/23", "IMPS-X-Y-PAYMENT", "-500.00"]]


def test_deposit_becomes_positive_amount_xlsx_none_style():
    """openpyxl represents an empty numeric cell as None."""
    rows = _sheet(["02/04/23", "NEFT CR-SALARY", "REF2", "02/04/23",
                   None, 50000.0, 59500.0])
    result = _rows_to_transactions(rows)
    assert result == [["02/04/23", "NEFT CR-SALARY", "50000.00"]]


def test_multiple_transactions_same_day_all_kept_in_order():
    rows = _sheet(
        ["01/04/23", "FIRST", "R1", "01/04/23", 100.0, "", 900.0],
        ["01/04/23", "SECOND", "R2", "01/04/23", "", 200.0, 1100.0],
    )
    result = _rows_to_transactions(rows)
    assert result == [
        ["01/04/23", "FIRST", "-100.00"],
        ["01/04/23", "SECOND", "200.00"],
    ]


def test_footer_and_preamble_rows_are_skipped():
    rows = _sheet(["01/04/23", "A TXN", "REF", "01/04/23", 10.0, "", 990.0])
    result = _rows_to_transactions(rows)
    assert len(result) == 1
    assert result[0][0] == "01/04/23"


def test_narration_stripped_of_surrounding_whitespace():
    rows = _sheet(["01/04/23", "  PADDED NARRATION  ", "REF", "01/04/23",
                   10.0, "", 990.0])
    result = _rows_to_transactions(rows)
    assert result[0][1] == "PADDED NARRATION"


def test_row_with_unparseable_amount_is_skipped():
    rows = _sheet(["01/04/23", "BAD ROW", "REF", "01/04/23",
                   "not-a-number", "", 990.0])
    result = _rows_to_transactions(rows)
    assert result == []


def test_no_header_found_returns_empty():
    assert _rows_to_transactions([["random"], ["junk"]]) == []


def test_empty_sheet_returns_empty():
    assert _rows_to_transactions([]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Narration", "Amount"]
