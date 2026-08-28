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
