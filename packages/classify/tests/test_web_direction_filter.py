"""A `direction` filter (debit/credit) on /api/transactions and /api/queue
-- the same filter surface pattern as month/category/account, so both the
ledger page and the review queue can be narrowed to just spend or just
income."""
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


def test_web_transactions_direction_filter(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        Transaction(id="d1", date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="SWIGGY", account="cc"),
        Transaction(id="c1", date="2026-06-02", amount=5000, direction=Direction.CREDIT,
                    description_raw="SALARY", account="cc"),
    ])
    srv, port = _server(store)
    try:
        debit_only = _get(port, "/api/transactions?direction=debit")["rows"]
        assert [r["id"] for r in debit_only] == ["d1"]

        credit_only = _get(port, "/api/transactions?direction=credit")["rows"]
        assert [r["id"] for r in credit_only] == ["c1"]

        both = _get(port, "/api/transactions")["rows"]
        assert {r["id"] for r in both} == {"d1", "c1"}
    finally:
        srv.shutdown()


def test_web_queue_direction_filter(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("categories", ["Dining"])
    store.upsert_transactions([
        Transaction(id="d1", date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-UNMAPPED MART@okaxis-999912345001", account="cc"),
        Transaction(id="c1", date="2026-06-02", amount=5000, direction=Direction.CREDIT,
                    description_raw="UPI-UNMAPPED SALARY@okaxis-999912345002", account="cc"),
    ])
    srv, port = _server(store)
    try:
        debit_only = _get(port, "/api/queue?direction=debit")["rows"]
        assert [r["id"] for r in debit_only] == ["d1"]

        credit_only = _get(port, "/api/queue?direction=credit")["rows"]
        assert [r["id"] for r in credit_only] == ["c1"]
    finally:
        srv.shutdown()
