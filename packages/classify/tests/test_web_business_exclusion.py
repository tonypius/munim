"""Tests for excluding 'business'-tagged transactions from spend/income
reporting (dashboard totals and the on-the-go chart endpoint) -- the same
netting-out treatment already given to transfers, since a reimbursed
expense isn't real personal spend or income even though real money moved.
"""
import json
import sys
import threading
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


def _txn(id_, date, amount, direction, category="Subscriptions", account="cc"):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"X {id_}", account=account,
                       category=category)


def _seed(tmp_path):
    store = Store(home=tmp_path)
    business_debit = _txn("b1", "2026-06-01", 1000, Direction.DEBIT)
    personal_debit = _txn("p1", "2026-06-02", 500, Direction.DEBIT)
    business_credit = _txn("b2", "2026-06-03", 1000, Direction.CREDIT, category="Income")
    store.upsert_transactions([business_debit, personal_debit, business_credit])
    store.set_tags("b1", ["business"])
    store.set_tags("b2", ["business"])
    return store


def test_chart_flow_excludes_business_tagged_by_default(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/chart/flow?group_by=category&direction=debit")
        assert d == {"labels": ["Subscriptions"], "values": [500.0]}
    finally:
        srv.shutdown()


def test_chart_flow_can_include_business_when_asked(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/chart/flow?group_by=category&direction=debit&exclude_business=0")
        assert d == {"labels": ["Subscriptions"], "values": [1500.0]}
    finally:
        srv.shutdown()


def test_chart_flow_only_business_shows_only_tagged(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/chart/flow?group_by=category&direction=debit&only_business=1")
        assert d == {"labels": ["Subscriptions"], "values": [1000.0]}
    finally:
        srv.shutdown()


def test_chart_flow_only_business_and_credit_shows_reimbursement_income(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/chart/flow?group_by=category&direction=credit&only_business=1")
        assert d == {"labels": ["Income"], "values": [1000.0]}
    finally:
        srv.shutdown()


def test_dashboard_excludes_business_tagged_from_spend_total(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/dashboard")
        assert d["total"] == 500.0
        assert d["top_categories"] == [{"name": "Subscriptions", "total": 500.0}]
    finally:
        srv.shutdown()


def test_dashboard_excludes_business_tagged_from_net_roots(tmp_path):
    store = _seed(tmp_path)
    srv, port = _server(store)
    try:
        d = _get(port, "/api/dashboard")
        # Both the reimbursement credit (b2, Income) and the reimbursed
        # expense (b1, Subscriptions/Expenses) are tagged business, so
        # neither should reach the five-root rollup at all.
        assert d["roots"]["Income"] == 0.0
        assert d["roots"]["Expenses"] == 500.0
        assert d["net"] == -500.0
    finally:
        srv.shutdown()
