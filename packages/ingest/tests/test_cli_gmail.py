import pytest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from munim_ingest.cli import app, gmail_app

runner = CliRunner()

FAKE_PASSWORD = "hunter2-totally-distinctive-app-password"


@pytest.fixture(autouse=True)
def _no_password_env(monkeypatch):
    """Never let a real MUNIM_GMAIL_APP_PASSWORD in the developer's shell
    leak into these tests — every test patches getpass instead."""
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)


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


# --- Finding 1: the app password must never reach the terminal ------------

def test_typer_apps_disable_pretty_exception_locals():
    """Typer's locals table would print the `password` local verbatim on any
    unhandled exception. Both Typer apps must opt out explicitly, rather
    than relying on whichever typer version happens to be installed."""
    assert app.pretty_exceptions_show_locals is False
    assert gmail_app.pretty_exceptions_show_locals is False


def test_fetch_connect_failure_exits_cleanly_without_leaking_password():
    """A wrong password or unreachable server must produce a one-line error
    and exit 1 — never an unhandled exception, and never the password."""
    import imaplib

    with patch("munim_ingest.cli.connect",
               side_effect=imaplib.IMAP4.error(
                   b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app, ["gmail", "fetch", "hdfc", "--email", "me@example.com"],
        )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "could not connect or log in" in result.output.lower()
    assert FAKE_PASSWORD not in result.output
    assert "Traceback" not in result.output


def test_fetch_connect_failure_message_does_not_echo_credentials():
    """Even if the underlying exception text is hostile, the printed error
    must not carry the password through."""
    with patch("munim_ingest.cli.connect",
               side_effect=OSError("connection refused")), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app, ["gmail", "fetch", "hdfc", "--email", "me@example.com"],
        )

    assert result.exit_code == 1
    assert FAKE_PASSWORD not in result.output
    assert "connection refused" in result.output


# --- Finding 3: sender-controlled filenames are not Rich markup -----------

@pytest.mark.parametrize("evil_name", ["[red]evil.csv", "[/red]x.csv", "[bold]a[/]b.csv"])
def test_dry_run_renders_markup_filenames_literally(tmp_path, evil_name):
    """An attachment filename containing Rich markup must neither crash the
    run (MarkupError) nor be consumed as styling — --dry-run is the
    documented safety check, so it must show the real name."""
    fake_conn = MagicMock()
    fake_conn.fetch.return_value = (
        "OK", [(b"1 (RFC822 {123}", _sample_message_bytes(filename=evil_name))],
    )

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com",
             "--out", str(tmp_path / "out"), "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert evil_name in result.output
    assert "1 attachment(s) would be downloaded" in result.output


def test_real_run_renders_markup_filenames_literally(tmp_path):
    fake_conn = MagicMock()
    fake_conn.fetch.return_value = (
        "OK", [(b"1 (RFC822 {123}", _sample_message_bytes(filename="[red]evil.csv"))],
    )
    out_dir = tmp_path / "out"

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    assert (out_dir / "[red]evil.csv").exists()
    assert "[red]evil.csv" in result.output


def test_unknown_bank_with_markup_in_name_exits_cleanly():
    """The PackNotFoundError message embeds the caller-supplied bank name."""
    result = runner.invoke(app, ["gmail", "fetch", "[/red]", "--email", "me@example.com"])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "[/red]" in result.output


# --- Finding 2: the reported count matches the files actually written -----

def test_fetch_reports_real_count_for_same_named_attachments(tmp_path):
    """Two messages whose attachments share a filename must both survive on
    disk, and the reported total must be the number of files written."""
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()
    bodies = {
        b"1": _sample_message_bytes(filename="Statement.csv", content=b"january"),
        b"2": _sample_message_bytes(filename="Statement.csv", content=b"february"),
    }
    fake_conn.fetch.side_effect = lambda uid, _spec: ("OK", [(b"hdr", bodies[uid])])

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    written = sorted(p.name for p in out_dir.iterdir())
    assert written == ["Statement (2).csv", "Statement.csv"]
    assert (out_dir / "Statement.csv").read_bytes() == b"january"
    assert (out_dir / "Statement (2).csv").read_bytes() == b"february"
    assert "2 attachment(s) downloaded" in result.output


# --- Finding 5: malformed FETCH response shapes are skipped ---------------

def test_fetch_skips_non_tuple_fetch_response_item(tmp_path):
    """A bare-bytes response item (e.g. b'1 (FLAGS (\\Seen))') must be
    skipped, not silently indexed into an int."""
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()
    fake_conn.fetch.return_value = ("OK", [b"1 (FLAGS (\\Seen))"])

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "0 attachment(s) downloaded" in result.output
    # It must be recognised as a non-message response item and skipped
    # outright — NOT fall through to `raw = item[1]` (which silently yields
    # an int) and only then be rescued by the per-message error handler.
    assert "Skipping message" not in result.output


def test_fetch_continues_past_malformed_item_to_good_message(tmp_path):
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()
    responses = {
        b"1": ("OK", [b"1 (FLAGS (\\Seen))"]),
        b"2": ("OK", [(b"hdr", _sample_message_bytes())]),
    }
    fake_conn.fetch.side_effect = lambda uid, _spec: responses[uid]

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    assert (out_dir / "statement.csv").exists()
    assert "1 attachment(s) downloaded" in result.output


