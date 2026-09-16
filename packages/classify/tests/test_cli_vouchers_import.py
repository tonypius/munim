import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store


def test_vouchers_import_creates_transactions_and_persists_records(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))

    records = [
        {"kind": "purchase", "brand": "swiggy", "value": 2000.0,
         "code": "VGHDR7VACB6SD15E", "purchased_at": "2026-09-14"},
        {"kind": "spend", "brand": "swiggy", "source": "instamart_order",
         "amount": 395.0, "merchant": "Instamart",
         "order_id": "248336149154232", "order_date": "2026-09-14",
         "paid_via": None},
    ]
    jsonl_file = tmp_path / "vouchers.jsonl"
    with open(jsonl_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["vouchers", "import", str(jsonl_file)])
    assert result.exit_code == 0, result.output

    store = Store(home=tmp_path)
    accounts = {t.account for t in store.all_transactions()}
    assert accounts == {"voucher-swiggy"}
    assert len(store.all_transactions()) == 2

    stored_records = store.get_config("voucher_records", [])
    assert len(stored_records) == 2


def test_vouchers_import_is_safe_to_rerun_without_duplicating(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))

    records = [
        {"kind": "purchase", "brand": "swiggy", "value": 2000.0,
         "code": "VGHDR7VACB6SD15E", "purchased_at": "2026-09-14"},
    ]
    jsonl_file = tmp_path / "vouchers.jsonl"
    with open(jsonl_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    runner.invoke(app, ["vouchers", "import", str(jsonl_file)])
    runner.invoke(app, ["vouchers", "import", str(jsonl_file)])

    store = Store(home=tmp_path)
    assert len(store.all_transactions()) == 1
    # the record log should not grow unboundedly on repeated imports of
    # the exact same source file
    assert len(store.get_config("voucher_records", [])) == 1
