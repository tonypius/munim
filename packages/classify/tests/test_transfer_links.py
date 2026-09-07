"""Tests for transfer-pair linking: the transfer_links and
transfer_dismissals tables, and Store's core methods over them."""
import sys
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def test_fresh_store_has_transfer_tables(tmp_path):
    store = Store(home=tmp_path)
    tables = {r[0] for r in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "transfer_links" in tables
    assert "transfer_dismissals" in tables


def test_link_transfer_then_is_linked(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    assert store.is_linked("txn-a")
    assert store.is_linked("txn-b")
    assert not store.is_linked("txn-c")


def test_linked_counterpart_works_both_directions(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    assert store.linked_counterpart("txn-a") == "txn-b"
    assert store.linked_counterpart("txn-b") == "txn-a"
    assert store.linked_counterpart("txn-c") is None


def test_link_transfer_is_idempotent(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b")
    store.link_transfer("txn-a", "txn-b")  # re-linking the same pair
    rows = store.all_transfer_links()
    assert len(rows) == 1


def test_transfer_link_map_covers_both_directions(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b", confidence="auto")
    store.link_transfer("txn-c", "txn-d", confidence="confirmed")
    m = store.transfer_link_map()
    assert m == {"txn-a": "txn-b", "txn-b": "txn-a",
                "txn-c": "txn-d", "txn-d": "txn-c"}


def test_all_transfer_links_records_confidence(tmp_path):
    store = Store(home=tmp_path)
    store.link_transfer("txn-a", "txn-b", confidence="confirmed")
    rows = store.all_transfer_links()
    assert len(rows) == 1
    assert rows[0]["confidence"] == "confirmed"
    assert {rows[0]["txn_id_a"], rows[0]["txn_id_b"]} == {"txn-a", "txn-b"}


def test_dismiss_transfer_then_is_dismissed(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    assert store.is_dismissed("txn-x")
    assert not store.is_dismissed("txn-y")


def test_dismissed_ids_returns_a_set(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    store.dismiss_transfer("txn-y")
    assert store.dismissed_ids() == {"txn-x", "txn-y"}


def test_dismiss_transfer_is_idempotent(tmp_path):
    store = Store(home=tmp_path)
    store.dismiss_transfer("txn-x")
    store.dismiss_transfer("txn-x")
    assert len(store.dismissed_ids()) == 1


def _transfer(id_, date, amount, direction, account):
    return Transaction(id=id_, date=date, amount=amount, direction=direction,
                       description_raw=f"TRANSFER {id_}", account=account,
                       is_transfer=True, category="Transfers")


def test_find_transfer_candidates_exact_single_match_is_auto(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == [("d1", "c1")]
    assert result["ambiguous"] == []


def test_find_transfer_candidates_multiple_matches_is_ambiguous(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-03", 5000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert len(result["ambiguous"]) == 1
    assert result["ambiguous"][0][0] == "d1"
    assert set(result["ambiguous"][0][1]) == {"c1", "c2"}


def test_find_transfer_candidates_same_account_never_matches(tmp_path):
    """A debit and credit in the SAME account can't be a transfer between
    two of the user's accounts by definition."""
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "bank")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_outside_window_does_not_match(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-20", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_excludes_already_linked(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_excludes_dismissed(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.dismiss_transfer("d1")
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_ignores_non_transfers(tmp_path):
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit = Transaction(id="d1", date="2026-06-01", amount=5000,
                        direction=Direction.DEBIT, description_raw="GROCERY",
                        account="bank", is_transfer=False, category="Groceries")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert result["ambiguous"] == []


def test_find_transfer_candidates_credit_claimed_by_two_debits_is_ambiguous(tmp_path):
    """A credit that looks like the sole candidate for two different debits
    can't be safely auto-linked to either -- the system genuinely cannot
    tell which debit it really pairs with."""
    from munim.structural.transfer_matching import find_transfer_candidates
    store = Store(home=tmp_path)
    debit1 = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    debit2 = _transfer("d2", "2026-06-01", 5000, Direction.DEBIT, "bank2")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit1, debit2, credit])
    result = find_transfer_candidates(store)
    assert result["auto"] == []
    assert {d for d, _ in result["ambiguous"]} == {"d1", "d2"}


def test_apply_auto_links_links_exact_matches_only(tmp_path):
    from munim.structural.transfer_matching import apply_auto_links
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    ambiguous_debit = _transfer("d2", "2026-06-01", 7000, Direction.DEBIT, "bank")
    ambiguous_credit1 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "card")
    ambiguous_credit2 = _transfer("c3", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit, ambiguous_debit,
                               ambiguous_credit1, ambiguous_credit2])
    n = apply_auto_links(store)
    assert n == 1
    assert store.linked_counterpart("d1") == "c1"
    assert not store.is_linked("d2")


def test_import_csv_auto_links_transfers(tmp_path, monkeypatch):
    """End-to-end: importing a CSV that structurally detects a transfer
    which exactly matches an existing unlinked transfer must auto-link
    them, without a separate `transfers link` call. Pre-seeds a saved
    CSV profile (matching _load_or_build_profile's "name in profiles"
    branch) so the import runs straight through without the interactive
    column-mapping wizard."""
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    store.set_config("region", "in")
    store.set_config("csv_profiles", {
        "test": {"date_col": "Date", "description_col": "Narration",
                 "amount_col": "Amount", "debit_col": "", "credit_col": "",
                 "currency": "INR", "date_format": ""},
    })
    existing = _transfer("c1", "2026-06-02", 45230, Direction.CREDIT, "tony-hdfc-regalia-cc")
    store.upsert_transactions([existing])

    csv_path = tmp_path / "bank.csv"
    csv_path.write_text(
        "Date,Narration,Amount\n"
        "01/06/2026,CREDIT CARD PAYMENT BILLDESK HDFC CARD,-45230.00\n",
        encoding="utf-8")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["import", str(csv_path), "--profile", "test",
                                 "--account", "tony-hdfc-savings"])
    assert result.exit_code == 0, result.output

    reloaded = Store(home=tmp_path)
    new_debit_id = [t.id for t in reloaded.all_transactions() if t.id != "c1"][0]
    assert reloaded.linked_counterpart(new_debit_id) == "c1"


def test_transfers_link_command_reports_count(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "link"])
    assert result.exit_code == 0, result.output
    assert "1" in result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.linked_counterpart("d1") == "c1"


def test_transfers_review_links_the_chosen_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 7000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 7000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    # "2" selects the second listed candidate
    result = runner.invoke(app, ["transfers", "review"], input="2\n")
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.is_linked("d1")
    rows = reloaded.all_transfer_links()
    assert rows[0]["confidence"] == "confirmed"


def test_transfers_review_skip_leaves_unlinked(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 7000, Direction.DEBIT, "bank")
    credit1 = _transfer("c1", "2026-06-02", 7000, Direction.CREDIT, "card")
    credit2 = _transfer("c2", "2026-06-02", 7000, Direction.CREDIT, "wallet")
    store.upsert_transactions([debit, credit1, credit2])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "review"], input="s\n")
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert not reloaded.is_linked("d1")


def test_transfers_review_empty_queue_message(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "review"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "nothing" in result.output.lower()


def test_transfers_dismiss_marks_dismissed(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    store.upsert_transactions([debit])
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "d1"])
    assert result.exit_code == 0, result.output
    reloaded = Store(home=tmp_path)
    assert reloaded.is_dismissed("d1")


def test_transfers_dismiss_rejects_already_linked_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    store.upsert_transactions([debit, credit])
    store.link_transfer("d1", "c1")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "d1"])
    assert result.exit_code != 0
    reloaded = Store(home=tmp_path)
    assert not reloaded.is_dismissed("d1")


