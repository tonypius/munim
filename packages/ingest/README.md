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

### The app password

Gmail needs an [app password](https://support.google.com/accounts/answer/185833)
(IMAP only — no OAuth, no Google Cloud project).

**Prefer the interactive prompt.** Running the command without setting any
environment variable makes it prompt for the password, read it with
`getpass` (no echo), hold it in memory only, and never write it to disk.

Avoid `MUNIM_GMAIL_APP_PASSWORD=... munim-ingest gmail fetch ...` — an
inline assignment on a command line normally lands in your shell history
file (`~/.zsh_history`, `~/.bash_history`), which persists the secret to
disk through a channel this tool cannot control.

If you do want the environment-variable route (for scripting, or to avoid
retyping across several runs), read it into the environment without it
ever appearing in a command line:

```sh
read -rs MUNIM_GMAIL_APP_PASSWORD && export MUNIM_GMAIL_APP_PASSWORD
munim-ingest gmail fetch hdfc --email you@gmail.com
```

The variable then lives only in that shell session; `unset
MUNIM_GMAIL_APP_PASSWORD` clears it.
