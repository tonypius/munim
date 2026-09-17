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


UNPARSEABLE_SWIGGY_BODY = """Your order is on its way!
Order ID: 999888777
"""  # missing Restaurant icon / Paid Via -- a real format variant we
     # haven't matched, must still be counted as "seen" for this sender


def test_fetch_vouchers_reports_per_sender_seen_vs_parsed_counts(tmp_path, monkeypatch):
    # A parser silently returning None for a real Swiggy/Amazon Pay email
    # (a format variant the regex doesn't match) is otherwise invisible --
    # nothing distinguishes "no voucher mail from this sender" from
    # "dozens of real emails from this sender that all failed to parse".
    # The per-sender breakdown must surface that gap.
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    good_raw = _msg("Your order from Cafe Iftar", "Swiggy <noreply@swiggy.in>",
                    "Wed, 28 Aug 2024 23:17:00 +0530",
                    "ORDER JOURNEY\nRestaurant icon\nRestaurant icon\nCafe Iftar\n"
                    "Order ID: 246907327135063\nPaid Via Credit/Debit card\t\tRs391")
    bad_raw = _msg("Your order is on its way", "Swiggy <noreply@swiggy.in>",
                   "Wed, 28 Aug 2024 20:00:00 +0530", UNPARSEABLE_SWIGGY_BODY)

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.side_effect = [
            ("OK", [(b"1 (RFC822 {123}", good_raw)]),
            ("OK", [(b"2 (RFC822 {123}", bad_raw)]),
        ]
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    assert "swiggy.in" in result.output
    assert "2" in result.output  # 2 seen from swiggy.in
    assert "1" in result.output  # 1 parsed from swiggy.in


def test_fetch_vouchers_dump_unparsed_saves_one_raw_email_per_domain(tmp_path, monkeypatch):
    # When a real fetched email fails to parse, the copy-paste a user can
    # give back is what their mail client RENDERS, not the raw MIME
    # source the parser actually sees (HTML entities, tag structure,
    # multipart layout) -- --dump-unparsed saves the actual raw bytes
    # locally so the real structure can be inspected directly, instead
    # of relying on a human transcription of it.
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    bad_raw = _msg("Your order is on its way", "Swiggy <noreply@swiggy.in>",
                   "Wed, 28 Aug 2024 20:00:00 +0530", UNPARSEABLE_SWIGGY_BODY)

    dump_dir = tmp_path / "dump"
    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", bad_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file), "--dump-unparsed", str(dump_dir)])

    assert result.exit_code == 0, result.output
    dumped = dump_dir / "swiggy.in-order.eml"
    assert dumped.exists()
    assert dumped.read_bytes() == bad_raw


def test_fetch_vouchers_dump_unparsed_only_saves_one_per_domain_and_category(tmp_path, monkeypatch):
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    first_bad = _msg("Your order is on its way", "Swiggy <noreply@swiggy.in>",
                     "Wed, 28 Aug 2024 20:00:00 +0530", UNPARSEABLE_SWIGGY_BODY)
    second_bad = _msg("Order update", "Swiggy <noreply@swiggy.in>",
                      "Wed, 28 Aug 2024 21:00:00 +0530",
                      "A different order id: 111222333, still unparseable.")

    dump_dir = tmp_path / "dump"
    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.side_effect = [
            ("OK", [(b"1 (RFC822 {123}", first_bad)]),
            ("OK", [(b"2 (RFC822 {123}", second_bad)]),
        ]
        out_file = tmp_path / "vouchers.jsonl"
        runner.invoke(app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                            "--out", str(out_file), "--dump-unparsed", str(dump_dir)])

    dumped = dump_dir / "swiggy.in-order.eml"
    assert dumped.read_bytes() == first_bad  # not overwritten by the second, same category


def test_fetch_vouchers_dump_unparsed_saves_distinct_categories_separately(tmp_path, monkeypatch):
    # A food-delivery order and a Dineout order both fail to parse for
    # different reasons -- both should be captured in one run, not just
    # whichever comes first.
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    food_order_raw = _msg("Your order from Cafe X", "Swiggy <noreply@swiggy.in>",
                          "Wed, 28 Aug 2024 20:00:00 +0530",
                          "ORDER JOURNEY\nRestaurant icon\nRestaurant icon\nCafe X\n"
                          "Order ID: 555\nsomething unmatched here")
    dineout_raw = _msg("Your Swiggy Dineout payment", "Swiggy Dineout <noreply@swiggy.in>",
                       "Wed, 28 Aug 2024 21:00:00 +0530",
                       "Your Dineout payment. Order ID: 777\nsomething unmatched")

    dump_dir = tmp_path / "dump"
    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1", b"2"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.side_effect = [
            ("OK", [(b"1 (RFC822 {123}", food_order_raw)]),
            ("OK", [(b"2 (RFC822 {123}", dineout_raw)]),
        ]
        out_file = tmp_path / "vouchers.jsonl"
        runner.invoke(app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                            "--out", str(out_file), "--dump-unparsed", str(dump_dir)])

    assert (dump_dir / "swiggy.in-food-delivery-order.eml").read_bytes() == food_order_raw
    assert (dump_dir / "swiggy.in-dineout.eml").read_bytes() == dineout_raw
