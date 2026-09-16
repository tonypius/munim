"""The `export` CLI command must exclude 'business'-tagged transactions by
default, the same way `report` and the web dashboard already do (see
test_cli_report_business_exclusion.py, test_web_business_exclusion.py) --
a reimbursed business expense isn't real personal spend and shouldn't leak
into Firefly/ledger/CSV exports fed to downstream budgeting tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _txn(id_, date, amount, category="Subscriptions"):
    return Transaction(id=id_, date=date, amount=amount, direction=Direction.DEBIT,
                       description_raw=f"X {id_}", account="cc", category=category)


def test_export_csv_excludes_business_tagged_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("b1", "2026-06-01", 1000),
        _txn("p1", "2026-06-02", 500),
    ])
    store.set_tags("b1", ["business"])

    monkeypatch.chdir(tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["export", "--format", "csv"])
    assert result.exit_code == 0, result.output

    out_file = tmp_path / "munim-export.csv"
    rows = out_file.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2  # header + p1 only
    assert "500" in rows[1]
    assert "1000" not in rows[1]


def test_export_csv_can_include_business_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("b1", "2026-06-01", 1000),
        _txn("p1", "2026-06-02", 500),
    ])
    store.set_tags("b1", ["business"])

    monkeypatch.chdir(tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["export", "--format", "csv", "--include-business"])
    assert result.exit_code == 0, result.output

    out_file = tmp_path / "munim-export.csv"
    rows = out_file.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3  # header + both transactions
