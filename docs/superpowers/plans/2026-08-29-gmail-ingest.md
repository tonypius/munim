# Gmail Ingest (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `packages/ingest/` workspace member (`munim-ingest` console script) that connects to Gmail over IMAP with an app password, searches for a bank's statement emails by sender domain, and downloads matching attachments to a local folder — no OAuth, no Google Cloud project, no cloud service, matching munim's "no account, no API key" ethos.

**Architecture:** Four small, independently-testable modules (`packs.py` — bank search-pack loader, `imap_client.py` — IMAP connection + search-query building, `attachments.py` — MIME attachment extraction + safe file saving) wired together by one CLI command (`munim-ingest gmail fetch <bank>`). Every module is unit-tested with mocks/fixtures — **no automated test in this plan makes a real network call or touches a real mailbox.** The final manual check against a real Gmail account is explicitly the human's step, documented at the end of Task 5, not something any subagent or the controller performs.

**Tech Stack:** Python `>=3.10`, `typer`/`rich` (matching `packages/classify`'s CLI style), `pyyaml` (pack files), stdlib `imaplib`/`email` (no third-party IMAP or email-parsing library needed).

## Global Constraints

- This plan produces `packages/ingest/`, the uv workspace's second member (`packages/classify/` is the first, from Phase 0). Root `pyproject.toml`'s `members = ["packages/*"]` already covers it — no root-level change needed.
- No automated test connects to a real IMAP server or a real mailbox. Every IMAP interaction is tested against a mock connection object; every email/attachment test constructs its own in-memory MIME message. If a task's brief seems to require a live connection to pass its tests, that's a plan defect — stop and flag it rather than improvising real credentials.
- **Never persist the Gmail app password to disk.** Read it from the `MUNIM_GMAIL_APP_PASSWORD` environment variable if set, otherwise prompt with `getpass.getpass()` at command runtime. No task in this plan writes a password to any file, config, or log.
- **The bank pack `from_domains` values (Task 2) are best-guess placeholders**, not verified facts — nobody involved in writing or implementing this plan has access to the user's real inbox to confirm which sender addresses their banks actually use. Task 2's brief says this explicitly, and Task 5 ends with an instruction for the human to verify/correct the pack files against a real statement email's `From:` header before relying on this for real, using `--dry-run` first.
- Scope boundary: this phase downloads raw attachments (CSV/PDF) to a local folder. It does **not** parse PDFs (that's Phase 2) and does **not** produce the canonical transaction JSONL (`ingest` → `classify` contract, documented in `docs/phases.md`) — a CSV attachment downloaded here is already in a form `munim import` can consume directly; a PDF attachment downloaded here waits for Phase 2. Don't treat the absence of JSONL output as a gap in this plan.
- Console script name: `munim-ingest` (distinct from `packages/classify`'s `munim`, so both can be installed side by side without collision).
- Package name: `munim-ingest`; Python import package name: `munim_ingest` (underscore — hyphens aren't valid in Python module names).
- Every new package **must** ship its own `README.md` beside its `pyproject.toml` before the `readme = "README.md"` key is added — Phase 0's final review caught this exact packaging bug (a `readme` key pointing at a file that doesn't exist beside the manifest silently drops the package's long description). Task 1 creates this file as part of package scaffolding, not as an afterthought.

---

### Task 1: Scaffold `packages/ingest/` as the workspace's second member

**Files:**
- Create: `packages/ingest/pyproject.toml`
- Create: `packages/ingest/README.md`
- Create: `packages/ingest/munim_ingest/__init__.py`
- Create: `packages/ingest/munim_ingest/cli.py`
- Create: `packages/ingest/tests/__init__.py`
- Create: `packages/ingest/tests/test_cli.py`

**Interfaces:**
- Consumes: nothing (first task; the workspace root from Phase 0 already exists and needs no changes).
- Produces: a working `munim-ingest` console script installed via `uv run --package munim-ingest <cmd>`, and a `typer.Typer` instance at `munim_ingest.cli:app` that later tasks (2-5) attach subcommands to. This is what Task 5 imports and extends.

- [ ] **Step 1: Write the failing test**

`packages/ingest/tests/test_cli.py`:

```python
from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def test_help_runs_and_mentions_the_package():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "munim-ingest" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/ingest && python3 -m pytest tests/test_cli.py -v` (this will fail with `ModuleNotFoundError: No module named 'munim_ingest'` — expected, the package doesn't exist yet)

- [ ] **Step 3: Write `packages/ingest/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "munim-ingest"
version = "0.1.0"
description = "Statement ingestion for munim: pulls bank statement attachments from email into a local folder for munim to classify."
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
dependencies = [
  "typer>=0.12",
  "rich>=13.0",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[project.scripts]
munim-ingest = "munim_ingest.cli:app"

[tool.setuptools.packages.find]
include = ["munim_ingest*"]

[tool.setuptools.package-data]
munim_ingest = ["packs/*.yaml"]
```

- [ ] **Step 4: Write `packages/ingest/README.md`**

```markdown
# munim-ingest

Pulls bank statement attachments from Gmail (via IMAP + an app password —
no OAuth, no Google Cloud project) into a local folder, so
[`munim import`](../classify/README.md) can classify them.

Part of the [munim uv workspace](../../docs/phases.md) — see the repo
root [README](../../README.md) for the full picture.
```

- [ ] **Step 5: Write `packages/ingest/munim_ingest/__init__.py`** (empty file)

- [ ] **Step 6: Write `packages/ingest/munim_ingest/cli.py`**

```python
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


if __name__ == "__main__":
    app()
```

- [ ] **Step 7: Write `packages/ingest/tests/__init__.py`** (empty file)

- [ ] **Step 8: Sync the workspace and confirm both members resolve**

Run from the repo root:

```bash
uv sync --all-extras
uv run --package munim-ingest munim-ingest --help
```

Expected: installs `munim-ingest` alongside the existing `munim` package; `--help` prints the Typer help banner including "munim-ingest — pull bank statement attachments from email into a local folder."

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_cli.py -v`
Expected: `1 passed`

- [ ] **Step 10: Confirm Phase 0's package still works untouched**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: `15 passed` — this task must not disturb `packages/classify/` at all.

- [ ] **Step 11: Commit**

```bash
git add packages/ingest
git commit -m "Scaffold packages/ingest as the workspace's second member"
```

---

### Task 2: Bank search-pack loader

**Files:**
- Create: `packages/ingest/munim_ingest/packs.py`
- Create: `packages/ingest/munim_ingest/packs/hdfc.yaml`
- Create: `packages/ingest/munim_ingest/packs/sib.yaml`
- Create: `packages/ingest/munim_ingest/packs/sbi.yaml`
- Create: `packages/ingest/tests/test_packs.py`

**Interfaces:**
- Consumes: Task 1's package skeleton (this task adds a sibling module, no changes to `cli.py` yet).
- Produces: `BankPack` dataclass (`bank: str`, `from_domains: list[str]`, `attachment_extensions: list[str]`), `load_pack(bank: str) -> BankPack`, `list_packs() -> list[str]`, `PackNotFoundError` exception — Task 3's CLI wiring (Task 5) and this task's own tests are the only consumers of these exact names.

**Important — read before writing the pack files:** the `from_domains` values below are placeholders based on general knowledge of these banks' likely sending domains, not verified against any real inbox. Nobody implementing this plan has access to the user's actual statement emails. Write them as given below, but Task 5's final step explicitly tells the human to open a real statement email from each bank and correct these files against the actual `From:` address before trusting `--dry-run` output. Do not present these as confirmed-correct in your commit message or report.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_packs.py`:

```python
import pytest

from munim_ingest.packs import PackNotFoundError, list_packs, load_pack


def test_load_hdfc_pack():
    pack = load_pack("hdfc")
    assert pack.bank == "hdfc"
    assert "hdfcbank.net" in pack.from_domains
    assert ".csv" in pack.attachment_extensions
    assert ".pdf" in pack.attachment_extensions


def test_load_sib_pack():
    pack = load_pack("sib")
    assert pack.bank == "sib"
    assert len(pack.from_domains) > 0


def test_load_sbi_pack():
    pack = load_pack("sbi")
    assert pack.bank == "sbi"
    assert len(pack.from_domains) > 0


def test_load_unknown_bank_raises_with_available_list():
    with pytest.raises(PackNotFoundError) as exc_info:
        load_pack("nonexistent_bank_xyz")
    assert "hdfc" in str(exc_info.value)


def test_list_packs_includes_all_three():
    packs = list_packs()
    assert {"hdfc", "sib", "sbi"}.issubset(set(packs))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_packs.py -v`
Expected: `ModuleNotFoundError: No module named 'munim_ingest.packs'`

- [ ] **Step 3: Write `packages/ingest/munim_ingest/packs.py`**

```python
"""Bank search packs: which sender domains and attachment types identify a
bank's statement emails. Mirrors packages/classify's region-pack pattern
(packages/classify/munim/normalize/packs/).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PACKS_DIR = Path(__file__).parent / "packs"


@dataclass
class BankPack:
    bank: str
    from_domains: list[str] = field(default_factory=list)
    attachment_extensions: list[str] = field(default_factory=list)


class PackNotFoundError(Exception):
    pass


def load_pack(bank: str) -> BankPack:
    pack_file = PACKS_DIR / f"{bank}.yaml"
    if not pack_file.exists():
        available = ", ".join(list_packs())
        raise PackNotFoundError(f"No pack for {bank!r}. Available: {available}")
    data = yaml.safe_load(pack_file.read_text())
    return BankPack(
        bank=data["bank"],
        from_domains=data.get("from_domains", []),
        attachment_extensions=data.get("attachment_extensions", [".csv", ".pdf"]),
    )


def list_packs() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.yaml"))
```

- [ ] **Step 4: Write `packages/ingest/munim_ingest/packs/hdfc.yaml`**

```yaml
bank: hdfc
# PLACEHOLDER — verify against a real HDFC statement email's From: address
# before relying on this. See Task 5's final step.
from_domains:
  - hdfcbank.net
  - hdfcbank.com
attachment_extensions:
  - .csv
  - .pdf
```

- [ ] **Step 5: Write `packages/ingest/munim_ingest/packs/sib.yaml`**

```yaml
bank: sib
# PLACEHOLDER — verify against a real South Indian Bank statement email's
# From: address before relying on this. See Task 5's final step.
from_domains:
  - sib.co.in
  - southindianbank.com
attachment_extensions:
  - .csv
  - .pdf
```

- [ ] **Step 6: Write `packages/ingest/munim_ingest/packs/sbi.yaml`**

```yaml
bank: sbi
# PLACEHOLDER — verify against a real SBI statement email's From: address
# before relying on this. See Task 5's final step.
from_domains:
  - sbi.co.in
  - onlinesbi.sbi
attachment_extensions:
  - .csv
  - .pdf
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_packs.py -v`
Expected: `5 passed`

- [ ] **Step 8: Commit**

```bash
git add packages/ingest/munim_ingest/packs.py packages/ingest/munim_ingest/packs packages/ingest/tests/test_packs.py
git commit -m "Add bank search-pack loader with placeholder hdfc/sib/sbi packs"
```

---

### Task 3: IMAP client — connect and build a from-domain search query

**Files:**
- Create: `packages/ingest/munim_ingest/imap_client.py`
- Create: `packages/ingest/tests/test_imap_client.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 directly (this module has no dependency on `packs.py` — it takes a plain `list[str]` of domains, decoupling IMAP mechanics from pack-loading).
- Produces: `ImapConfig` dataclass (`host: str`, `port: int`, `email: str`, `password: str`), `connect(config: ImapConfig) -> imaplib.IMAP4_SSL`, `build_from_query(from_domains: list[str]) -> bytes`, `search_uids(conn, mailbox: str, from_domains: list[str]) -> list[bytes]` — Task 5's CLI wiring is the consumer of all four names.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_imap_client.py`:

```python
from unittest.mock import MagicMock

import pytest

from munim_ingest.imap_client import build_from_query, search_uids


def test_build_from_query_single_domain():
    assert build_from_query(["hdfcbank.net"]) == b'(FROM "hdfcbank.net")'


def test_build_from_query_two_domains_ors_them():
    query = build_from_query(["hdfcbank.net", "hdfcbank.com"])
    assert query == b'(OR (FROM "hdfcbank.net") (FROM "hdfcbank.com"))'


def test_build_from_query_three_domains_nests_or():
    query = build_from_query(["a.com", "b.com", "c.com"])
    assert query == b'(OR (FROM "a.com") (OR (FROM "b.com") (FROM "c.com")))'


def test_build_from_query_empty_raises():
    with pytest.raises(ValueError):
        build_from_query([])


def test_search_uids_selects_mailbox_readonly_and_searches():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("OK", [b"12 13 14"])

    uids = search_uids(conn, "INBOX", ["hdfcbank.net"])

    conn.select.assert_called_once_with("INBOX", readonly=True)
    conn.search.assert_called_once()
    assert uids == [b"12", b"13", b"14"]


def test_search_uids_empty_results():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("OK", [b""])

    uids = search_uids(conn, "INBOX", ["hdfcbank.net"])

    assert uids == []


def test_search_uids_raises_on_search_failure():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("NO", [None])

    with pytest.raises(RuntimeError):
        search_uids(conn, "INBOX", ["hdfcbank.net"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_imap_client.py -v`
Expected: `ModuleNotFoundError: No module named 'munim_ingest.imap_client'`

- [ ] **Step 3: Write `packages/ingest/munim_ingest/imap_client.py`**

```python
"""IMAP connection and search for bank statement emails. Standard library
only (imaplib) — no OAuth, no external API, just IMAP + an app password.
"""
from __future__ import annotations

import imaplib
from dataclasses import dataclass


@dataclass
class ImapConfig:
    host: str
    port: int
    email: str
    password: str


def connect(config: ImapConfig) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config.host, config.port)
    conn.login(config.email, config.password)
    return conn


def build_from_query(from_domains: list[str]) -> bytes:
    """Build an IMAP SEARCH criteria string matching any of the given
    sender domains. A single domain is `(FROM "domain")`; more are OR'd:
    `(OR (FROM "a") (OR (FROM "b") (FROM "c")))`.
    """
    if not from_domains:
        raise ValueError("from_domains must be non-empty")
    terms = [f'(FROM "{d}")' for d in from_domains]
    query = terms[-1]
    for term in reversed(terms[:-1]):
        query = f"(OR {term} {query})"
    return query.encode()


def search_uids(conn: imaplib.IMAP4_SSL, mailbox: str, from_domains: list[str]) -> list[bytes]:
    conn.select(mailbox, readonly=True)
    query = build_from_query(from_domains)
    status, data = conn.search(None, query)
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    if not data or not data[0]:
        return []
    return data[0].split()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_imap_client.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add packages/ingest/munim_ingest/imap_client.py packages/ingest/tests/test_imap_client.py
git commit -m "Add IMAP client: connect and build a from-domain search query"
```

---

### Task 4: Attachment extraction and safe file saving

**Files:**
- Create: `packages/ingest/munim_ingest/attachments.py`
- Create: `packages/ingest/tests/test_attachments.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-3 (pure functions over raw bytes and paths — no dependency on `packs.py` or `imap_client.py`).
- Produces: `extract_attachments(raw_message: bytes, extensions: list[str]) -> list[tuple[str, bytes]]`, `save_attachments(attachments: list[tuple[str, bytes]], out_dir: Path) -> list[Path]` — Task 5's CLI wiring is the consumer of both names.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_attachments.py`:

```python
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from munim_ingest.attachments import extract_attachments, save_attachments


def _message_with_attachment(filename: str, content: bytes) -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = "Your statement"
    msg["From"] = "alerts@hdfcbank.net"
    msg.attach(MIMEText("See attached.", "plain"))
    part = MIMEApplication(content, Name=filename)
    part["Content-Disposition"] = f'attachment; filename="{filename}"'
    msg.attach(part)
    return msg.as_bytes()


def test_extract_attachments_finds_matching_extension():
    raw = _message_with_attachment("statement.csv", b"date,amount\n2026-06-01,100")
    found = extract_attachments(raw, [".csv", ".pdf"])
    assert len(found) == 1
    filename, content = found[0]
    assert filename == "statement.csv"
    assert content == b"date,amount\n2026-06-01,100"


def test_extract_attachments_ignores_non_matching_extension():
    raw = _message_with_attachment("logo.png", b"\x89PNG fake bytes")
    found = extract_attachments(raw, [".csv", ".pdf"])
    assert found == []


def test_extract_attachments_no_attachment_returns_empty():
    msg = MIMEMultipart()
    msg["Subject"] = "No attachment here"
    msg.attach(MIMEText("Just text.", "plain"))
    found = extract_attachments(msg.as_bytes(), [".csv", ".pdf"])
    assert found == []


def test_extract_attachments_matches_case_insensitively():
    raw = _message_with_attachment("STATEMENT.CSV", b"data")
    found = extract_attachments(raw, [".csv"])
    assert len(found) == 1


def test_save_attachments_writes_files(tmp_path):
    saved = save_attachments([("statement.csv", b"hello")], tmp_path / "hdfc")
    assert len(saved) == 1
    assert saved[0].read_bytes() == b"hello"
    assert saved[0].name == "statement.csv"


def test_save_attachments_creates_out_dir(tmp_path):
    out_dir = tmp_path / "does" / "not" / "exist" / "yet"
    saved = save_attachments([("a.csv", b"x")], out_dir)
    assert out_dir.exists()
    assert saved[0].parent == out_dir


def test_save_attachments_strips_path_traversal_from_filename(tmp_path):
    """A malicious email attachment filename must not be able to write
    outside out_dir — e.g. '../../etc/passwd' must save as 'passwd'
    inside out_dir, never traverse up."""
    out_dir = tmp_path / "out"
    saved = save_attachments([("../../etc/passwd", b"evil")], out_dir)
    assert saved[0].name == "passwd"
    assert saved[0].parent == out_dir
    assert saved[0] == out_dir / "passwd"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_attachments.py -v`
Expected: `ModuleNotFoundError: No module named 'munim_ingest.attachments'`

- [ ] **Step 3: Write `packages/ingest/munim_ingest/attachments.py`**

```python
"""Extract matching attachments from a raw RFC822 email message and save
them safely to a local folder.
"""
from __future__ import annotations

import email
from pathlib import Path


def extract_attachments(raw_message: bytes, extensions: list[str]) -> list[tuple[str, bytes]]:
    """Returns [(filename, content_bytes), ...] for every attachment whose
    filename ends with one of the given extensions (case-insensitive).
    """
    msg = email.message_from_bytes(raw_message)
    found = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        if any(filename.lower().endswith(ext.lower()) for ext in extensions):
            payload = part.get_payload(decode=True)
            if payload:
                found.append((filename, payload))
    return found


def save_attachments(attachments: list[tuple[str, bytes]], out_dir: Path) -> list[Path]:
    """Saves each attachment into out_dir, stripping any path components
    from the filename first — an email attachment's filename is untrusted
    input and must never be used to write outside out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for filename, content in attachments:
        safe_name = Path(filename).name
        dest = out_dir / safe_name
        dest.write_bytes(content)
        saved.append(dest)
    return saved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_attachments.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add packages/ingest/munim_ingest/attachments.py packages/ingest/tests/test_attachments.py
git commit -m "Add attachment extraction with path-traversal-safe saving"
```

---

### Task 5: Wire it together — `munim-ingest gmail fetch` and `gmail list-banks`

**Files:**
- Modify: `packages/ingest/munim_ingest/cli.py`
- Create: `packages/ingest/tests/test_cli_gmail.py`

**Interfaces:**
- Consumes: `load_pack`/`list_packs`/`PackNotFoundError` (Task 2), `ImapConfig`/`connect`/`search_uids` (Task 3), `extract_attachments`/`save_attachments` (Task 4).
- Produces: the finished `munim-ingest gmail fetch <bank>` and `munim-ingest gmail list-banks` commands — nothing downstream in this plan consumes these (this is the last task); Phase 2 (PDF extraction, a separate future plan) will read the files this command saves to disk, but does not import any Python name from this module.

- [ ] **Step 1: Write the failing tests**

`packages/ingest/tests/test_cli_gmail.py`:

```python
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def test_list_banks_prints_all_three():
    result = runner.invoke(app, ["gmail", "list-banks"])
    assert result.exit_code == 0
    assert "hdfc" in result.output
    assert "sib" in result.output
    assert "sbi" in result.output


def test_fetch_unknown_bank_exits_nonzero():
    # Pack lookup fails before any password prompt, so no stdin/getpass
    # patching is needed for this path.
    result = runner.invoke(
        app, ["gmail", "fetch", "nonexistent_bank_xyz", "--email", "me@example.com"],
    )
    assert result.exit_code == 1
    assert "no pack" in result.output.lower() or "nonexistent_bank_xyz" in result.output.lower()


def test_fetch_dry_run_does_not_write_files(tmp_path):
    # getpass.getpass() opens /dev/tty directly on most platforms and does
    # NOT reliably read from CliRunner's `input=` stdin redirection — patch
    # it directly rather than relying on stdin feeding, so this test is not
    # flaky depending on whether the sandbox running it has a controlling tty.
    fake_conn = MagicMock()

    with patch("munim_ingest.cli.connect", return_value=fake_conn) as mock_connect, \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]) as mock_search, \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", _sample_message_bytes())])

        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com",
             "--out", str(tmp_path / "out"), "--dry-run"],
        )

    assert result.exit_code == 0
    assert "would save" in result.output.lower() or "dry run" in result.output.lower()
    assert not (tmp_path / "out").exists()
    mock_connect.assert_called_once()
    mock_search.assert_called_once()
    fake_conn.logout.assert_called_once()


def test_fetch_saves_matching_attachment(tmp_path):
    fake_conn = MagicMock()

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", _sample_message_bytes())])

        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com",
             "--out", str(tmp_path / "out")],
        )

    assert result.exit_code == 0
    saved_file = tmp_path / "out" / "statement.csv"
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"date,amount\n2026-06-01,100"
    fake_conn.logout.assert_called_once()


def _sample_message_bytes() -> bytes:
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["Subject"] = "Your statement"
    msg["From"] = "alerts@hdfcbank.net"
    msg.attach(MIMEText("See attached.", "plain"))
    part = MIMEApplication(b"date,amount\n2026-06-01,100", Name="statement.csv")
    part["Content-Disposition"] = 'attachment; filename="statement.csv"'
    msg.attach(part)
    return msg.as_bytes()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_cli_gmail.py -v`
Expected: fails — no `gmail` subcommand exists yet on `app`.

- [ ] **Step 3: Extend `packages/ingest/munim_ingest/cli.py`**

Replace the file's contents with:

```python
"""munim-ingest CLI: pull bank statement attachments from email into a
local folder for munim to classify.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path

import typer
from rich.console import Console

from .attachments import extract_attachments, save_attachments
from .imap_client import ImapConfig, connect, search_uids
from .packs import PackNotFoundError, list_packs, load_pack

app = typer.Typer(
    help="munim-ingest — pull bank statement attachments from email into a local folder.",
    no_args_is_help=True, add_completion=False,
)
console = Console()

gmail_app = typer.Typer(help="Fetch bank statement attachments from Gmail via IMAP.")
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
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    password = os.environ.get("MUNIM_GMAIL_APP_PASSWORD") or getpass.getpass(
        f"App password for {email} (never stored): ")

    config = ImapConfig(host=imap_host, port=imap_port, email=email, password=password)
    conn = connect(config)
    try:
        uids = search_uids(conn, mailbox, pack.from_domains)
        console.print(f"Found {len(uids)} message(s) from {bank} senders in {mailbox}.")

        total = 0
        out_dir = out or (DEFAULT_HOME / "downloads" / bank)
        for uid in uids:
            status, data = conn.fetch(uid, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                continue
            raw = data[0][1]
            found = extract_attachments(raw, pack.attachment_extensions)
            if not found:
                continue
            if dry_run:
                for filename, _content in found:
                    console.print(f"  [dim]would save:[/dim] {filename}")
                total += len(found)
            else:
                saved = save_attachments(found, out_dir)
                for path in saved:
                    console.print(f"  [green]saved:[/green] {path}")
                total += len(saved)

        if dry_run:
            console.print(f"\n[bold]{total}[/bold] attachment(s) would be downloaded (dry run).")
        else:
            console.print(f"\n[bold]{total}[/bold] attachment(s) downloaded to {out_dir}.")
    finally:
        conn.logout()


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package munim-ingest pytest packages/ingest/tests/test_cli_gmail.py -v`
Expected: `4 passed`. If a test fails because of the placeholder-seam line noted in Step 1, simplify that one test as instructed there and re-run — don't spend more than one iteration on it.

- [ ] **Step 5: Run the full ingest test suite**

Run: `uv run --package munim-ingest pytest packages/ingest/tests -v`
Expected: `24 passed` (1 from Task 1 + 5 from Task 2 + 7 from Task 3 + 7 from Task 4 + 4 from Task 5). If the count doesn't match, something regressed — investigate before moving on, don't just note the discrepancy and continue.

- [ ] **Step 6: Confirm `packages/classify` is still untouched**

Run: `uv run --package munim pytest packages/classify/tests -q`
Expected: `15 passed`

- [ ] **Step 7: Commit**

```bash
git add packages/ingest/munim_ingest/cli.py packages/ingest/tests/test_cli_gmail.py
git commit -m "Wire gmail fetch/list-banks commands into munim-ingest"
```

- [ ] **Step 8: Update the roadmap**

In `docs/phases.md`, under the `## Phase 1 — Ingest: Gmail fetch` heading:

1. Change `**Status: not started**` to `**Status: done**`.
2. Replace the existing `Plan: not yet written.` line (mirroring how Phase 0's entry links to its plan) with:

```markdown
Plan: [superpowers/plans/2026-08-29-gmail-ingest.md](superpowers/plans/2026-08-29-gmail-ingest.md)
```

Don't leave both the old `Plan: not yet written.` line and the new one — replace it in place. Leave Phase 2's and Phase 3's sections (which also currently say `Plan: not yet written.`) untouched — this step only touches Phase 1's section.

Commit:

```bash
git add docs/phases.md
git commit -m "Mark Phase 1 (Gmail ingest) done in the roadmap"
```

---

## Post-plan state: manual verification required (human, not a subagent)

Everything above is tested with mocks and fixtures — no automated step in this plan has touched a real mailbox. Before relying on this for real bank statements, **you** (not an agent) need to:

1. Create a Gmail [app password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification enabled on the account).
2. Open one real statement email from each bank you use and check its actual `From:` address — correct `packages/ingest/munim_ingest/packs/{hdfc,sib,sbi}.yaml`'s `from_domains` if they don't match what Task 2 guessed.
3. Run a dry run first: `MUNIM_GMAIL_APP_PASSWORD=<your app password> uv run --package munim-ingest munim-ingest gmail fetch hdfc --email you@gmail.com --dry-run` — confirm it finds the right messages before downloading anything for real.
4. Once the dry run looks right, drop `--dry-run` to actually download.

## What's deliberately out of scope here

- PDF parsing/extraction of downloaded statements — Phase 2, a separate future plan.
- Producing the canonical transaction JSONL contract — that's Phase 2's output, once it can actually read a downloaded CSV/PDF and emit structured transactions.
- Any credential persistence, config file, or "remember my password" convenience feature — deliberately not built in Phase 1 to keep the credential-handling surface as small as possible for a first version.
- IMAP providers other than Gmail (Outlook, Fastmail, etc.) — the code is written generically enough (`imap_host`/`imap_port` are already CLI options, not hardcoded) that adding one later is cheap, but this plan only ships Gmail's defaults and only names the command `gmail fetch`.
