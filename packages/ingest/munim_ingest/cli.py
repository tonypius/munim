"""munim-ingest CLI: pull bank statement attachments from email into a
local folder for munim to classify.
"""
from __future__ import annotations

import getpass
import os
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from .attachments import extract_attachments, save_attachments
from .csv_writer import write_csv
from . import axis_bank_account_excel, hdfc_bank_account, hdfc_bank_account_excel, hdfc_credit_card, hdfc_credit_card_v2
from . import sbi_credit_card
from . import sbi_credit_card_statement
from . import sib_account
from . import sib_account_pdf
from .hdfc_credit_card import normalize_hdfc_credit_card_amounts, normalize_hdfc_credit_card_dates
from .imap_client import ImapConfig, connect, search_uids
from .packs import PackNotFoundError, list_packs, load_pack
from .pdf_extract import (
    PdfPasswordError, extract_all_text, extract_rows, filter_transaction_rows, open_pdf,
)

def _is_hdfc_v2_layout(rows):
    """The newer HDFC template (a card-number upgrade on the same
    account, statements from ~Sep 2025 on) never forms a ruled table, so
    filter_transaction_rows keeps single-column lines instead of the
    older format's 5-column shape — that row width is what distinguishes
    the two layouts after filtering, without the user needing a separate
    flag for each."""
    return bool(rows) and len(rows[0]) == 1


def _normalize_hdfc_credit_card(rows):
    if _is_hdfc_v2_layout(rows):
        return hdfc_credit_card_v2.normalize_hdfc_v2_rows(rows)
    return normalize_hdfc_credit_card_dates(normalize_hdfc_credit_card_amounts(rows))


# Bank-specific post-filter normalizers, opted into via `pdf extract --bank`.
# Each is scoped to exactly one bank's known amount/column/date convention —
# never applied by default, since it encodes real assumptions about that
# bank's statement layout that don't generalize to others.
BANK_NORMALIZERS = {
    "hdfc": _normalize_hdfc_credit_card,
    "hdfc-bank": hdfc_bank_account.normalize_hdfc_bank_account_rows,
}

# --bank sbi, --bank sbi-statement, and --bank sib don't go through
# BANK_NORMALIZERS at all — see the early special cases in
# pdf_extract_cmd for why (extract_rows()/filter_transaction_rows() are
# actively wrong for all three: sbi's netbanking export never forms a
# real ruled table, sbi-statement's one ruled table has column-major
# cells that aren't safely index-alignable, and sib's yearly statement
# forms no ruled table at all). Still recognized --bank values, so all
# three are included here for validation and help text alongside the
# banks that do use BANK_NORMALIZERS.
PDF_BANKS = (*BANK_NORMALIZERS, "sbi", "sbi-statement", "sib")

# pretty_exceptions_show_locals=False: an unhandled exception anywhere in
# this CLI must never render a locals table, which would print the Gmail
# app password held in a local variable. Typer's default for this is True
# in several released versions, so set it explicitly on every Typer app.
app = typer.Typer(
    help="munim-ingest — pull bank statement attachments from email into a local folder.",
    no_args_is_help=True, add_completion=False,
    pretty_exceptions_show_locals=False,
)
console = Console()

gmail_app = typer.Typer(
    help="Fetch bank statement attachments from Gmail via IMAP.",
    # Kept for consistency/explicitness, not because it's independently
    # load-bearing: once registered via add_typer, the top-level `app`'s
    # pretty_exceptions_show_locals is what Typer actually consults at
    # call time — sub-apps don't control this on their own.
    pretty_exceptions_show_locals=False,
)
app.add_typer(gmail_app, name="gmail")

pdf_app = typer.Typer(
    help="Extract bank statement PDFs into CSV for `munim import`.",
    # See the same note on gmail_app above: the real protection is the
    # top-level `app`'s setting, this one is kept for explicitness only.
    pretty_exceptions_show_locals=False,
)
app.add_typer(pdf_app, name="pdf")

excel_app = typer.Typer(
    help="Extract bank statement Excel exports into CSV for `munim import`.",
    # See the same note on gmail_app above: the real protection is the
    # top-level `app`'s setting, this one is kept for explicitness only.
    pretty_exceptions_show_locals=False,
)
app.add_typer(excel_app, name="excel")

