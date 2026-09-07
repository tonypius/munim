"""Tests for the web UI's balance-sheet support on the Accounts endpoint."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.web.server import Handler


def _server(store):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _get(port, path):
    return json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=3).read())


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=3)


def test_api_accounts_includes_opening_and_current_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        row = next(r for r in d["rows"] if r["account"] == "bank")
        assert row["opening_balance"] == {"balance": 1000.0, "as_of": "2026-06-01"}
        assert row["current_balance"] == 1500.0
    finally:
        srv.shutdown()


def test_api_accounts_reports_no_balance_as_null(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.DEBIT,
                    description_raw="X", account="untracked"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        row = next(r for r in d["rows"] if r["account"] == "untracked")
        assert row["opening_balance"] is None
        assert row["current_balance"] is None
    finally:
        srv.shutdown()


def test_api_accounts_includes_account_known_only_via_opening_balance(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"fixed-deposit": {"balance": 50000.0, "as_of": "2026-06-01"}})
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        accounts = {r["account"] for r in d["rows"]}
        assert "fixed-deposit" in accounts
        row = next(r for r in d["rows"] if r["account"] == "fixed-deposit")
        assert row["current_balance"] == 50000.0
        assert row["n"] == 0
    finally:
        srv.shutdown()


def test_api_accounts_includes_account_known_only_via_account_types(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_types", {"hdfc-cc": "Liabilities"})
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        accounts = {r["account"] for r in d["rows"]}
        assert "hdfc-cc" in accounts
    finally:
        srv.shutdown()


def test_api_accounts_net_worth_totals_and_coverage(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("account_types", {"cc": "Liabilities"})
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "cc": {"balance": 200.0, "as_of": "2026-06-01"},
    })
    store.upsert_transactions([
        Transaction(date="2026-06-05", amount=500, direction=Direction.CREDIT,
                    description_raw="SALARY", account="bank"),
        Transaction(date="2026-06-05", amount=50, direction=Direction.DEBIT,
                    description_raw="PURCHASE", account="cc"),
        Transaction(date="2026-06-05", amount=10, direction=Direction.DEBIT,
                    description_raw="NO OPENING BALANCE", account="untracked"),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/accounts")
        nw = d["net_worth"]
        assert nw["assets"] == 1500.0
        assert nw["liabilities"] == 250.0
        assert nw["net"] == 1250.0
        assert nw["counted"] == 2
        assert nw["total"] == 3
    finally:
        srv.shutdown()


def test_post_opening_balance_writes_config(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        res = _post(port, "/api/accounts/opening-balance",
                    {"account": "bank", "balance": 1000.0, "as_of": "2026-06-01"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        balances = reloaded.get_config("account_opening_balances", {})
        assert balances["bank"] == {"balance": 1000.0, "as_of": "2026-06-01"}
    finally:
        srv.shutdown()


def test_post_opening_balance_rejects_invalid_date(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/accounts/opening-balance",
                 {"account": "bank", "balance": 1000.0, "as_of": "not-a-date"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert reloaded.get_config("account_opening_balances", {}) == {}
    finally:
        srv.shutdown()
