"""Tests for word-boundary merchant matching (audit fix 2026-05-01).

Proves the resolver no longer fires substring false positives:
  - "rent" master key must NOT match "rental car" or "current account"
  - "gems" master key must NOT match "engagement gift"
  - Multi-word keys still match contiguous phrases.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merchant_resolver import (
    build_master_from_rows,
    resolve,
    merchant_matches,
    phrase_matches_tokens,
    tokens_of,
)


def _master():
    return build_master_from_rows([
        ["banner — ignored"],
        ["Merchant_Keyword", "Merchant_Clean", "Category", "Subcategory"],
        ["rent", "Rent", "Housing", "Rent"],
        ["gems", "GEMS", "Education", "School Fees"],
        ["GEMS Education", "GEMS Education", "Education", "School Fees"],
        ["Carrefour", "Carrefour", "Groceries", "Supermarket"],
    ])


# ── tokens_of ──────────────────────────────────────────────────────────

def test_tokens_of_basic():
    assert tokens_of("RENT MAY 2026") == ["rent", "may", "2026"]
    assert tokens_of("Carrefour MOE!") == ["carrefour", "moe"]
    assert tokens_of("") == []


def test_tokens_drops_geography_noise():
    assert tokens_of("Spinneys Marina DXB AE") == ["spinneys", "marina"]


# ── phrase_matches_tokens ─────────────────────────────────────────────

def test_phrase_matches_single_token_at_start():
    assert phrase_matches_tokens(["rent"], ["rent", "may", "2026"]) is True


def test_phrase_matches_single_token_at_end():
    assert phrase_matches_tokens(["rta"], ["dubai", "rta", "metro"]) is True


def test_phrase_does_not_match_inside_word():
    # "rent" tokenised is ["rent"]; "rental" tokenised is ["rental"].
    # phrase_matches_tokens compares full tokens, not substrings.
    assert phrase_matches_tokens(["rent"], ["rental", "car"]) is False


def test_phrase_matches_multiword_contiguous():
    assert phrase_matches_tokens(["gems", "education"], ["gems", "education", "dubai"]) is True


def test_phrase_does_not_match_multiword_non_contiguous():
    assert phrase_matches_tokens(["gems", "education"], ["gems", "city", "education"]) is False


# ── merchant_matches helper ───────────────────────────────────────────

def test_merchant_matches_word_boundary_positive():
    assert merchant_matches("rent", "RENT MAY 2026")
    assert merchant_matches("gems", "GEMS Education Dubai")
    assert merchant_matches("amazon", "amazon ae")


def test_merchant_matches_no_substring_false_positive_rental():
    """The audit's headline regression: 'rent' MUST NOT match 'rental car'."""
    assert not merchant_matches("rent", "rental car downtown")


def test_merchant_matches_no_substring_false_positive_current():
    assert not merchant_matches("rent", "current account fee")


def test_merchant_matches_no_substring_false_positive_gems():
    assert not merchant_matches("gems", "engagement gift card")


def test_merchant_matches_multiword_phrase():
    assert merchant_matches("gems education", "GEMS Education Dubai International")
    # Non-contiguous → false
    assert not merchant_matches("gems education", "GEMS City Education")


# ── resolver tier-1 with word-boundary master ─────────────────────────

def test_resolver_tier1_word_boundary_positive():
    m = _master()
    r = resolve("RENT MAY 2026", m)
    assert r["tier"] == 1
    assert r["category"] == "Housing"


def test_resolver_tier1_no_substring_false_positive_rental():
    m = _master()
    r = resolve("rental car downtown", m)
    # "rent" master key MUST NOT match inside "rental"
    assert r["tier"] != 1, f"FALSE POSITIVE: 'rent' matched 'rental' → {r}"


def test_resolver_tier1_no_substring_false_positive_current():
    m = _master()
    r = resolve("current account fee", m)
    assert r["tier"] != 1, f"FALSE POSITIVE: 'rent' matched 'current' → {r}"


def test_resolver_longest_token_phrase_wins():
    m = _master()
    # 'gems' AND 'gems education' both in master. Multi-word phrase should win.
    r = resolve("GEMS Education School Fees Dubai", m)
    assert r["category"] == "Education"
    assert r["subcategory"] == "School Fees"


def test_resolver_tier2_keyword_word_boundary():
    """Tier 2 cues also use word-boundary matching."""
    from merchant_resolver import keyword_resolve
    # 'rent' is a default cue → matches 'RENT MAY' but NOT 'rental car'
    assert keyword_resolve("RENT MAY 2026") is not None
    assert keyword_resolve("rental car") is None


def test_resolver_tier2_du_no_longer_overmatches():
    """Old cue ' du ' (with spaces) was a hack; the new normalised form is
    just 'du' which still applies word-boundary safely. We don't ship 'du'
    as a cue post-fix, but if a user adds it, it should match correctly."""
    from merchant_resolver import keyword_resolve
    cues = [("du", "Utilities", "Mobile & Internet")]
    assert keyword_resolve("du mobile bill", cues=cues) is not None
    assert keyword_resolve("dubai mall food court", cues=cues) is None


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
