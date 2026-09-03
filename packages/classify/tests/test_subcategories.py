"""Category subcategories: a second, optional level under a category
head (Groceries -> Groceries:Alcohol), taught via memory rules and
applied independently of the existing flat category field."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.schema import Transaction, Direction


def test_transaction_subcategory_defaults_to_empty_string():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP")
    assert t.subcategory == ""


def test_transaction_subcategory_can_be_set():
    t = Transaction(date="2026-06-01", amount=100, direction=Direction.DEBIT,
                     description_raw="SHETTY BEER SHOP",
                     category="Groceries", subcategory="Alcohol")
    assert t.subcategory == "Alcohol"