# Bank-specific Excel-export parsers, opted into via `excel extract --bank`.
# Each is scoped to exactly one bank's known column layout — never applied
# by default, same rationale as BANK_NORMALIZERS below.
EXCEL_PARSERS = {
    "hdfc-bank": hdfc_bank_account_excel.parse_hdfc_bank_excel,
    "axis": axis_bank_account_excel.parse_axis_bank_excel,
}

# Banks whose EXCEL_PARSERS entry already returns munim's canonical
# (Date, Narration, Amount) shape — these get the shared HEADER_ROW
# instead of the generic "Column N" fallback below.
_EXCEL_CANONICAL_HEADER_BANKS = {"hdfc-bank": hdfc_bank_account_excel.HEADER_ROW,
                                  "axis": axis_bank_account_excel.HEADER_ROW}

csv_app = typer.Typer(
    help="Extract bank statement CSV exports (downloaded directly from "
         "the bank's own website, not emailed) into a clean CSV for "
         "`munim import`.",
    # See the same note on gmail_app above: the real protection is the
    # top-level `app`'s setting, this one is kept for explicitness only.
    pretty_exceptions_show_locals=False,
)
app.add_typer(csv_app, name="csv")

# Bank-specific direct-website CSV-export parsers, opted into via
# `csv extract --bank`. Each is scoped to exactly one bank's known
# preamble/column layout — never applied by default, same rationale as
# BANK_NORMALIZERS and EXCEL_PARSERS above. Distinct from `excel extract`
# because these banks' own netbanking portals export CSV directly (no
# spreadsheet library needed), not .xls/.xlsx.
CSV_PARSERS = {
    "sib": sib_account.parse_sib_account_csv,
}

DEFAULT_HOME = Path.home() / ".munim-ingest"

# A long-lived Gmail account can have years of mail from a bank's sending
# domain that isn't a statement (alerts, OTPs, promos) — --since narrows the
# search dramatically. It also matters for connection stability: fetching
# thousands of messages over one IMAP connection has been observed to
# exhaust Gmail's per-connection limits and drop the connection outright.
CONSECUTIVE_FAILURE_LIMIT = 5


@gmail_app.command("list-banks")
def gmail_list_banks():
    """List the available bank search packs."""
    for bank in list_packs():
        console.print(bank)


