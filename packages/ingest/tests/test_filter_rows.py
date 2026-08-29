"""Tests for filter_transaction_rows, using fictional data shaped after a
real HDFC statement's extracted structure (page-header titles, per-page
summary boxes, blank spacer rows, and a repeated column-header row all
mixed into the same extract_rows() output alongside genuine 5-column
transaction rows) — never the user's real financial data.
"""
from munim_ingest.pdf_extract import filter_transaction_rows


def _transaction(date, desc, points, amount):
    return [date, desc, points, amount, None]


def test_keeps_only_dominant_length_rows_starting_with_a_date():
    rows = [
        ["Statement Title Text"],  # 1-col page header noise
        ["Statement Date:01/01/2024", "Card No: 1234", "AAN: 999"],  # 3-col summary
        ["Payment Due Date", "Total Dues", "Minimum Amount Due"],  # 3-col header
        ["12/03/2024", "32,682.00", "1,695.00"],  # 3-col summary row (starts with a
        # date but wrong shape — not a transaction; the dominant length filter
        # must exclude this even though the date-prefix check alone would not)
        ["Date", "Transaction Description", "Feature Reward", "Amount (in Rs.)", None],
        [None, "TONY PIUS ALAPATT", None, None, None],  # 5-col blank/name row
        _transaction("21/01/2024", "GROFERS INDIA", None, "379.00"),
        _transaction("21/01/2024 12:55:34", "ZOMATO LTD", "4", "179.00"),
        _transaction("23/01/2024", "RAZ*IRCTC", "- 68", "2,600.00Cr"),
    ]

    result = filter_transaction_rows(rows)

    assert result == [
        _transaction("21/01/2024", "GROFERS INDIA", None, "379.00"),
        _transaction("21/01/2024 12:55:34", "ZOMATO LTD", "4", "179.00"),
        _transaction("23/01/2024", "RAZ*IRCTC", "- 68", "2,600.00Cr"),
    ]


def test_recovers_a_date_not_at_the_very_start_of_the_cell():
    """A real extraction artifact: pdfplumber occasionally prepends stray
    text (e.g. a hidden-layer marker) before the date in a cell. The date
    must still be found anywhere in the first column, not just as a strict
    prefix — otherwise a genuine transaction is silently dropped."""
    rows = [
        _transaction("garbage09/02/2024 14:54:14", "SLACK SUBSCRIPTION", "144", "5,438.01"),
        _transaction("21/01/2024", "GROFERS INDIA", None, "379.00"),
        [None, "TONY PIUS ALAPATT", None, None, None],
    ]

    result = filter_transaction_rows(rows)

    assert len(result) == 2
    assert result[0][0] == "garbage09/02/2024 14:54:14"


def test_empty_input_returns_empty():
    assert filter_transaction_rows([]) == []


def test_no_row_has_a_date_returns_empty():
    """If nothing looks like a transaction (e.g. extraction found only
    header/summary noise), the result must be empty, not a crash — a
    length-0 CSV is a visible, honest signal something's wrong, not silent
    corruption."""
    rows = [
        ["Statement Title"],
        ["Payment Due Date", "Total Dues", "Minimum Amount Due"],
    ]
    assert filter_transaction_rows(rows) == []


def test_all_rows_same_shape_and_dated_keeps_everything():
    rows = [
        _transaction("01/01/2024", "A", None, "1.00"),
        _transaction("02/01/2024", "B", None, "2.00"),
    ]
    assert filter_transaction_rows(rows) == rows


def test_handles_none_cells_without_crashing():
    """Rows can contain None cells (pdfplumber emits None for unruled
    cells) — a row whose first cell is None must be excluded, not raise."""
    rows = [
        [None, None, None, None, None],
        _transaction("01/01/2024", "A", None, "1.00"),
    ]
    result = filter_transaction_rows(rows)
    assert result == [_transaction("01/01/2024", "A", None, "1.00")]
