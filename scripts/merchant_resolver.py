"""
merchant_resolver.py — three-tier merchant + category resolver.

Public version of the validated resolver core. Generalised for any user:
the master is loaded from the user's Google Sheet (or local CSV); no
private paths or sheet IDs.

Tier 1 — Known merchant: word-boundary phrase match against MERCHANT_MASTER.
Tier 2 — Keyword resolved: word-boundary token/phrase match against learned/seeded keyword cues.
Tier 3 — Vague — REJECT: refuse to guess; surface a clarifying question.

Matching safety (post-2026-05-01 audit fix):
  - Replaced raw substring matching with word-boundary phrase matching.
  - Single-token keys match only when the token appears as a standalone word
    in the input (e.g. master key "rent" matches "RENT MAY 2026" but NOT
    "current account fee" or "rental income").
  - Multi-token keys ("gems education") match only when the full phrase
    appears as a contiguous run of word-boundary tokens in the input.
  - Aliases follow the same rule.

Web enrichment (optional, opt-in) sits between tier 2 and tier 3 and is
implemented in `web_enrichment.py`. This module exposes hooks but does not
trigger network calls itself.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable, Any
import csv


# ---------- normalisation ----------

_WHITESPACE_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")


_NOISE_TOKENS = {"ae", "uae", "usa", "uk", "in", "dxb", "abu", "dhabi"}


def normalise_merchant(raw: str) -> str:
    s = (raw or "").lower().strip()
    s = _NONWORD_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    # Tokenise and drop common geography/region noise tokens.
    tokens = [t for t in s.split() if t not in _NOISE_TOKENS]
    return " ".join(tokens)


def tokens_of(raw: str) -> list[str]:
    """Normalise and return token list. Empty string → []."""
    n = normalise_merchant(raw)
    return n.split() if n else []


def phrase_matches_tokens(phrase_tokens: list[str], input_tokens: list[str]) -> bool:
    """True if `phrase_tokens` appears as a contiguous run in `input_tokens`,
    matching on full token equality (word-boundary). Empty phrase → False."""
    if not phrase_tokens or not input_tokens:
        return False
    n = len(phrase_tokens)
    for i in range(len(input_tokens) - n + 1):
        if input_tokens[i:i + n] == phrase_tokens:
            return True
    return False


# ---------- master loader ----------

@dataclass
class MerchantMaster:
    by_key: dict        # normalised_keyword (str) -> {category, subcategory, merchant_clean}
    by_alias: dict      # alias_norm (str) -> canonical_key (str)
    keys_sorted: list   # keys sorted longest-first (token count, then char length)

    def lookup(self, raw: str) -> Optional[dict]:
        """Word-boundary phrase match. Longest-keyword (in tokens) wins."""
        input_tokens = tokens_of(raw)
        if not input_tokens:
            return None

        # Exact phrase equality (covers single-token exact-match cases too).
        full_phrase = " ".join(input_tokens)
        if full_phrase in self.by_key:
            return self.by_key[full_phrase]
        if full_phrase in self.by_alias:
            return self.by_key.get(self.by_alias[full_phrase])

        # Phrase containment, longest-first.
        for k in self.keys_sorted:
            k_tokens = k.split() if k else []
            if not k_tokens:
                continue
            if phrase_matches_tokens(k_tokens, input_tokens):
                return self.by_key[k]

        # Alias containment, same word-boundary rule.
        for alias_key, canonical in self.by_alias.items():
            a_tokens = alias_key.split() if alias_key else []
            if not a_tokens:
                continue
            if phrase_matches_tokens(a_tokens, input_tokens):
                return self.by_key.get(canonical)

        return None


def build_master_from_rows(rows: Iterable[Iterable[str]]) -> MerchantMaster:
    """
    Accepts MERCHANT_MASTER tab rows (banner + header + data). Tolerates column
    variants. Required columns (case-insensitive substring match):
      Merchant_Keyword (or merchant_raw / keyword)
      Category
      Subcategory
      Merchant_Clean (optional — falls back to keyword)
      Aliases        (optional — pipe-separated)
    """
    rows = list(rows)
    if not rows or len(rows) < 2:
        return MerchantMaster(by_key={}, by_alias={}, keys_sorted=[])

    header_idx = 0
    while header_idx < min(4, len(rows)):
        cells = [c.strip().lower() for c in rows[header_idx]]
        has_merchant = any("merchant" in c or c == "keyword" for c in cells)
        has_category = any(c == "category" for c in cells)
        if has_merchant and has_category:
            break
        header_idx += 1
    if header_idx >= len(rows):
        return MerchantMaster(by_key={}, by_alias={}, keys_sorted=[])

    header = [c.strip() for c in rows[header_idx]]
    lower = [c.lower() for c in header]

    def col(*names) -> Optional[int]:
        for n in names:
            for i, h in enumerate(lower):
                if n in h:
                    return i
        return None

    i_keyword = col("merchant_keyword", "keyword", "merchant_raw")
    i_clean = col("merchant_clean", "clean")
    i_cat = col("category")
    i_sub = col("subcategory", "sub-cat", "sub_cat")
    i_alias = col("alias")

    by_key: dict = {}
    by_alias: dict = {}
    phrase_targets: dict[str, tuple[str, str, str]] = {}

    for row in rows[header_idx + 1:]:
        if not row or all((c or "").strip() == "" for c in row):
            continue
        keyword = row[i_keyword] if i_keyword is not None and i_keyword < len(row) else ""
        clean = row[i_clean] if i_clean is not None and i_clean < len(row) else ""
        cat = row[i_cat] if i_cat is not None and i_cat < len(row) else ""
        sub = row[i_sub] if i_sub is not None and i_sub < len(row) else ""

        key = normalise_merchant(keyword)
        if not key:
            continue
        category = (cat or "").strip()
        subcategory = (sub or "").strip()
        pair = (category.casefold(), subcategory.casefold())
        existing = phrase_targets.get(key)
        if existing is not None and existing[:2] != pair:
            raise ValueError(
                f"Conflicting merchant phrase '{key}' maps to more than one taxonomy pair"
            )
        phrase_targets[key] = (*pair, key)
        by_key[key] = {
            "category": category,
            "subcategory": subcategory,
            "merchant_clean": (clean or keyword).strip(),
        }
        if i_alias is not None and i_alias < len(row):
            for a in (row[i_alias] or "").split("|"):
                ak = normalise_merchant(a)
                if ak:
                    existing = phrase_targets.get(ak)
                    if existing is not None and existing[:2] != pair:
                        raise ValueError(
                            f"Conflicting merchant phrase '{ak}' maps to more than one "
                            "taxonomy pair"
                        )
                    phrase_targets[ak] = (*pair, key)
                    by_alias[ak] = key

    # Sort by token count (descending), then char length (descending).
    # More-specific multi-word keys win over generic single-token ones.
    keys_sorted = sorted(
        by_key.keys(),
        key=lambda k: (-len(k.split()), -len(k)),
    )
    return MerchantMaster(by_key=by_key, by_alias=by_alias, keys_sorted=keys_sorted)


def load_master_from_csv(path: str | Path) -> MerchantMaster:
    """For local-first / SQLite-canonical setups."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            rows.append(r)
    return build_master_from_rows(rows)


