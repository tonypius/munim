"""Tests for SBI Elite credit card 'Transaction History' exports — a
from-Gmail or self-service download, not a monthly billing PDF. Its own
"Date Description Type Amount" column header renders as a small ruled
table via pdfplumber, but the transaction rows themselves never do —
they sit in each page's plain, unruled text instead, which makes the
generic extract_rows()/filter_transaction_rows() path actively wrong for
this bank (it finds the header "table" and returns only that, skipping
every real transaction on every page).

Word dicts here use pdfplumber's real extract_words() shape (a `text`,
an `x0`, and a `top` are all this module reads — pdfplumber's real dicts
carry more keys, all ignored). Positions are fictional but shaped after
real ones: a normal row's words share one `top`; the pre/post fragments
of a wrapped row sit within a few points of their own row's date, with
the next row's date a full ~27pt below — this is the exact structural
pattern (not just the counts) confirmed against three real statement
exports spanning Dec 2022–Jun 2025, cross-checked byte-for-byte against
an independent extraction done by hand during development. Never the
user's real financial data.
"""
from munim_ingest.sbi_credit_card import HEADER_ROW, parse_transactions


def w(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


class FakePage:
    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return self._words


def test_simple_debit_row():
    page = FakePage([
        w("20/03/2023", 57.4, 100.0), w("CRED", 125.0, 100.0),
        w("GURGAON", 165.0, 100.0), w("IN", 220.0, 100.0),
        w("Debit", 368.6, 100.0), w("32037.00", 468.0, 100.0),
    ])
    assert parse_transactions([page]) == [("20/03/2023", "CRED GURGAON IN", "-32037.00")]


def test_simple_credit_row():
    page = FakePage([
        w("10/03/2023", 57.4, 100.0), w("PAYMENT", 125.0, 100.0),
        w("RECEIVED", 175.0, 100.0), w("Credit", 368.6, 100.0),
        w("339.00", 468.0, 100.0),
    ])
    assert parse_transactions([page]) == [("10/03/2023", "PAYMENT RECEIVED", "339.00")]


def test_wrapped_description_fragment_before_and_after_the_date_line():
    """The exact real structure that broke a first (text-stream-order)
    implementation of this parser: a long merchant name wraps onto its
    own line ABOVE the date/type/amount line, with a trailing fragment
    (here, the "IN" country-code suffix) on its own line below. A
    top-to-bottom text scan has no way to know the first fragment
    belongs to the row whose date hasn't been seen yet; clustering by
    vertical distance to the nearest date does."""
    page = FakePage([
        # previous row, for the pre-date fragment to be tested against a
        # real neighboring row rather than the page's first-row fallback
        w("31/03/2024", 57.4, 314.1), w("LULU", 125.0, 314.1),
        w("Debit", 368.6, 314.1), w("588.00", 468.0, 314.1),
        # this row's own description wraps ABOVE its own date line
        w("SKYROCKET", 125.0, 341.3), w("BEVERAGES", 192.6, 341.3),
        w("30/03/2024", 57.4, 347.3), w("Debit", 368.6, 347.3), w("62.00", 468.0, 347.3),
        w("IN", 125.0, 353.4),  # trailing fragment, below the date line
        # next row, so the wrapped row's upper bound is a true midpoint
        w("29/03/2024", 57.4, 380.5), w("MTR", 125.0, 380.5),
        w("Debit", 368.6, 380.5), w("200.00", 468.0, 380.5),
    ])
    result = parse_transactions([page])
    assert result == [
        ("31/03/2024", "LULU", "-588.00"),
        ("30/03/2024", "SKYROCKET BEVERAGES IN", "-62.00"),
        ("29/03/2024", "MTR", "-200.00"),
    ]


def test_monthly_installments_row_is_excluded_and_does_not_corrupt_neighbors():
    page = FakePage([
        w("23/10/2023", 57.4, 100.0), w("6760.74", 125.0, 100.0),
        w("FP", 165.0, 100.0), w("EMI", 185.0, 100.0),
        w("Monthly", 300.0, 100.0), w("0.00", 468.0, 106.0),
        w("Installments", 125.0, 106.0),
        w("23/10/2023", 57.4, 127.2), w("IGST", 125.0, 127.2),
        w("Debit", 368.6, 127.2), w("15.02", 468.0, 127.2),
    ])
    assert parse_transactions([page]) == [("23/10/2023", "IGST", "-15.02")]


def test_amount_shaped_reference_number_in_description_is_not_mistaken_for_the_amount():
    """A reference number embedded in the description can coincidentally
    look like an amount (digits + a decimal-shaped suffix) — only a word
    comfortably in the right-hand amount column may be trusted as the
    real amount."""
    page = FakePage([
        w("05/07/2025", 57.4, 100.0), w("REF#", 125.0, 100.0),
        w("12,345.67", 160.0, 100.0),  # amount-shaped, but in the description column
        w("Debit", 368.6, 100.0), w("500.00", 468.0, 100.0),
    ])
    assert parse_transactions([page]) == [("05/07/2025", "REF# 12,345.67", "-500.00")]


def test_multiple_pages_combined_in_order():
    page1 = FakePage([
        w("29/06/2025", 57.4, 100.0), w("GURUMURTHY", 125.0, 100.0),
        w("Debit", 368.6, 100.0), w("524.00", 468.0, 100.0),
    ])
    page2 = FakePage([
        w("01/06/2025", 57.4, 100.0), w("SILLY", 125.0, 100.0),
        w("LEMON", 160.0, 100.0), w("Debit", 368.6, 100.0), w("1177.00", 468.0, 100.0),
    ])
    result = parse_transactions([page1, page2])
    assert result == [
        ("29/06/2025", "GURUMURTHY", "-524.00"),
        ("01/06/2025", "SILLY LEMON", "-1177.00"),
    ]


def test_page_with_no_words_is_skipped():
    assert parse_transactions([FakePage([])]) == []


def test_no_dates_on_page_returns_empty():
    page = FakePage([w("Statement", 49.5, 51.0), w("Date:21/04/2021", 49.5, 60.0)])
    assert parse_transactions([page]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Description", "Amount (in Rs.)"]
