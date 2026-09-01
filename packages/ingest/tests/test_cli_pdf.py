from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from munim_ingest.cli import app
from munim_ingest.pdf_extract import PdfPasswordError

runner = CliRunner()


def _fake_pdf():
    fake = MagicMock()
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)
    return fake


def test_pdf_extract_wrong_password_exits_cleanly_without_leaking_it(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")  # exists=True only checks presence, not validity

    with patch("munim_ingest.cli.getpass.getpass", return_value="hunter2-distinctive-pw"), \
         patch("munim_ingest.cli.open_pdf",
               side_effect=PdfPasswordError("Could not open statement.pdf")):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 1
    assert "hunter2-distinctive-pw" not in result.output
    assert "could not open" in result.output.lower()


def test_pdf_extract_writes_csv_and_prints_next_step(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"

    with patch("munim_ingest.cli.getpass.getpass", return_value="testpw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows",
               return_value=[["Date", "Amount"], ["2026-06-01", "100"]]):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--raw"])

    assert result.exit_code == 0
    assert out_path.exists()
    assert out_path.read_text().splitlines()[0] == "Date,Amount"
    assert "munim import" in result.output
    assert str(out_path) in result.output


def test_pdf_extract_reads_password_from_env_var_first(tmp_path, monkeypatch):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    monkeypatch.setenv("MUNIM_PDF_PASSWORD", "env-password")

    with patch("munim_ingest.cli.getpass.getpass") as mock_getpass, \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()) as mock_open, \
         patch("munim_ingest.cli.extract_rows", return_value=[["01/01/2024"]]):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 0
    mock_getpass.assert_not_called()
    mock_open.assert_called_once_with(pdf_path, "env-password")


def test_pdf_extract_no_rows_found_exits_nonzero(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=[]):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 1


def test_pdf_extract_default_output_path_is_pdf_stem_with_csv_suffix(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=[["01/01/2024"]]):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 0
    assert (tmp_path / "statement.csv").exists()


def test_pdf_extract_write_failure_exits_cleanly_without_leaking_password(tmp_path):
    """Finding 1: write_csv() runs after the try/except in the original
    code, so a write failure (e.g. --out's parent is a regular file, not a
    directory) reached an unhandled traceback instead of a clean error —
    with `password` still a live local in that frame. Reproduce the exact
    repro: point --out's parent at a file."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    not_a_directory = tmp_path / "not_a_directory"
    not_a_directory.write_text("i am a file, not a directory")
    out_path = not_a_directory / "out.csv"

    with patch("munim_ingest.cli.getpass.getpass", return_value="hunter2-distinctive-pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=[["01/01/2024", "100"]]):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path), "--out", str(out_path)])

    assert result.exit_code == 1
    # No unhandled traceback: Click/Typer's CliRunner captures an
    # unexpected exception in result.exception rather than propagating it,
    # so assert directly that nothing but a clean typer.Exit(1) (raised as
    # SystemExit) escaped, and that no traceback text or the password
    # leaked into the rendered output.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert "hunter2-distinctive-pw" not in result.output


def test_pdf_extract_overwrites_existing_output_with_warning(tmp_path):
    """Finding 5: write_csv silently overwrites an existing output file.
    A second run must warn visibly before clobbering it."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    out_path.write_text("stale,content\n")

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows",
               return_value=[["Date", "Amount"], ["01/01/2024", "100"]]):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--raw"])

    assert result.exit_code == 0
    assert "overwriting" in result.output.lower()
    assert str(out_path) in result.output
    assert out_path.read_text().splitlines()[0] == "Date,Amount"
    assert "stale" not in out_path.read_text()


