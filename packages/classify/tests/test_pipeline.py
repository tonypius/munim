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


def test_upi_handle_trailing_disambiguator_suffix_is_stripped():
    """Real finding: the same person's UPI handle can carry a trailing
    "-N" when they link it through a second bank app — e.g.
    "priya.sureshk@oksbi" vs "priya.sureshk-1@okicici" are the same
    real person, but without stripping the suffix they normalize to two
    different payee handles, so classifying one never helps the other
    (a real cause of "rules feel too rigid" — a rule that never fires on
    a plainly-recurring counterparty because of one disambiguator digit)."""
    n = Normalizer(region="in")
    plain = n.normalize("UPI-PRIYA SURESH K-PRIYA.SURESHK@OKSBI-SBIN0008614-300984376011-PRIYA")
    suffixed = n.normalize("UPI-PRIYA SURESH K-PRIYA.SURESHK-1@OKICICI-SBIN0008614-319342257966-CHECKING")
    assert plain.merchant == suffixed.merchant


def test_upi_extraction_survives_stray_space_after_at_sign():
    """Real finding, and the single biggest cause of unresolved
    transactions found in one real account (283 of 1000, 28%): the
    hdfc_bank_account.py PDF narration reconstruction collapses embedded
    newlines to a single space, and the PDF often wraps a line right at
    the '@' boundary of a VPA — producing 'name@ domain' instead of
    'name@domain'. The old UPI extract regex required '@' to be
    IMMEDIATELY followed by the domain characters with zero tolerance
    for whitespace, so a stray space made the regex fail to match at
    all — the entire raw string (UPI- prefix, ref numbers and all) fell
    through as the merchant candidate instead of the real name.
    'ganesh.raobs@ oksbi' and 'ganesh.raobs@oksbi' must extract the
    same merchant regardless of that stray space."""
    n = Normalizer(region="in")
    clean = n.normalize("UPI-GANESH RAO B S-9123456780@AXL-KARB0000212-107756254596-MILK")
    spaced = n.normalize("UPI-GANESH RAO B S-9123456780@ axl-KARB0000212-569454154786-milk")
    assert clean.merchant == spaced.merchant == "GANESH RAO B S"


def test_value_dt_ref_suffix_stripped_from_system_narrations():
    """Real finding: bank-generated system narrations (interest posting,
    SMS alert fees) never pass through any of the UPI/NEFT/IMPS extract
    rails — there's no '@domain' to capture up to — so a trailing
    'Value Dt DD/MM/YYYY [Ref <ref>]' (present on almost every one) was
    never stripped, fragmenting one real recurring narration type into
    many distinct merchant strings (one per date it happened to post
    on) — 'CREDIT INTEREST CAPITALISED' every month, unrelated to any
    specific date, should normalize identically regardless of which
    month's instance it is."""
    n = Normalizer(region="in")
    bare = n.normalize("CREDIT INTEREST CAPITALISED")
    dated = n.normalize("Credit Interest Capitalised Value Dt 31/12/2023")
    reffed = n.normalize(
        "JulSep25 InstaAlertChg 6 SMS 031025-MIR2633595356023 "
        "Value Dt 02/12/2025 Ref MIR2633595356023")
    assert bare.merchant == dated.merchant
    assert "VALUE" not in reffed.merchant and "REF" not in reffed.merchant.split()


def test_upi_handle_disambiguator_suffix_does_not_eat_real_trailing_digits():
    """Defensive: only a short (1-2 digit) trailing '-N' is a plausible
    disambiguator suffix — don't strip longer numeric segments that could
    be a real, meaningful part of a merchant/account identifier."""
    n = Normalizer(region="in")
    r = n.normalize("UPI-SOME MERCHANT-merchant-12345@okaxis-513324498812")
    assert "12345" in r.merchant


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


