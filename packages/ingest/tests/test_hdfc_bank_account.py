"""Tests for HDFC savings/current account statement parsing — a
physically different document from either credit-card layout
(hdfc_credit_card.py / hdfc_credit_card_v2.py): a genuine ruled table,
but pdfplumber merges an entire page into one row, with each of Date /
Narration / Withdrawals / Deposits / Closing Balance newline-joined
within its own cell across every transaction on that page.

Fictional data shaped after a real statement (verified 2026-09-01): the
narration for one transaction wraps across a variable number of physical
lines and has no clean delimiter of its own, but every entry reliably
ends with "Value Dt DD/MM/YYYY Ref <refnum>" — used here to segment the
blob back into one narration per transaction. Direction needs no
inference at all (unlike both credit-card formats) since Withdrawals and
Deposits are already separate columns; verified by reconstructing the
running balance from real column data and finding it matched the
statement's own closing balance to the rupee across all 42 real
transactions before writing this module.
"""
from munim_ingest.hdfc_bank_account import (
    HEADER_ROW,
    count_unparseable_pages,
    find_statement_period,
    normalize_hdfc_bank_account_rows,
)


def _mega_row(dates, narrations, withdrawals, deposits, balances):
    return [
        "\n".join(dates), "\n".join(narrations),
        "\n".join(withdrawals), "\n".join(deposits), "\n".join(balances),
    ]


def test_single_withdrawal_becomes_negative_amount():
    row = _mega_row(
        ["01/07/2026"],
        ["UPI-SWIGGY-swiggy@okaxis-SBIN0001-618223321380-food "
         "Value Dt 01/07/2026 Ref 618223321380"],
        ["500.00"], ["0.00"], ["9500.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert result == [["01/07/2026",
                        "UPI-SWIGGY-swiggy@okaxis-SBIN0001-618223321380-food "
                        "Value Dt 01/07/2026 Ref 618223321380", "-500.00"]]


