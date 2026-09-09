"""Tests for South Indian Bank's emailed yearly "Statement of Account"
PDF — a different source and format from the netbanking CSV export
handled by sib_account.py: pdfplumber finds no ruled table at all here
(a borderless, position-only layout), and a transaction row's own
Withdrawals/Deposits/Balance figures sit on their OWN line, physically
BETWEEN the two fragments of a wrapped Particulars narration -- e.g. a
real row renders as "01-04-25 NACH_DR/.../CAMS" / "500.00 20,389.49Cr" /
"LTD/ACH_DR", three separate physical lines for one transaction. Some
shorter narrations don't wrap at all and fit everything on one line.
Word dicts here use pdfplumber's real extract_words() shape (only
`text`, `x0`, and `top` are read).

Positions are fictional but shaped after a real statement (password-
verified 2026-09-09, covering 01-04-2025 to 31-03-2026): a normal row's
date sits at x0≈23, its Particulars fragments at x0≈87, its Withdrawals
amount at x0≈365-375, Deposits at x0≈450-465, and Balance (with a "Cr"
suffix glued to the number) at x0≈525-535 -- gaps of 70-90pt between
these column bands, comfortably wider than the safety margins used to
tell them apart. Confirmed against three real pages spanning the whole
statement that the running balance (opening + cumulative signed amount)
matches this PDF's own Balance column for every single row.
"""
from munim_ingest.sib_account_pdf import HEADER_ROW, parse_transactions


def w(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


class FakePage:
    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return self._words


def test_wrapped_withdrawal_row_with_narration_split_around_the_amount_line():
    page = FakePage([
        w("01-04-25", 23.0, 285.1),
        w("NACH_DR/SIBL0000000000965549/CAMS", 87.0, 284.8),
        w("500.00", 374.5, 289.4),
        w("20,389.49Cr", 527.0, 289.4),
        w("LTD/ACH_DR", 87.0, 294.1),
        # next row, so the wrapped row's lower bound is a true midpoint
        w("01-04-25", 23.0, 313.1),
        w("NACH_DR/SIBL0000000000965549/CAMS", 87.0, 312.8),
        w("500.00", 374.5, 317.4),
        w("19,889.49Cr", 527.0, 317.4),
        w("LTD/ACH_DR", 87.0, 322.1),
    ])
    result = parse_transactions([page])
    assert result[0] == ("01-04-25", "NACH_DR/SIBL0000000000965549/CAMS LTD/ACH_DR", "-500.00")


def test_unwrapped_row_with_everything_on_one_line():
    page = FakePage([
        w("06-04-25", 23.0, 565.1),
        w("MOB/RRN-509608803622/Family/IMPS", 87.0, 566.9),
        w("9,146.00", 367.9, 566.9),
        w("5,243.49Cr", 531.4, 566.9),
    ])
    assert parse_transactions([page]) == [
        ("06-04-25", "MOB/RRN-509608803622/Family/IMPS", "-9146.00")
    ]


def test_deposit_row_produces_positive_signed_amount():
    page = FakePage([
        w("07-04-25", 23.0, 400.0),
        w("NEFT:TONY", 87.0, 400.0),
        w("PIUS", 130.0, 400.0),
        w("ALAPATT/", 160.0, 400.0),
        w("20,000.00", 457.9, 400.0),
        w("40,000.00Cr", 527.0, 400.0),
    ])
    assert parse_transactions([page]) == [
        ("07-04-25", "NEFT:TONY PIUS ALAPATT/", "20000.00")
    ]


def test_page_total_footer_row_is_excluded():
    """A large vertical gap (real statements: ~45pt vs. a normal row's
    ~21-28pt) separates the last real transaction from the per-page
    "Page Total : ..." summary row -- it must never be swept into the
    last transaction's cluster nor emitted as one of its own."""
    page = FakePage([
        w("09-04-25", 23.0, 723.1),
        w("NACH_DR/SIBL0000000000965549/CAMS", 87.0, 722.8),
        w("500.00", 374.5, 727.4),
        w("2,737.59Cr", 531.4, 727.4),
        w("LTD/ACH_DR", 87.0, 732.1),
        w("Page", 24.0, 768.1),
        w("Total", 44.9, 768.1),
        w(":", 64.9, 768.1),
        w("20,651.90", 363.4, 768.1),
        w("2,500.00", 457.9, 768.1),
        w("2,737.59Cr", 530.4, 768.1),
    ])
    result = parse_transactions([page])
    assert result == [("09-04-25", "NACH_DR/SIBL0000000000965549/CAMS LTD/ACH_DR", "-500.00")]


def test_multiple_pages_combined_in_order():
    page1 = FakePage([
        w("01-04-25", 23.0, 285.1),
        w("FIRST", 87.0, 285.1),
        w("500.00", 374.5, 285.1),
        w("100.00Cr", 527.0, 285.1),
    ])
    page2 = FakePage([
        w("02-04-25", 23.0, 285.1),
        w("SECOND", 87.0, 285.1),
        w("100.00", 457.9, 285.1),
        w("200.00Cr", 527.0, 285.1),
    ])
    result = parse_transactions([page1, page2])
    assert result == [
        ("01-04-25", "FIRST", "-500.00"),
        ("02-04-25", "SECOND", "100.00"),
    ]


def test_page_with_no_words_is_skipped():
    assert parse_transactions([FakePage([])]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Particulars", "Amount"]
