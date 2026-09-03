"""Transaction tags: manually-assigned, multi-valued ownership/purpose
labels (Business, Personal, a family member's name) from a curated list.
Orthogonal to category — never auto-applied by any pipeline mechanism."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _column_names(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_store_has_tags_table(tmp_path):
    store = Store(home=tmp_path)
    tables = {r[0] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "tags" in tables


def test_set_tags_then_read_back(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business", "Spouse"])
    assert sorted(store.tags_for("txn1")) == ["Business", "Spouse"]


def test_set_tags_replaces_not_merges(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn1", ["Personal"])
    assert store.tags_for("txn1") == ["Personal"]


def test_set_tags_empty_list_clears(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn1", [])
    assert store.tags_for("txn1") == []


def test_all_tags_returns_only_transactions_with_tags(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn2", ["Spouse", "Business"])
    assert store.all_tags() == {"txn1": ["Business"], "txn2": ["Business", "Spouse"]}


def test_tag_counts(tmp_path):
    store = Store(home=tmp_path)
    store.set_tags("txn1", ["Business"])
    store.set_tags("txn2", ["Business", "Spouse"])
    assert store.tag_counts() == {"Business": 2, "Spouse": 1}


def test_apply_tag_to_pattern_tags_every_matching_transaction(tmp_path):
    store = Store(home=tmp_path)
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="UBER RIDE 1")
    t1.merchant_norm = "UBER INDIA SYSTEMS"
    t2 = Transaction(date="2026-06-02", amount=250, direction=Direction.DEBIT,
                     description_raw="UBER RIDE 2")
    t2.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t1, t2])
    n = store.apply_tag_to_pattern("UBER INDIA SYSTEMS", "Business")
    assert n == 2
    assert store.tags_for(t1.id) == ["Business"]
    assert store.tags_for(t2.id) == ["Business"]


def test_apply_tag_to_pattern_adds_without_removing_existing_tags(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    t.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t])
    store.set_tags(t.id, ["Spouse"])
    store.apply_tag_to_pattern("UBER INDIA SYSTEMS", "Business")
    assert sorted(store.tags_for(t.id)) == ["Business", "Spouse"]


def test_apply_tag_to_pattern_matches_payee_handle_for_payee_kind(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=5000, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-513324498817")
    t.merchant_norm, t.payee_handle = "", "RAMESH KUMAR"
    store.upsert_transactions([t])
    n = store.apply_tag_to_pattern("RAMESH KUMAR", "Spouse", "payee")
    assert n == 1
    assert store.tags_for(t.id) == ["Spouse"]


from typer.testing import CliRunner
from munim.cli import app

runner = CliRunner()


def test_tags_add_creates_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    result = runner.invoke(app, ["tags", "add", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.get_config("tags", []) == ["Business"]


def test_tags_add_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    result = runner.invoke(app, ["tags", "add", "Business"])
    assert result.exit_code != 0


def test_tags_add_enforces_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", [f"Tag{i}" for i in range(30)])
    result = runner.invoke(app, ["tags", "add", "OneTooMany"])
    assert result.exit_code != 0
    result_forced = runner.invoke(app, ["tags", "add", "OneTooMany", "--force"])
    assert result_forced.exit_code == 0, result_forced.output


def test_tags_list_shows_usage_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    store.set_tags("txn1", ["Business"])
    result = runner.invoke(app, ["tags", "list"])
    assert result.exit_code == 0
    assert "Business" in result.output


def test_tags_remove_deletes_from_taxonomy_and_all_transactions(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    store.set_tags("txn1", ["Business"])
    result = runner.invoke(app, ["tags", "remove", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.get_config("tags", []) == []
    assert fresh.tags_for("txn1") == []


def test_tag_command_sets_tags_on_one_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business", "Spouse"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["tag", t.id, "Business", "Spouse"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert sorted(fresh.tags_for(t.id)) == ["Business", "Spouse"]


def test_tag_command_rejects_tag_not_in_curated_list(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    result = runner.invoke(app, ["tag", t.id, "NotARealTag"])
    assert result.exit_code != 0


def test_tag_command_with_pattern_bulk_applies(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="UBER 1")
    t1.merchant_norm = "UBER INDIA SYSTEMS"
    t2 = Transaction(date="2026-06-02", amount=250, direction=Direction.DEBIT,
                     description_raw="UBER 2")
    t2.merchant_norm = "UBER INDIA SYSTEMS"
    store.upsert_transactions([t1, t2])
    result = runner.invoke(app, ["tag", "--pattern", "UBER INDIA SYSTEMS", "Business"])
    assert result.exit_code == 0, result.output
    fresh = Store(home=tmp_path)
    assert fresh.tags_for(t1.id) == ["Business"]
    assert fresh.tags_for(t2.id) == ["Business"]


import json
import threading
import urllib.request
from http.server import HTTPServer
from munim.web.server import Handler


def _server(store):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_api_tags_returns_curated_list_and_counts(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business", "Spouse"])
    store.set_tags("txn1", ["Business"])
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/tags", timeout=3).read())
        assert d["tags"] == ["Business", "Spouse"]
        assert d["counts"] == {"Business": 1}
    finally:
        srv.shutdown()


def test_post_api_tag_sets_tags_on_one_transaction(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    srv, port = _server(store)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tag", method="POST",
            data=json.dumps({"id": t.id, "tags": ["Business"]}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert res["ok"] is True
        assert store.tags_for(t.id) == ["Business"]
    finally:
        srv.shutdown()


def test_post_api_tags_bulk_add_and_remove(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("tags", ["Business"])
    t1 = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                     description_raw="A")
    t2 = Transaction(date="2026-06-02", amount=200, direction=Direction.DEBIT,
                     description_raw="B")
    store.upsert_transactions([t1, t2])
    srv, port = _server(store)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tags/bulk", method="POST",
            data=json.dumps({"ids": [t1.id, t2.id], "tag": "Business",
                             "action": "add"}).encode(),
            headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=3).read())
        assert res["ok"] is True and res["updated"] == 2
        assert store.tags_for(t1.id) == ["Business"]
        assert store.tags_for(t2.id) == ["Business"]

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/tags/bulk", method="POST",
            data=json.dumps({"ids": [t1.id], "tag": "Business",
                             "action": "remove"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        assert store.tags_for(t1.id) == []
        assert store.tags_for(t2.id) == ["Business"]
    finally:
        srv.shutdown()


def test_api_transactions_rows_include_tags(tmp_path):
    store = Store(home=tmp_path)
    t = Transaction(date="2026-06-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UBER RIDE")
    store.upsert_transactions([t])
    store.set_tags(t.id, ["Business"])
    srv, port = _server(store)
    try:
        d = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/transactions", timeout=3).read())
        assert d["rows"][0]["tags"] == ["Business"]
    finally:
        srv.shutdown()