def test_web_confirm_as_transfers_sets_is_transfer(tmp_path):
    """A transaction the structural detector couldn't auto-pair (e.g. a
    credit-card bill payment where only the card's statement is imported,
    not the source bank account) still needs is_transfer=True when the
    user manually confirms it as "Transfers" via the review page —
    category alone isn't what reports/dashboard check, is_transfer is.
    Without this, a manually-confirmed transfer is silently double-
    counted as income or spending."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Transfers", "Other"])
    t = Transaction(date="2026-06-05", amount=130643, direction=Direction.CREDIT,
                    description_raw="NETBANKING TRANSFER (Ref# 00000000000510015695123)")
    Pipeline(store).run([t])
    store.upsert_transactions([t])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/confirm", method="POST",
        data=json.dumps({"id": t.id, "category": "Transfers"}).encode(),
        headers={"Content-Type": "application/json"})
    assert json.loads(urllib.request.urlopen(req, timeout=3).read())["ok"]

    reloaded = store.get_transaction(t.id)
    assert reloaded.category == "Transfers"
    assert reloaded.is_transfer is True
    srv.shutdown()


def test_propagate_sets_is_transfer_for_transfers_category(tmp_path):
    """propagate() cascades a confirmed category to every other
    unconfirmed transaction with the identical merchant string — when
    that category is "Transfers", the cascaded rows need is_transfer=True
    too, not just the one row the user directly clicked confirm on."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Transfers", "Other"])
    txns = [
        Transaction(date="2026-06-01", amount=1000, direction=Direction.CREDIT,
                    description_raw="NETBANKING TRANSFER (Ref# A)"),
        Transaction(date="2026-07-01", amount=2000, direction=Direction.CREDIT,
                    description_raw="NETBANKING TRANSFER (Ref# B)"),
    ]
    store.upsert_transactions(txns)
    # both txns normalize to the same merchant_norm ("NETBANKING TRANSFER"),
    # so propagating from the first must reach the second.
    assert txns[0].merchant_norm == txns[1].merchant_norm

    n = store.propagate(txns[0].merchant_norm, "Transfers", "merchant",
                        exclude_id=txns[0].id)
    assert n == 1
    other = store.get_transaction(txns[1].id)
    assert other.category == "Transfers"
    assert other.is_transfer is True
    assert other.status == Status.CONFIRMED


def test_propagate_clears_is_transfer_for_non_transfer_category(tmp_path):
    """The inverse must also hold: propagating a correction AWAY from
    Transfers to a real spending category must clear is_transfer, or a
    previously-mis-flagged transfer would keep being excluded from
    spending totals after the user explicitly fixed its category."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Transfers", "Shopping"])
    t = Transaction(date="2026-06-01", amount=500, direction=Direction.DEBIT,
                    description_raw="SOME STORE XYZ", is_transfer=True,
                    category="Transfers")
    store.upsert_transactions([t])

    n = store.propagate(t.merchant_norm, "Shopping", "merchant", exclude_id="nonexistent")
    assert n == 1
    reloaded = store.get_transaction(t.id)
    assert reloaded.category == "Shopping"
    assert reloaded.is_transfer is False


def test_memory_match_to_transfers_sets_is_transfer(tmp_path):
    """A transaction resolved via a MEMORY_EXACT rule to category=
    "Transfers" (e.g. a recurring credit-card autopay, taught once via
    review, now auto-resolving on every subsequent import with no
    structural re-detection) must get is_transfer=True too — not just
    category. Pipeline._assign() is the single function every
    non-structural stage (memory, dictionary, purpose, fallback) routes
    through, and it previously set only category/subcategory/stage/
    confidence/status, never is_transfer — silently leaving every
    memory-resolved transfer counted as real spend/income in the
    dashboard and Categories page, which check is_transfer, not the
    category string. This is the same invariant test_propagate_sets_
    is_transfer_for_transfers_category already enforces for propagate();
    this test covers the pipeline's own classification path instead."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.remember("SOME AUTOPAY MERCHANT XYZ", "Transfers", kind="merchant")
    t = Transaction(date="2026-06-05", amount=5000, direction=Direction.DEBIT,
                    description_raw="SOME AUTOPAY MERCHANT XYZ")
    Pipeline(store).run([t])
    assert t.category == "Transfers"
    assert t.stage == Stage.MEMORY_EXACT
    assert t.is_transfer is True


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


