"""Tests for merchant_resolver — three-tier behaviour."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merchant_resolver import build_master_from_rows, resolve, normalise_merchant


def _master():
    return build_master_from_rows([
        ["banner — ignored"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["Carrefour", "Carrefour", "Groceries", "Supermarket"],
        ["GEMS Education", "GEMS Education", "Education", "School Fees"],
        ["GEMS", "GEMS", "Education", "Other"],
        ["Amazon", "Amazon", "Shopping", "Online Retail"],
    ])


def test_normalisation():
    assert normalise_merchant("Carrefour MOE!") == "carrefour moe"
    assert normalise_merchant("AMAZON.AE  ae") == "amazon"
    assert normalise_merchant("") == ""


def test_tier1_exact():
    m = _master()
    r = resolve("Carrefour", m)
    assert r["tier"] == 1
    assert r["category"] == "Groceries"


def test_tier1_substring():
    m = _master()
    r = resolve("Carrefour MOE Branch 12", m)
    assert r["tier"] == 1
    assert r["category"] == "Groceries"


def test_longest_keyword_wins():
    m = _master()
    # "GEMS Education" should beat "GEMS" because it's longer
    r = resolve("GEMS Education School Fees", m)
    assert r["category"] == "Education"
    assert r["subcategory"] == "School Fees"


def test_tier2_keyword_cue():
    m = _master()
    r = resolve("STARBUCKS COFFEE 7723", m)  # not in master, but in default cues
    assert r["tier"] == 2
    assert r["category"] == "Dining"


def test_tier3_unknown():
    m = _master()
    r = resolve("XYZ123 UNKNOWN", m)
    assert r["tier"] == 3


def test_tier3_vague():
    m = _master()
    r = resolve("PURCHASE", m)
    assert r["tier"] == 3
    assert "vague" in r["confidence"]


@pytest.mark.parametrize("descriptor", ["POS 123456", "CARD PAYMENT 7788", "ONLINE PURCHASE 99"])
def test_generic_card_descriptors_are_transaction_only(descriptor):
    history = [
        {"merchant_clean": descriptor, "amount": 10, "card": "Visa", "source": "sms", "status": "Confirmed", "category": "Dining", "subcategory": "Cafe"},
        {"merchant_clean": descriptor, "amount": 10, "card": "Visa", "source": "sms", "status": "Confirmed", "category": "Dining", "subcategory": "Cafe"},
    ]
    result = resolve(descriptor, _master(), history_rows=history, amount=10, card="Visa", source="sms")
    assert result["tier"] == 3
    assert result["learning_scope"] == "transaction_only"


def test_empty_input():
    m = _master()
    r = resolve("", m)
    assert r["tier"] == 3


def test_historical_rows_prevent_repeat_review_for_stable_named_merchant():
    m = _master()
    history = [
        {"merchant_clean": "Corner Bakery", "amount": 25, "card": "Visa", "source": "sms", "category": "Dining", "subcategory": "Bakery"},
        {"merchant_clean": "Corner Bakery", "amount": 31, "card": "Visa", "source": "sms", "category": "Dining", "subcategory": "Bakery"},
    ]
    r = resolve("Corner Bakery", m, history_rows=history, amount=25, card="Visa", source="sms")
    assert r["tier"] == 1
    assert r["category"] == "Dining"
    assert r["confidence"] == "historical-stable"


def test_generic_descriptor_options_are_transaction_only():
    m = _master()
    history = [
        {"merchant_clean": "House Help", "amount": 550, "card": "Cash", "source": "recurring", "category": "Housing", "subcategory": "Housekeeping"},
        {"merchant_clean": "House Help", "amount": 550, "card": "Cash", "source": "recurring", "category": "Housing", "subcategory": "Housekeeping"},
    ]
    r = resolve("Payment", m, history_rows=history, amount=550, card="Cash", source="recurring")
    assert r["tier"] == 3
    assert r["review_options"][0]["category"] == "Housing"
    assert r["learning_scope"] == "transaction_only"


def test_recurring_day_breaks_a_generic_same_amount_tie():
    m = _master()
    history = [
        {"merchant_clean": "House Help", "date": "2026-05-01", "amount": "550.00", "card": "Cash", "source": "recurring", "status": "Confirmed", "category": "Housing", "subcategory": "Housekeeping"},
        {"merchant_clean": "House Help", "date": "2026-06-02", "amount": 550, "card": "Cash", "source": "recurring", "status": "Confirmed", "category": "Housing", "subcategory": "Housekeeping"},
        {"merchant_clean": "Unrelated", "date": "2026-05-20", "amount": 550, "card": "Cash", "source": "recurring", "status": "Confirmed", "category": "Shopping", "subcategory": "General"},
    ]
    r = resolve("Payment", m, history_rows=history, amount=550, card="Cash", source="recurring", date="2026-07-01")
    assert r["review_options"][0]["subcategory"] == "Housekeeping"
    assert r["learning_scope"] == "transaction_only"


def test_review_rows_and_misc_other_do_not_become_history_intelligence():
    m = _master()
    history = [
        {"merchant_clean": "New Merchant", "amount": "not-a-number", "status": "Review", "category": "Utilities", "subcategory": "Internet"},
        {"merchant_clean": "New Merchant", "amount": 10, "status": "Confirmed", "category": "Misc", "subcategory": "Other"},
    ]
    r = resolve("New Merchant", m, history_rows=history, amount=10)
    assert r["tier"] == 3
    assert r["review_options"] == []


def test_confirmed_history_blocks_a_conflicting_generic_keyword_cue():
    m = _master()
    history = [
        {"merchant_clean": "Starbucks Membership", "amount": 100, "status": "Confirmed", "category": "Subscriptions", "subcategory": "Memberships"},
    ]
    r = resolve("Starbucks Membership", m, history_rows=history, amount=100)
    assert r["tier"] == 3
    assert r["confidence"] == "evidence-conflict"
    assert r["review_options"][0]["category"] == "Subscriptions"


def test_conflicting_alias_mapping_is_rejected():
    with pytest.raises(ValueError, match="Conflicting merchant phrase"):
        build_master_from_rows([
            ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory", "Aliases"],
            ["Corner Cafe", "Corner Cafe", "Dining", "Cafe", "corner"],
            ["Corner Market", "Corner Market", "Groceries", "Supermarket", "corner"],
        ])


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
