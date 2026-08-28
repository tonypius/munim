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
from .imap_client import ImapConfig, connect, search_uids
from .packs import PackNotFoundError, list_packs, load_pack

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
    pretty_exceptions_show_locals=False,
)
app.add_typer(gmail_app, name="gmail")

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


if __name__ == "__main__":
    app()
