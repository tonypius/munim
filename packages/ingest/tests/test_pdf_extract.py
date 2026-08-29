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


def test_open_pdf_wrong_password_error_message_has_no_dangling_empty_reason(tmp_path):
    """Finding 3: pdfplumber's underlying exception for a wrong password
    typically has an empty str(), which left the message with a dangling
    colon and no actual reason shown ("...decrypt: "). The message must
    always end with something informative."""
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="testpw123",
                        table_rows=[["Date", "Amount"], ["2026-06-01", "100"]])
    with pytest.raises(PdfPasswordError) as exc_info:
        open_pdf(pdf_path, "wrongpassword")

    message = str(exc_info.value)
    assert not message.rstrip().endswith(":")
    # pdfplumber's underlying exception for a wrong password has an empty
    # str() (verified: PdfminerException(PDFPasswordIncorrect()) -> ""),
    # so the fallback reason must be substituted in.
    assert "incorrect password" in message.lower()
