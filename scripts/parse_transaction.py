"""
parse_transaction.py — turn a raw notification/SMS/email-alert string into
a structured Transaction.

Strategy:
  1. Try learned regex patterns from user's bank profile (config.banks[]).
  2. Fall back to generic amount+merchant extraction.
  3. Emit a hash for dedup: sha1(date|amount|merchant_normalised).

Output schema matches `references/ledger-schema.md`.
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional


# Patterns tried in order. Each entry: (regex, description). The first match
# wins. Patterns are deliberately conservative — if none match, fall back to
# the generic extractor below.
DEFAULT_PATTERNS = [
    # "AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026"
    (re.compile(
        r"(?P<currency>[A-Z]{3})\s*(?P<amount>[0-9,]+(?:\.\d{1,2})?)\s+spent\s+on\s+(?P<card>\w+)\s+at\s+(?P<merchant>.+?)\s+on\s+(?P<date>\d{2}[/\-]\d{2}[/\-]\d{4})",
        re.I), "spent_on_at"),
    # "Charge of AED 87.00 at AMAZON.AE — 29 Apr 2026"
    (re.compile(
        r"(?:[Cc]harge|[Dd]ebit|[Ss]pent)\s+(?:of\s+)?(?P<currency>[A-Z]{3})\s*(?P<amount>[0-9,]+(?:\.\d{1,2})?)\s+at\s+(?P<merchant>.+?)\s*[—\-,]\s*(?P<date>\d{1,2}\s+\w+\s+\d{4})"
    ), "charge_at"),
    # "AED 250 at LULU HYPER on 28-04-2026" — bare currency+amount+at+merchant+on+date
    (re.compile(
        r"(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9,]+(?:\.\d{1,2})?)\s+at\s+(?P<merchant>.+?)\s+on\s+(?P<date>\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        re.I), "currency_amount_at_on"),
    # "USD 14.99 NETFLIX — 27 Apr 2026" — currency amount merchant — date
    (re.compile(
        r"(?P<currency>[A-Z]{3})\s+(?P<amount>[0-9,]+(?:\.\d{1,2})?)\s+(?P<merchant>[A-Za-z][\w\s\.&'\-]+?)\s*[—\-]\s*(?P<date>\d{1,2}\s+\w+\s+\d{4})"
    ), "currency_amount_merchant_dash_date"),
    # Generic: <amount> <currency> <merchant>
    (re.compile(
        r"(?P<amount>[0-9,]+(?:\.\d{1,2})?)\s*(?P<currency>[A-Z]{3})\s+(?P<merchant>[^\d]{3,})",
        re.I), "amount_currency_merchant"),
]


def _parse_amount(s: str) -> Optional[float]:
    if not s: return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[str]:
    if not s: return None
    s = s.strip()
    fmts = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y")
    for f in fmts:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


@dataclass
class Transaction:
    raw_input: str
    date: str = ""
    amount: float = 0.0
    currency: str = ""
    merchant_raw: str = ""
    card: str = ""
    pattern_id: str = ""
    hash: str = ""
    valid: bool = False
    error: str = ""


def _hash_for(date: str, amount: float, merchant: str) -> str:
    base = f"{date}|{amount:.2f}|{merchant.strip().lower()}"
    # SHA-1 is retained for ledger compatibility; this is a duplicate key,
    # not a password, signature, or other security primitive.
    return hashlib.sha1(base.encode(), usedforsecurity=False).hexdigest()[:16]


def parse(raw: str, user_patterns: list[tuple] | None = None) -> Transaction:
    txn = Transaction(raw_input=raw or "")
    if not raw:
        txn.error = "empty input"
        return txn

    patterns = user_patterns or []
    patterns = patterns + DEFAULT_PATTERNS

    for pattern, pid in patterns:
        m = pattern.search(raw)
        if not m:
            continue
        groups = m.groupdict()
        txn.pattern_id = pid
        txn.merchant_raw = (groups.get("merchant") or "").strip()
        amt = _parse_amount(groups.get("amount") or "")
        if amt is not None:
            txn.amount = amt
        txn.currency = (groups.get("currency") or "").upper().strip()
        txn.card = (groups.get("card") or "").strip()
        if "date" in groups:
            d = _parse_date(groups["date"])
            if d:
                txn.date = d
        else:
            txn.date = datetime.now().strftime("%Y-%m-%d")
        break
    else:
        txn.error = "no pattern matched"
        return txn

    if txn.amount > 0 and txn.merchant_raw:
        txn.valid = True
        txn.hash = _hash_for(txn.date, txn.amount, txn.merchant_raw)
    else:
        txn.error = "incomplete fields"

    return txn


if __name__ == "__main__":
    import json, sys
    samples = sys.argv[1:] or [
        "AED 87.00 spent on WioCredit at AMAZON.AE on 29/04/2026",
        "Charge of AED 12.50 at STARBUCKS DXB — 29 Apr 2026",
    ]
    for s in samples:
        t = parse(s)
        print(json.dumps(asdict(t), indent=2))
