from unittest.mock import patch

from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def _mock_parser(return_value=None, side_effect=None):
    """EXCEL_PARSERS binds the parser function by reference at module
    import time — patching the attribute on hdfc_bank_account_excel
    afterward doesn't reach the already-bound reference inside the dict,
    so the dict entry itself must be replaced instead."""
    fn = (lambda path: (_ for _ in ()).throw(side_effect)) if side_effect \
        else (lambda path: return_value)
    return patch.dict("munim_ingest.cli.EXCEL_PARSERS", {"hdfc-bank": fn})


def test_excel_extract_writes_csv_and_prints_next_step(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")
    out_path = tmp_path / "out.csv"

    with _mock_parser(return_value=[["01/04/23", "SOME NARRATION", "-100.00"]]):
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--out", str(out_path),
                  "--bank", "hdfc-bank"])

    assert result.exit_code == 0, result.output
    lines = out_path.read_text().splitlines()
    assert lines[0] == "Date,Narration,Amount"
    assert lines[1] == "01/04/23,SOME NARRATION,-100.00"
    assert "munim import" in result.output
    assert str(out_path) in result.output


def test_excel_extract_no_password_prompt(tmp_path):
    """Unlike `pdf extract`, HDFC's own website Excel export isn't
    encrypted — no password should ever be requested."""
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")

    with _mock_parser(return_value=[["01/04/23", "X", "10.00"]]), \
         patch("munim_ingest.cli.getpass.getpass") as mock_getpass:
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--bank", "hdfc-bank"])

    assert result.exit_code == 0, result.output
    mock_getpass.assert_not_called()


def test_excel_extract_no_rows_found_exits_nonzero(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")

    with _mock_parser(return_value=[]):
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--bank", "hdfc-bank"])

    assert result.exit_code == 1


def test_excel_extract_unknown_bank_exits_cleanly(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")

    result = runner.invoke(
        app, ["excel", "extract", str(file_path), "--bank", "not_a_real_bank"])

    assert result.exit_code == 1
    assert "unknown --bank" in result.output.lower()


def test_excel_extract_parse_error_exits_cleanly(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")

    with _mock_parser(side_effect=ValueError("Unsupported spreadsheet format")):
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--bank", "hdfc-bank"])

    assert result.exit_code == 1
    assert "unsupported spreadsheet format" in result.output.lower()


def test_excel_extract_default_output_path_is_stem_with_csv_suffix(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")

    with _mock_parser(return_value=[["01/04/23", "X", "10.00"]]):
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--bank", "hdfc-bank"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "statement.csv").exists()


def test_excel_extract_overwrites_existing_output_with_warning(tmp_path):
    file_path = tmp_path / "statement.xls"
    file_path.write_bytes(b"fake-xls-bytes")
    out_path = tmp_path / "out.csv"
    out_path.write_text("stale,content\n")

    with _mock_parser(return_value=[["01/04/23", "X", "10.00"]]):
        result = runner.invoke(
            app, ["excel", "extract", str(file_path), "--out", str(out_path),
                  "--bank", "hdfc-bank"])

    assert result.exit_code == 0, result.output
    assert "overwriting" in result.output.lower()
    assert "stale" not in out_path.read_text()