@gmail_app.command("fetch")
def gmail_fetch(
    bank: str = typer.Argument(..., help="Bank pack name, e.g. hdfc, sib, sbi"),
    email: str = typer.Option(..., prompt=True, help="Your Gmail address"),
    out: Path = typer.Option(None, help="Download directory (default: ~/.munim-ingest/downloads/<bank>/)"),
    mailbox: str = typer.Option("INBOX", help="IMAP mailbox to search"),
    imap_host: str = typer.Option("imap.gmail.com"),
    imap_port: int = typer.Option(993),
    since: str = typer.Option(
        None, "--since",
        help="Only messages on/after this date (YYYY-MM-DD). Strongly "
             "recommended for a long-lived inbox — sender-domain search alone "
             "can match years of unrelated mail from the bank, not just "
             "statements, and fetching thousands of messages risks Gmail "
             "dropping the connection."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List matches without downloading"),
):
    """Search Gmail for a bank's statement emails and download matching
    attachments. The app password is read from MUNIM_GMAIL_APP_PASSWORD
    if set, otherwise prompted — it is never written to disk.
    """
    try:
        pack = load_pack(bank)
    except PackNotFoundError as e:
        # The message embeds the caller-supplied bank name, which may contain
        # Rich markup — escape it so a bad name exits cleanly instead of
        # raising MarkupError.
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)

    since_date = None
    if since is not None:
        try:
            since_date = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]--since must be YYYY-MM-DD, got {escape(since)}[/red]")
            raise typer.Exit(1)

    password = os.environ.get("MUNIM_GMAIL_APP_PASSWORD") or getpass.getpass(
        f"App password for {email} (never stored): ")

    config = ImapConfig(host=imap_host, port=imap_port, email=email, password=password)
    # Catch everything: imaplib raises several unrelated exception types for
    # connection/auth failures, and no exception here may reach an unhandled
    # traceback while the password is a live local.
    try:
        conn = connect(config)
    except Exception as e:
        console.print(f"[red]Could not connect or log in: {escape(str(e))}[/red]")
        raise typer.Exit(1)
    try:
        uids = search_uids(conn, mailbox, pack.from_domains, since=since_date,
                            subject_keywords=pack.subject_keywords)
        console.print(
            f"Found {len(uids)} message(s) from {escape(bank)} senders in {escape(mailbox)}.")

        total = 0
        consecutive_failures = 0
        out_dir = out or (DEFAULT_HOME / "downloads" / bank)
        for uid in uids:
            # Isolate per-message failures: one malformed or crafted message
            # must not abandon every remaining message in the run. But a
            # SUSTAINED streak of failures usually means the connection
            # itself died (e.g. a broken pipe from Gmail dropping a
            # connection under heavy fetch load) — every subsequent fetch on
            # a dead connection fails identically, so grinding through
            # thousands of remaining UIDs one at a time wastes time and
            # floods the output. Stop after a short streak instead.
            try:
                status, data = conn.fetch(uid, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    continue
                item = data[0]
                # Servers can interleave non-literal response items such as
                # b'1 (FLAGS (\\Seen))'. Those are bare bytes, not a
                # (response, literal) tuple — indexing them would silently
                # yield an int instead of the raw message.
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                raw = item[1]
                found = extract_attachments(raw, pack.attachment_extensions)
                if not found:
                    continue
                # Attachment filenames are sender-controlled: escape them so
                # they render literally and cannot inject or break markup.
                if dry_run:
                    for filename, _content in found:
                        console.print(f"  [dim]would save:[/dim] {escape(filename)}")
                    total += len(found)
                else:
                    saved = save_attachments(found, out_dir)
                    for path in saved:
                        console.print(f"  [green]saved:[/green] {escape(str(path))}")
                    total += len(saved)
            except Exception as e:
                consecutive_failures += 1
                console.print(
                    f"[yellow]Skipping message {escape(str(uid))}: {escape(str(e))}[/yellow]")
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    console.print(
                        f"\n[red]Stopping after {consecutive_failures} consecutive "
                        "failures — the connection may have dropped. "
                        f"{total} attachment(s) processed before the failures started. "
                        "Try narrowing further with --since, or re-run once the "
                        "connection issue clears (already-saved files are kept, not "
                        "re-downloaded).[/red]")
                    break
                continue
            else:
                consecutive_failures = 0

        if dry_run:
            console.print(f"\n[bold]{total}[/bold] attachment(s) would be downloaded (dry run).")
        else:
            console.print(
                f"\n[bold]{total}[/bold] attachment(s) downloaded to {escape(str(out_dir))}.")
    finally:
        conn.logout()


@pdf_app.command("extract")
def pdf_extract_cmd(
    file: Path = typer.Argument(..., exists=True, help="Password-protected statement PDF"),
    out: Path = typer.Option(None, help="Output CSV path (default: <file>.csv next to the source)"),
    raw: bool = typer.Option(
        False, "--raw",
        help="Skip transaction-row filtering; write every extracted row "
             "as-is. Useful if the automatic filter doesn't fit a bank's "
             "layout, or to inspect what was extracted before cleanup."),
    bank: str = typer.Option(
        None, "--bank",
        help=f"Apply a bank-specific amount normalization after the "
             f"generic filter (ignored with --raw, except --bank sbi, "
             f"--bank sbi-statement, and --bank sib — see below). "
             f"Available: {', '.join(PDF_BANKS)}."),
):
    """Decrypt a password-protected statement PDF and extract its rows to a
    CSV file. The password is read from MUNIM_PDF_PASSWORD if set,
    otherwise prompted — never written to disk. Extraction is generic (no
    bank-specific column knowledge): ruled tables where pdfplumber finds
    them, one row per line of text otherwise. Real bank table extraction
    often mixes genuine transaction rows with page-header titles and
    per-page summary boxes pdfplumber also detects as "tables" — by
    default, rows are filtered down to the dominant (most common) row
    shape whose first cell looks like a date, which is what a real
    transaction row looks like; pass --raw to skip this and get everything
    extracted, unfiltered. --bank hdfc additionally normalizes HDFC credit
    card statements' amount convention (auto-detecting either the older
    positive-magnitude-plus-Cr/Dr-suffix layout or the newer structural-
    direction layout) into munim's expected signed-amount format.
    --bank hdfc-bank does the same for HDFC savings/current account
    statements, exploding each page's merged multi-transaction row back
    into one row per transaction. --bank sbi and --bank sbi-statement are
    different from the other two, and from each other. SBI's netbanking
    "Transaction History" export (--bank sbi) never forms a ruled table
    at all except for its own column-header row, which makes the generic
    extraction above actively wrong (it finds that one header "table" and
    returns only it, skipping every real transaction) — so --bank sbi
    reads each word's own position on the page directly instead of going
    through the generic row/table path this command otherwise always
    uses (necessary because pdfplumber's text-stream order scrambles a
    wrapped long merchant name relative to its own date/type/amount —
    see sbi_credit_card.py for the real example). SBI Card's monthly
    emailed e-statement (--bank sbi-statement) does form one ruled table,
    but its cells are column-major in a way that isn't safely
    index-alignable (see sbi_credit_card_statement.py), so it instead
    reads one transaction per physical text line. South Indian Bank's
    emailed yearly statement (--bank sib) forms no ruled table at all
    (a borderless, position-only layout) — like --bank sbi, it reads
    each word's own position on the page directly (see
    sib_account_pdf.py), necessary because a wrapped row's Withdrawals/
    Deposits/Balance figures sit on their own physical line between the
    two fragments of a wrapped Particulars narration. --raw has no
    effect with any of the three.
    Run `munim import` on the output next to map columns and classify,
    same as any bank CSV export.
    """
    if bank is not None and bank not in PDF_BANKS:
        console.print(
            f"[red]Unknown --bank '{escape(bank)}'. Available: "
            f"{', '.join(PDF_BANKS)}.[/red]")
        raise typer.Exit(1)

    password = os.environ.get("MUNIM_PDF_PASSWORD") or getpass.getpass(
        f"Password for {file.name} (never stored): ")

    # Catch everything: a corrupt PDF, a wrong password, an extraction
    # failure, or a failure writing the output CSV (e.g. --out pointing at
    # a path whose parent isn't a directory) must all exit cleanly rather
    # than reach an unhandled traceback while the password is a live local.
    # This whole block, not just the pdf-opening part, must stay inside the
    # try — anything that can fail while `password` is still a live local
    # belongs here.
    try:
        if bank == "sbi":
            # Bypasses extract_rows()/filter_transaction_rows() entirely —
            # see this command's docstring for why those are actively
            # wrong for this bank (pdfplumber finds only a small header
            # "table" and returns just that, never the real transactions).
            if raw:
                console.print(
                    "[yellow]--raw has no effect for --bank sbi: this "
                    "bank's transactions are read from each word's own "
                    "position on the page, not through the generic "
                    "row/table path --raw controls.[/yellow]")
            with open_pdf(file, password) as pdf:
                final_rows = sbi_credit_card.parse_transactions(pdf.pages)
            if not final_rows:
                console.print(
                    "[yellow]No transactions found — this may not be an "
                    "SBI 'Transaction History' export, or its format has "
                    "changed.[/yellow]")
                raise typer.Exit(1)
            final_rows = [sbi_credit_card.HEADER_ROW, *final_rows]
            out_path = out or file.with_suffix(".csv")
            if out_path.exists():
                console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
            write_csv(final_rows, out_path)
            console.print(
                f"[green]Extracted {len(final_rows) - 1} transaction row(s) "
                f"to {escape(str(out_path))}[/green]", soft_wrap=True)
            console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                          "to map columns and classify.", soft_wrap=True)
            return

        if bank == "sbi-statement":
            # Bypasses extract_rows()/filter_transaction_rows() entirely —
            # see this command's docstring for why (the one ruled table
            # pdfplumber finds here has column-major cells that aren't
            # safely index-alignable across a section divider row).
            if raw:
                console.print(
                    "[yellow]--raw has no effect for --bank sbi-statement: "
                    "this bank's transactions are read one per physical "
                    "text line, not through the generic row/table path "
                    "--raw controls.[/yellow]")
            with open_pdf(file, password) as pdf:
                final_rows = sbi_credit_card_statement.parse_transactions(pdf.pages)
            if not final_rows:
                console.print(
                    "[yellow]No transactions found — this may not be an "
                    "SBI Card monthly e-statement, or its format has "
                    "changed.[/yellow]")
                raise typer.Exit(1)
            final_rows = [sbi_credit_card_statement.HEADER_ROW, *final_rows]
            out_path = out or file.with_suffix(".csv")
            if out_path.exists():
                console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
            write_csv(final_rows, out_path)
            console.print(
                f"[green]Extracted {len(final_rows) - 1} transaction row(s) "
                f"to {escape(str(out_path))}[/green]", soft_wrap=True)
            console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                          "to map columns and classify.", soft_wrap=True)
            return

        if bank == "sib":
            # Bypasses extract_rows()/filter_transaction_rows() entirely —
            # this bank's yearly statement forms no ruled table at all
            # (a borderless, position-only layout), so it reads each
            # word's own position on the page directly instead, same
            # rationale as --bank sbi.
            if raw:
                console.print(
                    "[yellow]--raw has no effect for --bank sib: this "
                    "bank's transactions are read from each word's own "
                    "position on the page, not through the generic "
                    "row/table path --raw controls.[/yellow]")
            with open_pdf(file, password) as pdf:
                final_rows = sib_account_pdf.parse_transactions(pdf.pages)
            if not final_rows:
                console.print(
                    "[yellow]No transactions found — this may not be a "
                    "SIB yearly statement, or its format has "
                    "changed.[/yellow]")
                raise typer.Exit(1)
            final_rows = [sib_account_pdf.HEADER_ROW, *final_rows]
            out_path = out or file.with_suffix(".csv")
            if out_path.exists():
                console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
            write_csv(final_rows, out_path)
            console.print(
                f"[green]Extracted {len(final_rows) - 1} transaction row(s) "
                f"to {escape(str(out_path))}[/green]", soft_wrap=True)
            console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                          "to map columns and classify.", soft_wrap=True)
            return

        with open_pdf(file, password) as pdf:
            rows = extract_rows(pdf)
            # Only hdfc-bank statements are known to carry this, and only
            # while the PDF is still open — captured here so it can still
            # be reported after the `with` block closes it.
            statement_period = (
                hdfc_bank_account.find_statement_period(extract_all_text(pdf))
                if bank == "hdfc-bank" else None)

        if not rows:
            console.print("[yellow]No text or tables found in this PDF.[/yellow]")
            raise typer.Exit(1)

        if raw:
            final_rows = rows
            if bank is not None:
                console.print(
                    "[yellow]--bank normalization skipped: --raw bypasses "
                    "all row processing, including bank-specific "
                    "normalization.[/yellow]")
        else:
            final_rows = filter_transaction_rows(rows)
            if not final_rows:
                console.print(
                    f"[yellow]The transaction filter kept 0 of {len(rows)} "
                    "extracted row(s) — this PDF's layout may not match "
                    "what the filter expects. Re-run with --raw to see "
                    "everything extracted, unfiltered.[/yellow]")
                raise typer.Exit(1)
            dropped = len(rows) - len(final_rows)
            console.print(
                f"Kept {len(final_rows)} likely transaction row(s), filtered "
                f"out {dropped} non-transaction row(s) (headers, summaries, "
                "blanks). Spot-check the output — pass --raw to see "
                "everything unfiltered if this looks wrong.")
            is_v2 = bank == "hdfc" and _is_hdfc_v2_layout(final_rows)
            if bank is not None:
                pre_normalize_rows = final_rows
                final_rows = BANK_NORMALIZERS[bank](final_rows)
                if bank == "hdfc-bank":
                    dropped_pages = hdfc_bank_account.count_unparseable_pages(
                        pre_normalize_rows)
                    if dropped_pages:
                        console.print(
                            f"[red]{dropped_pages} page(s) could not be "
                            "parsed (an unrecognized narration format broke "
                            "the alignment check) and every transaction on "
                            "those pages was dropped. Re-run with --raw and "
                            "inspect the output — this needs a parser fix, "
                            "not a retry.[/red]")
                if is_v2:
                    console.print(
                        f"Applied {escape(bank)} normalization for the newer "
                        "statement layout (no Cr/Dr suffix on this template — "
                        "direction is inferred structurally: a bare '+' "
                        "immediately before the trailing amount marks a "
                        "credit, everything else defaults to debit).")
                elif bank == "hdfc-bank":
                    console.print(
                        f"Applied {escape(bank)} normalization (each page's "
                        "merged Date/Narration/Withdrawals/Deposits row "
                        "exploded back into one transaction per row; no "
                        "direction inference needed — Withdrawals and "
                        "Deposits are already separate columns).")
                    if statement_period:
                        from_date, to_date = statement_period
                        # HDFC's own statement period isn't guaranteed to
                        # start on the 1st of its named month — a real
                        # statement has been seen starting 2 days in,
                        # silently missing those days from a naive
                        # "one PDF per calendar month" pull. Flag it
                        # rather than let it pass unnoticed.
                        if from_date[:2] == "01":
                            console.print(
                                f"Statement period: {from_date} → {to_date}.")
                        else:
                            console.print(
                                f"[yellow]Statement period: {from_date} → "
                                f"{to_date} — starts mid-month, not on the "
                                "1st. If the previous statement you have "
                                f"doesn't end the day before ({from_date}), "
                                "some days are missing between them and "
                                "need a different source (e.g. an Excel "
                                "export) to fill.[/yellow]")
                else:
                    console.print(
                        f"Applied {escape(bank)} normalization (amount: "
                        "positive-magnitude + Cr/Dr suffix → munim's signed "
                        "convention; date: strips a time component and any "
                        "stray leading text down to a bare date).")
                if not final_rows:
                    console.print(
                        f"[yellow]{escape(bank)} normalization left 0 "
                        "transaction row(s) — every extracted line was "
                        "dropped as unparseable. Re-run with --raw to see "
                        "everything unfiltered.[/yellow]")
                    raise typer.Exit(1)

            # munim import's column-mapping wizard treats row 1 as a
            # header (csv.DictReader) — filter_transaction_rows's output
            # never has one (the real header row, if any, doesn't start
            # with a date and gets filtered out along with the other
            # noise), so without this, the wizard would silently treat
            # the first real transaction as the header and drop it. Use
            # HDFC's real, known column names when the shape matches what
            # --bank hdfc expects for either known layout; otherwise a
            # generic numbered header — honest about not knowing the
            # semantic meaning of a column for a bank this tool hasn't
            # verified.
            width = len(final_rows[0])
            if bank == "hdfc" and is_v2:
                header_row = hdfc_credit_card_v2.HEADER_ROW
            elif bank == "hdfc" and width == len(hdfc_credit_card.HEADER_ROW):
                header_row = hdfc_credit_card.HEADER_ROW
            elif bank == "hdfc-bank":
                header_row = hdfc_bank_account.HEADER_ROW
            else:
                header_row = [f"Column {i + 1}" for i in range(width)]
            final_rows = [header_row, *final_rows]

        out_path = out or file.with_suffix(".csv")
        if out_path.exists():
            console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
        write_csv(final_rows, out_path)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)
    # soft_wrap=True: a long absolute output path (common under macOS's deep
    # /private/var/folders tmp dirs, and plausible for a user's own nested
    # download folders) must not be broken across lines by Rich's default
    # 80-column wrap, which would corrupt the path if copy-pasted.
    row_word = "row" if raw else "transaction row"
    row_count = len(final_rows) - (0 if raw else 1)  # exclude the prepended header
    console.print(
        f"[green]Extracted {row_count} {row_word}(s) to {escape(str(out_path))}[/green]",
        soft_wrap=True)
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.", soft_wrap=True)


