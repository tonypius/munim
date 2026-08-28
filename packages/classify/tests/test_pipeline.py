"""Core behavior tests. Run: pytest"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.normalize import Normalizer
from munim.memory import MemoryMatcher
from munim.pipeline import Pipeline
from munim.store import Store
from munim.schema import Transaction, Direction, Status, Stage


def test_upi_merchant_extraction():
    n = Normalizer(region="in")
    r = n.normalize("UPI-SWIGGY8102 ST BLR@okaxis-513324498812")
    assert "SWIGGY" in r.merchant
    assert r.payee_handle == ""


def test_fuzzy_survives_spacing_damage():
    m = MemoryMatcher(user_rules={}, region="in")
    hit = m.match("SWIG GY INSTAMART")
    assert hit and hit.category == "Groceries"


def test_user_memory_outranks_dictionary():
    m = MemoryMatcher(user_rules={"SWIGGY8102": "Groceries"}, region="in")
    hit = m.match("SWIGGY8102")
    assert hit.source == "memory" and hit.category == "Groceries"


def test_person_routes_to_payee_not_merchant(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-04", amount=5000, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-513324498817")
    Pipeline(store).run([t])
    assert t.payee_handle == "RAMESH KUMAR"
    assert t.status == Status.UNRESOLVED  # only the user can label a person


def test_cc_bill_payment_is_transfer_not_spending(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-05", amount=45230, direction=Direction.DEBIT,
                    description_raw="CREDIT CARD PAYMENT BILLDESK HDFC CARD")
    Pipeline(store).run([t])
    assert t.is_transfer and t.category == "Transfers"


def test_predictions_never_enter_memory_without_confirmation(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-01", amount=340, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY8102@okaxis-513324498812")
    Pipeline(store).run([t])
    assert t.status == Status.PROVISIONAL          # dictionary hit is a suggestion
    assert store.memory_rules("merchant") == {}     # ...not a memory write


def test_contribute_never_exports_people(tmp_path):
    """Privacy guarantee: payee (person) rules never leave the machine."""
    from munim.contribute import build_bundle
    import yaml
    store = Store(home=tmp_path / "home")
    store.set_config("region", "in")
    store.remember("RAMESH KUMAR", "Family & Friends", kind="payee")
    store.remember("KATHURIA SWEETS", "Dining", kind="merchant")
    result = build_bundle(store, tmp_path / "contrib")
    data = yaml.safe_load(open(result["file"]).read().split("PR.\n")[-1])
    flat = [p for pats in data.values() for p in pats]
    assert "RAMESH KUMAR" not in flat
    assert "KATHURIA SWEETS" in flat


def test_ledger_export_balances_and_marks_transfers(tmp_path):
    from munim.export_formats import to_ledger
    t = Transaction(date="2026-06-05", amount=45230, direction=Direction.DEBIT,
                    description_raw="CC PAYMENT", account="hdfc",
                    is_transfer=True, category="Transfers")
    out = to_ledger([t])
    assert "Equity:Transfers" in out and "Expenses:" not in out


def test_learn_then_classify_roundtrip(tmp_path):
    """The embedding contract: learn() makes the next classify() resolve."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t1 = Transaction(date="2026-07-03", amount=280, direction=Direction.DEBIT,
                     description_raw="UPI-BLUE TOKAI COFFEE@icici-999912345681")
    Pipeline(store).run([t1])
    assert t1.status == Status.UNRESOLVED
    store.remember("BLUE TOKAI COFFEE", "Dining", kind="merchant")  # = learn
    t2 = Transaction(date="2026-07-04", amount=310, direction=Direction.DEBIT,
                     description_raw="UPI-BLUE TOKAI COFFEE@icici-999912345699")
    Pipeline(store).run([t2])
    assert t2.category == "Dining" and t2.stage == Stage.MEMORY_EXACT


