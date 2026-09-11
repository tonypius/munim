"""The `report` CLI command must exclude 'business'-tagged transactions
the same way the web dashboard and chart endpoint do (see
test_web_business_exclusion.py) -- CLI/web parity for spend reporting."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _txn(id_, date, amount, category="Subscriptions"):
    return Transaction(id=id_, date=date, amount=amount, direction=Direction.DEBIT,
                       description_raw=f"X {id_}", account="cc", category=category)


def test_report_excludes_business_tagged_spend(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("b1", "2026-06-01", 1000),
        _txn("p1", "2026-06-02", 500),
    ])
    store.set_tags("b1", ["business"])

    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["report", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["categories"] == {"Subscriptions": 500.0}
