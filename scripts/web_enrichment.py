"""
web_enrichment.py — optional unknown-merchant lookup. OPT-IN, FAIL-CLOSED.

Rules (per references/categorization.md § merchant research):
  - An external review flow must call this helper explicitly
  - User must have set categorization.web_enrichment to "ask" or "always"
  - Search merchant name only; never search full transaction rows
  - Cache results locally; never re-query for the same merchant
  - Do not classify if categories tied or merchant tokens missing from evidence
  - Store evidence summary, not full pages
  - Never write to ledger from a web result without user confirmation

This module exposes a single function `enrich(merchant_raw, config)` that
returns either a candidate dict or None. Network access is wrapped behind a
provider hook so users can plug in:
  - Google Programmable Search (requires user-supplied API key + cx)
  - none (always returns None)
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Optional

CACHE_DIR = Path("~/.expense-bookkeeper/state/web_cache").expanduser()


def _cache_path(merchant: str) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in merchant.lower())[:80]
    return CACHE_DIR / f"{safe}.json"


def _from_cache(merchant: str) -> Optional[dict]:
    p = _cache_path(merchant)
    if p.exists():
        try:
            d = json.loads(p.read_text())
            # Honour 30-day cache TTL
            if time.time() - d.get("_cached_at", 0) < 30 * 86400:
                return d
        except Exception:
            return None
    return None


def _to_cache(merchant: str, result: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result["_cached_at"] = time.time()
    _cache_path(merchant).write_text(json.dumps(result, indent=2))


def _provider_google_pse(merchant: str, api_key: str, cx: str) -> Optional[dict]:
    """Google Programmable Search Engine. User provides api_key + cx."""
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": merchant, "key": api_key, "cx": cx, "num": 3},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return None
        return {
            "merchant": merchant,
            "evidence": [{"title": i.get("title"), "link": i.get("link"),
                          "snippet": i.get("snippet")} for i in items[:3]],
            "provider": "google_pse",
        }
    except Exception:
        return None


def _provider_none(merchant: str, *_) -> Optional[dict]:
    return None


PROVIDERS = {
    "google_pse": _provider_google_pse,
    "none": _provider_none,
}


def enrich(merchant_raw: str, config: dict) -> Optional[dict]:
    """
    Entry point. Returns evidence dict or None. Caller decides whether to use
    the evidence (must require token-overlap before adopting a category).
    """
    cat = config.get("categorization", {})
    mode = cat.get("web_enrichment", "never")
    if mode == "never":
        return None

    cached = _from_cache(merchant_raw)
    if cached:
        return cached

    provider_name = cat.get("web_enrichment_provider", "none")
    provider = PROVIDERS.get(provider_name)
    if not provider:
        return None

    api_key = cat.get("web_enrichment_api_key") or os.environ.get("EXPENSE_BOOKKEEPER_PSE_KEY")
    cx = cat.get("web_enrichment_cx") or os.environ.get("EXPENSE_BOOKKEEPER_PSE_CX")

    result = provider(merchant_raw, api_key, cx) if provider_name == "google_pse" else provider(merchant_raw)
    if result:
        _to_cache(merchant_raw, result)
    return result


def has_token_overlap(merchant_raw: str, evidence: list) -> bool:
    """Fail-closed gate: a web result is only usable if the merchant tokens
    appear in the evidence text."""
    tokens = {t for t in merchant_raw.lower().split() if len(t) >= 3}
    if not tokens:
        return False
    text = " ".join(((e.get("title") or "") + " " + (e.get("snippet") or "")) for e in evidence).lower()
    return any(t in text for t in tokens)
