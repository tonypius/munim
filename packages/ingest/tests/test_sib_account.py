"""Tests for South Indian Bank's own netbanking "Transaction History"
export ("OpTransactionHistory...csv") — a clean-enough CSV, but not one
`munim import`'s generic CSV loader can read directly: a preamble block
(account holder name/address, statement/account metadata, From/To Date)
sits before the real column header, and a "****End of A/c Statement****"
footer sits after the last real row. Columns are SlNo, Transaction Date,
Value Date, Particulars, two blank columns, Cheque Number, Withdrawals,
Deposits, Balance Amount.

Fictional data shaped after four real statements spanning April 2021 -
March 2025 (verified 2026-09-09): the running Balance Amount column
matches opening balance + cumulative signed amount for every single row
in each file, byte-for-byte — the strongest verification available since
this bank actually prints its own running balance per row, unlike SBI's
export.
"""
from munim_ingest.sib_account import HEADER_ROW, _find_header_row, _rows_to_transactions


def _sheet(*data_rows):
    return [
        ["", "", "Account Name : ", "", "TONY PIUS ALAPATT", "", "", "", ""],
        ["", "", "Customer Address : ", "", "SOME ADDRESS LINE", "", "", "", ""],
        ["", "", "Statement Date :", "", "13-Dec-2024 , 04:19 PM", "", "", "", ""],
        ["", "", "Account No :", "", "0396053000012504 INR", "", "", "", ""],
        ["", "", "From Date:", "", "01-Apr-2021", "", "", "", ""],
        ["", "", "To Date:", "", "31-Mar-2022", "", "", "", ""],
        ["SlNo", "Transaction Date", "Value Date", "Particulars", "", "",
         "Cheque Number", "Withdrawals", "Deposits", "Balance Amount"],
        *data_rows,
        ["", "", "", "", "", "****End of A/c Statement****", "", "", ""],
    ]


def test_finds_header_row_by_transaction_date_and_particulars_columns():
    rows = _sheet(["1", "05-Apr-2021", "05-Apr-2021", "SOME NARRATION", "", "",
                    "", "500.00", "", "45,613.29"])
    assert _find_header_row(rows) == 6


def test_debit_row_produces_negative_signed_amount():
    rows = _sheet(["1", "05-Apr-2021", "05-Apr-2021",
                    "NACH/SIBL0000000000965549/HDFCMF 05042021 CAMS", "", "",
                    "", "500.00", "", "45,613.29"])
    assert _rows_to_transactions(rows) == [("05-Apr-2021", "NACH/SIBL0000000000965549/HDFCMF 05042021 CAMS", "-500.00")]


def test_credit_row_produces_positive_signed_amount():
    rows = _sheet(["1", "06-Mar-2022", "06-Mar-2022", "IMPS/HDFC/TONY PIUS ALAPATT/Monthly s",
                    "", "", "", "", "20,000.00", "7,12,880.85"])
    assert _rows_to_transactions(rows) == [("06-Mar-2022", "IMPS/HDFC/TONY PIUS ALAPATT/Monthly s", "20000.00")]


def test_indian_comma_grouped_amount_is_parsed_correctly():
    """"7,05,506.47" (lakh grouping, not the 000-grouping a plain comma
    strip might be tuned for) must still parse to 705506.47."""
    rows = _sheet(["1", "01-Apr-2022", "01-Apr-2022", "SOME DEBIT", "", "",
                    "", "7,05,506.47", "", "0.00"])
    assert _rows_to_transactions(rows) == [("01-Apr-2022", "SOME DEBIT", "-705506.47")]


def test_footer_and_preamble_rows_are_excluded():
    rows = _sheet(["1", "05-Apr-2021", "05-Apr-2021", "REAL ROW", "", "",
                    "", "500.00", "", "45,613.29"])
    result = _rows_to_transactions(rows)
    assert len(result) == 1
    assert result[0][1] == "REAL ROW"


def test_running_balance_matches_the_files_own_balance_column():
    """The file prints its own running balance per row — the strongest
    available cross-check. opening_balance + cumulative signed amount
    must equal the file's own Balance Amount for every row."""
    rows = _sheet(
        ["1", "05-Apr-2021", "05-Apr-2021", "DEBIT ONE", "", "", "", "500.00", "", "45,613.29"],
        ["2", "06-Apr-2021", "06-Apr-2021", "CREDIT ONE", "", "", "", "", "9,146.00", "54,759.29"],
        ["3", "07-Apr-2021", "07-Apr-2021", "DEBIT TWO", "", "", "", "5.90", "", "54,753.39"],
    )
    result = _rows_to_transactions(rows)
    opening_balance = 46113.29  # balance immediately before the first row
    running = opening_balance
    file_balances = [45613.29, 54759.29, 54753.39]
    for (_, _, signed_amount), expected_balance in zip(result, file_balances):
        running += float(signed_amount)
        assert round(running, 2) == expected_balance


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Particulars", "Amount"]