def test_single_deposit_becomes_positive_amount():
    row = _mega_row(
        ["02/07/2026"],
        ["UPI-EMPLOYER-payroll@hdfcbank-HDFC0001-655052472739-salary "
         "Value Dt 02/07/2026 Ref 655052472739"],
        ["0.00"], ["50000.00"], ["59500.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert result[0][2] == "50000.00"


def test_multiple_transactions_in_one_mega_row_align_correctly():
    row = _mega_row(
        ["01/07/2026", "01/07/2026", "02/07/2026"],
        [
            "UPI-A MERCHANT-a@okaxis-SBIN0001-111-food "
            "Value Dt 01/07/2026 Ref 111",
            "UPI-B MERCHANT-b@okaxis-SBIN0002-222-taxi "
            "Value Dt 01/07/2026 Ref 222",
            "IMPS-333-C PERSON-UTIB-xxxxxxxx1234-IMPS "
            "Value Dt 02/07/2026 Ref 333",
        ],
        ["100.00", "200.00", "0.00"],
        ["0.00", "0.00", "1000.00"],
        ["9900.00", "9700.00", "10700.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert len(result) == 3
    assert result[0] == ["01/07/2026",
                          "UPI-A MERCHANT-a@okaxis-SBIN0001-111-food "
                          "Value Dt 01/07/2026 Ref 111", "-100.00"]
    assert result[1][0] == "01/07/2026" and result[1][2] == "-200.00"
    assert result[2][0] == "02/07/2026" and result[2][2] == "1000.00"


def test_ref_number_wrapped_onto_next_line_still_parses():
    """Real extraction artifact: the reference number sometimes wraps to
    the line after 'Ref' instead of staying on the same line — a plain
    'Ref \\S+' (single space) pattern misses this and silently
    mis-segments every narration after it."""
    row = _mega_row(
        ["03/07/2026"],
        ["UPI-TONY PIUS ALAPATT-tony@oksbi-SIBL0001-655052472739-save "
         "Value Dt 03/07/2026 Ref\n655052472739"],
        ["300.00"], ["0.00"], ["9200.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert len(result) == 1
    assert result[0][2] == "-300.00"


def test_narration_whitespace_is_collapsed_to_single_line():
    row = _mega_row(
        ["01/07/2026"],
        ["UPI-INTERNATIONAL\nCOUNCI-body@\nsbi-SBIN0001-111-doctor\n"
         "Value Dt 01/07/2026 Ref 111"],
        ["200.00"], ["0.00"], ["9800.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert "\n" not in result[0][1]
    assert result[0][1] == ("UPI-INTERNATIONAL COUNCI-body@ "
                             "sbi-SBIN0001-111-doctor Value Dt "
                             "01/07/2026 Ref 111")


def test_multiple_mega_rows_all_produce_transactions():
    row1 = _mega_row(["01/07/2026"],
                      ["A Value Dt 01/07/2026 Ref 1"], ["10.00"], ["0.00"], ["90.00"])
    row2 = _mega_row(["02/07/2026"],
                      ["B Value Dt 02/07/2026 Ref 2"], ["0.00"], ["20.00"], ["110.00"])
    result = normalize_hdfc_bank_account_rows([row1, row2])
    assert len(result) == 2
    assert result[0][0] == "01/07/2026"
    assert result[1][0] == "02/07/2026"


def test_narration_with_no_ref_number_still_splits_correctly():
    """Real extraction artifact (found 2026-09-01 comparing against a
    bank-downloaded Excel export of the same month): interest-posting and
    FD-transfer entries ('FD Redeem Interest...', 'FT -: FD A/C NO...',
    'Interest debited till...') end with just 'Value Dt DATE' and no
    trailing 'Ref <number>' at all — a regex that requires Ref failed to
    match these, misaligning the narration-segment count against the
    date count and silently dropping the ENTIRE page (all transactions
    on it, not just the Ref-less ones) via the alignment guard. This was
    the actual root cause of transactions missing from a real account:
    47 of 355 transactions across 9 months, including one very large FD
    redemption, all silently dropped this way with no warning."""
    row = _mega_row(
        ["03/08/2024", "03/08/2024", "04/08/2024"],
        [
            "FD Redeem Interest -50300775239247/2 Value Dt 03/08/2024",
            "FT -: FD A/C NO 50300775239247 Value Dt 03/08/2024",
            "UPI-FAISAL MOHAMMED SHAL-faisal@okicici-ICIC0001-42172 "
            "Value Dt 04/08/2024 Ref 421729191704",
        ],
        ["0.00", "0.00", "0.00"],
        ["1270.00", "600000.00", "2500.00"],
        ["137075.47", "137075.47", "139325.47"])
    result = normalize_hdfc_bank_account_rows([row])
    assert len(result) == 3
    assert result[0][2] == "1270.00"
    assert result[1][2] == "600000.00"
    assert result[1][1] == "FT -: FD A/C NO 50300775239247 Value Dt 03/08/2024"
    assert result[2][2] == "2500.00"


def test_narration_with_ref_number_unaffected_by_no_ref_support():
    """Regression guard: making Ref optional must not cause a normal
    Ref-bearing narration to stop matching early (greedy '?' should still
    consume 'Ref <num>' when it's actually present right after
    'Value Dt DATE')."""
    row = _mega_row(
        ["01/07/2026"],
        ["UPI-SWIGGY-swiggy@okaxis-SBIN0001-618223321380-food "
         "Value Dt 01/07/2026 Ref 618223321380"],
        ["500.00"], ["0.00"], ["9500.00"])
    result = normalize_hdfc_bank_account_rows([row])
    assert result[0][1] == ("UPI-SWIGGY-swiggy@okaxis-SBIN0001-618223321380-food "
                             "Value Dt 01/07/2026 Ref 618223321380")


def test_misaligned_counts_are_skipped_not_guessed():
    """If the narration-segment count doesn't match the date count (an
    unexpected layout variant), the whole mega-row is dropped rather than
    guessing which narration belongs to which date."""
    row = [
        "01/07/2026\n02/07/2026",  # 2 dates
        "Only one narration Value Dt 01/07/2026 Ref 1",  # 1 narration
        "10.00\n20.00", "0.00\n0.00", "90.00\n70.00",
    ]
    result = normalize_hdfc_bank_account_rows([row])
    assert result == []


def test_row_too_short_is_skipped():
    result = normalize_hdfc_bank_account_rows([["01/07/2026", "only two cols"]])
    assert result == []


def test_empty_input_returns_empty():
    assert normalize_hdfc_bank_account_rows([]) == []


def test_header_row_shape():
    assert HEADER_ROW == ["Date", "Narration", "Amount"]


def test_count_unparseable_pages_zero_when_all_pages_align():
    row1 = _mega_row(["01/07/2026"],
                      ["A Value Dt 01/07/2026 Ref 1"], ["10.00"], ["0.00"], ["90.00"])
    row2 = _mega_row(["02/07/2026"],
                      ["B Value Dt 02/07/2026 Ref 2"], ["0.00"], ["20.00"], ["110.00"])
    assert count_unparseable_pages([row1, row2]) == 0


def test_find_statement_period_extracts_from_and_to_dates():
    """Real finding (2026-09-02): a statement's own declared period can
    start partway into its named month rather than on the 1st — one real
    November 2025 statement was "Statement From : 03/11/2025 To
    30/11/2025", silently missing Nov 1-2 from that PDF entirely (not an
    extraction bug — those days genuinely aren't in this statement, they
    belonged to whatever statement covered the days just before). Naively
    assuming one PDF per calendar month gives full coverage caused 2 real
    transactions to go missing until caught by cross-checking a bank
    Excel export. Surfacing the declared period lets this be caught
    immediately instead."""
    text = ("Tony Pius Alapatt\nAccount Number : 50100130659482\n"
            "Statement From : 03/11/2025 To 30/11/2025 Karnataka\n"
            "Currency : INR 560078")
    assert find_statement_period(text) == ("03/11/2025", "30/11/2025")


def test_find_statement_period_calendar_aligned_case():
    text = "Statement From : 01/12/2025 To 31/12/2025 Karnataka"
    assert find_statement_period(text) == ("01/12/2025", "31/12/2025")


def test_find_statement_period_not_found_returns_none():
    assert find_statement_period("no period text here at all") is None


def test_find_statement_period_empty_string_returns_none():
    assert find_statement_period("") is None


def test_count_unparseable_pages_counts_each_misaligned_page():
    good = _mega_row(["01/07/2026"],
                      ["A Value Dt 01/07/2026 Ref 1"], ["10.00"], ["0.00"], ["90.00"])
    bad = [
        "01/07/2026\n02/07/2026",  # 2 dates
        "Only one narration Value Dt 01/07/2026 Ref 1",  # 1 narration
        "10.00\n20.00", "0.00\n0.00", "90.00\n70.00",
    ]
    assert count_unparseable_pages([good, bad, bad]) == 2
