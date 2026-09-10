"""Tests for munim/reporting.py -- the aggregation module shared by the
Dashboard tab and on-the-go conversational charts (see
docs/superpowers/specs/2026-09-10-chart-engine-design.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from munim.schema import Transaction, Direction
from munim.reporting import flow_query


def _txn(date, amount, direction, **kw):
    return Transaction(date=date, amount=amount, direction=direction,
                       description_raw=kw.pop("description_raw", "X"), **kw)


def test_flow_query_groups_by_month_sorted_chronologically():
    txns = [
        _txn("2026-07-01", 100, Direction.DEBIT),
        _txn("2026-06-01", 50, Direction.DEBIT),
        _txn("2026-06-15", 25, Direction.DEBIT),
    ]
    rows = flow_query(txns, "month")
    assert rows == [
        {"label": "2026-06", "value": 75.0},
        {"label": "2026-07", "value": 100.0},
    ]


def test_flow_query_groups_by_category_sorted_by_descending_value():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, category="Dining"),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Groceries"),
        _txn("2026-06-03", 5, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category")
    assert rows == [
        {"label": "Groceries", "value": 50.0},
        {"label": "Dining", "value": 15.0},
    ]


def test_flow_query_uncategorized_label_for_empty_category():
    txns = [_txn("2026-06-01", 10, Direction.DEBIT, category="")]
    rows = flow_query(txns, "category")
    assert rows == [{"label": "(uncategorized)", "value": 10.0}]


def test_flow_query_groups_by_subcategory_none_label_when_empty():
    txns = [_txn("2026-06-01", 10, Direction.DEBIT, category="Groceries", subcategory="")]
    rows = flow_query(txns, "subcategory")
    assert rows == [{"label": "(none)", "value": 10.0}]


def test_flow_query_groups_by_merchant_falls_back_to_payee_handle():
    t = _txn("2026-06-01", 10, Direction.DEBIT)
    t.merchant_norm = ""
    t.payee_handle = "RAMESH KUMAR"
    rows = flow_query([t], "merchant")
    assert rows == [{"label": "RAMESH KUMAR", "value": 10.0}]


def test_flow_query_merchant_unknown_label_when_both_empty():
    rows = flow_query([_txn("2026-06-01", 10, Direction.DEBIT)], "merchant")
    assert rows == [{"label": "(unknown)", "value": 10.0}]


def test_flow_query_groups_by_account():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, account="hdfc"),
        _txn("2026-06-02", 20, Direction.DEBIT, account="sib"),
        _txn("2026-06-03", 5, Direction.DEBIT, account="hdfc"),
    ]
    rows = flow_query(txns, "account")
    assert rows == [
        {"label": "sib", "value": 20.0},
        {"label": "hdfc", "value": 15.0},
    ]


def test_flow_query_excludes_transfers_by_default():
    txns = [
        _txn("2026-06-01", 100, Direction.DEBIT, category="Transfers", is_transfer=True),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category")
    assert rows == [{"label": "Dining", "value": 50.0}]


def test_flow_query_can_include_transfers_when_asked():
    txns = [_txn("2026-06-01", 100, Direction.DEBIT, category="Transfers", is_transfer=True)]
    rows = flow_query(txns, "category", exclude_transfers=False)
    assert rows == [{"label": "Transfers", "value": 100.0}]


def test_flow_query_filters_by_direction():
    txns = [
        _txn("2026-06-01", 100, Direction.CREDIT, category="Income"),
        _txn("2026-06-02", 50, Direction.DEBIT, category="Dining"),
    ]
    rows = flow_query(txns, "category", direction="credit")
    assert rows == [{"label": "Income", "value": 100.0}]


def test_flow_query_filters_by_account_category_subcategory():
    txns = [
        _txn("2026-06-01", 10, Direction.DEBIT, account="a", category="Groceries", subcategory="Alcohol"),
        _txn("2026-06-02", 20, Direction.DEBIT, account="b", category="Groceries", subcategory="Alcohol"),
        _txn("2026-06-03", 30, Direction.DEBIT, account="a", category="Groceries", subcategory="Meat"),
        _txn("2026-06-04", 40, Direction.DEBIT, account="a", category="Dining"),
    ]
    rows = flow_query(txns, "month", account="a", category="Groceries", subcategory="Alcohol")
    assert rows == [{"label": "2026-06", "value": 10.0}]


def test_flow_query_filters_by_date_range_inclusive():
    txns = [
        _txn("2026-05-31", 1, Direction.DEBIT),
        _txn("2026-06-01", 2, Direction.DEBIT),
        _txn("2026-06-30", 4, Direction.DEBIT),
        _txn("2026-07-01", 8, Direction.DEBIT),
    ]
    rows = flow_query(txns, "month", date_from="2026-06-01", date_to="2026-06-30")
    assert rows == [{"label": "2026-06", "value": 6.0}]


def test_flow_query_unknown_group_by_raises():
    with pytest.raises(ValueError, match="group_by"):
        flow_query([], "not-a-real-dimension")


def test_flow_query_empty_input_returns_empty_list():
    assert flow_query([], "month") == []
