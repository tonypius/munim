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
    assert record["brand"] == "gyftr"
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
    assert "0 voucher record(s) found" in result.output
    assert not out_file.exists() or out_file.read_text().strip() == ""


def test_fetch_vouchers_warns_and_counts_unrecognized_gyftr_brand(tmp_path, monkeypatch):
    # A genuine GYFTR purchase email with a brand not in GYFTR_BRAND_MAP
    # must be distinguishable from "not a voucher email at all" -- it
    # should print a warning naming the unmatched product line and be
    # called out separately in the summary, not just silently produce 0
    # records indistinguishable from an inbox with no voucher mail.
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    croma_raw = _msg(
        "Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
        "Mon, 14 Sep 2026 14:09:00 +0530",
        GYFTR_BODY.replace("Swiggy Money Voucher", "Croma Voucher"))

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", croma_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    assert "Croma Voucher" in result.output
    assert "unrecognized" in result.output.lower()
    assert "0 voucher record(s) found" in result.output
    assert not out_file.exists() or out_file.read_text().strip() == ""
