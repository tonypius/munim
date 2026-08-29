import pytest

from munim_ingest.pdf_extract import PdfPasswordError, open_pdf

from .pdf_fixtures import make_encrypted_pdf


def test_open_pdf_correct_password_succeeds(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="testpw123",
                        table_rows=[["Date", "Amount"], ["2026-06-01", "100"]])
    with open_pdf(pdf_path, "testpw123") as pdf:
        assert len(pdf.pages) == 1


def test_open_pdf_wrong_password_raises_clear_error(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="testpw123",
                        table_rows=[["Date", "Amount"], ["2026-06-01", "100"]])
    with pytest.raises(PdfPasswordError):
        open_pdf(pdf_path, "wrongpassword")
