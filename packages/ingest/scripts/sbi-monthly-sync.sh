#!/usr/bin/env bash
# Fetches any new SBI Card e-statements from Gmail, extracts their
# transactions, and imports them into munim — the full monthly routine in
# one script. Run it by hand whenever you think of it (e.g. once a month);
# nothing here schedules itself.
#
# Both passwords are read interactively (never written to disk, same as
# `munim-ingest`'s own convention — see packages/ingest/README.md). If you
# already exported MUNIM_GMAIL_APP_PASSWORD / MUNIM_PDF_PASSWORD in this
# shell, those are used instead and you won't be prompted again.
#
# Usage: packages/ingest/scripts/sbi-monthly-sync.sh you@gmail.com
set -euo pipefail

EMAIL="${1:?Usage: $0 you@gmail.com}"
ACCOUNT="tony-sbi-elite-cc"
PROFILE="sbi-cc"
DOWNLOAD_DIR="$HOME/.munim-ingest/downloads/sbi"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if [ -z "${MUNIM_GMAIL_APP_PASSWORD:-}" ]; then
    read -rs -p "Gmail app password for $EMAIL (never stored): " MUNIM_GMAIL_APP_PASSWORD
    echo
fi
export MUNIM_GMAIL_APP_PASSWORD

# Fetch from just after the newest statement already on disk, so already-
# downloaded months aren't re-fetched and disambiguated into "(2)" copies.
# Filenames are "<card-number>_DDMMYYYY.pdf"; falls back to a fixed start
# date the first time this runs against an empty download directory.
SINCE="2025-06-01"
if [ -d "$DOWNLOAD_DIR" ] && ls "$DOWNLOAD_DIR"/*.pdf >/dev/null 2>&1; then
    LATEST=$(for f in "$DOWNLOAD_DIR"/*.pdf; do
        base=$(basename "$f" .pdf)
        ddmmyyyy="${base##*_}"
        echo "${ddmmyyyy:4:4}-${ddmmyyyy:2:2}-${ddmmyyyy:0:2}"
    done | sort | tail -1)
    SINCE=$(date -j -v+1d -f "%Y-%m-%d" "$LATEST" "+%Y-%m-%d" 2>/dev/null \
        || date -d "$LATEST + 1 day" "+%Y-%m-%d")
fi
echo "Fetching SBI statements since $SINCE..."

uv run --directory "$REPO_ROOT/packages/ingest" munim-ingest gmail fetch sbi \
    --email "$EMAIL" --since "$SINCE"

if [ -z "${MUNIM_PDF_PASSWORD:-}" ]; then
    read -rs -p "PDF password for these statements (never stored): " MUNIM_PDF_PASSWORD
    echo
fi
export MUNIM_PDF_PASSWORD

# Extraction and import are both idempotent (extraction overwrites its own
# CSV deterministically; import dedups by content hash), so re-running
# them over every downloaded statement — not just this run's new ones —
# is safe and self-healing against a partial past run.
for pdf in "$DOWNLOAD_DIR"/*.pdf; do
    csv="${pdf%.pdf}.csv"
    echo "--- $(basename "$pdf") ---"
    uv run --directory "$REPO_ROOT/packages/ingest" munim-ingest pdf extract "$pdf" \
        --bank sbi-statement --out "$csv"
    uv run --directory "$REPO_ROOT/packages/classify" munim import "$csv" \
        --profile "$PROFILE" --account "$ACCOUNT"
done

echo
echo "Done. Run 'munim review' to classify anything new."