def test_pdf_extract_filters_by_default_and_reports_counts(tmp_path):
    """Real-world extraction mixes genuine transaction rows with
    page-header/summary noise pdfplumber also detects as table rows — the
    default behavior must filter down to transaction-shaped rows and tell
    the user how many were kept vs dropped."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [
        ["Statement Title Noise"],  # 1-col header — different shape, dropped
        ["01/01/2024", "GROCERY STORE", "100.00"],
        ["02/01/2024", "COFFEE SHOP", "5.50"],
    ]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path), "--out", str(out_path)])

    assert result.exit_code == 0, result.output
    assert "kept 2" in result.output.lower()
    assert "filtered out 1" in result.output.lower()
    lines = out_path.read_text().splitlines()
    assert len(lines) == 3  # generic header + 2 kept transaction rows
    assert lines[0] == "Column 1,Column 2,Column 3"
    assert "Statement Title Noise" not in out_path.read_text()


def test_pdf_extract_raw_flag_skips_filtering(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [
        ["Statement Title Noise"],
        ["01/01/2024", "GROCERY STORE", "100.00"],
    ]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--raw"])

    assert result.exit_code == 0, result.output
    assert "kept" not in result.output.lower()
    lines = out_path.read_text().splitlines()
    assert len(lines) == 2
    assert "Statement Title Noise" in out_path.read_text()


def test_pdf_extract_zero_kept_after_filter_exits_cleanly(tmp_path):
    """If nothing in the extraction looks like a transaction (e.g. a
    layout the filter doesn't fit), fail loudly and suggest --raw rather
    than silently writing an empty CSV."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    raw_rows = [["Statement Title Noise"], ["Another header line"]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 1
    assert "--raw" in result.output


def test_pdf_extract_prepends_generic_header_by_default(tmp_path):
    """munim import's column wizard treats row 1 as a header — the
    filtered output has no header row (it was itself filtered out as
    non-transaction noise), so one must be added or the wizard would
    silently treat the first real transaction as the header."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["01/01/2024", "STORE", "100.00"]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path), "--out", str(out_path)])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Column 1,Column 2,Column 3"
    assert lines[1] == "01/01/2024,STORE,100.00"


def test_pdf_extract_raw_does_not_add_a_header(tmp_path):
    """--raw is an inspect-the-raw-extraction escape hatch — row widths
    may not even be uniform, so no header is fabricated."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["Some Header Text"], ["01/01/2024", "STORE", "100.00"]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--raw"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Some Header Text"
    assert lines[1] == "01/01/2024,STORE,100.00"


def test_pdf_extract_bank_hdfc_uses_real_header_labels(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["01/01/2024", "GROCERY STORE", None, "100.00", None]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Date,Transaction Description,Feature Reward Points,Amount (in Rs.),"
    assert lines[1] == "01/01/2024,GROCERY STORE,,-100.00,"


def test_pdf_extract_bank_hdfc_falls_back_to_generic_header_on_unexpected_width(tmp_path):
    """If a real HDFC statement ever yields a width other than 5 (a
    layout variant), fall back to the generic numbered header rather
    than mislabel columns with the wrong semantic names."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["01/01/2024", "STORE", "100.00"]]  # 3 columns, not HDFC's 5

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Column 1,Column 2,Column 3"


def test_pdf_extract_bank_hdfc_normalizes_amounts(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [
        ["01/01/2024", "GROCERY STORE", None, "100.00", None],
        ["02/01/2024", "REFUND", None, "50.00Cr", None],
    ]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    assert "hdfc normalization" in result.output.lower()
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Date,Transaction Description,Feature Reward Points,Amount (in Rs.),"
    assert lines[1].endswith(",-100.00,")
    assert lines[2].endswith(",50.00,")


def test_pdf_extract_bank_hdfc_strips_time_component_from_dates(tmp_path):
    """munim's date parser can't handle a time component — the exact
    crash that would have hit `munim import` on a real HDFC statement
    before this normalization existed."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["21/01/2024 12:55:34", "GROFERS INDIA", None, "379.00", None]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[1].startswith("21/01/2024,")
    assert "12:55:34" not in lines[1]


def test_pdf_extract_bank_hdfc_auto_detects_newer_layout(tmp_path):
    """The newer HDFC template (post card-upgrade, same account) never
    forms a ruled table — filter_transaction_rows keeps single-column
    lines instead of the older 5-column shape. --bank hdfc must detect
    this from row shape and dispatch to the v2 parser automatically,
    without the user needing a different flag."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [
        ["21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l"],
        ["10/11/2025| 07:11 AUTOPAY THANK YOU (Ref# X) + C 45,248.00 l"],
    ]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Date,Transaction Description,Amount (in Rs.)"
    assert lines[1] == "21/10/2025,NETFLIX DI SIMUMBAI,-649.00"
    assert lines[2] == "10/11/2025,AUTOPAY THANK YOU (Ref# X),45248.00"


def test_pdf_extract_bank_hdfc_v2_message_describes_structural_detection(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l"]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    assert "newer" in result.output.lower()
    # Must not claim the OLD format's convention was applied.
    assert "positive-magnitude" not in result.output.lower()


def test_pdf_extract_bank_hdfc_v2_drops_unparseable_rows_silently_from_output(tmp_path):
    """Rows filter_transaction_rows kept (date-shaped first cell) but that
    still don't match the full transaction-line pattern must not corrupt
    the uniform 3-column output — they're dropped, not left malformed."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [
        ["21/10/2025| 08:30 NETFLIX DI SIMUMBAI C 649.00 l"],
        ["21/10/2025 this looks date-shaped but has no real transaction body"],
    ]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path), "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert len(lines) == 2  # header + the one real transaction only


