import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class Worksheet:
    def __init__(self, rows):
        self.rows = rows

    def get_all_values(self):
        return [list(row) for row in self.rows]


class Sheet:
    def __init__(self, expenses, merchants, categories):
        self.worksheets = {
            "EXPENSES": Worksheet(expenses),
            "MERCHANT_MASTER": Worksheet(merchants),
            "CATEGORIES": Worksheet(categories),
        }

    def worksheet(self, name):
        return self.worksheets[name]


def _sheet(*, master_pair=("Dining", "Cafe"), category_pair=("Dining", "Cafe")):
    expenses = [
        ["banner"],
        ["Txn_ID", "Date", "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean"],
        ["T1", "2026-07-20", "Misc", "Other", "Corner Cafe", "Corner Cafe"],
    ]
    merchants = [
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["Corner Cafe", "Corner Cafe", *master_pair],
    ]
    categories = [
        ["banner"],
        ["Category", "Subcategory", "Active"],
        [*category_pair, "TRUE"],
    ]
    return Sheet(expenses, merchants, categories)


def test_history_plan_uses_canonical_active_taxonomy_spelling():
    from recategorise_history import plan_changes

    plan = plan_changes(
        _sheet(master_pair=("dining", "cafe")),
        {},
        since=None,
        until=None,
        cat_map={},
    )
    assert plan[0]["proposed"] == {"category": "Dining", "subcategory": "Cafe"}


def test_history_plan_rejects_pair_outside_active_taxonomy():
    from recategorise_history import plan_changes

    with pytest.raises(RuntimeError, match="not active in CATEGORIES"):
        plan_changes(
            _sheet(master_pair=("Dining", "Restaurant")),
            {},
            since=None,
            until=None,
            cat_map={},
        )
