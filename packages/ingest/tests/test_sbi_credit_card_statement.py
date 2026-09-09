"""Tests for SBI Card's monthly e-statement PDF (the "Your SBI CARD ELITE
Monthly Statement" / "Your AURUM Card Monthly Statement" email attachment)
— a different document from the netbanking "Transaction History" export
that sbi_credit_card.py handles. Its transaction table renders as a
single ruled table via pdfplumber, but that table's own cell text is
column-major (all dates newline-joined in one cell, all descriptions in
the next, all amounts in the last) and NOT reliably index-aligned across
those three cells: a "TRANSACTIONS FOR <name>" section-divider line is
injected into the description cell's newline-joined text with no
corresponding entry in either the date or amount cell, silently shifting
every later row by one if the three cells were naively zipped by line
index. This module sidesteps that by reading each page's plain
extract_text() output instead and matching one transaction per physical
text line — confirmed across all 15 real statements spanning Jun 2025 to
Aug 2026 (2-33 transactions each) that every transaction is fully
self-contained on its own line (date, full description, amount, and
Credit/Debit letter all together), with no wrapped continuations.

Verified against those same 15 real statements: this module's total
transaction count per statement, and the sum of its parsed amounts,
matched each statement's own printed "ACCOUNT SUMMARY" totals.

Dates come out normalized to "DD/MM/YYYY" (not the statement's own
"DD Mon YY") so this format's CSV output matches sbi_credit_card.py's
date shape and both bank flags can share one csv_profile.
"""
from munim_ingest.sbi_credit_card_statement import HEADER_ROW, parse_transactions


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


def test_simple_debit_line():
    page = FakePage("23 May 25 NEW HAPPY BAR AND REST BANGALORE IN 1,000.00 D")
    assert parse_transactions([page]) == [("23/05/2025", "NEW HAPPY BAR AND REST BANGALORE IN", "-1000.00")]


def test_simple_credit_line_payment_received():
    page = FakePage("11 Jun 25 PAYMENT RECEIVED 000DP015162082316HAsesB 31,303.00 C")
    assert parse_transactions([page]) == [
        ("11/06/2025", "PAYMENT RECEIVED 000DP015162082316HAsesB", "31303.00")
    ]


def test_pay_in_emis_suffix_is_stripped():
    """This e-statement format annotates a transaction converted to EMI
    with a trailing "(Pay in EMIs)" that the netbanking "Transaction
    History" export (sbi_credit_card.py) never carries for the same real
    transaction. Left in, it silently defeats munim's content-hash dedup
    across the two formats' ~1-month overlap — confirmed as a real bug:
    three real transactions (Fame Diagnostic, Favourite Shop, and a
    payment for a family birthday party at Joys Palace) were double-
    counted for ₹21,905 total the first time this format was imported,
    because only the e-statement's copy of each carried this suffix."""
    page = FakePage("31 May 25 Fame Diagnostic & BANGALORE IN (Pay in EMIs) 3,400.00 D")
    assert parse_transactions([page]) == [
        ("31/05/2025", "Fame Diagnostic & BANGALORE IN", "-3400.00")
    ]


def test_non_transaction_lines_are_skipped():
    text = "\n".join([
        "Date Transaction Details Amount ( ` )",
        "for Statement Period: 24 May 25 to 23 Jun 25",
        "TRANSACTIONS FOR TONY ALAPATT",
        "Statement Date 23 Jun 2025",
        "23 May 25 NEW HAPPY BAR AND REST BANGALORE IN 1,000.00 D",
    ])
    page = FakePage(text)
    assert parse_transactions([page]) == [("23/05/2025", "NEW HAPPY BAR AND REST BANGALORE IN", "-1000.00")]


def test_multiple_pages_combined_in_order():
    page1 = FakePage("23 May 25 NEW HAPPY BAR AND REST BANGALORE IN 1,000.00 D")
    page2 = FakePage("24 May 25 M S THEOBROMA FOODS PV BENGALURU IN 1,834.90 D")
    result = parse_transactions([page1, page2])
    assert result == [
        ("23/05/2025", "NEW HAPPY BAR AND REST BANGALORE IN", "-1000.00"),
        ("24/05/2025", "M S THEOBROMA FOODS PV BENGALURU IN", "-1834.90"),
    ]


def test_dateless_tax_line_immediately_after_a_transaction_inherits_its_date():
    """A real gap found in one of 15 statements: an annual-fee charge's
    GST is billed as its own separate Debit line directly below it, but
    that GST line carries no date of its own — only the fee line above it
    does. Silently dropping it (because it never matches the dated-line
    pattern) would lose real money from the ledger; this line's amount
    (1,799.82) does not appear anywhere else in that statement."""
    text = "\n".join([
        "23 Dec 25 ANNUAL FEE CHARGED (EXCL TAX 1799.82) 9,999.00 D",
        "IGST DB @ 18.00% 1,799.82 D",
    ])
    page = FakePage(text)
    assert parse_transactions([page]) == [
        ("23/12/2025", "ANNUAL FEE CHARGED (EXCL TAX 1799.82)", "-9999.00"),
        ("23/12/2025", "IGST DB @ 18.00%", "-1799.82"),
    ]


def test_dateless_line_not_immediately_after_a_transaction_is_ignored():
    """A continuation line only ever attaches to the transaction line
    directly above it — an unrelated line elsewhere that happens to end
    in an amount+C/D shape must not be misattributed to an unrelated
    earlier date."""
    text = "\n".join([
        "23 Dec 25 ANNUAL FEE CHARGED 9,999.00 D",
        "Some unrelated boilerplate paragraph line.",
        "Stray amount-shaped line 1,799.82 D",
    ])
    page = FakePage(text)
    assert parse_transactions([page]) == [("23/12/2025", "ANNUAL FEE CHARGED", "-9999.00")]


def test_page_with_no_text_is_skipped():
    assert parse_transactions([FakePage(None)]) == []
    assert parse_transactions([FakePage("")]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Description", "Amount (in Rs.)"]
