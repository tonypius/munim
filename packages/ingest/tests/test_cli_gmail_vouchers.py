import json
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def _msg(subject, from_addr, date_header, body) -> bytes:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date_header
    return msg.as_bytes()


GYFTR_BODY = """Please find your instant voucher details.

Swiggy Money Voucher
Swiggy Money Voucher

E-Gift Card Code
VGHDR7VACB6SD15E

Value
2000
PIN
525269

Valid Till
06 Mar 2027
"""


def test_fetch_vouchers_writes_jsonl_records(tmp_path, monkeypatch):
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    gyftr_raw = _msg(
        "Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
        "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_BODY)

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", gyftr_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "purchase"
    assert record["brand"] == "swiggy"
    assert record["value"] == 2000.0
    assert record["purchased_at"] == "2026-09-14"


def test_fetch_vouchers_skips_unparseable_messages(tmp_path, monkeypatch):
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    unrelated_raw = _msg("Hello", "someone@example.com",
                         "Mon, 14 Sep 2026 12:09:00 +0530", "Not a voucher.")

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", unrelated_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    assert "0" in result.output
    assert not out_file.exists() or out_file.read_text().strip() == ""