# --- Finding 6: one bad message does not abort the whole run --------------

def test_fetch_isolates_per_message_errors(tmp_path):
    """A message that blows up mid-processing is warned about and skipped;
    the messages before and after it are still downloaded."""
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()

    def _fetch(uid, _spec):
        if uid == b"2":
            raise ValueError("crafted message exploded")
        name = {b"1": "first.csv", b"3": "third.csv"}[uid]
        return ("OK", [(b"hdr", _sample_message_bytes(filename=name))])

    fake_conn.fetch.side_effect = _fetch

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2", b"3"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert (out_dir / "first.csv").exists()
    assert (out_dir / "third.csv").exists()
    assert "Skipping message" in result.output
    assert "crafted message exploded" in result.output
    assert "2 attachment(s) downloaded" in result.output
    fake_conn.logout.assert_called_once()


# --- --since date narrowing -------------------------------------------

def test_fetch_since_invalid_format_exits_cleanly():
    result = runner.invoke(
        app,
        ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--since", "not-a-date"],
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "yyyy-mm-dd" in result.output.lower()


def test_fetch_since_valid_date_is_forwarded_to_search_uids():
    from datetime import date

    fake_conn = MagicMock()
    fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", _sample_message_bytes())])

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]) as mock_search, \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com",
             "--since", "2024-06-01", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    mock_search.assert_called_once()
    _args, kwargs = mock_search.call_args
    assert kwargs.get("since") == date(2024, 6, 1) or date(2024, 6, 1) in mock_search.call_args[0]


def test_fetch_passes_pack_subject_keywords_to_search_uids():
    """The bridge point for subject-line narrowing: the CLI must forward
    the loaded pack's subject_keywords, not just from_domains/since."""
    fake_conn = MagicMock()
    fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", _sample_message_bytes())])

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]) as mock_search, \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    _args, kwargs = mock_search.call_args
    assert kwargs.get("subject_keywords") == ["Credit Card Statement"]


def test_fetch_without_since_passes_none():
    fake_conn = MagicMock()
    fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", _sample_message_bytes())])

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]) as mock_search, \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    _args, kwargs = mock_search.call_args
    since_value = kwargs.get("since") if "since" in kwargs else mock_search.call_args[0][-1]
    assert since_value is None


# --- Circuit breaker: a dead connection must not grind through every -----
# --- remaining message printing the same error one at a time -------------

def test_fetch_stops_after_consecutive_failure_streak(tmp_path):
    """Simulates a broken pipe on every fetch from message 3 onward — the
    command must stop early with a clear message instead of looping
    through all remaining UIDs re-raising the same dead-connection error."""
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()
    uids = [str(i).encode() for i in range(1, 21)]  # 20 messages queued

    def _fetch(uid, _spec):
        if uid in (b"1", b"2"):
            return ("OK", [(b"hdr", _sample_message_bytes(filename=f"{uid.decode()}.csv"))])
        raise OSError("[Errno 32] Broken pipe")

    fake_conn.fetch.side_effect = _fetch

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=uids), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    # The two good messages before the streak were saved.
    assert (out_dir / "1.csv").exists()
    assert (out_dir / "2.csv").exists()
    # It must have stopped well before attempting all 18 remaining UIDs —
    # not ground through every single one printing the identical error.
    assert fake_conn.fetch.call_count < 15
    assert "stopping" in result.output.lower()
    assert "broken pipe" in result.output.lower()


def test_fetch_does_not_trip_breaker_on_interspersed_failures(tmp_path):
    """Occasional isolated failures mixed with successes must not trip the
    circuit breaker — only a sustained streak indicates a dead connection."""
    out_dir = tmp_path / "out"
    fake_conn = MagicMock()
    # Pattern: fail, fail, succeed, fail, fail, succeed, ... never 5 in a row.
    uids = [str(i).encode() for i in range(1, 10)]

    def _fetch(uid, _spec):
        n = int(uid)
        if n % 3 == 0:
            return ("OK", [(b"hdr", _sample_message_bytes(filename=f"{n}.csv"))])
        raise ValueError("transient blip")

    fake_conn.fetch.side_effect = _fetch

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=uids), \
         patch("munim_ingest.cli.getpass.getpass", return_value=FAKE_PASSWORD):
        result = runner.invoke(
            app,
            ["gmail", "fetch", "hdfc", "--email", "me@example.com", "--out", str(out_dir)],
        )

    assert result.exit_code == 0, result.output
    # All 9 UIDs must have been attempted — the breaker must not have
    # tripped on scattered, non-consecutive failures.
    assert fake_conn.fetch.call_count == 9
    assert "stopping" not in result.output.lower()
    assert (out_dir / "3.csv").exists()
    assert (out_dir / "6.csv").exists()
    assert (out_dir / "9.csv").exists()


def _sample_message_bytes(
    filename: str = "statement.csv", content: bytes = b"date,amount\n2026-06-01,100",
) -> bytes:
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg["Subject"] = "Your statement"
    msg["From"] = "alerts@hdfcbank.net"
    msg.attach(MIMEText("See attached.", "plain"))
    part = MIMEApplication(content, Name=filename)
    part["Content-Disposition"] = f'attachment; filename="{filename}"'
    msg.attach(part)
    return msg.as_bytes()
