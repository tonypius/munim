# PDF Statement Extraction (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `munim-ingest pdf extract <file.pdf>` — decrypts a password-protected bank statement PDF and extracts its rows into a CSV file, so the user can run `munim import <output.csv>` (the existing, already-tested classify-package command) to map columns via its interactive wizard and classify normally.

**Architecture:** This plan deliberately does **not** build per-bank PDF layout parsers. Nobody implementing this plan has a real HDFC/SBI/SIB statement PDF to build or verify a column parser against — fabricating one would produce false confidence about numbers that matter (real transaction amounts). Instead: `pdfplumber` extracts rows generically (ruled tables where it finds them, one-row-per-text-line as a fallback where it doesn't), and the well-tested CSV-import wizard already in `packages/classify` handles column mapping from there, exactly as it would for a CSV exported directly from a bank's website. This keeps `packages/ingest` and `packages/classify` decoupled (a file handoff — a CSV on disk — not a shared import), matching the existing architecture.

**Tech Stack:** `pdfplumber` (runtime — its `password=` argument decrypts RC4/AES-128-encrypted PDFs natively via `pdfminer.six`, no separate decryption library needed), `pypdf` + `reportlab` (dev-only, to generate small encrypted PDF fixtures for tests — no real bank PDF ever touches this repo).

## Global Constraints

- **Never persist the PDF password to disk.** Read from the `MUNIM_PDF_PASSWORD` environment variable if set, otherwise prompt with `getpass.getpass()` — the exact pattern Phase 1 already established for the Gmail app password.
- **Bake in Phase 1's hard-won lessons from the start, don't wait for another review cycle to catch them:** every new `typer.Typer(...)` sub-app in this plan must set `pretty_exceptions_show_locals=False` explicitly (an unhandled exception must never render a locals table containing the password); every `console.print` that interpolates PDF-derived content (extracted text, filenames, error messages that might embed PDF content) must use `rich.markup.escape(...)` on that content, since Phase 1's final review found this exact class of bug (attacker/malformed-input content breaking or spoofing Rich markup) twice.
- **No per-bank column-layout parsing.** Extraction is generic: try `page.extract_tables()` on every page; if no page yields any table across the whole document, fall back to one CSV row per line of `page.extract_text()`. Do not attempt to guess column boundaries, delimiters, or which columns are date/amount/description — that's exactly the judgment call the existing CSV-import wizard already handles well, and duplicating it here with unverified guesses would be worse than not doing it at all.
- **Extraction reliability against real bank statement layouts is explicitly unverified by this plan's automated tests.** Every test in this plan uses a synthetic PDF built with `reportlab`+`pypdf` inside the test itself — no real bank PDF exists anywhere in this repo or its history. The manual verification section at the end of this plan is not optional decoration; it's where this actually gets tested against reality, by the human, with their own real statement PDF and real password.
- Output is a **CSV file on disk**, not the canonical JSONL contract (`ingest`→`classify` JSONL boundary documented in `docs/phases.md`) — this phase's output feeds `munim import`, which already knows how to turn an arbitrary CSV into that contract via its interactive column wizard. Don't treat the absence of direct JSONL output as a gap; it's the deliberate design choice from this plan's brainstorming.
- Multi-page PDFs: rows from every page are concatenated in order, with **no deduplication of repeated header rows** (many bank statements repeat a header row on every page). This is a known, documented limitation to watch for during manual verification — don't silently "fix" it with a guessed heuristic (e.g. "drop any row identical to row 0") without real data to confirm it's safe; a heuristic like that could just as easily drop a real transaction that happens to match.
- `packages/classify/` must remain completely untouched by this entire plan.
- Console script: extends the existing `munim-ingest` CLI (already installed, from Phase 1) with a new `pdf` subcommand group — `munim-ingest pdf extract`. Does not create a new package or console script.

---

### Task 1: PDF decrypt/open wrapper, plus a shared encrypted-PDF test fixture helper

**Files:**
- Create: `packages/ingest/munim_ingest/pdf_extract.py`
- Create: `packages/ingest/tests/pdf_fixtures.py` (a plain helper module, not itself a test file — Task 2 also imports from it)
- Create: `packages/ingest/tests/test_pdf_extract.py`
- Modify: `packages/ingest/pyproject.toml` (add `pdfplumber` to `dependencies`, add `pypdf` and `reportlab` to the `dev` extra)

**Interfaces:**
- Consumes: nothing from Phase 1 (this is new, independent functionality within the same package).
- Produces: `PdfPasswordError` exception, `open_pdf(path: Path, password: str) -> pdfplumber.PDF` (a context manager — callers use `with open_pdf(path, password) as pdf:`), and `make_encrypted_pdf(out_path: Path, password: str, table_rows: list[list[str]] | None = None, plain_text: str | None = None) -> None` in the test helper — Task 2's tests and Task 1's own tests both call `make_encrypted_pdf`; Task 4's CLI wiring imports `open_pdf` and `PdfPasswordError` from this module.

**Verified before writing this brief:** every piece of code below was run for real in a scratch venv (`pdfplumber`, `pypdf`, `reportlab` installed) — a wrong password raises `PdfminerException` (a subclass path this task wraps into `PdfPasswordError`) **eagerly at the `pdfplumber.open()` call itself**, not lazily on first page access, and this happens whether or not you're inside a `with` block. The `make_encrypted_pdf` fixture helper's table-rows path and plain-text path were both built and round-tripped through `pdfplumber.open(..., password=...)` — `extract_tables()` found the ruled table exactly, and `extract_text()` returned the plain-text lines with line breaks intact.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/pdf_fixtures.py`:

```python
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
```

`packages/ingest/tests/test_pdf_extract.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_pdf_extract.py -v` (from repo root, after Step 2 has NOT yet added the dependencies — expect this to fail with `ModuleNotFoundError: No module named 'pdfplumber'` or similar, since neither `pdf_extract.py` nor the new dependencies exist yet)

Expected: import error, not an assertion failure — confirming the module genuinely doesn't exist yet.

- [ ] **Step 3: Add the new dependencies to `packages/ingest/pyproject.toml`**

Change the `dependencies` list to add `pdfplumber`:

```toml
dependencies = [
  # 0.16 is the oldest release verified to work here: earlier typer
  # (through 0.15.x) breaks against click >= 8.2 with
  # "TyperArgument.make_metavar() takes 1 positional argument but 2 were
  # given", which makes even `gmail fetch --help` fail.
  "typer>=0.16",
  "rich>=13.0",
  "pyyaml>=6.0",
  "pdfplumber>=0.11",
]
```

Change the `dev` extra to add `pypdf` and `reportlab`:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "pypdf>=4.0", "reportlab>=4.0"]
```

- [ ] **Step 4: Sync the workspace**

Run: `uv sync --all-extras` (from repo root)
Expected: resolves and installs `pdfplumber`, `pypdf`, `reportlab` and their own dependencies without conflict.

- [ ] **Step 5: Write `packages/ingest/munim_ingest/pdf_extract.py`**

```python
"""Stage: decrypt and open a password-protected bank statement PDF.

pdfplumber (via pdfminer.six) decrypts standard RC4/AES-128 PDF encryption
natively through its `password=` argument — no separate decryption library
is needed for that case. AES-256-encrypted PDFs are a known gap: if a real
statement uses it, pdfplumber will raise here just like a wrong password
would, and that's indistinguishable from this module's point of view. If
that turns out to matter for a real bank, it needs a follow-up, not a
guess made now.
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber


class PdfPasswordError(Exception):
    """Raised when a PDF can't be opened with the given password — either
    the password is wrong, or the file isn't a PDF pdfplumber can decrypt
    (e.g. AES-256 encryption, or a corrupt/non-PDF file)."""


def open_pdf(path: Path, password: str) -> pdfplumber.PDF:
    try:
        return pdfplumber.open(path, password=password)
    except Exception as e:
        raise PdfPasswordError(
            f"Could not open {path.name} — check the password, or this "
            f"may not be a PDF pdfplumber can decrypt: {e}") from e
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_pdf_extract.py -v`
Expected: `2 passed`

- [ ] **Step 7: Confirm the rest of the ingest suite and classify are untouched**

Run: `uv run --package munim-ingest pytest packages/ingest/tests -q` — expected `49 passed` (47 from Phase 1 + 2 new)
Run: `uv run --package munim pytest packages/classify/tests -q` — expected `15 passed`

- [ ] **Step 8: Commit**

```bash
git add packages/ingest/pyproject.toml packages/ingest/munim_ingest/pdf_extract.py packages/ingest/tests/pdf_fixtures.py packages/ingest/tests/test_pdf_extract.py
git commit -m "Add PDF decrypt/open wrapper and a synthetic-PDF test fixture helper"
```

---

### Task 2: Row extraction — ruled tables first, text-line fallback otherwise

**Files:**
- Modify: `packages/ingest/munim_ingest/pdf_extract.py` (add `extract_rows`)
- Create: `packages/ingest/tests/test_pdf_rows.py`

**Interfaces:**
- Consumes: `open_pdf` (Task 1, used only inside this task's own tests to build a real `pdfplumber.PDF` from a fixture — `extract_rows` itself takes an already-open `pdfplumber.PDF`, it doesn't open anything), `make_encrypted_pdf` (Task 1's test fixture helper).
- Produces: `extract_rows(pdf: pdfplumber.PDF) -> list[list[str]]` — Task 4's CLI wiring calls this on the object `open_pdf` returns.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_pdf_rows.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_pdf_rows.py -v`
Expected: `ImportError: cannot import name 'extract_rows' from 'munim_ingest.pdf_extract'`

- [ ] **Step 3: Add `extract_rows` to `packages/ingest/munim_ingest/pdf_extract.py`**

Append to the file (keep everything already there from Task 1 unchanged):

```python
def extract_rows(pdf: pdfplumber.PDF) -> list[list[str]]:
    """Rows from every page, concatenated in order. Prefers ruled tables
    (pdfplumber's extract_tables()) if ANY page has one; if no page in the
    whole document has a table, falls back to one row per non-empty line
    of extract_text(). No column-splitting is attempted in the fallback —
    each line becomes a single-element row; munim's CSV-import wizard
    handles turning arbitrary columns into a mapped schema from there.
    """
    all_tables: list[list[str]] = []
    for page in pdf.pages:
        for table in page.extract_tables():
            all_tables.extend(table)
    if all_tables:
        return all_tables

    all_lines: list[list[str]] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            if line.strip():
                all_lines.append([line])
    return all_lines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_pdf_rows.py -v`
Expected: `3 passed`

- [ ] **Step 5: Run the full pdf-related test set together**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_pdf_extract.py packages/ingest/tests/test_pdf_rows.py -v`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add packages/ingest/munim_ingest/pdf_extract.py packages/ingest/tests/test_pdf_rows.py
git commit -m "Extract rows from tables when present, text lines otherwise"
```

---

### Task 3: CSV writer

**Files:**
- Create: `packages/ingest/munim_ingest/csv_writer.py`
- Create: `packages/ingest/tests/test_csv_writer.py`

**Interfaces:**
- Consumes: nothing (pure function over `list[list[str]]` and a `Path`).
- Produces: `write_csv(rows: list[list[str]], out_path: Path) -> None` — Task 4's CLI wiring is the consumer.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_csv_writer.py`:

```python
import csv

from munim_ingest.csv_writer import write_csv


def test_write_csv_writes_rows_correctly(tmp_path):
    out_path = tmp_path / "out.csv"
    write_csv([["Date", "Amount"], ["2026-06-01", "100"]], out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [["Date", "Amount"], ["2026-06-01", "100"]]


def test_write_csv_creates_parent_directory(tmp_path):
    out_path = tmp_path / "does" / "not" / "exist" / "out.csv"
    write_csv([["a"]], out_path)
    assert out_path.exists()


def test_write_csv_handles_ragged_rows(tmp_path):
    """The fallback (text-line) extraction path can produce single-column
    rows while a table path produces multi-column rows — csv.writer must
    not choke on rows of differing length in the same file."""
    out_path = tmp_path / "out.csv"
    write_csv([["Date", "Amount"], ["just one field"]], out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [["Date", "Amount"], ["just one field"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_csv_writer.py -v`
Expected: `ModuleNotFoundError: No module named 'munim_ingest.csv_writer'`

- [ ] **Step 3: Write `packages/ingest/munim_ingest/csv_writer.py`**

```python
"""Writes extracted PDF rows to a CSV file for munim import to consume."""
from __future__ import annotations

import csv
from pathlib import Path


def write_csv(rows: list[list[str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_csv_writer.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add packages/ingest/munim_ingest/csv_writer.py packages/ingest/tests/test_csv_writer.py
git commit -m "Add CSV writer for extracted PDF rows"
```

---

### Task 4: Wire it together — `munim-ingest pdf extract`, and update the roadmap

**Files:**
- Modify: `packages/ingest/munim_ingest/cli.py`
- Create: `packages/ingest/tests/test_cli_pdf.py`
- Modify: `docs/phases.md`

**Interfaces:**
- Consumes: `open_pdf`, `PdfPasswordError`, `extract_rows` (Task 1 & 2), `write_csv` (Task 3).
- Produces: the finished `munim-ingest pdf extract <file>` command — the last task of this plan; nothing downstream in this plan consumes it. The human's next step (documented, not automated) is running `munim import <output.csv>` from `packages/classify`.

The current `packages/ingest/munim_ingest/cli.py` (as of the end of Phase 1) has: a top-level `app = typer.Typer(..., pretty_exceptions_show_locals=False)`, a `gmail_app` sub-Typer (also with `pretty_exceptions_show_locals=False`) registered via `app.add_typer(gmail_app, name="gmail")`, and the `gmail list-banks`/`gmail fetch` commands. This task adds a sibling `pdf_app` sub-Typer with a `pdf extract` command, following the exact same patterns already established (env-var-or-getpass password, `pretty_exceptions_show_locals=False`, `rich.markup.escape(...)` on every interpolated value that isn't a fixed literal string, broad `except Exception` around anything that could raise while the password is a live local).

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_cli_pdf.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_cli_pdf.py -v`
Expected: fails — no `pdf` subcommand exists on `app` yet.

- [ ] **Step 3: Extend `packages/ingest/munim_ingest/cli.py`**

Add these imports near the top, alongside the existing ones:

```python
from .csv_writer import write_csv
from .pdf_extract import PdfPasswordError, extract_rows, open_pdf
```

Add this sub-Typer registration right after the existing `gmail_app` block (after the `app.add_typer(gmail_app, name="gmail")` line, before `DEFAULT_HOME = Path.home() / ".munim-ingest"`):

```python
pdf_app = typer.Typer(
    help="Extract bank statement PDFs into CSV for `munim import`.",
    pretty_exceptions_show_locals=False,
)
app.add_typer(pdf_app, name="pdf")
```

Add this command anywhere after the `gmail_fetch` function (e.g. at the end of the file, before the `if __name__ == "__main__":` block):

```python
@pdf_app.command("extract")
def pdf_extract_cmd(
    file: Path = typer.Argument(..., exists=True, help="Password-protected statement PDF"),
    out: Path = typer.Option(None, help="Output CSV path (default: <file>.csv next to the source)"),
):
    """Decrypt a password-protected statement PDF and extract its rows to a
    CSV file. The password is read from MUNIM_PDF_PASSWORD if set,
    otherwise prompted — never written to disk. Extraction is generic (no
    bank-specific column knowledge): ruled tables where pdfplumber finds
    them, one row per line of text otherwise. Run `munim import` on the
    output next to map columns and classify, same as any bank CSV export.
    """
    password = os.environ.get("MUNIM_PDF_PASSWORD") or getpass.getpass(
        f"Password for {file.name} (never stored): ")

    # Catch everything: a corrupt PDF, a wrong password, or an extraction
    # failure must all exit cleanly rather than reach an unhandled
    # traceback while the password is a live local.
    try:
        with open_pdf(file, password) as pdf:
            rows = extract_rows(pdf)
    except Exception as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)

    if not rows:
        console.print("[yellow]No text or tables found in this PDF.[/yellow]")
        raise typer.Exit(1)

    out_path = out or file.with_suffix(".csv")
    write_csv(rows, out_path)
    console.print(f"[green]Extracted {len(rows)} row(s) to {escape(str(out_path))}[/green]")
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_cli_pdf.py -v`
Expected: `5 passed`

- [ ] **Step 5: Run the full ingest suite**

Run: `uv run --package munim-ingest pytest packages/ingest/tests -q`
Expected: `60 passed` (Phase 1 shipped 47; Task 1 adds 2 → 49; Task 2 adds 3 → 52; Task 3 adds 3 → 55; Task 4 adds 5 → 60). If your actual count differs, investigate why before moving on — don't just note the discrepancy and continue, the same way a prior task in this repo's history caught its own stale count and got it right.

- [ ] **Step 6: Confirm `packages/classify` is still untouched**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: `15 passed`

- [ ] **Step 7: Commit the CLI wiring**

```bash
git add packages/ingest/munim_ingest/cli.py packages/ingest/tests/test_cli_pdf.py
git commit -m "Wire pdf extract command into munim-ingest"
```

- [ ] **Step 8: Update `docs/phases.md`**

Under the `## Phase 2 — Ingest: PDF extraction (per-bank adapters)` heading, replace the entire section (heading text included, since "per-bank adapters" in the heading is no longer accurate) with:

```markdown
## Phase 2 — Ingest: PDF extraction
**Status: done**

`munim-ingest pdf extract <file.pdf>` decrypts a password-protected
statement PDF (pdfplumber's native password support — no per-bank
knowledge needed) and extracts its rows generically: ruled tables where
found, one row per line of text otherwise. Output is a CSV file, fed into
the existing `munim import` command's interactive column-mapping wizard
(from `packages/classify`) rather than a bank-specific parser — nobody
implementing this had a real HDFC/SBI/SIB statement PDF to build or
verify a column parser against, and reusing the proven wizard avoided
guessing at layouts that determine real transaction amounts.

Plan: [superpowers/plans/2026-08-29-pdf-extraction.md](superpowers/plans/2026-08-29-pdf-extraction.md)
```

Leave Phase 3's section untouched.

Commit:

```bash
git add docs/phases.md
git commit -m "Mark Phase 2 (PDF extraction) done in the roadmap"
```

---

## Post-plan state: manual verification required (human, not a subagent)

Every automated test in this plan runs against a synthetic PDF generated at test time — none of them prove this works against a real bank statement. Before trusting this for real:

1. Get one real password-protected statement PDF from each bank you use.
2. Run `MUNIM_PDF_PASSWORD=<password> uv run --package munim-ingest munim-ingest pdf extract statement.pdf` (or omit the env var and enter the password when prompted — see Phase 1's README section on why the interactive prompt is the safer option for shell-history reasons).
3. Open the resulting CSV and check: did `extract_tables()` find the real table, or did it fall back to one-row-per-line? Either is fine, but you should know which happened before running `munim import` on it.
4. Run `munim import <output.csv>` and use its interactive wizard to map columns, exactly as you would for any bank's CSV export.
5. If a real statement's PDF uses AES-256 encryption, `pdf extract` will fail with the same message a wrong password gives — that's a known, documented gap in this plan, not a bug to silently work around; report back if you hit it and it'll need a real follow-up (likely a `pikepdf`-based decrypt-then-reopen path), not a guess.

## What's deliberately out of scope here

- Per-bank column parsing — not built, on purpose (see Architecture above).
- The canonical transaction JSONL contract — this phase hands off a CSV to `munim import`, which already produces that contract internally; this plan doesn't touch it directly.
- Per-bank password-derivation formulas — passwords are prompted per-run (or read from `MUNIM_PDF_PASSWORD`), matching Phase 1's Gmail-password pattern. A configurable per-bank derivation formula was discussed but deferred until the real formulas for HDFC/SBI/SIB are known — fabricating one would be exactly the kind of unverified guess this plan's Architecture section already refuses to make for column layouts.
