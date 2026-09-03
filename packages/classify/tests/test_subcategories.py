"""Subcategories feature tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_max_subcategories_per_parent_constant_exists():
    from munim.tree import MAX_SUBCATEGORIES_PER_PARENT
    assert MAX_SUBCATEGORIES_PER_PARENT == 10
