from munim_ingest.pdf_extract import extract_rows, open_pdf

from .pdf_fixtures import make_encrypted_pdf


def test_extract_rows_uses_table_when_present(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="pw", table_rows=[
        ["Date", "Description", "Amount"],
        ["2026-06-01", "UPI-SWIGGY8102", "340.00"],
        ["2026-06-02", "AMAZON PAY", "1200.00"],
    ])
    with open_pdf(pdf_path, "pw") as pdf:
        rows = extract_rows(pdf)
    assert rows == [
        ["Date", "Description", "Amount"],
        ["2026-06-01", "UPI-SWIGGY8102", "340.00"],
        ["2026-06-02", "AMAZON PAY", "1200.00"],
    ]


def test_extract_rows_falls_back_to_text_lines_when_no_table(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="pw",
                        plain_text="Statement of Account\nOpening balance 1000.00\nClosing balance 2000.00")
    with open_pdf(pdf_path, "pw") as pdf:
        rows = extract_rows(pdf)
    assert rows == [
        ["Statement of Account"],
        ["Opening balance 1000.00"],
        ["Closing balance 2000.00"],
    ]


def test_extract_rows_no_content_returns_empty_list(tmp_path):
    pdf_path = tmp_path / "statement.pdf"
    make_encrypted_pdf(pdf_path, password="pw", plain_text="")
    with open_pdf(pdf_path, "pw") as pdf:
        rows = extract_rows(pdf)
    assert rows == []
