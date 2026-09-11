"""Tests for the dashboard's date-range filter (date_from/date_to),
replacing the old exact-month-prefix filter with an inclusive range that
the frontend's new date-range picker drives."""
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


def _txn(id_, date, amount, direction, category="Dining"):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"X {id_}", account="cc", category=category)


def test_dashboard_filters_spend_by_date_range(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("a", "2026-01-15", 100, Direction.DEBIT),
        _txn("b", "2026-03-15", 200, Direction.DEBIT),
        _txn("c", "2026-06-15", 400, Direction.DEBIT),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/dashboard?date_from=2026-02-01&date_to=2026-04-01")
        assert d["total"] == 200.0
    finally:
        srv.shutdown()


def test_dashboard_date_range_is_inclusive_of_boundary_dates(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("a", "2026-02-01", 100, Direction.DEBIT),
        _txn("b", "2026-04-01", 200, Direction.DEBIT),
        _txn("c", "2026-04-02", 300, Direction.DEBIT),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/dashboard?date_from=2026-02-01&date_to=2026-04-01")
        assert d["total"] == 300.0
    finally:
        srv.shutdown()


def test_dashboard_no_range_includes_everything(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("a", "2026-01-15", 100, Direction.DEBIT),
        _txn("b", "2026-06-15", 400, Direction.DEBIT),
    ])
    srv, port = _server(store)
    try:
        d = _get(port, "/api/dashboard")
        assert d["total"] == 500.0
    finally:
        srv.shutdown()


def test_dashboard_reports_date_min_and_max_across_all_transactions(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("a", "2026-01-15", 100, Direction.DEBIT),
        _txn("b", "2026-06-15", 400, Direction.DEBIT),
    ])
    srv, port = _server(store)
    try:
        # date_min/date_max describe the whole dataset, not the filtered
        # window, so a picker can offer sensible "All time" bounds.
        d = _get(port, "/api/dashboard?date_from=2026-03-01")
        assert d["date_min"] == "2026-01-15"
        assert d["date_max"] == "2026-06-15"
    finally:
        srv.shutdown()