@excel_app.command("extract")
def excel_extract_cmd(
    file: Path = typer.Argument(..., exists=True,
                                 help="Bank statement Excel export (.xls/.xlsx)"),
    out: Path = typer.Option(None, help="Output CSV path (default: <file>.csv next to the source)"),
    bank: str = typer.Option(
        ..., "--bank",
        help=f"Which bank's Excel export layout to parse. Available: "
             f"{', '.join(EXCEL_PARSERS)}."),
):
    """Parse a bank statement Excel export — downloaded directly from the
    bank's own website, not emailed — into a CSV for `munim import`.
    Unlike `pdf extract`, no password is ever requested: these exports
    aren't encrypted the way emailed statement PDFs are.
    """
    if bank not in EXCEL_PARSERS:
        console.print(
            f"[red]Unknown --bank '{escape(bank)}'. Available: "
            f"{', '.join(EXCEL_PARSERS)}.[/red]")
        raise typer.Exit(1)

    try:
        rows = EXCEL_PARSERS[bank](file)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)

    if not rows:
        console.print(
            "[yellow]No transaction rows found in this file — the parser "
            "may not fit this export's layout.[/yellow]")
        raise typer.Exit(1)

    header_row = _EXCEL_CANONICAL_HEADER_BANKS.get(
        bank, [f"Column {i + 1}" for i in range(len(rows[0]))])
    final_rows = [header_row, *rows]

    out_path = out or file.with_suffix(".csv")
    if out_path.exists():
        console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
    write_csv(final_rows, out_path)
    console.print(
        f"[green]Extracted {len(rows)} transaction row(s) to {escape(str(out_path))}[/green]",
        soft_wrap=True)
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.", soft_wrap=True)