# ---------- keyword tier ----------
# These cues are seed-only. The skill REPLACES them at setup with the user's
# own taxonomy inferred from their imported statements. Shipped values are
# defaults that work in many countries; users will override.
#
# Each cue is a phrase. Matching is word-boundary contiguous: cue tokens must
# appear as a contiguous run in the normalised input.

DEFAULT_KEYWORD_CUES = [
    # Transport
    ("uber", "Transport", "Ride-Hailing"),
    ("lyft", "Transport", "Ride-Hailing"),
    ("careem", "Transport", "Ride-Hailing"),
    ("ola", "Transport", "Ride-Hailing"),
    ("taxi", "Transport", "Taxi"),
    ("metro", "Transport", "Public Transit"),
    ("rta", "Transport", "Public Transit"),
    ("salik", "Transport", "Tolls & Parking"),
    ("parking", "Transport", "Tolls & Parking"),
    ("fuel", "Transport", "Fuel"),
    ("petrol", "Transport", "Fuel"),
    ("gas station", "Transport", "Fuel"),
    # Food
    ("starbucks", "Dining", "Cafe"),
    ("costa", "Dining", "Cafe"),
    ("tim hortons", "Dining", "Cafe"),
    ("talabat", "Dining", "Food Delivery"),
    ("deliveroo", "Dining", "Food Delivery"),
    ("zomato", "Dining", "Food Delivery"),
    ("doordash", "Dining", "Food Delivery"),
    ("ubereats", "Dining", "Food Delivery"),
    ("grubhub", "Dining", "Food Delivery"),
    ("restaurant", "Dining", "Restaurant"),
    # Groceries
    ("carrefour", "Groceries", "Supermarket"),
    ("lulu", "Groceries", "Supermarket"),
    ("waitrose", "Groceries", "Supermarket"),
    ("spinneys", "Groceries", "Supermarket"),
    ("walmart", "Groceries", "Supermarket"),
    ("whole foods", "Groceries", "Supermarket"),
    ("trader joe", "Groceries", "Supermarket"),
    # Online retail
    ("amazon", "Shopping", "Online Retail"),
    ("noon", "Groceries & Household", "Online Grocery"),
    ("ebay", "Shopping", "Online Retail"),
    # Subscriptions
    ("netflix", "Subscriptions", "Streaming"),
    ("spotify", "Subscriptions", "Streaming"),
    ("apple com", "Subscriptions", "Apple Services"),
    ("icloud", "Subscriptions", "Cloud Storage"),
    ("microsoft", "Subscriptions", "SaaS"),
    # Utilities
    ("dewa", "Utilities", "Electricity & Water"),
    ("etisalat", "Utilities", "Mobile & Internet"),
    ("verizon", "Utilities", "Mobile & Internet"),
    # Health
    ("pharmacy", "Health", "Pharmacy"),
    ("clinic", "Health", "Doctor & Clinic"),
    ("hospital", "Health", "Hospital"),
    # Housing
    ("rent", "Housing", "Rent"),
]