def test_pdf_extract_bank_hdfc_bank_explodes_mega_rows(tmp_path):
    """--bank hdfc-bank explodes a page's merged multi-transaction row
    (Date/Narration/Withdrawals/Deposits each newline-joined within one
    cell) back into one row per real transaction, with its own header
    and no direction-inference message (unlike --bank hdfc)."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [[
        "01/07/2026\n02/07/2026",
        "UPI-A MERCHANT-a@okaxis-SBIN0001-111-food Value Dt 01/07/2026 Ref 111\n"
        "UPI-B MERCHANT-b@okaxis-SBIN0002-222-taxi Value Dt 02/07/2026 Ref 222",
        "100.00\n0.00",
        "0.00\n500.00",
        "900.00\n1400.00",
    ]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path),
                  "--bank", "hdfc-bank"])

    assert result.exit_code == 0, result.output
    assert "direction is inferred" not in result.output.lower()
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Date,Narration,Amount"
    assert len(lines) == 3
    assert lines[1].startswith("01/07/2026,") and lines[1].endswith(",-100.00")
    assert lines[2].startswith("02/07/2026,") and lines[2].endswith(",500.00")


def test_pdf_extract_bank_hdfc_bank_warns_about_unparseable_pages(tmp_path):
    """A version of hdfc_bank_account's parser once dropped a whole page
    silently on any narration-alignment failure, with no way for the
    user to notice — 47 real transactions across 9 months were lost this
    way (including one large FD redemption) before it was caught. The
    CLI must warn loudly whenever this happens, not just report the
    (now-smaller) transaction count."""
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [[
        "01/07/2026\n02/07/2026",  # 2 dates
        "Only one narration Value Dt 01/07/2026 Ref 1",  # 1 narration segment
        "10.00\n20.00", "0.00\n0.00", "90.00\n70.00",
    ]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path),
                  "--bank", "hdfc-bank"])

    assert "1 page(s) could not be parsed" in result.output
    assert "parser fix, not a retry" in result.output.lower()


def test_pdf_extract_unknown_bank_exits_cleanly(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    result = runner.invoke(app, ["pdf", "extract", str(pdf_path), "--bank", "not_a_real_bank"])

    assert result.exit_code == 1
    assert "unknown --bank" in result.output.lower()


def test_pdf_extract_bank_ignored_with_raw(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    out_path = tmp_path / "out.csv"
    raw_rows = [["01/01/2024", "X", None, "100.00", None]]

    with patch("munim_ingest.cli.getpass.getpass", return_value="pw"), \
         patch("munim_ingest.cli.open_pdf", return_value=_fake_pdf()), \
         patch("munim_ingest.cli.extract_rows", return_value=raw_rows):
        result = runner.invoke(
            app, ["pdf", "extract", str(pdf_path), "--out", str(out_path),
                  "--raw", "--bank", "hdfc"])

    assert result.exit_code == 0, result.output
    assert "skipped" in result.output.lower()
    # Amount left as the raw "100.00", not normalized to "-100.00".
    assert out_path.read_text().splitlines()[0].endswith(",100.00,")