@csv_app.command("extract")
def csv_extract_cmd(
    file: Path = typer.Argument(..., exists=True,
                                 help="Bank statement CSV export, downloaded directly from the bank's website"),
    out: Path = typer.Option(None, help="Output CSV path (default: <file>.csv next to the source)"),
    bank: str = typer.Option(
        ..., "--bank",
        help=f"Which bank's direct-website CSV export layout to parse. Available: "
             f"{', '.join(CSV_PARSERS)}."),
):
    """Parse a bank statement CSV export — downloaded directly from the
    bank's own netbanking portal, not emailed — into a clean CSV for
    `munim import`. Unlike `pdf extract`, no password is ever requested:
    these exports aren't encrypted the way emailed statement PDFs are.
    The source file already is a CSV, but not one munim import's generic
    loader can read directly — a preamble block (account holder details,
    statement metadata) sits before the real column header, and a
    footer sits after the last real row; this strips both.
    """
    if bank not in CSV_PARSERS:
        console.print(
            f"[red]Unknown --bank '{escape(bank)}'. Available: "
            f"{', '.join(CSV_PARSERS)}.[/red]")
        raise typer.Exit(1)

    try:
        rows = CSV_PARSERS[bank](file)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)

    if not rows:
        console.print(
            "[yellow]No transaction rows found in this file — the parser "
            "may not fit this export's layout.[/yellow]")
        raise typer.Exit(1)

    header_row = sib_account.HEADER_ROW if bank == "sib" else [f"Column {i + 1}" for i in range(len(rows[0]))]
    final_rows = [header_row, *rows]

    # Unlike pdf/excel extract, the source here is already a .csv — a
    # bare with_suffix(".csv") default would silently collide with (and
    # overwrite) the input file itself, destroying the raw export.
    out_path = out or file.with_name(f"{file.stem}.parsed.csv")
    if out_path == file:
        console.print(
            f"[red]--out must not be the same file as the input "
            f"({escape(str(file))}) — this would overwrite your source export.[/red]")
        raise typer.Exit(1)
    if out_path.exists():
        console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
    write_csv(final_rows, out_path)
    console.print(
        f"[green]Extracted {len(rows)} transaction row(s) to {escape(str(out_path))}[/green]",
        soft_wrap=True)
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.", soft_wrap=True)


if __name__ == "__main__":
    app()