def test_web_server_endpoints(tmp_path):
    """The web layer serves the page, reads data, and confirm() closes Loop 1."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Dining", "Groceries", "Other"])
    t = Transaction(date="2026-07-01", amount=450, direction=Direction.DEBIT,
                    description_raw="UPI-KATHURIA SWEETS AND SNACKS@okaxis-999912345680")
    Pipeline(store).run([t])
    store.upsert_transactions([t])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    get = lambda p: urllib.request.urlopen(
        f"http://127.0.0.1:{port}{p}", timeout=3).read()

    assert "मुनीम".encode() in get("/")
    assert json.loads(get("/api/overview"))["total"] == 1
    queue = json.loads(get("/api/queue"))["rows"]
    assert len(queue) == 1

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/confirm", method="POST",
        data=json.dumps({"id": queue[0]["id"], "category": "Dining"}).encode(),
        headers={"Content-Type": "application/json"})
    assert json.loads(urllib.request.urlopen(req, timeout=3).read())["ok"]
    # the confirmation reached memory (Loop 1) and the transaction
    assert store.memory_rules("merchant") == \
        {"KATHURIA SWEETS AND SNACKS": "Dining"}
    assert json.loads(get("/api/queue"))["rows"] == []
    srv.shutdown()


def test_dictionary_ships_with_package():
    """Regression: the community dictionary must load from inside the
    installed package. An empty dictionary silently collapses accuracy."""
    m = MemoryMatcher(user_rules={}, region="in")
    assert len(m.dictionary) > 100, "dictionary missing — packaging is broken"


def test_web_multiple_confirms_and_new_endpoints(tmp_path):
    """Regression for the once:true bug: several confirms in a row must all
    land. Also smoke-tests /api/accounts and /api/dashboard."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Dining", "Groceries", "Other"])
    txns = [
        Transaction(date="2026-07-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP ONE@okaxis-999912345001",
                    account="hdfc"),
        Transaction(date="2026-07-02", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP TWO@okaxis-999912345002",
                    account="icici"),
        Transaction(date="2026-07-03", amount=300, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP THREE@okaxis-999912345003",
                    account="hdfc"),
    ]
    Pipeline(store).run(txns)
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    def confirm(txn_id, cat):
        req = urllib.request.Request(
            base + "/api/confirm", method="POST",
            data=json.dumps({"id": txn_id, "category": cat}).encode(),
            headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=3).read())

    # three confirms back to back — every one must succeed server-side
    queue = get("/api/queue")["rows"]
    assert len(queue) == 3
    for row in queue:
        assert confirm(row["id"], "Dining")["ok"]
    assert get("/api/queue")["rows"] == []
    assert len(store.memory_rules("merchant")) == 3

    accounts = get("/api/accounts")["rows"]
    assert {r["account"] for r in accounts} == {"hdfc", "icici"}
    dash = get("/api/dashboard")
    assert dash["total"] == 600 and dash["top_categories"][0]["name"] == "Dining"
    srv.shutdown()


def test_tree_resolves_and_validates():
    from munim.tree import default_tree, resolve, valid_path, root_of
    tree = default_tree(["Dining", "Income", "Transfers", "Investments"])
    assert resolve(tree, "Dining") == "Expenses:Dining"
    assert resolve(tree, "Income") == "Income"
    assert resolve(tree, "Transfers") == "Equity:Transfers"
    assert resolve(tree, "Investments") == "Assets:Investments"
    assert resolve(tree, "") == "Expenses:Uncategorized"
    assert valid_path("Liabilities:HDFC CC") and not valid_path("Wealth:Foo")
    assert root_of("Expenses:Food:Dining") == "Expenses"


def test_ledger_uses_tree_and_liability_accounts():
    from munim.export_formats import to_ledger
    tree = {"Dining": "Expenses:Food:Dining", "Transfers": "Equity:Transfers"}
    t = Transaction(date="2026-06-01", amount=340, direction=Direction.DEBIT,
                    description_raw="x", account="icici-cc", category="Dining",
                    merchant_norm="SWIGGY")
    out = to_ledger([t], tree=tree, account_types={"icici-cc": "Liabilities"})
    assert "Expenses:Food:Dining" in out
    assert "Liabilities:icici-cc" in out and "Assets:icici-cc" not in out


def test_dashboard_filters_and_roots(tmp_path):
    import json, threading, urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Dining", "Income", "Transfers"])
    txns = [
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY@ok-999912345001", account="hdfc",
                    category="Dining", status=Status.CONFIRMED),
        Transaction(date="2026-07-01", amount=5000, direction=Direction.CREDIT,
                    description_raw="NEFT-SALARY-999912345002", account="hdfc",
                    category="Income", status=Status.CONFIRMED),
    ]
    store.upsert_transactions(txns)
    srv = HTTPServer(("127.0.0.1", 0), Handler); srv.store = store
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    get = lambda p: json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{srv.server_address[1]}{p}", timeout=3).read())
    d = get("/api/dashboard")
    assert d["roots"]["Expenses"] == 100 and d["roots"]["Income"] == 5000
    assert d["net"] == 4900
    d_june = get("/api/dashboard?month=2026-06")
    assert d_june["roots"]["Income"] == 0 and d_june["total"] == 100
    srv.shutdown()
