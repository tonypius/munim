"""Tests for the newer HDFC credit-card statement layout (~Sep 2025
onward, after a card-number upgrade on the same account) — a physically
different template from the one hdfc_credit_card.py handles: no ruled
transaction table at all, so every transaction arrives as its own
single-column line via the generic text-line fallback, shaped
"DD/MM/YYYY| HH:MM DESCRIPTION [REWARDS] [+] C AMOUNT l".

Fictional data shaped after real patterns confirmed against four actual
statements (Sep 2025, Nov 2025, Jan 2026, Jun 2026) — never the user's
real financial data. In particular the per-statement computed debit/credit
sums exactly matched each statement's own header totals, and two
independent real refunds (different months, different merchants) both
showed the same signature: a negative reward-points reversal matching the
original purchase's points, plus a bare "+" direction marker.
"""
from munim_ingest.hdfc_credit_card_v2 import (
    HEADER_ROW,
    normalize_hdfc_v2_rows,
    parse_transaction_line,
)


def test_plain_debit_no_rewards():
    result = parse_transaction_line("21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l")
    assert result == ("21/10/2025", "NETFLIX DI SIMUMBAI", "-649.00")


def test_debit_with_reward_points_earned():
    result = parse_transaction_line("23/08/2025| 00:04 ZOMATONEW DELHI + 12 C 540.44 l")
    assert result == ("23/08/2025", "ZOMATONEW DELHI", "-540.44")


def test_bill_payment_is_credit_via_bare_plus_marker():
    """A bill payment shows a bare '+' (no attached number) immediately
    before 'C <amount> l' — distinct from the reward-points '+N'
    annotation that appears right after the description on ordinary
    purchases."""
    result = parse_transaction_line(
        "10/11/2025| 07:11 AUTOPAY THANK YOU (Ref# ST253150083000010201921) + C 45,248.00 l")
    assert result == ("10/11/2025", "AUTOPAY THANK YOU (Ref# ST253150083000010201921)", "45248.00")


def test_manual_payment_description_also_recognized_as_credit():
    """A different description pattern (manual/BillDesk payment rather
    than autopay) carries the exact same bare-'+' marker — the direction
    signal is structural, not tied to specific wording."""
    result = parse_transaction_line(
        "09/09/2025| 12:36 BPPY CC PAYMENT DP015252123605JpxUT "
        "(Ref# ST252530083000010198352) + C 1,10,234.00 l")
    assert result == (
        "09/09/2025", "BPPY CC PAYMENT DP015252123605JpxUT (Ref# ST252530083000010198352)",
        "110234.00")


def test_refund_is_credit_via_negative_reward_reversal_plus_bare_plus():
    """A refund shows a negative reward-points reversal (mirroring what
    was earned on the original purchase) immediately followed by the same
    bare '+' direction marker seen on bill payments."""
    result = parse_transaction_line(
        "06/11/2025| 00:00 WASTELAND ENTERTAINMGURGAON - 12 + C 521.51 l")
    assert result == ("06/11/2025", "WASTELAND ENTERTAINMGURGAON", "521.51")


def test_debit_amount_with_lakh_comma_grouping():
    result = parse_transaction_line("26/10/2025| 21:20 EMI AMBER MEGASTOREBENGALURU C 3,143.00 l")
    assert result == ("26/10/2025", "EMI AMBER MEGASTOREBENGALURU", "-3143.00")


def test_leading_name_text_before_date_is_ignored():
    """A page-header name sometimes lands on the same extracted cell as
    the next transaction line, separated by an embedded newline."""
    result = parse_transaction_line(
        "RAMESH KUMAR\n21/08/2025| 09:28 NETFLIX DI SIMUMBAI C 649.00 l")
    assert result == ("21/08/2025", "NETFLIX DI SIMUMBAI", "-649.00")


def test_foreign_currency_row_ignores_the_foreign_amount():
    """Only the trailing 'C <amount> l' (the INR-converted amount) is the
    real amount column — a preceding foreign-currency figure (e.g. USD)
    must not be picked up instead."""
    result = parse_transaction_line(
        "01/11/2025 | 09:17 DIGITALOCEAN.COMAMSTERDAM USD 9.92 + 20 C 881.21 l")
    assert result == ("01/11/2025", "DIGITALOCEAN.COMAMSTERDAM USD 9.92", "-881.21")


def test_scrambled_multiline_row_still_extracts_date_and_amount():
    """A real extraction artifact: when a reference number wraps to a new
    visual line, pdfplumber can interleave it around the date/time/amount
    rather than after the full description. The date/amount/direction
    must still parse correctly even though the description is degraded."""
    result = parse_transaction_line(
        "IGST-VPS2714254487596-RATE 18.0 -32 (Ref#\n"
        "21/05/2026| 00:00 C 35.82 l\n"
        "09999999980521000367421)")
    assert result[0] == "21/05/2026"
    assert result[2] == "-35.82"


def test_no_transaction_pattern_returns_none():
    assert parse_transaction_line("DATE & TIME TRANSACTION DESCRIPTION REWARDS AMOUNT PI") is None


def test_empty_string_returns_none():
    assert parse_transaction_line("") is None


def test_normalize_rows_produces_three_column_shape_with_header():
    rows = [
        ["21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l"],
        ["10/11/2025| 07:11 AUTOPAY THANK YOU (Ref# X) + C 45,248.00 l"],
    ]
    result = normalize_hdfc_v2_rows(rows)
    assert result == [
        ["21/10/2025", "NETFLIX DI SIMUMBAI", "-649.00"],
        ["10/11/2025", "AUTOPAY THANK YOU (Ref# X)", "45248.00"],
    ]
    assert HEADER_ROW == ["Date", "Transaction Description", "Amount (in Rs.)"]


def test_normalize_rows_drops_unparseable_rows_rather_than_guess():
    """This normalizer reshapes row width (1 column in, 3 out) — unlike
    the older format's column-preserving normalizer, an unparsed row can't
    be left as-is without breaking CSV column-count uniformity for every
    other row, so it's dropped instead of guessed at."""
    rows = [
        ["21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l"],
        ["Some noise line with no transaction shape"],
        [None],
        [],
    ]
    result = normalize_hdfc_v2_rows(rows)
    assert result == [["21/10/2025", "NETFLIX DI SIMUMBAI", "-649.00"]]


def test_normalize_rows_empty_input_returns_empty():
    assert normalize_hdfc_v2_rows([]) == []


def test_computed_sums_match_real_statement_header_totals():
    """Regression pin for the exact-sum verification done against four
    real statements before this module was written — every one of the
    fictional rows below mirrors a real line, and the credit/debit split
    below sums to the same figures the real Nov 2025 statement header
    reported (C45,769.51 credits / a subset of C69,838.77 debits)."""
    rows = [
        ["27/10/2025| 14:50 WASTELAND ENTERTAINMGURGAON + 12 C 521.51 l"],  # original purchase
        ["06/11/2025| 00:00 WASTELAND ENTERTAINMGURGAON - 12 + C 521.51 l"],  # its refund
        ["10/11/2025| 07:11 AUTOPAY THANK YOU (Ref# X) + C 45,248.00 l"],  # bill payment
    ]
    result = normalize_hdfc_v2_rows(rows)
    credit_total = sum(float(r[2]) for r in result if float(r[2]) > 0)
    assert round(credit_total, 2) == 45769.51