def test_web_queue_search_and_filters(tmp_path):
    """The review page's search bar and filters: /api/queue accepts the
    same query params as /api/transactions (month, q), plus a `suggested`
    filter (a category name, or the sentinel "__none__" for rows with no
    suggestion at all) — the search/filter surface a large queue needs to
    be navigable rather than just the first 100 lowest-confidence rows."""
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
        # SWIGGY is a real community-dictionary entry (-> Dining); the
        # other two deliberately are not, so they land with no suggestion.
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY DINER@okaxis-999912345001"),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-UNMAPPED MART@okaxis-999912345002"),
        Transaction(date="2026-07-02", amount=300, direction=Direction.DEBIT,
                    description_raw="UPI-RANDOM UNKNOWN CO@okaxis-999912345003"),
    ]
    Pipeline(store).run(txns)
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    # unfiltered: all three still in the queue
    assert len(get("/api/queue")["rows"]) == 3

    # text search over merchant/description
    assert [r["merchant"] for r in get("/api/queue?q=SWIGGY")["rows"]] == ["SWIGGY DINER"]

    # month filter
    assert len(get("/api/queue?month=2026-07")["rows"]) == 2
    assert len(get("/api/queue?month=2026-06")["rows"]) == 1

    # suggested-category filter: SWIGGY gets a dictionary suggestion
    # (Dining), the other two don't match anything in the dictionary
    dining_rows = get("/api/queue?suggested=Dining")["rows"]
    assert len(dining_rows) == 1 and dining_rows[0]["merchant"] == "SWIGGY DINER"
    none_rows = get("/api/queue?suggested=__none__")["rows"]
    assert len(none_rows) == 2
    assert all(r["category"] in (None, "") for r in none_rows)
    assert any("RANDOM UNKNOWN" in r["raw"] for r in none_rows)
    assert any("UNMAPPED MART" in r["raw"] for r in none_rows)

    # combining filters
    combined = get("/api/queue?month=2026-06&q=SWIGGY")["rows"]
    assert len(combined) == 1

    # months/suggestions lists are returned for populating the dropdowns
    full = get("/api/queue")
    assert "2026-07" in full["months"] and "2026-06" in full["months"]
    assert isinstance(full["suggestions"], list)
    srv.shutdown()


def test_web_queue_account_filter_and_list(tmp_path):
    """The review page's filter surface also needs an `account` filter —
    exact match on the account name, same as /api/transactions — plus an
    `accounts` list in the response for populating that filter's
    dropdown, so a large multi-account review queue can be narrowed to
    one account at a time."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Dining", "Groceries"])
    txns = [
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-UNMAPPED MART@okaxis-999912345001",
                    account="tony-hdfc-savings"),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-RANDOM UNKNOWN CO@okaxis-999912345002",
                    account="tony-sib-savings"),
    ]
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    hdfc_rows = get("/api/queue?account=tony-hdfc-savings")["rows"]
    assert len(hdfc_rows) == 1 and "UNMAPPED MART" in hdfc_rows[0]["raw"]

    combined = get("/api/queue?account=tony-sib-savings&month=2026-07")["rows"]
    assert len(combined) == 1 and "RANDOM UNKNOWN" in combined[0]["raw"]

    full = get("/api/queue")
    assert set(full["accounts"]) == {"tony-hdfc-savings", "tony-sib-savings"}
    srv.shutdown()


def test_web_transactions_category_filter_and_list(tmp_path):
    """The transactions ("ledger") page's search/filter surface should
    match the review page's: /api/transactions already had month + q, this
    adds a `category` filter (an exact category name, or the sentinel
    "__none__" for rows with no category at all yet) plus a `categories`
    list in the response for populating that filter's dropdown — same
    shape as /api/queue's `suggested` + `suggestions`."""
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
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY DINER@okaxis-999912345001",
                    category="Dining", status=Status.CONFIRMED),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-BIG BAZAAR MART@okaxis-999912345002",
                    category="Groceries", status=Status.CONFIRMED),
        Transaction(date="2026-07-02", amount=300, direction=Direction.DEBIT,
                    description_raw="UPI-RANDOM UNKNOWN CO@okaxis-999912345003"),
    ]
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    # category filter: exact match
    dining_rows = get("/api/transactions?category=Dining")["rows"]
    assert len(dining_rows) == 1 and "SWIGGY" in dining_rows[0]["raw"]

    # __none__ sentinel: rows with no category assigned yet
    none_rows = get("/api/transactions?category=__none__")["rows"]
    assert len(none_rows) == 1
    assert "RANDOM UNKNOWN" in none_rows[0]["raw"]

    # combining with the existing month/q filters
    combined = get("/api/transactions?category=Groceries&month=2026-07")["rows"]
    assert len(combined) == 1 and "BIG BAZAAR" in combined[0]["raw"]

    # categories list returned for populating the filter dropdown
    full = get("/api/transactions")
    assert set(full["categories"]) == {"Dining", "Groceries"}
    srv.shutdown()


