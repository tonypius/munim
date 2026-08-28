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


def test_save_attachments_disambiguates_same_basename_in_one_call(tmp_path):
    """Every month's statement is often literally named 'Statement.csv'.
    Saving several in one call must keep all of them, not silently
    overwrite — and the returned list must be the real files written so
    the CLI's count is honest."""
    out_dir = tmp_path / "out"
    saved = save_attachments(
        [
            ("Statement.csv", b"january"),
            ("Statement.csv", b"february"),
            ("Statement.csv", b"march"),
        ],
        out_dir,
    )

    assert len(saved) == 3
    assert [p.name for p in saved] == [
        "Statement.csv", "Statement (2).csv", "Statement (3).csv",
    ]
    # All three exist on disk with their own original content.
    assert all(p.exists() for p in saved)
    assert saved[0].read_bytes() == b"january"
    assert saved[1].read_bytes() == b"february"
    assert saved[2].read_bytes() == b"march"
    assert len(list(out_dir.iterdir())) == 3


def test_save_attachments_disambiguates_after_path_traversal_stripping(tmp_path):
    """Deduplication composes with the path-traversal guard: two different
    traversal paths that sanitize to the same basename must not clobber
    each other, and must still land inside out_dir."""
    out_dir = tmp_path / "out"
    saved = save_attachments(
        [("../../a/passwd", b"first"), ("../../../b/passwd", b"second")], out_dir,
    )

    assert len(saved) == 2
    assert [p.name for p in saved] == ["passwd", "passwd (2)"]
    assert all(p.parent == out_dir for p in saved)
    assert saved[0].read_bytes() == b"first"
    assert saved[1].read_bytes() == b"second"


def test_save_attachments_disambiguates_case_insensitively(tmp_path):
    """On macOS/Windows 'Statement.csv' and 'STATEMENT.CSV' are the same
    file, so they must be disambiguated too."""
    out_dir = tmp_path / "out"
    saved = save_attachments(
        [("Statement.csv", b"one"), ("STATEMENT.CSV", b"two")], out_dir,
    )

    assert len(saved) == 2
    assert saved[0].name == "Statement.csv"
    assert saved[1].name == "STATEMENT (2).CSV"
    assert saved[0].read_bytes() == b"one"
    assert saved[1].read_bytes() == b"two"


def test_save_attachments_extensionless_names_disambiguate(tmp_path):
    out_dir = tmp_path / "out"
    saved = save_attachments([("statement", b"a"), ("statement", b"b")], out_dir)
    assert [p.name for p in saved] == ["statement", "statement (2)"]
    assert saved[1].read_bytes() == b"b"


def test_save_attachments_disambiguates_across_separate_calls(tmp_path):
    """The CLI calls save_attachments once per message, so a collision
    between two messages shows up as a collision with a file already on
    disk — it must be disambiguated too, not overwritten."""
    out_dir = tmp_path / "out"
    first = save_attachments([("Statement.csv", b"january")], out_dir)
    second = save_attachments([("Statement.csv", b"february")], out_dir)

    assert first[0].name == "Statement.csv"
    assert second[0].name == "Statement (2).csv"
    assert first[0].read_bytes() == b"january"
    assert second[0].read_bytes() == b"february"


def test_save_attachments_refetching_identical_content_is_idempotent(tmp_path):
    """Re-running the same fetch must not pile up '(2)', '(3)', ... copies
    of a file that is already there byte-for-byte."""
    out_dir = tmp_path / "out"
    for _ in range(3):
        saved = save_attachments([("Statement.csv", b"same-bytes")], out_dir)
        assert [p.name for p in saved] == ["Statement.csv"]

    assert len(list(out_dir.iterdir())) == 1
    assert (out_dir / "Statement.csv").read_bytes() == b"same-bytes"


def test_save_attachments_does_not_overwrite_a_preexisting_different_file(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "Statement.csv").write_bytes(b"precious existing data")

    saved = save_attachments([("Statement.csv", b"new")], out_dir)

    assert saved[0].name == "Statement (2).csv"
    assert (out_dir / "Statement.csv").read_bytes() == b"precious existing data"


def test_save_attachments_skips_past_a_directory_in_the_way(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "Statement.csv").mkdir()

    saved = save_attachments([("Statement.csv", b"data")], out_dir)

    assert saved[0].name == "Statement (2).csv"
    assert saved[0].read_bytes() == b"data"


def test_save_attachments_strips_path_traversal_from_filename(tmp_path):
    """A malicious email attachment filename must not be able to write
    outside out_dir — e.g. '../../etc/passwd' must save as 'passwd'
    inside out_dir, never traverse up."""
    out_dir = tmp_path / "out"
    saved = save_attachments([("../../etc/passwd", b"evil")], out_dir)
    assert saved[0].name == "passwd"
    assert saved[0].parent == out_dir
    assert saved[0] == out_dir / "passwd"


def test_save_attachments_skips_dangerous_dotdot_and_dot_filenames(tmp_path):
    """Edge case: filenames that sanitize to '.' or '..' must be skipped,
    as they would escape out_dir or overwrite it."""
    out_dir = tmp_path / "out"

    # Try to save attachments with dangerous sanitized names
    saved = save_attachments(
        [
            ("..", b"dangerous1"),
            (".", b"dangerous2"),
            ("foo/..", b"dangerous3"),
            ("normal.csv", b"safe"),
        ],
        out_dir,
    )

    # Only the normal file should be saved
    assert len(saved) == 1
    assert saved[0].name == "normal.csv"
    assert saved[0].read_bytes() == b"safe"

    # Verify only normal.csv exists in out_dir (no dangerous files)
    files_in_out_dir = list(out_dir.iterdir())
    assert len(files_in_out_dir) == 1
    assert files_in_out_dir[0].name == "normal.csv"
