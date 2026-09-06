"""End-to-end dry-run smoke test: parse → resolve → row build."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from parse_transaction import parse
from merchant_resolver import build_master_from_rows, resolve
from write_sheet import transaction_to_row, HEADERS


def test_end_to_end_dry_run():
    raw = "AED 87.00 spent on WioCredit at CARREFOUR MOE on 29/04/2026"
    txn = parse(raw)
    assert txn.valid

    master = build_master_from_rows([
        ["banner"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["Carrefour", "Carrefour", "Groceries", "Supermarket"],
    ])
    decision = resolve(txn.merchant_raw, master)
    assert decision["tier"] == 1
    assert decision["category"] == "Groceries"

    row = transaction_to_row({
        "date": txn.date,
        "amount": txn.amount,
        "currency": txn.currency,
        "merchant_raw": txn.merchant_raw,
        "merchant_clean": decision["merchant_clean"],
        "category": decision["category"],
        "subcategory": decision["subcategory"],
        "card": txn.card,
        "source": "Test",
        "status": "Confirmed",
        "hash": txn.hash,
    })
    assert len(row) == len(HEADERS)
    assert row[HEADERS.index("Hash")] == txn.hash
    assert row[HEADERS.index("Category")] == "Groceries"


if __name__ == "__main__":
    try:
        test_end_to_end_dry_run()
        print("  ✅ test_end_to_end_dry_run")
    except AssertionError as e:
        print(f"  ❌ test_end_to_end_dry_run: {e}")
        sys.exit(1)
    print("\n1 passed")
