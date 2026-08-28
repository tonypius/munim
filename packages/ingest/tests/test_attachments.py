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
