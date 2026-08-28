"""munim-ingest CLI: pull bank statement attachments from email into a
local folder for munim to classify.
"""
from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    help="munim-ingest — pull bank statement attachments from email into a local folder.",
    no_args_is_help=True, add_completion=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main():
    """munim-ingest — pull bank statement attachments from email into a local folder."""
    pass


if __name__ == "__main__":
    app()
