from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def test_help_runs_and_mentions_the_package():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "munim-ingest" in result.output
