import importlib.util
from pathlib import Path


ROOT = Path(__file__).parent.parent
SPEC = importlib.util.spec_from_file_location(
    "validate_install_taxonomy_test",
    ROOT / "scripts" / "validate_install.py",
)
validate_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_install)


class Worksheet:
    def __init__(self, rows):
        self.rows = rows
        self.row_count = len(rows)

    def row_values(self, row):
        return list(self.rows[row - 1])

    def get_all_values(self):
        return [list(row) for row in self.rows]


class Sheet:
    def __init__(self, master_rows, category_rows):
        self.worksheets = {
            "MERCHANT_MASTER": Worksheet(master_rows),
            "CATEGORIES": Worksheet(category_rows),
        }

    def worksheet(self, name):
        return self.worksheets[name]


def _rows(master_data, category_data):
    master = [
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases"],
        *master_data,
    ]
    categories = [
        ["banner"],
        ["Category", "Subcategory", "Active"],
        *category_data,
    ]
    return master, categories


def test_integrity_gate_accepts_valid_master_pairs():
    master, categories = _rows(
        [["Corner Cafe", "Corner Cafe", "Dining", "Cafe"]],
        [["Dining", "Cafe", "TRUE"], ["Misc", "Other", "TRUE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is True
    assert "1 merchants" in message


def test_integrity_gate_rejects_blank_subcategory():
    master, categories = _rows(
        [["Corner Cafe", "Corner Cafe", "Dining", ""]],
        [["Dining", "Cafe", "TRUE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "missing Category/Subcategory" in message


def test_integrity_gate_rejects_empty_taxonomy():
    master, categories = _rows([], [])
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "no active Category/Subcategory pairs" in message


def test_integrity_gate_rejects_pair_outside_active_taxonomy():
    master, categories = _rows(
        [["Corner Cafe", "Corner Cafe", "Dining", "Restaurant"]],
        [["Dining", "Cafe", "TRUE"], ["Dining", "Restaurant", "FALSE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "not present in active CATEGORIES" in message


def test_integrity_gate_rejects_conflicting_duplicate_merchant():
    master, categories = _rows(
        [
            ["Corner Cafe", "Corner Cafe", "Dining", "Cafe"],
            ["corner cafe", "Corner Cafe", "Dining", "Restaurant"],
        ],
        [["Dining", "Cafe", "TRUE"], ["Dining", "Restaurant", "TRUE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "conflicting duplicate keyword" in message


def test_integrity_gate_requires_review_fallback_pair():
    master, categories = _rows(
        [["Corner Cafe", "Corner Cafe", "Dining", "Cafe"]],
        [["Dining", "Cafe", "TRUE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "Misc / Other" in message


def test_integrity_gate_rejects_conflicting_alias_mapping():
    master, categories = _rows(
        [
            ["Corner Cafe", "Corner Cafe", "Dining", "Cafe", "corner"],
            ["Corner Market", "Corner Market", "Groceries", "Supermarket", "corner"],
        ],
        [
            ["Dining", "Cafe", "TRUE"],
            ["Groceries", "Supermarket", "TRUE"],
            ["Misc", "Other", "TRUE"],
        ],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "Conflicting merchant phrase" in message


def test_integrity_gate_normalizes_duplicate_merchant_keywords():
    master, categories = _rows(
        [
            ["Corner-Cafe", "Corner Cafe", "Dining", "Cafe"],
            ["Corner Cafe", "Corner Cafe", "Dining", "Restaurant"],
        ],
        [["Dining", "Cafe", "TRUE"], ["Dining", "Restaurant", "TRUE"]],
    )
    ok, message = validate_install.g4b({"_book": Sheet(master, categories)})
    assert ok is False
    assert "conflicting duplicate keyword" in message
