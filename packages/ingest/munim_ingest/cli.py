"""munim-ingest CLI: pull bank statement attachments from email into a
local folder for munim to classify.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from .attachments import extract_attachments, save_attachments
from .csv_writer import write_csv
from .imap_client import ImapConfig, connect, search_uids
from .packs import PackNotFoundError, list_packs, load_pack
from .pdf_extract import PdfPasswordError, extract_rows, open_pdf

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

DEFAULT_HOME = Path.home() / ".munim-ingest"


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
        uids = search_uids(conn, mailbox, pack.from_domains)
        console.print(
            f"Found {len(uids)} message(s) from {escape(bank)} senders in {escape(mailbox)}.")

        total = 0
        out_dir = out or (DEFAULT_HOME / "downloads" / bank)
        for uid in uids:
            # Isolate per-message failures: one malformed or crafted message
            # must not abandon every remaining message in the run.
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
                console.print(
                    f"[yellow]Skipping message {escape(str(uid))}: {escape(str(e))}[/yellow]")
                continue

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

    # Catch everything: a corrupt PDF, a wrong password, an extraction
    # failure, or a failure writing the output CSV (e.g. --out pointing at
    # a path whose parent isn't a directory) must all exit cleanly rather
    # than reach an unhandled traceback while the password is a live local.
    # This whole block, not just the pdf-opening part, must stay inside the
    # try — anything that can fail while `password` is still a live local
    # belongs here.
    try:
        with open_pdf(file, password) as pdf:
            rows = extract_rows(pdf)

        if not rows:
            console.print("[yellow]No text or tables found in this PDF.[/yellow]")
            raise typer.Exit(1)

        out_path = out or file.with_suffix(".csv")
        if out_path.exists():
            console.print(f"[yellow]Overwriting existing {escape(str(out_path))}[/yellow]")
        write_csv(rows, out_path)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1)
    # soft_wrap=True: a long absolute output path (common under macOS's deep
    # /private/var/folders tmp dirs, and plausible for a user's own nested
    # download folders) must not be broken across lines by Rich's default
    # 80-column wrap, which would corrupt the path if copy-pasted.
    console.print(f"[green]Extracted {len(rows)} row(s) to {escape(str(out_path))}[/green]",
                  soft_wrap=True)
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.", soft_wrap=True)


if __name__ == "__main__":
    app()
