"""Tests for parse_transaction — bank notification → Transaction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from parse_transaction import parse


def test_spent_on_at():
    t = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    assert t.valid
    assert t.amount == 87.00
    assert t.currency == "AED"
    assert "AMAZON" in t.merchant_raw
    assert t.card == "WioCredit"
    assert t.date == "2026-04-29"


def test_charge_at():
    t = parse("Charge of AED 12.50 at STARBUCKS DXB — 29 Apr 2026")
    assert t.valid
    assert t.amount == 12.50
    assert "STARBUCKS" in t.merchant_raw


def test_generic_pattern():
    t = parse("150.00 AED Carrefour MOE")
    assert t.valid
    assert t.amount == 150.0


def test_empty_input_invalid():
    t = parse("")
    assert not t.valid


def test_no_pattern_invalid():
    t = parse("hello world this is not a transaction")
    assert not t.valid


def test_hash_dedup_consistency():
    a = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    b = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    assert a.hash == b.hash


def test_hash_differentiates_merchant():
    a = parse("AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026")
    c = parse("AED 87.00 spent on WioCredit at NOON.COM on 29/04/2026")
    assert a.hash != c.hash


if __name__ == "__main__":
    failures = 0
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except AssertionError as e:
            print(f"  ❌ {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}")
            failures += 1
    print(f"\n{len(fns) - failures} passed · {failures} failed")
    sys.exit(0 if failures == 0 else 1)
