"""The category tree: a DISPLAY mapping from flat leaf categories to full
ledger paths under the five accounting roots.

Design rule (docs/philosophy.md): the engine classifies flat leaves because
labeling consistency is the product; trees are a view, not a truth. Nothing
in matching, memory, review, or the classifier ever sees a path. Only the
reporting edges — exporters, dashboard — resolve leaves through this map.
"""
from __future__ import annotations

ROOTS = ("Assets", "Liabilities", "Equity", "Income", "Expenses")

# Leaves that don't belong under Expenses by default
SPECIAL = {
    "Income": "Income",
    "Transfers": "Equity:Transfers",
    "Investments": "Assets:Investments",
}

MAX_LEAVES = 20   # labeling consistency collapses beyond this; hard limit

# Subcategories only ever show up once you've already committed to a
# parent head, so they get their own smaller, per-parent budget instead
# of competing for the scarce top-level MAX_LEAVES slots.
MAX_SUBCATEGORIES_PER_PARENT = 10


def default_tree(categories: list[str]) -> dict[str, str]:
    return {c: SPECIAL.get(c, f"Expenses:{c}") for c in categories}


def get_tree(store) -> dict[str, str]:
    """Default mapping, overlaid with the user's config. Every leaf always
    resolves — unmapped leaves default under Expenses."""
    cats = store.get_config("categories", [])
    tree = default_tree(cats)
    for leaf, path in (store.get_config("category_tree", {}) or {}).items():
        if valid_path(path):
            tree[leaf] = path
    return tree


def valid_path(path: str) -> bool:
    return bool(path) and path.split(":")[0] in ROOTS


def root_of(path: str) -> str:
    return path.split(":")[0]


def resolve(tree: dict[str, str], leaf: str) -> str:
    if leaf in tree:
        return tree[leaf]
    if leaf in SPECIAL:   # Transfers/Income/Investments are never Expenses
        return SPECIAL[leaf]
    return f"Expenses:{leaf}" if leaf else "Expenses:Uncategorized"


def account_root(store, account: str) -> str:
    """Bank accounts are Assets unless the user marks them Liabilities
    (credit cards, loans)."""
    types = store.get_config("account_types", {}) or {}
    return types.get(account, "Assets")
