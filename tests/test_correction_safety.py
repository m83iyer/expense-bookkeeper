"""Tests for correction handler safety guards (audit fix 2026-05-01).

Covers:
  - Bulk recategorise defaults to dry-run preview (no silent mutation)
  - MERCHANT_MASTER conflict detection (refuses overwrite without flag)
  - Audit log appended for every applied change
  - Bulk match uses word-boundary phrase matching, not substring

Uses an in-process gspread mock — no live Google API calls.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ── In-memory worksheet/spreadsheet mock ─────────────────────────────

class MockWorksheet:
    def __init__(self, name, rows):
        self.name = name
        self._rows = [list(r) for r in rows]
        self.update_calls = []
        self.append_calls = []

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def update_cell(self, row, col, value):
        # 1-indexed
        while len(self._rows) < row:
            self._rows.append([])
        while len(self._rows[row - 1]) < col:
            self._rows[row - 1].append("")
        self._rows[row - 1][col - 1] = value
        self.update_calls.append((row, col, value))

    def append_row(self, row, value_input_option=None):
        self._rows.append(list(row))
        self.append_calls.append(row)


class MockSheet:
    def __init__(self, **worksheets):
        self._ws = worksheets

    def worksheet(self, name):
        return self._ws[name]


def _make_sheet(*, master_rows=None, expenses_rows=None, categories_rows=None):
    master_rows = master_rows or [
        ["banner — MERCHANT_MASTER"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases", "Last_Updated"],
    ]
    expenses_rows = expenses_rows or [
        ["banner — EXPENSES"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
    ]
    categories_rows = categories_rows or [
        ["banner — CATEGORIES"],
        ["Category", "Subcategory", "Active", "Notes"],
        ["Groceries", "In-store", "TRUE", ""],
        ["Groceries", "Online", "TRUE", ""],
    ]
    return MockSheet(
        MERCHANT_MASTER=MockWorksheet("MERCHANT_MASTER", master_rows),
        EXPENSES=MockWorksheet("EXPENSES", expenses_rows),
        CATEGORIES=MockWorksheet("CATEGORIES", categories_rows),
    )


def _config_for_audit(tmpdir):
    return {
        "metadata": {"state_dir": str(tmpdir)},
        "sheet": {"id": "x", "service_account_path": "/dev/null"},
    }


# ── Conflict detection ──────────────────────────────────────────────

def test_merchant_master_conflict_refused():
    from correction_handler import update_merchant_master

    sh = _make_sheet(master_rows=[
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases", "Last_Updated"],
        ["Spinneys", "Spinneys", "Groceries", "Online", "", "2026-04-30"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    result = update_merchant_master(sh, "Spinneys", "Groceries", "In-store", cfg,
                                    dry_run=False, allow_overwrite=False)
    assert result["action"] == "conflict_refused", result
    assert result["existing"] == {"category": "Groceries", "subcategory": "Online"}
    assert result["proposed"] == {"category": "Groceries", "subcategory": "In-store"}
    # Critical: NO mutation
    assert sh._ws["MERCHANT_MASTER"].update_calls == []


def test_merchant_master_overwrite_with_flag():
    from correction_handler import update_merchant_master

    sh = _make_sheet(master_rows=[
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases", "Last_Updated"],
        ["Spinneys", "Spinneys", "Groceries", "Online", "", "2026-04-30"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    result = update_merchant_master(sh, "Spinneys", "Groceries", "In-store", cfg,
                                    dry_run=False, allow_overwrite=True)
    assert result["action"] == "overwritten", result
    assert result["previous"] == {"category": "Groceries", "subcategory": "Online"}
    assert result["current"] == {"category": "Groceries", "subcategory": "In-store"}
    # Mutation happened
    assert len(sh._ws["MERCHANT_MASTER"].update_calls) == 3  # cat, sub, last_updated


def test_merchant_master_noop_when_already_set():
    from correction_handler import update_merchant_master
    sh = _make_sheet(master_rows=[
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases", "Last_Updated"],
        ["Spinneys", "Spinneys", "Groceries", "Online", "", "2026-04-30"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    result = update_merchant_master(sh, "Spinneys", "Groceries", "Online", cfg)
    assert result["action"] == "noop_already_set"
    assert sh._ws["MERCHANT_MASTER"].update_calls == []


# ── Bulk recategorise — word-boundary + dry-run default ─────────────

def test_recategorise_uses_word_boundary_not_substring():
    """The headline audit fix: 'rent' MUST NOT bulk-update rows for 'rental'."""
    from correction_handler import recategorise_expenses

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "100", "AED", "Expense", "Housing", "Rent",
         "RENT MAY 2026", "Rent", "", "", "", "", "Confirmed", "", "h1"],
        ["T2", "2026-04-02", "", "", "50", "AED", "Expense", "Transport", "Rental",
         "RENTAL CAR DOWNTOWN", "Rental Car", "", "", "", "", "Confirmed", "", "h2"],
        ["T3", "2026-04-03", "", "", "20", "AED", "Expense", "Banking", "Fees",
         "current account fee", "Account Fee", "", "", "", "", "Confirmed", "", "h3"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))

    # Dry-run preview by default
    result = recategorise_expenses(sh, "rent", "Housing", "Rent", cfg, dry_run=True)
    # Only T1 (RENT MAY 2026) should match — and it's already set, so no change needed.
    assert result["would_update"] == 0, f"unexpected match: {result}"


def test_recategorise_word_boundary_positive():
    from correction_handler import recategorise_expenses

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "100", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys Marina DXB", "Spinneys Marina", "", "", "", "", "Confirmed", "", "h1"],
        ["T2", "2026-04-02", "", "", "50", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys MOE", "Spinneys MOE", "", "", "", "", "Confirmed", "", "h2"],
        ["T3", "2026-04-03", "", "", "30", "AED", "Expense", "Right", "Already",
         "ENBD ATM Withdrawal", "ENBD", "", "", "", "", "Confirmed", "", "h3"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))

    # Preview
    result = recategorise_expenses(sh, "Spinneys", "Groceries", "In-store", cfg, dry_run=True)
    assert result["would_update"] == 2, f"expected 2, got {result}"
    assert sh._ws["EXPENSES"].update_calls == []  # preview = no mutation


def test_recategorise_writes_audit_on_apply():
    from correction_handler import recategorise_expenses

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "100", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys Marina", "Spinneys Marina", "", "", "", "", "Confirmed", "", "h1"],
    ])
    tmp = Path(tempfile.mkdtemp())
    cfg = _config_for_audit(tmp)
    result = recategorise_expenses(sh, "Spinneys", "Groceries", "In-store", cfg, dry_run=False)
    assert result["updated"] == 1
    audit = tmp / "correction_audit.log"
    assert audit.exists(), "audit log not written"
    lines = [json.loads(l) for l in audit.read_text().strip().splitlines() if l.strip()]
    assert any(e["op"] == "expenses.recategorise" for e in lines), f"audit op missing: {lines}"


# ── Apply-correction high-level safety ──────────────────────────────

def test_named_merchant_correction_defaults_to_preview():
    from correction_handler import apply_correction

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "50", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys Marina", "Spinneys Marina", "", "", "", "", "Confirmed", "", "h1"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "named_merchant", "merchant": "Spinneys",
              "category": "Groceries", "subcategory": "In-store"}
    result = apply_correction(sh, parsed, txn_id=None, cfg=cfg,
                              confirm_bulk=False, allow_overwrite=False)
    assert result.get("preview_only") is True
    assert sh._ws["EXPENSES"].update_calls == []
    assert sh._ws["MERCHANT_MASTER"].append_calls == []


def test_named_merchant_correction_applies_with_confirm():
    from correction_handler import apply_correction

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "50", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys Marina", "Spinneys Marina", "", "", "", "", "Confirmed", "", "h1"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "named_merchant", "merchant": "Spinneys",
              "category": "Groceries", "subcategory": "In-store"}
    result = apply_correction(sh, parsed, txn_id=None, cfg=cfg,
                              confirm_bulk=True, allow_overwrite=False)
    assert "preview_only" not in result
    assert result["bulk"]["updated"] == 1
    assert result["master"]["action"] == "appended"  # new master entry


def test_named_merchant_blocked_on_master_conflict():
    from correction_handler import apply_correction

    sh = _make_sheet(master_rows=[
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases", "Last_Updated"],
        ["Spinneys", "Spinneys", "Groceries", "Online", "", "2026-04-30"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "named_merchant", "merchant": "Spinneys",
              "category": "Groceries", "subcategory": "In-store"}
    result = apply_correction(sh, parsed, txn_id=None, cfg=cfg,
                              confirm_bulk=True, allow_overwrite=False)
    assert result.get("blocked") is True
    assert result.get("reason") == "merchant_master_conflict"
    # No mutation
    assert sh._ws["MERCHANT_MASTER"].update_calls == []
    assert sh._ws["EXPENSES"].update_calls == []


def test_correction_rejects_unknown_taxonomy_pair_before_any_write():
    from correction_handler import apply_correction

    sh = _make_sheet()
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "named_merchant", "merchant": "Spinneys",
              "category": "Groceries", "subcategory": "Typo bucket"}
    result = apply_correction(sh, parsed, txn_id=None, cfg=cfg,
                              confirm_bulk=True, allow_overwrite=False)
    assert result["blocked"] is True
    assert result["reason"] == "taxonomy_pair_not_found"
    assert result["taxonomy"]["valid_subcategories"] == ["In-store", "Online"]
    assert sh._ws["MERCHANT_MASTER"].append_calls == []
    assert sh._ws["EXPENSES"].update_calls == []


def test_correction_uses_canonical_taxonomy_spelling():
    from correction_handler import apply_correction

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "50", "AED", "Expense", "Wrong", "Wrong",
         "Spinneys Marina", "Spinneys Marina", "", "", "", "", "Confirmed", "", "h1"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "named_merchant", "merchant": "Spinneys",
              "category": "groceries", "subcategory": "in-STORE"}
    result = apply_correction(sh, parsed, txn_id=None, cfg=cfg,
                              confirm_bulk=True, allow_overwrite=False)
    assert result["master"]["category"] == "Groceries"
    assert result["master"]["subcategory"] == "In-store"


def test_single_review_correction_marks_expense_confirmed():
    from correction_handler import apply_correction

    sh = _make_sheet(expenses_rows=[
        ["banner"],
        ["Txn_ID", "Date", "Day", "Month-Year", "Amount", "Currency", "Txn_Type",
         "Category", "Subcategory", "Merchant_Raw", "Merchant_Clean",
         "Card_Used", "Source", "Person", "Notes", "Status", "Review_Reason", "Hash"],
        ["T1", "2026-04-01", "", "", "50", "AED", "Expense", "Misc", "Other",
         "Corner Market", "Corner Market", "", "", "", "", "Review",
         "Unknown merchant", "h1"],
    ])
    cfg = _config_for_audit(Path(tempfile.mkdtemp()))
    parsed = {"kind": "last_txn", "category": "Groceries", "subcategory": "In-store"}
    result = apply_correction(sh, parsed, txn_id="T1", cfg=cfg)
    assert result["single"]["action"] == "updated"
    row = sh._ws["EXPENSES"]._rows[2]
    headers = sh._ws["EXPENSES"]._rows[1]
    assert row[headers.index("Status")] == "Confirmed"
    assert row[headers.index("Review_Reason")] == ""


if __name__ == "__main__":
    failures = 0
    fns = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        try:
            fn()
            print(f"  ✅ {name}")
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failures += 1
        except Exception as e:
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            failures += 1
    print(f"\n{len(fns) - failures} passed · {failures} failed")
    sys.exit(0 if failures == 0 else 1)
