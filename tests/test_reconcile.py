"""Tests for reconcile_statement — match rule + dedup behaviour."""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from reconcile_statement import reconcile, _token_overlap


def test_token_overlap():
    assert _token_overlap("amazon ae", "amazon online") > 0.3
    assert _token_overlap("starbucks dxb", "carrefour moe") == 0.0


def test_match_within_tolerances():
    statement = [{"date": date(2026, 4, 15), "amount": 87.00, "merchant_raw": "AMAZON MARKETPLACE AE"}]
    ledger = [{"Date": "2026-04-15", "Amount": "87.00",
               "Merchant_Raw": "AMAZON MARKETPLACE", "Merchant_Clean": "Amazon"}]
    out = reconcile(statement, ledger)
    assert out[0]["status"] == "MATCHED"


def test_gap_when_amount_off():
    statement = [{"date": date(2026, 4, 15), "amount": 87.00, "merchant_raw": "AMAZON MARKETPLACE"}]
    ledger = [{"Date": "2026-04-15", "Amount": "100.00",
               "Merchant_Raw": "AMAZON.AE", "Merchant_Clean": "Amazon"}]
    out = reconcile(statement, ledger)
    assert out[0]["status"] == "GAP"


def test_gap_when_date_too_far():
    statement = [{"date": date(2026, 4, 15), "amount": 87.00, "merchant_raw": "AMAZON"}]
    ledger = [{"Date": "2026-04-20", "Amount": "87.00",
               "Merchant_Raw": "AMAZON.AE", "Merchant_Clean": "Amazon"}]
    out = reconcile(statement, ledger)
    assert out[0]["status"] == "GAP"


def test_gap_when_merchant_dissimilar():
    statement = [{"date": date(2026, 4, 15), "amount": 87.00, "merchant_raw": "MYSTERY VENDOR"}]
    ledger = [{"Date": "2026-04-15", "Amount": "87.00",
               "Merchant_Raw": "AMAZON.AE", "Merchant_Clean": "Amazon"}]
    out = reconcile(statement, ledger)
    assert out[0]["status"] == "GAP"


if __name__ == "__main__":
    failures = 0
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        try:
            fn(); print(f"  ✅ {fn.__name__}")
        except AssertionError as e:
            print(f"  ❌ {fn.__name__}: {e}"); failures += 1
        except Exception as e:
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}"); failures += 1
    print(f"\n{len(fns) - failures} passed · {failures} failed")
    sys.exit(0 if failures == 0 else 1)
