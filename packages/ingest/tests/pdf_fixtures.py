"""Builds small encrypted PDF fixtures for tests. Not a test file itself —
imported by test_pdf_extract.py and test_pdf_rows.py. No real bank PDF is
ever involved; every fixture here is synthetic, generated at test time.
"""
from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle


def make_encrypted_pdf(out_path: Path, password: str,
                        table_rows: list[list[str]] | None = None,
                        plain_text: str | None = None) -> None:
    """Writes an AES-128-encrypted PDF to out_path.

    Pass table_rows for a ruled table (pdfplumber's extract_tables() will
    find it). Pass plain_text (newline-separated lines) for unstructured
    text with no ruled table — this is what exercises the text-line
    fallback path, since extract_tables() finds nothing in it.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    if table_rows is not None:
        table = Table(table_rows)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
        doc.build([table])
    else:
        styles = getSampleStyleSheet()
        paras = [Paragraph(line, styles["Normal"])
                 for line in (plain_text or "").splitlines()]
        doc.build(paras)
    buf.seek(0)

    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=password, algorithm="AES-128")
    with open(out_path, "wb") as f:
        writer.write(f)
