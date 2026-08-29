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
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path), "--out", str(out_path)])

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
         patch("munim_ingest.cli.extract_rows", return_value=[["a"]]):
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
         patch("munim_ingest.cli.extract_rows", return_value=[["a"]]):
        result = runner.invoke(app, ["pdf", "extract", str(pdf_path)])

    assert result.exit_code == 0
    assert (tmp_path / "statement.csv").exists()
