# munim-ingest

Pulls bank statement attachments from Gmail (via IMAP + an app password —
no OAuth, no Google Cloud project) into a local folder, so
[`munim import`](../classify/README.md) can classify them.

Part of the [munim uv workspace](../../docs/phases.md) — see the repo
root [README](../../README.md) for the full picture.

## Usage

List the bank search packs that ship with the tool:

```sh
munim-ingest gmail list-banks
```

Preview what a fetch would download, without writing anything to disk —
run this first:

```sh
munim-ingest gmail fetch hdfc --email you@gmail.com --dry-run
```

Then do the real download:

```sh
munim-ingest gmail fetch hdfc --email you@gmail.com
```

Files land in `~/.munim-ingest/downloads/<bank>/` unless you pass `--out`.

Decrypt a password-protected statement PDF and extract its rows to a CSV
that [`munim import`](../classify/README.md) can consume:

```sh
munim-ingest pdf extract statement.pdf
```

This writes `statement.csv` next to the source file by default; pass
`--out path/to/file.csv` to choose a different location. Extraction is
generic (no bank-specific column knowledge): it uses pdfplumber's ruled
tables where it finds them, and falls back to one row per line of text
otherwise — run `munim import` on the resulting CSV to map columns and
classify, same as any bank CSV export. Re-running the command overwrites
an existing output file at the same path (with a visible warning first),
so save any manual edits elsewhere before re-extracting.

For a bank-account statement downloaded directly from the bank's own
website as an Excel export (`.xls`/`.xlsx`) rather than emailed as a PDF,
use `excel extract` instead — no password is ever requested, since these
exports aren't encrypted the way emailed statement PDFs are:

```sh
munim-ingest excel extract statement.xls --bank hdfc-bank
```

Unlike `pdf extract`, this one needs bank-specific column knowledge
(`--bank` is required); run `munim-ingest excel extract --help` for the
current list of supported layouts. Same output convention as `pdf
extract`: `statement.csv` next to the source by default, `--out` to
choose another path.

### The app password / PDF password

Gmail needs an [app password](https://support.google.com/accounts/answer/185833)
(IMAP only — no OAuth, no Google Cloud project), and `pdf extract` needs
the PDF's own password. Both are handled the same way — read from an
environment variable if set (`MUNIM_GMAIL_APP_PASSWORD` for `gmail fetch`,
`MUNIM_PDF_PASSWORD` for `pdf extract`), otherwise prompted interactively.

**Prefer the interactive prompt.** Running either command without setting
the corresponding environment variable makes it prompt for the password,
read it with `getpass` (no echo), hold it in memory only, and never write
it to disk.

Avoid `MUNIM_GMAIL_APP_PASSWORD=... munim-ingest gmail fetch ...` or
`MUNIM_PDF_PASSWORD=... munim-ingest pdf extract ...` — an inline
assignment on a command line normally lands in your shell history file
(`~/.zsh_history`, `~/.bash_history`), which persists the secret to disk
through a channel this tool cannot control.

If you do want the environment-variable route (for scripting, or to avoid
retyping across several runs), read it into the environment without it
ever appearing in a command line:

```sh
read -rs MUNIM_GMAIL_APP_PASSWORD && export MUNIM_GMAIL_APP_PASSWORD
munim-ingest gmail fetch hdfc --email you@gmail.com
```

```sh
read -rs MUNIM_PDF_PASSWORD && export MUNIM_PDF_PASSWORD
munim-ingest pdf extract statement.pdf
```

The variable then lives only in that shell session; `unset
MUNIM_GMAIL_APP_PASSWORD` (or `unset MUNIM_PDF_PASSWORD`) clears it.