def keyword_resolve(raw: str, cues=None) -> Optional[dict]:
    """Word-boundary phrase match against keyword cues.

    Cues are matched as full phrases (token-equal contiguous runs). A cue
    "rent" matches "RENT MAY 2026" but NOT "current account" or "rental".
    """
    cues = cues or DEFAULT_KEYWORD_CUES
    input_tokens = tokens_of(raw)
    if not input_tokens:
        return None
    for cue, cat, sub in cues:
        cue_tokens = tokens_of(cue)
        if phrase_matches_tokens(cue_tokens, input_tokens):
            return {
                "category": cat,
                "subcategory": sub,
                "merchant_clean": (raw or "").strip(),
            }
    return None


# ---------- tier 3 ----------

GENERIC_NOISE = {
    "purchase", "merchant", "transaction", "payment", "card payment",
    "unknown merchant", "shop", "store", "vendor",
}
GENERIC_TOKENS = {
    "pos", "purchase", "merchant", "transaction", "payment", "card",
    "debit", "credit", "shop", "store", "vendor", "online", "ecom",
    "ecommerce", "terminal", "autopay", "charge",
}


def _safe_amount(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _day_of_month(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).day
        except ValueError:
            pass
    for pattern in (
        r"^(\d{1,2})[-/]\d{1,2}[-/]\d{4}$",
        r"^\d{4}[-/]\d{1,2}[-/](\d{1,2})$",
    ):
        match = re.match(pattern, raw)
        if match:
            day = int(match.group(1))
            return day if 1 <= day <= 31 else None
    return None


def rank_review_options(
    raw_merchant: str,
    *,
    history_rows: Iterable[dict[str, Any]] | None = None,
    web_evidence: list[dict[str, Any]] | None = None,
    amount: float | None = None,
    card: str = "",
    date: str = "",
    source: str = "",
    cues=None,
) -> list[dict[str, Any]]:
    """Rank up to three review choices from local history and web evidence.

    Callers retain control of writes. Only merchant names may be sent to a web
    provider; this function consumes already-returned evidence and never calls
    the network itself.
    """
    merchant_key = normalise_merchant(raw_merchant)
    generic = is_too_vague(raw_merchant)
    target_amount = _safe_amount(amount)
    target_day = _day_of_month(date)
    scores: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}

    for row in history_rows or []:
        category = str(row.get("category") or "").strip()
        subcategory = str(row.get("subcategory") or "").strip()
        if not category or not subcategory:
            continue
        status = str(row.get("status") or "").strip().casefold()
        if status in {"review", "needs_review", "rejected", "failed"}:
            continue
        if category.casefold() in {"other", "unknown", "uncategorized", "uncategorised"}:
            continue
        if category.casefold() in {"misc", "miscellaneous"} and subcategory.casefold() == "other":
            continue
        row_merchant = str(row.get("merchant_clean") or row.get("merchant_raw") or "")
        identity_match = bool(merchant_key and normalise_merchant(row_merchant) == merchant_key)
        row_amount = _safe_amount(row.get("amount"))
        amount_match = bool(
            target_amount is not None
            and row_amount is not None
            and abs(row_amount - target_amount) <= max(0.5, abs(target_amount) * 0.003)
        )
        card_match = bool(card and str(row.get("card") or "").casefold() == card.casefold())
        source_match = bool(source and source.casefold() in str(row.get("source") or "").casefold())
        row_day = _day_of_month(row.get("date"))
        day_match = bool(
            target_day is not None
            and row_day is not None
            and min(abs(target_day - row_day), 31 - abs(target_day - row_day)) <= 2
        )
        if generic:
            if not amount_match or not (card_match or source_match):
                continue
        elif not identity_match:
            continue
        pair = (category, subcategory)
        evidence_score = (
            (6 if identity_match else 0)
            + (3 if amount_match else 0)
            + (1 if card_match else 0)
            + (1.5 if day_match else 0)
            + (0.5 if source_match else 0)
        )
        scores[pair] = scores.get(pair, 0.0) + evidence_score
        counts[pair] = counts.get(pair, 0) + 1

    if web_evidence:
        evidence_text = " ".join(
            f"{item.get('title') or ''} {item.get('snippet') or ''}"
            for item in web_evidence
        )
        web_hit = keyword_resolve(evidence_text, cues=cues)
        if web_hit:
            pair = (web_hit["category"], web_hit["subcategory"])
            scores[pair] = scores.get(pair, 0.0) + 2.0
            counts.setdefault(pair, 0)

    ranked = sorted(scores, key=lambda pair: (scores[pair], counts.get(pair, 0)), reverse=True)
    return [
        {
            "category": category,
            "subcategory": subcategory,
            "confidence": round(scores[(category, subcategory)], 1),
            "historical_rows": counts.get((category, subcategory), 0),
            "learning_scope": "transaction_only" if generic else "merchant_default",
        }
        for category, subcategory in ranked[:3]
    ]