def test_web_transactions_account_filter_and_list(tmp_path):
    """The ledger page's filter surface also needs an `account` filter —
    exact match on the account name — plus an `accounts` list in the
    response for populating that filter's dropdown, same shape as the
    existing `category`/`categories` pair."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Dining", "Groceries"])
    txns = [
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY DINER@okaxis-999912345001",
                    category="Dining", account="tony-hdfc-savings",
                    status=Status.CONFIRMED),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-BIG BAZAAR MART@okaxis-999912345002",
                    category="Groceries", account="tony-sib-savings",
                    status=Status.CONFIRMED),
    ]
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    hdfc_rows = get("/api/transactions?account=tony-hdfc-savings")["rows"]
    assert len(hdfc_rows) == 1 and "SWIGGY" in hdfc_rows[0]["raw"]

    combined = get("/api/transactions?account=tony-sib-savings&category=Groceries")["rows"]
    assert len(combined) == 1 and "BIG BAZAAR" in combined[0]["raw"]

    full = get("/api/transactions")
    assert set(full["accounts"]) == {"tony-hdfc-savings", "tony-sib-savings"}
    srv.shutdown()


def test_web_bulk_confirm(tmp_path):
    """POST /api/confirm with `ids` (plural) assigns one category to several
    transactions in one request — the review page's bulk-select feature."""
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
                    description_raw="UPI-LOCAL SHOP ONE@okaxis-999912345001"),
        Transaction(date="2026-07-02", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP TWO@okaxis-999912345002"),
        Transaction(date="2026-07-03", amount=300, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP THREE@okaxis-999912345003"),
    ]
    Pipeline(store).run(txns)
    store.upsert_transactions(txns)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    queue = get("/api/queue")["rows"]
    assert len(queue) == 3
    ids = [row["id"] for row in queue[:2]]  # bulk-assign only the first two

    req = urllib.request.Request(
        base + "/api/confirm", method="POST",
        data=json.dumps({"ids": ids, "category": "Dining"}).encode(),
        headers={"Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(req, timeout=3).read())
    assert result["ok"] and result["confirmed"] == 2

    remaining = get("/api/queue")["rows"]
    assert len(remaining) == 1
    assert remaining[0]["id"] not in ids

    dash = get("/api/dashboard")
    assert dash["top_categories"][0]["name"] == "Dining"
    srv.shutdown()


def test_web_bulk_confirm_reports_missing_ids(tmp_path):
    """An id in the batch that doesn't exist (e.g. a stale client-side
    selection) is reported, not silently dropped or a hard failure for the
    whole batch."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("currency", "INR")
    store.set_config("categories", ["Dining", "Other"])
    t = Transaction(date="2026-07-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-LOCAL SHOP ONE@okaxis-999912345001")
    Pipeline(store).run([t])
    store.upsert_transactions([t])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    real_id = get("/api/queue")["rows"][0]["id"]
    req = urllib.request.Request(
        base + "/api/confirm", method="POST",
        data=json.dumps({"ids": [real_id, "not-a-real-id"], "category": "Dining"}).encode(),
        headers={"Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(req, timeout=3).read())
    assert result["ok"] and result["confirmed"] == 1
    assert result["missing"] == ["not-a-real-id"]
    srv.shutdown()


def test_web_bulk_confirm_rejects_empty_ids_list(tmp_path):
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("categories", ["Dining"])
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/confirm", method="POST",
        data=json.dumps({"ids": [], "category": "Dining"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3)
        assert False, "expected HTTPError for an empty ids list"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    srv.shutdown()


def test_web_rules_flags_patterns_with_no_exact_transaction_match_as_broad(tmp_path):
    """The Rules page had no way to tell a deliberately-short generic
    keyword (e.g. "CREDCLUB", taught so it substring-matches every
    payment-processor variant of a recurring fee) apart from a full,
    effectively-exact merchant string — both rendered identically. A
    pattern that never equals any real transaction's complete
    merchant_norm/payee_handle can only ever have matched (or will
    match) via substring/fuzzy containment, never a literal lookup —
    that's checkable and is exactly the "broad" signal to surface."""
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("categories", ["Subscriptions", "Dining"])
    txns = [
        Transaction(date="2026-07-01", amount=100, direction=Direction.DEBIT,
                    description_raw="UPI-CREDCLUB1 CRED CLUB@okaxis-999912345001",
                    merchant_norm="CREDCLUB1 CRED CLUB", category="Subscriptions",
                    status=Status.CONFIRMED, stage=Stage.USER),
        Transaction(date="2026-07-02", amount=200, direction=Direction.DEBIT,
                    description_raw="UPI-SWIGGY8102@okaxis-999912345002",
                    merchant_norm="SWIGGY8102", category="Dining",
                    status=Status.CONFIRMED, stage=Stage.USER),
    ]
    store.upsert_transactions(txns)
    # "CREDCLUB" is a hand-typed generic keyword — it never equals either
    # transaction's full merchant_norm, only appears as a substring of one.
    store.remember("CREDCLUB", "Subscriptions", kind="merchant")
    # "SWIGGY8102" is the real, complete merchant_norm of an actual
    # transaction — an exact rule, not a generalized keyword.
    store.remember("SWIGGY8102", "Dining", kind="merchant")

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    learned = json.loads(urllib.request.urlopen(base + "/api/rules", timeout=3).read())["learned"]

    by_pattern = {r["pattern"]: r for r in learned}
    assert by_pattern["CREDCLUB"]["broad"] is True
    assert by_pattern["SWIGGY8102"]["broad"] is False
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


# ------------------------------------------------------- purpose-tail sweep
def test_normalizer_extracts_purpose_tail_from_upi_narration():
    """Real finding: 400+ otherwise-unclassifiable individual UPI payments
    in one real account carried a purpose word in the raw narration
    ('...-336468937787-fo od Value Dt 30/12/2023 Ref 336468937787' means
    "food") that the pipeline silently discarded — the UPI extract step
    replaces the whole string with just the captured VPA username, so
    this text never reached merchant_norm or payee_handle. Must survive
    the same stray-space-mid-word artifact as other narrations in this
    pack ("fo od", not "food")."""
    n = Normalizer(region="in")
    r = n.normalize(
        "UPI-MOUNTAIN VIEW SWEETS-gpay-11240952815@ okbizaxis-UTIB0000000-"
        "336468937787-fo od Value Dt 30/12/2023 Ref 336468937787")
    assert r.purpose.replace(" ", "").upper() == "FOOD"


def test_normalizer_extracts_purpose_even_when_payee_detected():
    """Payee detection returns early, before the merchant extract/strip
    logic runs — purpose extraction must not be skipped just because the
    counterparty turned out to be a person. P2P payments to unknown
    individuals are exactly where this signal matters most."""
    n = Normalizer(region="in")
    r = n.normalize(
        "UPI-P2P-ARJUN T-9123456781@okbizaxis-UTIB0000000-413471084825-"
        "ta xi Value Dt 13/05/2024 Ref 413471084825")
    assert r.payee_handle == "ARJUN T"
    assert r.purpose.replace(" ", "").upper() == "TAXI"


def test_purpose_matcher_exact_and_stray_space():
    from munim.memory import PurposeMatcher
    m = PurposeMatcher()
    assert m.match("fo od").category == "Dining"
    assert m.match("ta xi").category == "Transport"


def test_purpose_matcher_overcaptured_tail_resolves_via_suffix():
    """Some raw narrations over-capture (an earlier short digit run in
    the string matches first), leaving VPA/IFSC noise glued to the front
    of the real purpose word — must still resolve via the trailing word,
    not fail outright."""
    from munim.memory import PurposeMatcher
    m = PurposeMatcher()
    hit = m.match("2@YBL-KARB0000309-104666732612-TAXI")
    assert hit and hit.category == "Transport"


def test_purpose_matcher_generic_labels_stay_unmatched():
    from munim.memory import PurposeMatcher
    m = PurposeMatcher()
    assert m.match("UPI") is None
    assert m.match("misc") is None


def test_pipeline_resolves_unknown_payee_via_purpose_keyword(tmp_path):
    """The concrete gap this closes: a merchant-string counterparty with
    no matching memory/dictionary entry (real example: a one-off UPI
    recipient with a middle initial) used to dead-end at
    Stage.NONE/Status.UNRESOLVED even when the raw narration plainly said
    what it was for. This narration's merchant text doesn't parse as
    'name-like' by the existing heuristic (a single-letter middle initial
    breaks it), so it exercises the general merchant-miss path, not the
    payee-routing one."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-04", amount=120, direction=Direction.DEBIT,
                    description_raw="UPI-Arjun T-9123456781@okbizaxis-"
                                    "UTIB0000000-413471084825-taxi Value Dt "
                                    "13/05/2024 Ref 413471084825")
    Pipeline(store).run([t])
    assert t.category == "Transport"
    assert t.stage == Stage.PURPOSE
    assert t.status == Status.PROVISIONAL  # still needs a human to confirm


def test_pipeline_resolves_person_like_merchant_via_purpose_keyword(tmp_path):
    """Same gap, the dedicated dead end: a merchant string that the
    'looks like a person' heuristic recognizes (two clean alpha words, no
    business vocabulary) and routes to payee memory — which, with no rule
    taught yet, used to fall straight to Stage.NONE without ever trying
    the purpose tail."""
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    t = Transaction(date="2026-06-04", amount=85, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-"
                                    "UTIB0000000-421024554019-food Value Dt "
                                    "28/07/2024 Ref 421024554019")
    Pipeline(store).run([t])
    assert t.category == "Dining"
    assert t.stage == Stage.PURPOSE
    assert t.payee_handle == "RAMESH KUMAR"  # still routed to payee, just resolved


def test_pipeline_memory_still_outranks_purpose_keyword(tmp_path):
    """A specific taught rule for this exact person must win even when
    the raw narration also happens to carry a purpose word — purpose is
    a last resort, never a priority override."""
    store = Store(home=tmp_path)
    store.remember("RAMESH KUMAR", "Family & Friends", kind="payee")
    store.set_config("region", "in")
    t = Transaction(date="2026-06-04", amount=120, direction=Direction.DEBIT,
                    description_raw="UPI-RAMESH KUMAR@okhdfcbank-"
                                    "UTIB0000000-413471084825-taxi Value Dt "
                                    "13/05/2024 Ref 413471084825")
    Pipeline(store).run([t])
    assert t.category == "Family & Friends"
    assert t.stage == Stage.MEMORY_EXACT


def test_chart_flow_endpoint_groups_by_month(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Groceries"])
    store.upsert_transactions([
        Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                    description_raw="X", category="Groceries", subcategory="Alcohol"),
        Transaction(date="2026-07-01", amount=200, direction=Direction.DEBIT,
                    description_raw="Y", category="Groceries", subcategory="Alcohol"),
    ])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=3).read())

    d = get("/api/chart/flow?group_by=month&category=Groceries&subcategory=Alcohol")
    assert d == {"labels": ["2026-06", "2026-07"], "values": [100.0, 200.0]}
    srv.shutdown()


def test_chart_flow_endpoint_excludes_transfers_by_default(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("categories", ["Transfers", "Dining"])
    store.upsert_transactions([
        Transaction(date="2026-06-01", amount=999, direction=Direction.DEBIT,
                    description_raw="CC PAYMENT", category="Transfers", is_transfer=True),
        Transaction(date="2026-06-02", amount=50, direction=Direction.DEBIT,
                    description_raw="LUNCH", category="Dining"),
    ])

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/flow?group_by=category", timeout=3).read())
    assert d == {"labels": ["Dining"], "values": [50.0]}
    srv.shutdown()


def test_chart_flow_endpoint_rejects_unknown_group_by(tmp_path):
    import threading
    import urllib.request
    import urllib.error
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/chart/flow?group_by=bogus", timeout=3)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    srv.shutdown()


def test_chart_balance_endpoint_defaults_to_all_tracked_accounts(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("account_opening_balances",
                     {"bank": {"balance": 1000.0, "as_of": "2026-06-01"}})

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/balance", timeout=3).read())
    assert d == {"labels": ["2026-06"], "values": [1000.0]}
    srv.shutdown()


def test_chart_balance_endpoint_accepts_comma_separated_accounts(tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import HTTPServer
    from munim.web.server import Handler

    store = Store(home=tmp_path)
    store.set_config("account_opening_balances", {
        "bank": {"balance": 1000.0, "as_of": "2026-06-01"},
        "other": {"balance": 5000.0, "as_of": "2026-06-01"},
    })

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.store = store
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    d = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/chart/balance?accounts=bank", timeout=3).read())
    assert d == {"labels": ["2026-06"], "values": [1000.0]}
    srv.shutdown()