def test_transfers_dismiss_rejects_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "dismiss", "nonexistent"])
    assert result.exit_code != 0


def test_transfers_status_reports_all_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))
    store = Store(home=tmp_path)
    linked_a = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "bank")
    linked_b = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "card")
    pending = _transfer("d2", "2026-06-05", 3000, Direction.DEBIT, "bank")
    dismissed = _transfer("d3", "2026-06-06", 2000, Direction.DEBIT, "wallet")
    store.upsert_transactions([linked_a, linked_b, pending, dismissed])
    store.link_transfer("d1", "c1", confidence="auto")
    store.dismiss_transfer("d3")
    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["transfers", "status"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "bank" in out  # the pending one's account surfaced


def test_ledger_export_uses_real_account_for_linked_transfer(tmp_path):
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    credit = _transfer("c1", "2026-06-02", 5000, Direction.CREDIT, "tony-hdfc-regalia-cc")
    tree = default_tree(["Transfers"])
    account_types = {"tony-hdfc-savings": "Assets", "tony-hdfc-regalia-cc": "Liabilities"}
    links = {"d1": "c1", "c1": "d1"}
    out = to_ledger([debit, credit], tree=tree, account_types=account_types, links=links)
    assert "Equity:Transfers" not in out
    assert "Liabilities:tony-hdfc-regalia-cc" in out
    assert "Assets:tony-hdfc-savings" in out


def test_ledger_export_falls_back_to_equity_transfers_when_unlinked(tmp_path):
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    tree = default_tree(["Transfers"])
    out = to_ledger([debit], tree=tree, account_types={"tony-hdfc-savings": "Assets"})
    assert "Equity:Transfers" in out


def test_ledger_export_links_parameter_is_optional(tmp_path):
    """Existing callers that never pass `links` must see identical
    output to before this change -- links defaults to {}."""
    from munim.export_formats import to_ledger
    from munim.tree import default_tree
    debit = _transfer("d1", "2026-06-01", 5000, Direction.DEBIT, "tony-hdfc-savings")
    tree = default_tree(["Transfers"])
    out = to_ledger([debit], tree=tree, account_types={"tony-hdfc-savings": "Assets"})
    assert "Equity:Transfers" in out