def is_too_vague(raw: str) -> bool:
    s = normalise_merchant(raw)
    if not s:
        return True
    if s in GENERIC_NOISE:
        return True
    tokens = [token for token in s.split() if not token.isdigit()]
    meaningful = [token for token in tokens if token not in GENERIC_TOKENS]
    if not meaningful:
        return True
    return False


# ---------- public API ----------

def resolve(
    raw_merchant: str,
    master: MerchantMaster,
    cues=None,
    *,
    history_rows: Iterable[dict[str, Any]] | None = None,
    web_evidence: list[dict[str, Any]] | None = None,
    amount: float | None = None,
    card: str = "",
    date: str = "",
    source: str = "",
) -> dict:
    """
    Three-tier resolver. Returns dict with keys:
      category, subcategory, merchant_clean, tier, confidence, review_reason
    """
    hit = master.lookup(raw_merchant)
    if hit and hit["category"]:
        return {**hit, "tier": 1, "confidence": "known", "review_reason": ""}

    options = rank_review_options(
        raw_merchant,
        history_rows=history_rows,
        web_evidence=web_evidence,
        amount=amount,
        card=card,
        date=date,
        source=source,
        cues=cues,
    )
    if options:
        top = options[0]
        stable_history = bool(
            top["learning_scope"] == "merchant_default"
            and top["historical_rows"] >= 2
            and (len(options) == 1 or top["confidence"] >= options[1]["confidence"] * 1.5)
        )
        if stable_history:
            return {
                "category": top["category"],
                "subcategory": top["subcategory"],
                "merchant_clean": (raw_merchant or "").strip(),
                "tier": 1,
                "confidence": "historical-stable",
                "review_reason": "",
                "review_options": options,
                "learning_scope": top["learning_scope"],
                "research_attempted": bool(web_evidence),
            }

    hit = keyword_resolve(raw_merchant, cues=cues)
    if hit:
        if options:
            top = options[0]
            keyword_pair = (hit["category"].casefold(), hit["subcategory"].casefold())
            top_pair = (top["category"].casefold(), top["subcategory"].casefold())
            if keyword_pair != top_pair:
                if not any(
                    (option["category"].casefold(), option["subcategory"].casefold())
                    == keyword_pair
                    for option in options
                ):
                    options = [
                        *options[:2],
                        {
                            "category": hit["category"],
                            "subcategory": hit["subcategory"],
                            "confidence": 1.0,
                            "historical_rows": 0,
                            "learning_scope": "transaction_only" if is_too_vague(raw_merchant) else "merchant_default",
                        },
                    ]
                return {
                    "category": top["category"],
                    "subcategory": top["subcategory"],
                    "merchant_clean": (raw_merchant or "").strip(),
                    "tier": 3,
                    "confidence": "evidence-conflict",
                    "review_reason": "Historical or web evidence conflicts with a generic keyword cue",
                    "review_options": options[:3],
                    "learning_scope": top["learning_scope"],
                    "research_attempted": bool(web_evidence),
                }
        return {**hit, "tier": 2, "confidence": "soft", "review_reason": ""}

    if options:
        top = options[0]
        return {
            "category": top["category"],
            "subcategory": top["subcategory"],
            "merchant_clean": (raw_merchant or "").strip(),
            "tier": 3,
            "confidence": "review-options",
            "review_reason": "Ranked choices found; confirmation required before learning",
            "review_options": options,
            "learning_scope": top["learning_scope"],
            "research_attempted": bool(web_evidence),
        }

    if is_too_vague(raw_merchant):
        return {
            "category": "", "subcategory": "",
            "merchant_clean": (raw_merchant or "").strip(),
            "tier": 3, "confidence": "rejected-vague",
            "review_reason": "Vague descriptor — skill refused to guess",
            "review_options": [], "learning_scope": "transaction_only",
            "research_attempted": bool(web_evidence),
        }
    return {
        "category": "", "subcategory": "",
        "merchant_clean": (raw_merchant or "").strip(),
        "tier": 3, "confidence": "rejected-unknown",
        "review_reason": "Unknown merchant — skill asked instead of guessing",
        "review_options": [], "learning_scope": "merchant_default",
        "research_attempted": bool(web_evidence),
    }


# ---------- helpers exposed for correction_handler + recategorise_history ----------

def merchant_matches(merchant_keyword: str, candidate_text: str) -> bool:
    """Word-boundary check: does `merchant_keyword` appear as a contiguous
    phrase in `candidate_text`? Uses the same rule as tier-1 lookup so the
    correction_handler bulk-update path matches what the resolver would.

    Examples:
      merchant_matches("rent", "RENT MAY 2026")          -> True
      merchant_matches("rent", "rental car downtown")    -> False
      merchant_matches("rent", "current account fee")    -> False
      merchant_matches("gems", "GEMS Education Dubai")   -> True
      merchant_matches("gems", "engagement gift card")   -> False
    """
    k_tokens = tokens_of(merchant_keyword)
    i_tokens = tokens_of(candidate_text)
    return phrase_matches_tokens(k_tokens, i_tokens)
