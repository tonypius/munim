"""Tests for the web UI's transfer-pair linking endpoints."""
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


def _transfer(id_, date, amount, direction, account):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"TRANSFER {id_}", account=account,
                       is_transfer=True, category="Transfers")


def _get(port, path):
    return json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=3).read())


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=3)


def test_api_transfers_reports_coverage_and_buckets(tmp_path):
    store = Store(home=tmp_path)
    linked_a = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    linked_b = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    ambiguous_debit = _transfer("d2", "2026-06-01", 7000, Direction.DEBIT, "bank")
    ambiguous_c1 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "card")
    ambiguous_c2 = _transfer("c3", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    pending = _transfer("d3", "2026-06-05", 3000, Direction.DEBIT, "bank")
    dismissed = _transfer("d4", "2026-06-06", 2000, Direction.DEBIT, "wallet")
    store.upsert_transactions([linked_a, linked_b, ambiguous_debit,
                               ambiguous_c1, ambiguous_c2, pending, dismissed])
    store.link_transfer("d1", "c1", confidence="auto")
    store.dismiss_transfer("d4")
    srv, port = _server(store)
    try:
        d = _get(port, "/api/transfers")
        # coverage.pending matches the CLI's own transfers_status semantics:
        # every is_transfer transaction that's neither linked nor dismissed,
        # which includes BOTH legs of the still-open ambiguous pair (d2,
        # c2, c3) AND the genuinely zero-candidate d3 -- four rows total,
        # not just the one zero-candidate transaction.
        assert d["coverage"] == {"auto": 1, "confirmed": 0,
                                 "dismissed": 1, "pending": 4}
        assert len(d["ambiguous"]) == 1
        assert d["ambiguous"][0]["debit"]["id"] == "d2"
        assert {c["id"] for c in d["ambiguous"][0]["candidates"]} == {"c2", "c3"}
        # d["pending"] (the display list, distinct from coverage.pending
        # above) is narrower by design: it excludes anything already
        # actionable in the ambiguous queue, showing only genuinely
        # zero-candidate transactions -- so just d3 here, not d2/c2/c3.
        assert [p["id"] for p in d["pending"]] == ["d3"]
    finally:
        srv.shutdown()


def test_post_transfer_link_confirms_a_pair(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/link",
                    {"debit_id": "d1", "credit_id": "c1"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
        rows = reloaded.all_transfer_links()
        assert rows[0]["confidence"] == "confirmed"
    finally:
        srv.shutdown()


def test_post_transfer_link_rejects_already_linked(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 5000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    store.link_transfer("d1", "c1")
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/link",
                 {"debit_id": "d1", "credit_id": "c2"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
    finally:
        srv.shutdown()


def test_post_transfer_link_rejects_unknown_transaction(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/link",
                 {"debit_id": "d1", "credit_id": "nonexistent"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_marks_dismissed(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/dismiss", {"id": "d1"})
        assert json.loads(res.read())["ok"]
        reloaded = Store(home=tmp_path)
        assert reloaded.is_dismissed("d1")
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_rejects_already_linked(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/dismiss", {"id": "d1"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        reloaded = Store(home=tmp_path)
        assert not reloaded.is_dismissed("d1")
    finally:
        srv.shutdown()


def test_post_transfer_dismiss_rejects_unknown_id(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        try:
            _post(port, "/api/transfer/dismiss", {"id": "nonexistent"})
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_post_transfer_relink_runs_auto_linking(tmp_path):
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    srv, port = _server(store)
    try:
        res = _post(port, "/api/transfer/relink", {})
        assert json.loads(res.read()) == {"ok": True, "linked": 1}
        reloaded = Store(home=tmp_path)
        assert reloaded.linked_counterpart("d1") == "c1"
    finally:
        srv.shutdown()


def test_index_page_includes_transfers_tab(tmp_path):
    store = Store(home=tmp_path)
    srv, port = _server(store)
    try:
        html = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=3).read().decode()
        assert 'data-tab="transfers"' in html
        assert 'id="transfersBody"' in html
        assert 'id="transfersMeta"' in html
        assert 'id="relinkBtn"' in html
    finally:
        srv.shutdown()
