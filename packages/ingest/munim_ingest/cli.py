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
from .imap_client import ImapConfig, connect, search_uids
from .packs import PackNotFoundError, list_packs, load_pack
from .pdf_extract import PdfPasswordError, extract_rows, filter_transaction_rows, open_pdf

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
    extracted, unfiltered. Run `munim import` on the output next to map
    columns and classify, same as any bank CSV export.
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

        if raw:
            final_rows = rows
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
    console.print(f"[green]Extracted {len(final_rows)} row(s) to {escape(str(out_path))}[/green]",
                  soft_wrap=True)
    console.print(f"\nNext: [bold]munim import {escape(str(out_path))}[/bold] "
                  "to map columns and classify.", soft_wrap=True)


if __name__ == "__main__":
    app()
